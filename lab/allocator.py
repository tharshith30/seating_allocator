"""
lab/allocator.py — Smart lab allocation engine.

Scoring formula (named constants — NOT machine learning):
  With preference:    score = W_FIT×fit + W_BALANCE×balance + W_PREF×preference
  Without preference: score = W_FIT_NP×fit + W_BALANCE_NP×balance

  fit       = group_size / lab_capacity                     (1.0 = perfectly full)
  balance   = 1 - (booked_count_this_week / TOTAL_SLOTS)   (higher = less loaded)
  preference = 1.0 if preferred day+slot matches, 0.5 if day only, 0.0 otherwise

  Unverified labs (timetable=False) get UNVERIFIED_PENALTY subtracted.
  Labs without timetable data are excluded by default (include_unverified=False).

Batch allocation:
  Sort: faculty-first, then larger group first.
  Greedy: assign best candidate not overlapping already-taken slots.
  dry_run=True returns the plan without writing to DB.
  Commit requires in-charge PIN.
"""

from __future__ import annotations
import heapq
from datetime import date, timedelta

# ─── Scoring weights (named constants) ─────────────────────────────────────

W_FIT        = 0.40   # weight for fit (size/capacity) — with preference
W_BALANCE    = 0.30   # weight for lab balance — with preference
W_PREF       = 0.30   # weight for day/slot preference — with preference

W_FIT_NP     = 0.55   # weight for fit — without preference
W_BALANCE_NP = 0.45   # weight for balance — without preference

UNVERIFIED_PENALTY = 0.25  # subtracted from score for labs without timetable data
MAX_CANDIDATES     = 5     # top-N to return per suggest call

LUNCH_SLOT    = 5
ALL_SLOTS     = list(range(1, 10))
TEACHING_SLOTS = [s for s in ALL_SLOTS if s != LUNCH_SLOT]
TOTAL_TEACHING = 40   # 5 days × 8 non-lunch slots
DAYS          = ["Mon", "Tue", "Wed", "Thu", "Fri"]


# ─── Helpers ────────────────────────────────────────────────────────────────

def _consecutive_runs(slots: list[int], n: int) -> list[tuple[int, ...]]:
    """
    Return all consecutive runs of length n from a sorted list of slots,
    never crossing the lunch slot.
    E.g. slots=[1,2,3,6,7], n=2 → [(1,2),(2,3),(6,7)]
    """
    runs = []
    for i in range(len(slots) - n + 1):
        run = slots[i:i + n]
        # Check consecutive and not crossing lunch
        if all(run[j] + 1 == run[j + 1] for j in range(n - 1)):
            if LUNCH_SLOT not in run:
                runs.append(tuple(run))
    return runs


def _week_load(lab: str, week_monday: str, timetable_busy: set,
               booking_module) -> float:
    """
    Fraction of teaching slots occupied this week (timetable + bookings + overrides).
    Returns 0.0–1.0.
    """
    occupied = 0
    for day in DAYS:
        for slot in TEACHING_SLOTS:
            state = booking_module.get_slot_state(lab, week_monday, day, slot, timetable_busy)
            if state != "empty":
                occupied += 1
    return occupied / TOTAL_TEACHING


def _preference_score(day: str, start_slot: int,
                      preferred_day: str | None, preferred_slot: int | None) -> float:
    """
    Score 0.0–1.0 for how well (day, start_slot) matches the preference.
    1.0 → exact day+slot match
    0.5 → day matches only
    0.0 → no match
    """
    if preferred_day is None and preferred_slot is None:
        return 1.0  # no preference = always "matches"
    day_match = (preferred_day is None or day == preferred_day)
    slot_match = (preferred_slot is None or start_slot == preferred_slot)
    if day_match and slot_match:
        return 1.0
    if day_match:
        return 0.5
    return 0.0


# ─── Single-request suggestion ───────────────────────────────────────────────

def suggest(
    group_size: int,
    n_consecutive: int,
    week_monday: str,
    timetable_busy: set,
    labs_cfg: list[dict],
    booking_module,
    preferred_day: str | None = None,
    preferred_slot: int | None = None,
    include_unverified: bool = False,
) -> list[dict]:
    """
    Return top-MAX_CANDIDATES candidates for a booking request.

    Each candidate: {lab, day, slots, score, reasons, fit, balance, preference}
    """
    has_preference = (preferred_day is not None or preferred_slot is not None)

    candidates = []

    for lab in labs_cfg:
        lab_id = lab["id"]
        verified = lab.get("timetable", False)
        cap = lab["capacity"]

        if not verified and not include_unverified:
            continue  # skip unverified unless opted in

        if group_size > cap:
            # Cannot fit — skip entirely
            continue

        # Compute balance (load) for this week
        load = _week_load(lab_id, week_monday, timetable_busy, booking_module)
        balance = 1.0 - load

        fit = group_size / cap  # 1.0 = perfectly full

        # Find all (day, consecutive slot run) pairs where all slots are empty
        for day in DAYS:
            available_slots = [
                s for s in TEACHING_SLOTS
                if booking_module.get_slot_state(lab_id, week_monday, day, s, timetable_busy) == "empty"
            ]
            for run in _consecutive_runs(available_slots, n_consecutive):
                start = run[0]
                pref = _preference_score(day, start, preferred_day, preferred_slot)

                if has_preference:
                    score = W_FIT * fit + W_BALANCE * balance + W_PREF * pref
                else:
                    score = W_FIT_NP * fit + W_BALANCE_NP * balance

                if not verified:
                    score -= UNVERIFIED_PENALTY

                # Build human-readable reasons
                reasons = []
                reasons.append(
                    f"Fit: {group_size}/{cap} seats ({fit*100:.0f}% full)"
                )
                reasons.append(
                    f"Lab load this week: {load*100:.0f}% occupied (balance score {balance:.2f})"
                )
                if has_preference:
                    reasons.append(f"Preference match: {pref:.1f}")
                if not verified:
                    reasons.append(
                        f"⚠ Lab has no timetable data; availability unverified "
                        f"(penalty -{UNVERIFIED_PENALTY})"
                    )

                candidates.append({
                    "lab": lab_id,
                    "lab_name": lab["name"],
                    "day": day,
                    "slots": list(run),
                    "score": round(score, 4),
                    "fit": round(fit, 3),
                    "balance": round(balance, 3),
                    "preference": round(pref, 3),
                    "reasons": reasons,
                    "verified": verified,
                })

    # Sort descending by score; keep best start per (lab, day)
    candidates.sort(key=lambda c: -c["score"])

    # Deduplicate: one best entry per (lab, day) combination
    seen_lab_day = set()
    top = []
    for c in candidates:
        key = (c["lab"], c["day"])
        if key not in seen_lab_day:
            seen_lab_day.add(key)
            top.append(c)
        if len(top) >= MAX_CANDIDATES:
            break

    return top


# ─── Batch allocation ────────────────────────────────────────────────────────

def batch_allocate(
    requests: list[dict],
    week_monday: str,
    timetable_busy: set,
    labs_cfg: list[dict],
    booking_module,
    include_unverified: bool = False,
    dry_run: bool = True,
    pin: str | None = None,
) -> dict:
    """
    Greedy batch allocation for multiple requests.

    Request format:
        {name, role, group_size, n_consecutive, purpose,
         preferred_day (opt), preferred_slot (opt)}

    Returns:
        {allocated: [...], unallocated: [...], seat_efficiency_pct, committed}

    Sort order: faculty first, then larger group first (within same role).
    This gives faculty priority access and maximises seat utilisation.
    """
    # Sort: faculty first, then by group_size descending
    def sort_key(r):
        role_order = 0 if r.get("role") == "faculty" else 1
        return (role_order, -r.get("group_size", 0))

    sorted_requests = sorted(requests, key=sort_key)

    # Track slots taken during this batch (in-memory, not yet in DB)
    # key: (lab, day, slot)
    taken: set[tuple[str, str, int]] = set()

    allocated = []
    unallocated = []
    total_seats_used = 0
    total_capacity_used = 0

    for req in sorted_requests:
        name = req.get("name", "")
        role = req.get("role", "student")
        group_size = req.get("group_size", 1)
        n_consecutive = req.get("n_consecutive", 1)
        purpose = req.get("purpose", "")
        pref_day = req.get("preferred_day")
        pref_slot = req.get("preferred_slot")

        # Check if any lab can even fit this group
        max_cap = max((lab["capacity"] for lab in labs_cfg), default=0)
        if group_size > max_cap:
            unallocated.append({
                **req,
                "reason": f"Group size {group_size} exceeds the largest lab capacity ({max_cap}).",
            })
            continue

        # Find candidates, excluding slots already taken in this batch
        found = None
        for candidate in suggest(
            group_size=group_size,
            n_consecutive=n_consecutive,
            week_monday=week_monday,
            timetable_busy=timetable_busy,
            labs_cfg=labs_cfg,
            booking_module=booking_module,
            preferred_day=pref_day,
            preferred_slot=pref_slot,
            include_unverified=include_unverified,
        ):
            lab_id = candidate["lab"]
            day = candidate["day"]
            run = candidate["slots"]

            # Check not taken in this batch
            if any((lab_id, day, s) in taken for s in run):
                continue

            found = candidate
            break

        if found is None:
            # Determine reason
            if n_consecutive > 1:
                reason = (
                    f"No free block of {n_consecutive} consecutive periods available "
                    f"for group size {group_size}."
                )
            else:
                reason = f"No free single slot available for group size {group_size}."
            unallocated.append({**req, "reason": reason})
            continue

        # Reserve slots in batch tracker
        lab_id = found["lab"]
        day = found["day"]
        run = found["slots"]
        lab_cfg = next(l for l in labs_cfg if l["id"] == lab_id)
        cap = lab_cfg["capacity"]

        for s in run:
            taken.add((lab_id, day, s))

        allocated.append({
            **req,
            "lab": lab_id,
            "lab_name": found["lab_name"],
            "day": day,
            "slots": run,
            "score": found["score"],
            "reasons": found["reasons"],
        })
        total_seats_used += group_size * len(run)
        total_capacity_used += cap * len(run)

    seat_efficiency_pct = round(
        total_seats_used / total_capacity_used * 100, 1
    ) if total_capacity_used else 0.0

    committed = False
    if not dry_run and allocated:
        from lab import booking as bm
        if pin != bm._get_pin():
            raise PermissionError("Invalid PIN — batch commit requires the in-charge PIN.")
        for alloc in allocated:
            bm.book_slots(
                lab=alloc["lab"],
                week_monday=week_monday,
                day=alloc["day"],
                slots=alloc["slots"],
                name=alloc["name"],
                role=alloc["role"],
                purpose=alloc.get("purpose", "Batch allocation"),
                group_size=alloc["group_size"],
                timetable_busy=timetable_busy,
                lab_capacity=next(
                    l["capacity"] for l in labs_cfg if l["id"] == alloc["lab"]
                ),
            )
        committed = True

    return {
        "allocated": allocated,
        "unallocated": unallocated,
        "seat_efficiency_pct": seat_efficiency_pct,
        "committed": committed,
        "dry_run": dry_run,
    }
