"""
lab/routes.py — Flask Blueprint for all lab utilization endpoints.

Registered in app.py as:
    from lab.routes import lab_bp
    app.register_blueprint(lab_bp)

Page routes:  /lab/dashboard, /lab/booking
API routes:   /api/labs, /api/week, /api/status, /api/book, /api/bookings,
              /api/book/<id>, /api/smart/suggest, /api/smart/batch,
              /api/exam_blocks
Download:     /download/lab-report
"""

import json
import os
import logging
from datetime import date, timedelta
from functools import lru_cache

from flask import (
    Blueprint, render_template, request, jsonify,
    send_file, current_app, g, redirect
)

from lab import parser as tt_parser
from lab import analytics as lab_analytics
from lab import booking as bm
from lab import allocator as alloc
from pdf_generator import create_lab_report

logger = logging.getLogger(__name__)

# ─── Blueprint ───────────────────────────────────────────────────────────────

lab_bp = Blueprint("lab", __name__, url_prefix="")

# ─── Paths (relative to the app's root directory) ───────────────────────────

def _data(filename: str) -> str:
    return os.path.join(current_app.root_path, "data", filename)


def _outputs(filename: str) -> str:
    return os.path.join(current_app.root_path, "outputs", filename)


# ─── Cached parsed data (re-parse only on startup) ──────────────────────────

_sessions_cache: list[dict] | None = None
_analytics_cache: dict | None = None
_labs_cfg_cache: list[dict] | None = None
_timetable_busy_cache: set | None = None


def _load_data():
    """Parse timetable and compute analytics once per process."""
    global _sessions_cache, _analytics_cache, _labs_cfg_cache, _timetable_busy_cache

    if _sessions_cache is not None:
        return

    labs_json = _data("labs.json")
    timetable = _data("timetable.xlsx")
    extra_csv = _data("extra_sessions.csv")

    with open(labs_json, encoding="utf-8-sig") as f:
        labs_cfg = json.load(f)["labs"]
    _labs_cfg_cache = labs_cfg

    if not os.path.exists(timetable):
        logger.warning("timetable.xlsx not found — analytics will be empty.")
        _sessions_cache = []
    else:
        try:
            _sessions_cache = tt_parser.parse_timetable(timetable, labs_json, extra_csv)
        except Exception as exc:
            logger.error("Timetable parse error: %s", exc)
            _sessions_cache = []

    _analytics_cache = lab_analytics.compute_analytics(_sessions_cache, labs_cfg)

    # Build timetable_busy set: (lab, day, slot1) for all parsed sessions
    _timetable_busy_cache = {
        (s["lab"], s["day"], s["slot1"]) for s in _sessions_cache
    }

    logger.info("Lab timetable loaded: %d sessions", len(_sessions_cache))


def _get_analytics() -> dict:
    _load_data()
    return _analytics_cache


def _get_labs_cfg() -> list[dict]:
    _load_data()
    return _labs_cfg_cache


def _get_timetable_busy() -> set:
    _load_data()
    return _timetable_busy_cache


def _current_monday() -> str:
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


def _require_pin() -> str | None:
    """Extract X-Pin header. Returns None if missing."""
    return request.headers.get("X-Pin")


# ─── Page routes ─────────────────────────────────────────────────────────────

@lab_bp.route("/lab/dashboard")
def lab_dashboard():
    _load_data()
    return redirect("/?tab=analytics#analytics")


@lab_bp.route("/lab/booking")
def lab_booking():
    _load_data()
    return redirect("/?tab=booking#booking")


# ─── API: Labs list ──────────────────────────────────────────────────────────

@lab_bp.route("/api/labs")
def api_labs():
    return jsonify(_get_labs_cfg())


# ─── API: Week grid ──────────────────────────────────────────────────────────

@lab_bp.route("/api/week")
def api_week():
    """
    GET /api/week?lab=L1&week=2026-10-27
    Returns a 5×9 grid of slot states for the given lab and week.
    """
    lab_id = request.args.get("lab")
    week = request.args.get("week", _current_monday())

    if not lab_id:
        return jsonify({"error": "lab parameter required"}), 400

    lab_cfg = next((l for l in _get_labs_cfg() if l["id"] == lab_id), None)
    if not lab_cfg:
        return jsonify({"error": f"Unknown lab: {lab_id}"}), 404

    # Normalize week to Monday
    try:
        week_monday = bm._monday_of_week(week)
    except Exception:
        return jsonify({"error": "Invalid week date"}), 400

    grid = bm.get_week_grid(
        lab_id, week_monday, _get_timetable_busy(), lab_cfg["capacity"]
    )
    return jsonify({"lab": lab_id, "week_monday": week_monday, "grid": grid})


# ─── API: Set slot state (in-charge) ─────────────────────────────────────────

@lab_bp.route("/api/status", methods=["POST"])
def api_set_status():
    """
    POST /api/status
    Headers: X-Pin: <pin>
    Body: {lab, week, day, slot, state, note}
    state: in_use | empty | maintenance | reset
    """
    data = request.get_json(force=True) or {}
    pin = _require_pin()
    lab_id = data.get("lab")
    week = data.get("week", _current_monday())
    day = data.get("day")
    slot = data.get("slot")
    state = data.get("state")
    note = data.get("note", "")

    if not all([lab_id, day, slot, state]):
        return jsonify({"error": "lab, day, slot, state required"}), 400

    try:
        slot = int(slot)
        week_monday = bm._monday_of_week(week)
        if state == "reset":
            bm.reset_slot(lab_id, week_monday, day, slot, pin)
        else:
            bm.set_slot_state(lab_id, week_monday, day, slot, state, note, pin)
        return jsonify({"ok": True})
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ─── API: Book slots ─────────────────────────────────────────────────────────

@lab_bp.route("/api/book", methods=["POST"])
def api_book():
    """
    POST /api/book
    Body: {lab, week, day, slots: [1,2], name, role, purpose, group_size}
    """
    data = request.get_json(force=True) or {}
    lab_id = data.get("lab")
    week = data.get("week", _current_monday())
    day = data.get("day")
    slots = data.get("slots", [])
    name = data.get("name", "")
    role = data.get("role", "student")
    purpose = data.get("purpose", "")
    group_size = data.get("group_size", 1)

    if not all([lab_id, day, slots, name]):
        return jsonify({"error": "lab, day, slots, name required"}), 400

    lab_cfg = next((l for l in _get_labs_cfg() if l["id"] == lab_id), None)
    if not lab_cfg:
        return jsonify({"error": f"Unknown lab: {lab_id}"}), 404

    try:
        slots = [int(s) for s in slots]
        week_monday = bm._monday_of_week(week)
        ids = bm.book_slots(
            lab=lab_id,
            week_monday=week_monday,
            day=day,
            slots=slots,
            name=name,
            role=role,
            purpose=purpose,
            group_size=int(group_size),
            timetable_busy=_get_timetable_busy(),
            lab_capacity=lab_cfg["capacity"],
        )
        return jsonify({"ok": True, "booking_ids": ids}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return jsonify({"error": "Slot already booked (double booking not allowed)."}), 409
        return jsonify({"error": str(e)}), 500


# ─── API: List bookings ───────────────────────────────────────────────────────

@lab_bp.route("/api/bookings")
def api_bookings():
    """GET /api/bookings?lab=L1&week=2026-10-27"""
    lab_id = request.args.get("lab")
    week = request.args.get("week", _current_monday())
    if not lab_id:
        return jsonify({"error": "lab required"}), 400
    try:
        week_monday = bm._monday_of_week(week)
    except Exception:
        return jsonify({"error": "Invalid week"}), 400
    return jsonify(bm.list_bookings(lab_id, week_monday))


# ─── API: Cancel booking ──────────────────────────────────────────────────────

@lab_bp.route("/api/book/<int:booking_id>", methods=["DELETE"])
def api_cancel_booking(booking_id: int):
    """
    DELETE /api/book/<id>
    Headers: X-Pin (optional, for in-charge override)
    Body: {name} (for self-cancel)
    """
    data = request.get_json(force=True) or {}
    pin = _require_pin()
    name = data.get("name", "")
    try:
        bm.cancel_booking(booking_id, name, pin, _get_timetable_busy())
        return jsonify({"ok": True})
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403


# ─── API: Smart suggest ───────────────────────────────────────────────────────

@lab_bp.route("/api/smart/suggest", methods=["POST"])
def api_smart_suggest():
    """
    POST /api/smart/suggest
    Body: {group_size, n_consecutive, week (opt), preferred_day (opt),
           preferred_slot (opt), include_unverified (opt)}
    """
    data = request.get_json(force=True) or {}
    group_size = int(data.get("group_size", 1))
    n_consecutive = int(data.get("n_consecutive", 1))
    week = data.get("week", _current_monday())
    pref_day = data.get("preferred_day")
    pref_slot = data.get("preferred_slot")
    if pref_slot:
        pref_slot = int(pref_slot)
    include_unverified = bool(data.get("include_unverified", False))

    try:
        week_monday = bm._monday_of_week(week)
    except Exception:
        return jsonify({"error": "Invalid week"}), 400

    results = alloc.suggest(
        group_size=group_size,
        n_consecutive=n_consecutive,
        week_monday=week_monday,
        timetable_busy=_get_timetable_busy(),
        labs_cfg=_get_labs_cfg(),
        booking_module=bm,
        preferred_day=pref_day,
        preferred_slot=pref_slot,
        include_unverified=include_unverified,
    )
    return jsonify(results)


# ─── API: Batch allocation ────────────────────────────────────────────────────

@lab_bp.route("/api/smart/batch", methods=["POST"])
def api_smart_batch():
    """
    POST /api/smart/batch
    Headers: X-Pin (required for commit)
    Body: {requests: [...], week (opt), dry_run: true/false,
           include_unverified: false}
    """
    data = request.get_json(force=True) or {}
    requests_list = data.get("requests", [])
    week = data.get("week", _current_monday())
    dry_run = bool(data.get("dry_run", True))
    include_unverified = bool(data.get("include_unverified", False))
    pin = _require_pin()

    try:
        week_monday = bm._monday_of_week(week)
    except Exception:
        return jsonify({"error": "Invalid week"}), 400

    try:
        result = alloc.batch_allocate(
            requests=requests_list,
            week_monday=week_monday,
            timetable_busy=_get_timetable_busy(),
            labs_cfg=_get_labs_cfg(),
            booking_module=bm,
            include_unverified=include_unverified,
            dry_run=dry_run,
            pin=pin,
        )
        return jsonify(result)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Exam blocks (integration hook) ─────────────────────────────────────

@lab_bp.route("/api/exam_blocks", methods=["POST"])
def api_exam_blocks():
    """
    POST /api/exam_blocks
    Headers: X-Pin required
    Body: {lab, exam_date, slots: [1,2,...], exam_id}

    This is the integration hook for the exam seat allocation system.
    It marks lab slots as 'exam' state so they cannot be booked.
    Can also be called directly from Python:
        from lab.booking import mark_exam_slots
        mark_exam_slots("L1", "2026-11-15", [1,2,3,4,6,7,8,9], "EXAM-001", pin)
    """
    data = request.get_json(force=True) or {}
    pin = _require_pin()
    lab_id = data.get("lab")
    exam_date = data.get("exam_date")
    slots = data.get("slots", [])
    exam_id = data.get("exam_id", "")

    if not all([lab_id, exam_date, slots]):
        return jsonify({"error": "lab, exam_date, slots required"}), 400

    lab_cfg = next((l for l in _get_labs_cfg() if l["id"] == lab_id), None)
    if not lab_cfg:
        return jsonify({"error": f"Unknown lab: {lab_id}"}), 404

    try:
        bm.mark_exam_slots(lab_id, exam_date, [int(s) for s in slots], exam_id, pin)
        return jsonify({"ok": True})
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Download: Lab Utilization Report PDF ────────────────────────────────────

@lab_bp.route("/download/lab-report")
def download_lab_report():
    """Generate and download the Lab Utilization Report PDF."""
    out = _outputs("lab_report.pdf")
    analytics = _get_analytics()
    sessions = _sessions_cache or []
    try:
        create_lab_report(analytics, sessions, out)
        return send_file(out, as_attachment=True, download_name="lab_utilization_report.pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Analytics JSON (for frontend fetch) ─────────────────────────────────

@lab_bp.route("/api/analytics")
def api_analytics():
    """GET /api/analytics — returns full analytics dict for all labs."""
    a = _get_analytics()
    # Convert sessions lists to serializable form (they're already dicts)
    return jsonify(a)


# ─── API: Free labs finder ────────────────────────────────────────────────────

@lab_bp.route("/api/free_labs")
def api_free_labs():
    """GET /api/free_labs?day=Mon&slot=6 — return labs free at this timetable slot."""
    day = request.args.get("day")
    slot = request.args.get("slot")
    if not day or not slot:
        return jsonify({"error": "day and slot required"}), 400
    try:
        slot = int(slot)
    except ValueError:
        return jsonify({"error": "slot must be integer"}), 400
    free = lab_analytics.get_free_labs_for_slot(_get_analytics(), day, slot)
    return jsonify({"free_labs": free})
