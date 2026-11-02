"""
lab/analytics.py — Per-lab metrics, heatmap data, and rule-based forecast.

Design decisions:
- 40 teaching slots = 5 days × 8 non-lunch slots (S1–S4, S6–S9).
  This is the denominator for utilization %.
- Status thresholds are named constants so the UI and tests share them.
- Forecast is EXPLICITLY rule-based because we only have timetable data,
  not actual usage logs. The formula is:
      predicted = baseline × ATTENDANCE_FACTOR × week_type_factor
  This is NOT machine learning. It is a simple multiplicative model to
  give a rough idea of expected occupancy under different conditions.
- Labs with timetable=false get a "no_data" analytics object so the UI
  can show "No data" instead of 0%.
"""

from collections import defaultdict

# ─── Configurable constants ─────────────────────────────────────────────────

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
ALL_SLOTS = list(range(1, 10))          # S1–S9
LUNCH_SLOT = 5
TEACHING_SLOTS = [s for s in ALL_SLOTS if s != LUNCH_SLOT]  # 8 slots
TOTAL_TEACHING_SLOTS = len(DAYS) * len(TEACHING_SLOTS)       # 40

# Utilization status thresholds
UNDERUSED_THRESHOLD = 30   # < 30% → Underused
OVERLOADED_THRESHOLD = 90  # > 90% → Overloaded
# 30–90% → Healthy

# Rule-based forecast parameters (clearly NOT machine learning)
ATTENDANCE_FACTOR = 0.85          # fraction of enrolled students typically present
WEEK_FACTORS = {
    "normal": 1.0,
    "exam":   0.2,    # labs mostly unused during exams
    "holiday": 0.0,
}

# ─── Main analytics function ────────────────────────────────────────────────

def compute_analytics(sessions: list[dict], labs_cfg: list[dict]) -> dict:
    """
    Compute analytics for all labs.

    Args:
        sessions:  parsed session records from parser.parse_timetable()
        labs_cfg:  list of lab dicts from labs.json

    Returns:
        dict keyed by lab ID → analytics dict (or no_data dict).
    """
    # Index sessions by lab
    by_lab: dict[str, list[dict]] = defaultdict(list)
    for s in sessions:
        by_lab[s["lab"]].append(s)

    result = {}
    for lab in labs_cfg:
        lab_id = lab["id"]
        if not lab.get("timetable", False):
            result[lab_id] = _no_data_analytics(lab)
            continue

        lab_sessions = by_lab.get(lab_id, [])
        result[lab_id] = _compute_lab_analytics(lab, lab_sessions)

    return result


def _compute_lab_analytics(lab: dict, sessions: list[dict]) -> dict:
    """Compute full analytics for one lab that has timetable data."""
    cap = lab["capacity"]
    lab_id = lab["id"]

    # Booked slots: unique (day, slot1) pairs
    booked_keys = {(s["day"], s["slot1"]) for s in sessions}
    booked_count = len(booked_keys)
    free_count = TOTAL_TEACHING_SLOTS - booked_count
    utilization_pct = round(booked_count / TOTAL_TEACHING_SLOTS * 100, 1)

    # Status badge
    if utilization_pct < UNDERUSED_THRESHOLD:
        status = "Underused"
    elif utilization_pct > OVERLOADED_THRESHOLD:
        status = "Overloaded"
    else:
        status = "Healthy"

    # Average seat fill % (mean of occupancy_pct across sessions)
    if sessions:
        avg_fill_pct = round(sum(s["occupancy_pct"] for s in sessions) / len(sessions), 1)
    else:
        avg_fill_pct = 0.0

    # Over-capacity sessions
    over_cap_sessions = [s for s in sessions if s["strength"] > cap]
    over_cap_count = len(over_cap_sessions)

    # Heatmap: day × slot → {state, sessions}
    heatmap = _build_heatmap(sessions)

    # Free slots per lab
    free_slots = _free_slots(booked_keys)

    # Peak window: which 2-slot consecutive window has most sessions per day?
    peak_window = _peak_window(sessions)

    # Rule-based forecast (clearly labeled as such)
    forecast = _build_forecast(booked_count, utilization_pct)

    return {
        "lab_id": lab_id,
        "lab_name": lab["name"],
        "capacity": cap,
        "has_data": True,
        "booked_count": booked_count,
        "free_count": free_count,
        "total_slots": TOTAL_TEACHING_SLOTS,
        "utilization_pct": utilization_pct,
        "avg_fill_pct": avg_fill_pct,
        "over_cap_count": over_cap_count,
        "over_cap_sessions": [
            {k: s[k] for k in ("year", "section", "day", "slot1", "course", "strength")}
            for s in over_cap_sessions
        ],
        "status": status,
        "heatmap": heatmap,
        "free_slots": free_slots,
        "peak_window": peak_window,
        "forecast": forecast,
        "sessions": sessions,
    }


def _no_data_analytics(lab: dict) -> dict:
    """Placeholder analytics for labs without timetable data."""
    return {
        "lab_id": lab["id"],
        "lab_name": lab["name"],
        "capacity": lab["capacity"],
        "has_data": False,
        "booked_count": None,
        "free_count": None,
        "total_slots": TOTAL_TEACHING_SLOTS,
        "utilization_pct": None,
        "avg_fill_pct": None,
        "over_cap_count": None,
        "over_cap_sessions": [],
        "status": "No data",
        "heatmap": None,
        "free_slots": None,
        "peak_window": None,
        "forecast": None,
        "sessions": [],
    }


def _build_heatmap(sessions: list[dict]) -> list[list[dict]]:
    """
    Build a 5-row (days) × 9-col (slots) heatmap.
    Each cell: {state: "booked"|"empty"|"lunch", sessions: [...]}
    """
    # Index sessions by (day, slot1)
    sess_map: dict[tuple, list] = defaultdict(list)
    for s in sessions:
        sess_map[(s["day"], s["slot1"])].append(s)

    heatmap = []
    for day in DAYS:
        row = []
        for slot in ALL_SLOTS:
            if slot == LUNCH_SLOT:
                row.append({"state": "lunch", "sessions": []})
            else:
                cell_sessions = sess_map.get((day, slot), [])
                state = "booked" if cell_sessions else "empty"
                row.append({
                    "state": state,
                    "sessions": [
                        {k: s[k] for k in ("year", "section", "course", "strength", "occupancy_pct")}
                        for s in cell_sessions
                    ],
                })
        heatmap.append(row)
    return heatmap


def _free_slots(booked_keys: set) -> list[dict]:
    """Return list of {day, slot} for unbooked teaching slots."""
    free = []
    for day in DAYS:
        for slot in TEACHING_SLOTS:
            if (day, slot) not in booked_keys:
                free.append({"day": day, "slot": slot})
    return free


def _peak_window(sessions: list[dict]) -> dict:
    """
    Find the peak utilization window: pair of consecutive slots (not crossing lunch)
    with the highest total number of sessions across all days.
    """
    # Count sessions per slot
    slot_counts: dict[int, int] = defaultdict(int)
    for s in sessions:
        slot_counts[s["slot1"]] += 1

    # Valid consecutive slot pairs (not crossing lunch)
    valid_pairs = [
        (s, s + 1) for s in TEACHING_SLOTS
        if s + 1 in TEACHING_SLOTS and abs(s - LUNCH_SLOT) != 0 and abs(s + 1 - LUNCH_SLOT) != 0
        and s + 1 != LUNCH_SLOT and s != LUNCH_SLOT
    ]
    # Remove pairs that straddle lunch
    valid_pairs = [(a, b) for a, b in valid_pairs
                   if not (a < LUNCH_SLOT < b) and a != LUNCH_SLOT and b != LUNCH_SLOT]

    if not valid_pairs:
        return {}

    best_pair = max(valid_pairs, key=lambda p: slot_counts[p[0]] + slot_counts[p[1]])
    total = slot_counts[best_pair[0]] + slot_counts[best_pair[1]]
    return {"slots": list(best_pair), "session_count": total}


def _build_forecast(booked_count: int, utilization_pct: float) -> list[dict]:
    """
    Build a rule-based forecast table for different week types.

    NOTE: This is a rule-based prediction, NOT machine learning.
    We multiply the timetable baseline by an attendance factor and a week-type factor.
    These are configurable constants, not learned parameters.
    """
    rows = []
    baseline = booked_count  # timetable-derived baseline (absolute slot count)
    for week_type, factor in WEEK_FACTORS.items():
        predicted_slots = round(baseline * ATTENDANCE_FACTOR * factor)
        predicted_pct = round(predicted_slots / TOTAL_TEACHING_SLOTS * 100, 1) if TOTAL_TEACHING_SLOTS else 0
        rows.append({
            "week_type": week_type,
            "attendance_factor": ATTENDANCE_FACTOR,
            "week_factor": factor,
            "baseline_slots": baseline,
            "predicted_slots": predicted_slots,
            "predicted_pct": predicted_pct,
            # Surface the formula so the UI can display it honestly
            "formula": f"{baseline} × {ATTENDANCE_FACTOR} × {factor} = {predicted_slots} slots",
        })
    return rows


def get_free_labs_for_slot(analytics: dict, day: str, slot: int) -> list[str]:
    """
    Return list of lab IDs that are free (timetable-empty) for the given day+slot.
    Used by the 'find a free lab' form on the dashboard.
    """
    free = []
    for lab_id, info in analytics.items():
        if not info["has_data"]:
            continue
        if slot == LUNCH_SLOT:
            continue
        # Check heatmap
        try:
            day_idx = ["Mon", "Tue", "Wed", "Thu", "Fri"].index(day)
            slot_idx = slot - 1
            cell = info["heatmap"][day_idx][slot_idx]
            if cell["state"] == "empty":
                free.append(lab_id)
        except (ValueError, IndexError):
            pass
    return free
