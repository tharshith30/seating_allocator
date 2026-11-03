"""
campus/scheduling_service.py — Shared resource scheduling and cross-module conflict detection engine.

Responsibilities:
- Evaluates availability for Classrooms, Auditoriums, and Campus Spaces.
- Enforces cross-module conflict detection:
  1. Facility Maintenance Downtime: Blocks spaces having active Critical/High tickets or blocks_space=1.
  2. Academic Timetable Lectures: Regular classes scheduled in classroom_schedules.
  3. Ad-hoc Classroom Bookings: Confirmed department requests.
  4. Auditorium Approved Events: Approved multi-hour/full-day campus gatherings.
"""

import logging
from datetime import datetime, date
from . import db

logger = logging.getLogger(__name__)

# Standard 9-slot academic schedule (Slot 5 = Lunch)
STANDARD_SLOTS = {
    1: {"name": "Slot 1", "start": "09:00", "end": "09:50", "is_lunch": False},
    2: {"name": "Slot 2", "start": "09:50", "end": "10:40", "is_lunch": False},
    3: {"name": "Slot 3", "start": "10:50", "end": "11:40", "is_lunch": False},
    4: {"name": "Slot 4", "start": "11:40", "end": "12:30", "is_lunch": False},
    5: {"name": "Slot 5 (Lunch)", "start": "12:30", "end": "13:20", "is_lunch": True},
    6: {"name": "Slot 6", "start": "13:20", "end": "14:10", "is_lunch": False},
    7: {"name": "Slot 7", "start": "14:10", "end": "15:00", "is_lunch": False},
    8: {"name": "Slot 8", "start": "15:10", "end": "16:00", "is_lunch": False},
    9: {"name": "Slot 9", "start": "16:00", "end": "16:50", "is_lunch": False},
}

DAYS_MAP = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def parse_date_to_day(target_date_str: str) -> str:
    """Convert YYYY-MM-DD to three-letter weekday (e.g. 'Mon')."""
    try:
        dt = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        return DAYS_MAP[dt.weekday()]
    except Exception:
        return "Mon"


def check_maintenance_block(location_id: str) -> dict | None:
    """
    Check if a room or auditorium has an active maintenance request
    that causes downtime (Critical / High priority or blocks_space=1).
    """
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ticket_no, issue_title, category, priority, status, assigned_to, estimated_completion
        FROM maintenance_requests
        WHERE location_id = ?
          AND status IN ('reported', 'assigned', 'in_progress', 'on_hold')
          AND (priority IN ('Critical', 'High') OR blocks_space = 1)
        ORDER BY CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 ELSE 3 END
        LIMIT 1;
    """, (location_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "is_blocked": True,
            "ticket_no": row["ticket_no"],
            "issue_title": row["issue_title"],
            "category": row["category"],
            "priority": row["priority"],
            "status": row["status"],
            "assigned_to": row["assigned_to"] or "Unassigned",
            "estimated_completion": row["estimated_completion"] or "Pending estimation",
            "message": f"Downtime Active: {row['issue_title']} ({row['priority']} Priority Ticket #{row['ticket_no']})"
        }
    return None


def check_classroom_availability(classroom_id: str, booking_date: str, slot_start: int, slot_end: int) -> dict:
    """
    Check if a classroom is available for the given date and slot range (slot_start to slot_end inclusive).
    Validates:
    1. Maintenance downtime blocks
    2. Regular timetable classes from Excel import
    3. Confirmed ad-hoc bookings
    """
    # 1. Maintenance check
    maint = check_maintenance_block(classroom_id)
    if maint:
        return {
            "available": False,
            "conflict_type": "maintenance",
            "reason": maint["message"],
            "details": maint
        }

    conn = db.get_db()
    cursor = conn.cursor()

    # 2. Check Classroom exists
    cursor.execute("SELECT id, name, seating_capacity, status FROM classrooms WHERE id = ?;", (classroom_id,))
    classroom = cursor.fetchone()
    if not classroom:
        conn.close()
        return {"available": False, "conflict_type": "not_found", "reason": f"Classroom {classroom_id} does not exist."}

    # 3. Check regular academic timetable schedule
    day_name = parse_date_to_day(booking_date)
    cursor.execute("""
        SELECT slot, subject_code, subject_name, section, faculty_name
        FROM classroom_schedules
        WHERE classroom_id = ?
          AND day = ?
          AND slot >= ? AND slot <= ?;
    """, (classroom_id, day_name, slot_start, slot_end))
    classes = cursor.fetchall()

    if classes:
        conflict_list = [
            f"Slot {c['slot']}: {c['subject_code'] or c['subject_name'] or 'Lecture'} ({c['section'] or 'Class'}) by {c['faculty_name'] or 'Faculty'}"
            for c in classes
        ]
        conn.close()
        return {
            "available": False,
            "conflict_type": "timetable",
            "reason": f"Conflict with scheduled academic timetable: {'; '.join(conflict_list)}",
            "conflicts": [dict(c) for c in classes]
        }

    # 4. Check existing confirmed ad-hoc bookings
    cursor.execute("""
        SELECT id, department, booked_by, purpose, slot_start, slot_end
        FROM classroom_bookings
        WHERE classroom_id = ?
          AND booking_date = ?
          AND status = 'confirmed'
          AND NOT (slot_end < ? OR slot_start > ?);
    """, (classroom_id, booking_date, slot_start, slot_end))
    existing_bookings = cursor.fetchall()

    if existing_bookings:
        conflict_list = [
            f"Slots {b['slot_start']}-{b['slot_end']}: {b['department']} ({b['purpose']}) by {b['booked_by']}"
            for b in existing_bookings
        ]
        conn.close()
        return {
            "available": False,
            "conflict_type": "booking",
            "reason": f"Conflict with existing reservation: {'; '.join(conflict_list)}",
            "conflicts": [dict(b) for b in existing_bookings]
        }

    conn.close()
    return {
        "available": True,
        "conflict_type": None,
        "reason": "Classroom is completely free during this period.",
        "classroom": dict(classroom)
    }


def check_auditorium_availability(auditorium_id: str, event_date: str, start_time: str, end_time: str, exclude_event_id: int = None) -> dict:
    """
    Check if an auditorium is available on a specific date between start_time and end_time (HH:MM format).
    Validates:
    1. Maintenance downtime blocks
    2. Overlapping approved events
    """
    # 1. Maintenance check
    maint = check_maintenance_block(auditorium_id)
    if maint:
        return {
            "available": False,
            "conflict_type": "maintenance",
            "reason": maint["message"],
            "details": maint
        }

    conn = db.get_db()
    cursor = conn.cursor()

    # 2. Check Auditorium exists
    cursor.execute("SELECT id, name, capacity, status FROM auditoriums WHERE id = ?;", (auditorium_id,))
    aud = cursor.fetchone()
    if not aud:
        conn.close()
        return {"available": False, "conflict_type": "not_found", "reason": f"Auditorium {auditorium_id} not found."}

    # 3. Check overlapping approved events
    query = """
        SELECT id, event_title, department, start_time, end_time, organizer_name
        FROM auditorium_events
        WHERE auditorium_id = ?
          AND event_date = ?
          AND status = 'approved'
          AND NOT (end_time <= ? OR start_time >= ?)
    """
    params = [auditorium_id, event_date, start_time, end_time]
    if exclude_event_id:
        query += " AND id != ?"
        params.append(exclude_event_id)

    cursor.execute(query, params)
    events = cursor.fetchall()
    conn.close()

    if events:
        conflict_list = [
            f"'{e['event_title']}' ({e['start_time']} - {e['end_time']}) by {e['department']}"
            for e in events
        ]
        return {
            "available": False,
            "conflict_type": "event",
            "reason": f"Time overlaps with approved event: {'; '.join(conflict_list)}",
            "conflicts": [dict(e) for e in events]
        }

    return {
        "available": True,
        "conflict_type": None,
        "reason": "Auditorium is available for this time window.",
        "auditorium": dict(aud)
    }


def get_classroom_daily_timeline(classroom_id: str, target_date: str) -> list[dict]:
    """
    Generate an 9-slot schedule breakdown for a classroom on target_date.
    Each slot indicates whether it is free, regular class, booked, or blocked for maintenance.
    """
    day_name = parse_date_to_day(target_date)
    maint = check_maintenance_block(classroom_id)

    conn = db.get_db()
    cursor = conn.cursor()

    # Load timetable classes for this day
    cursor.execute("""
        SELECT slot, subject_code, subject_name, section, faculty_name
        FROM classroom_schedules
        WHERE classroom_id = ? AND day = ?;
    """, (classroom_id, day_name))
    tt_map = {row["slot"]: dict(row) for row in cursor.fetchall()}

    # Load ad-hoc bookings for this date
    cursor.execute("""
        SELECT slot_start, slot_end, department, booked_by, purpose
        FROM classroom_bookings
        WHERE classroom_id = ? AND booking_date = ? AND status = 'confirmed';
    """, (classroom_id, target_date))
    bookings = cursor.fetchall()
    conn.close()

    timeline = []
    for s_num in range(1, 10):
        slot_info = STANDARD_SLOTS[s_num]
        entry = {
            "slot": s_num,
            "name": slot_info["name"],
            "time_range": f"{slot_info['start']} - {slot_info['end']}",
            "is_lunch": slot_info["is_lunch"],
            "status": "free",
            "title": "Available",
            "subtitle": "",
            "badge_class": "badge-free"
        }

        if slot_info["is_lunch"]:
            entry["status"] = "lunch"
            entry["title"] = "Lunch Break"
            entry["badge_class"] = "badge-lunch"
        elif maint:
            entry["status"] = "maintenance"
            entry["title"] = maint["issue_title"]
            entry["subtitle"] = f"Maintenance ({maint['priority']})"
            entry["badge_class"] = "badge-maint"
        elif s_num in tt_map:
            tt = tt_map[s_num]
            entry["status"] = "timetable"
            entry["title"] = tt["subject_code"] or tt["subject_name"] or "Academic Class"
            entry["subtitle"] = f"{tt['section'] or 'Section'} &bull; {tt['faculty_name'] or 'Faculty'}"
            entry["badge_class"] = "badge-class"
        else:
            # Check if any ad-hoc booking covers this slot
            booked_match = None
            for b in bookings:
                if b["slot_start"] <= s_num <= b["slot_end"]:
                    booked_match = b
                    break
            if booked_match:
                entry["status"] = "booked"
                entry["title"] = booked_match["purpose"]
                entry["subtitle"] = f"{booked_match['department']} ({booked_match['booked_by']})"
                entry["badge_class"] = "badge-booked"

        timeline.append(entry)

    return timeline

