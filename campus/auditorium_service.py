"""
campus/auditorium_service.py — Business logic and analytics engine for Auditorium Management.

Features:
- Auditorium inventory with AV facility tags, stage dimensions, and maintenance status
- Event scheduling requests with attendee capacity checks and date/time conflict validation
- Multi-step Admin Approval Workflow (Pending -> Approved / Rejected / Cancelled)
- Interactive Event Readiness Checklist (AV test, stage lighting, HVAC, seating, power backup)
- Monthly availability calendar data feed
- Event utilization analytics and department engagement metrics
"""

import logging
from datetime import datetime, date
from . import db
from . import scheduling_service

logger = logging.getLogger(__name__)

STANDARD_CHECKLIST_ITEMS = [
    ("av_system", "Audio-Visual Systems: 4K Projector, Wireless Mics, Sound Mixer Check"),
    ("stage_lighting", "Stage & Podium: Backdrop Banner, Lighting, Lectern Setup"),
    ("hvac_aircon", "HVAC & Temperature: Central Chiller / AC Pre-cooling"),
    ("seating_cleanliness", "Hall Cleanliness: Seating Row Inspection & Sanitization"),
    ("power_backup", "Power Reliability: Silent Generator Backup Standby"),
    ("guest_hospitality", "Guest Hospitality: Green Room Preparation & VIP Seating"),
]


def list_auditoriums() -> list[dict]:
    """Retrieve all campus auditoriums with real-time maintenance indicators."""
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM auditoriums ORDER BY capacity DESC;")
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        item = dict(r)
        maint = scheduling_service.check_maintenance_block(item["id"])
        item["is_under_maintenance"] = bool(maint)
        item["maintenance_info"] = maint
        result.append(item)
    return result


def get_auditorium(auditorium_id: str) -> dict | None:
    """Fetch single auditorium by ID."""
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM auditoriums WHERE id = ?;", (auditorium_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        res = dict(row)
        res["maintenance_info"] = scheduling_service.check_maintenance_block(auditorium_id)
        return res
    return None


def add_or_update_auditorium(data: dict) -> dict:
    """Create or update auditorium record."""
    aud_id = data.get("id", "").strip().upper()
    name = data.get("name", "").strip()
    loc = data.get("location", "").strip()
    cap = int(data.get("capacity", 200))
    stage = data.get("stage_size", "Standard Stage")
    av = data.get("av_facilities", "Audio & Projector")
    gr = 1 if data.get("has_green_room", True) else 0
    status = data.get("status", "available")

    if not aud_id or not name:
        raise ValueError("Auditorium ID and Name are required.")

    conn = db.get_db()
    with conn:
        conn.execute("""
            INSERT INTO auditoriums (id, name, location, capacity, stage_size, av_facilities, has_green_room, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                location=excluded.location,
                capacity=excluded.capacity,
                stage_size=excluded.stage_size,
                av_facilities=excluded.av_facilities,
                has_green_room=excluded.has_green_room,
                status=excluded.status;
        """, (aud_id, name, loc, cap, stage, av, gr, status))
    conn.close()
    return get_auditorium(aud_id)


def request_event(data: dict) -> dict:
    """
    Submit a department event booking request for an auditorium.
    Validates:
    - Auditorium existence
    - Attendee capacity constraint
    - Maintenance availability
    - Time conflict with already approved events
    Generates standard readiness checklist upon submission.
    """
    aud_id = data.get("auditorium_id", "").strip().upper()
    title = data.get("event_title", "").strip()
    event_type = data.get("event_type", "Guest Lecture").strip()
    dept = data.get("department", "Academic Department").strip()
    organizer = data.get("organizer_name", "Faculty In-Charge").strip()
    email = data.get("contact_email", "").strip()
    ev_date = data.get("event_date", "").strip()
    start_t = data.get("start_time", "").strip()
    end_t = data.get("end_time", "").strip()
    attendees = int(data.get("expected_attendees", 0))
    reqs = data.get("special_requirements", "").strip()
    pin = data.get("pin")

    if not aud_id or not title or not ev_date or not start_t or not end_t:
        raise ValueError("Auditorium ID, Event Title, Date, and Start/End times are required.")

    # Validate staff PIN
    if not db.verify_role_pin("staff", pin):
        raise PermissionError("Valid Department Staff or Admin PIN is required to request an event.")

    aud = get_auditorium(aud_id)
    if not aud:
        raise ValueError(f"Auditorium {aud_id} not found.")

    if attendees > aud["capacity"]:
        raise ValueError(
            f"Expected attendees ({attendees}) exceeds auditorium capacity ({aud['capacity']} seats)."
        )

    # Check scheduling availability (maintenance & conflicting approved events)
    chk = scheduling_service.check_auditorium_availability(aud_id, ev_date, start_t, end_t)
    if not chk["available"]:
        raise ValueError(f"Auditorium Unavailable: {chk['reason']}")

    conn = db.get_db()
    with conn:
        cursor = conn.execute("""
            INSERT INTO auditorium_events 
            (auditorium_id, event_title, event_type, department, organizer_name, contact_email, 
             event_date, start_time, end_time, expected_attendees, special_requirements, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending');
        """, (aud_id, title, event_type, dept, organizer, email, ev_date, start_t, end_t, attendees, reqs))
        event_id = cursor.lastrowid

        # Insert readiness checklist items
        checklist_records = [
            (event_id, key, label, 0)
            for key, label in STANDARD_CHECKLIST_ITEMS
        ]
        conn.executemany("""
            INSERT INTO event_checklists (event_id, item_key, item_label, is_completed)
            VALUES (?, ?, ?, ?);
        """, checklist_records)

    conn.close()

    return {
        "status": "success",
        "event_id": event_id,
        "auditorium_id": aud_id,
        "event_title": title,
        "approval_status": "pending",
        "message": f"Event request '{title}' submitted successfully. Awaiting administrative approval."
    }


def review_event_request(event_id: int, action: str, reviewed_by: str, remarks: str, pin: str) -> dict:
    """
    Admin workflow to approve, reject, or cancel an event request.
    Strictly requires Admin PIN.
    """
    if not db.verify_role_pin("admin", pin):
        raise PermissionError("Admin PIN is required to review or approve event requests.")

    action_clean = action.lower().strip()
    if action_clean not in {"approve", "reject", "cancel"}:
        raise ValueError("Invalid action. Must be 'approve', 'reject', or 'cancel'.")

    status_target = "approved" if action_clean == "approve" else ("rejected" if action_clean == "reject" else "cancelled")

    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM auditorium_events WHERE id = ?;", (event_id,))
    event = cursor.fetchone()
    if not event:
        conn.close()
        raise ValueError(f"Event #{event_id} not found.")

    # If approving, re-verify availability
    if status_target == "approved":
        chk = scheduling_service.check_auditorium_availability(
            event["auditorium_id"], event["event_date"], event["start_time"], event["end_time"], exclude_event_id=event_id
        )
        if not chk["available"]:
            conn.close()
            raise ValueError(f"Cannot approve: {chk['reason']}")

    with conn:
        conn.execute("""
            UPDATE auditorium_events 
            SET status = ?, reviewed_by = ?, review_remarks = ?, reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?;
        """, (status_target, reviewed_by, remarks, event_id))

    conn.close()
    return {
        "status": "success",
        "event_id": event_id,
        "new_status": status_target,
        "message": f"Event #{event_id} has been {status_target}."
    }


def list_events(auditorium_id: str = None, status: str = None, from_date: str = None) -> list[dict]:
    """Retrieve event requests with checklist completion percentage."""
    conn = db.get_db()
    cursor = conn.cursor()

    query = """
        SELECT e.*, a.name as auditorium_name, a.capacity as auditorium_capacity,
               (SELECT COUNT(*) FROM event_checklists c WHERE c.event_id = e.id) as total_checklists,
               (SELECT COUNT(*) FROM event_checklists c WHERE c.event_id = e.id AND c.is_completed = 1) as completed_checklists
        FROM auditorium_events e
        JOIN auditoriums a ON e.auditorium_id = a.id
        WHERE 1=1
    """
    params = []

    if auditorium_id:
        query += " AND e.auditorium_id = ?"
        params.append(auditorium_id)
    if status:
        query += " AND e.status = ?"
        params.append(status)
    if from_date:
        query += " AND e.event_date >= ?"
        params.append(from_date)

    query += " ORDER BY e.event_date ASC, e.start_time ASC;"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        item = dict(r)
        tot = item["total_checklists"] or 0
        comp = item["completed_checklists"] or 0
        item["checklist_pct"] = round((comp / tot * 100), 0) if tot > 0 else 0
        result.append(item)
    return result


def get_event_details(event_id: int) -> dict | None:
    """Retrieve single event with its full readiness checklist."""
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT e.*, a.name as auditorium_name, a.location as auditorium_location, a.capacity as auditorium_capacity
        FROM auditorium_events e
        JOIN auditoriums a ON e.auditorium_id = a.id
        WHERE e.id = ?;
    """, (event_id,))
    ev = cursor.fetchone()
    if not ev:
        conn.close()
        return None

    res = dict(ev)

    cursor.execute("""
        SELECT id, item_key, item_label, is_completed, verified_by, updated_at
        FROM event_checklists
        WHERE event_id = ?
        ORDER BY id ASC;
    """, (event_id,))
    res["checklist"] = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return res


def toggle_checklist_item(event_id: int, item_key: str, is_completed: bool, verified_by: str, pin: str) -> dict:
    """Update event readiness checklist item status."""
    if not db.verify_role_pin("staff", pin) and not db.verify_role_pin("admin", pin):
        raise PermissionError("Staff or Admin authorization PIN is required to update checklist.")

    conn = db.get_db()
    with conn:
        conn.execute("""
            UPDATE event_checklists 
            SET is_completed = ?, verified_by = ?, updated_at = CURRENT_TIMESTAMP
            WHERE event_id = ? AND item_key = ?;
        """, (1 if is_completed else 0, verified_by, event_id, item_key))
    conn.close()
    return {"status": "success", "event_id": event_id, "item_key": item_key, "is_completed": is_completed}


def get_auditorium_calendar_events(month: int = None, year: int = None) -> list[dict]:
    """Retrieve approved events formatted for calendar rendering."""
    conn = db.get_db()
    cursor = conn.cursor()

    query = """
        SELECT e.id, e.auditorium_id, e.event_title, e.event_type, e.department, 
               e.event_date, e.start_time, e.end_time, e.expected_attendees, e.status,
               a.name as auditorium_name
        FROM auditorium_events e
        JOIN auditoriums a ON e.auditorium_id = a.id
        WHERE e.status = 'approved'
    """
    params = []

    if year and month:
        prefix = f"{year:04d}-{month:02d}%"
        query += " AND e.event_date LIKE ?"
        params.append(prefix)

    query += " ORDER BY e.event_date ASC, e.start_time ASC;"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_auditorium_analytics() -> dict:
    """Compute comprehensive analytics for campus auditorium utilization."""
    conn = db.get_db()
    cursor = conn.cursor()

    # Total Auditoriums
    cursor.execute("SELECT COUNT(*), SUM(capacity) FROM auditoriums;")
    a_stat = cursor.fetchone()
    total_auditoriums = a_stat[0] or 0
    total_capacity = a_stat[1] or 0

    # Event counts by status
    cursor.execute("""
        SELECT status, COUNT(*) as cnt
        FROM auditorium_events
        GROUP BY status;
    """)
    status_counts = {r["status"]: r["cnt"] for r in cursor.fetchall()}

    # Total approved events and attendees
    cursor.execute("""
        SELECT COUNT(*), SUM(expected_attendees)
        FROM auditorium_events
        WHERE status = 'approved';
    """)
    app_stat = cursor.fetchone()
    approved_count = app_stat[0] or 0
    total_attendees = app_stat[1] or 0

    # Department breakdown
    cursor.execute("""
        SELECT department, COUNT(*) as event_count
        FROM auditorium_events
        WHERE status = 'approved'
        GROUP BY department
        ORDER BY event_count DESC
        LIMIT 6;
    """)
    dept_distribution = [dict(r) for r in cursor.fetchall()]

    # Event Type breakdown
    cursor.execute("""
        SELECT event_type, COUNT(*) as cnt
        FROM auditorium_events
        WHERE status = 'approved'
        GROUP BY event_type
        ORDER BY cnt DESC;
    """)
    type_distribution = [dict(r) for r in cursor.fetchall()]

    # Per-auditorium event distribution
    cursor.execute("""
        SELECT a.id, a.name, a.capacity,
               COUNT(e.id) as approved_events,
               COALESCE(SUM(e.expected_attendees), 0) as total_attendees
        FROM auditoriums a
        LEFT JOIN auditorium_events e ON a.id = e.auditorium_id AND e.status = 'approved'
        GROUP BY a.id
        ORDER BY approved_events DESC;
    """)
    aud_breakdown = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return {
        "total_auditoriums": total_auditoriums,
        "total_capacity": total_capacity,
        "approved_events": approved_count,
        "pending_requests": status_counts.get("pending", 0),
        "rejected_requests": status_counts.get("rejected", 0),
        "total_attendees": total_attendees,
        "department_distribution": dept_distribution,
        "type_distribution": type_distribution,
        "auditorium_breakdown": aud_breakdown
    }
