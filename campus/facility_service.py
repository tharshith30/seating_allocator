"""
campus/facility_service.py — Business logic and tracking engine for Facility & Asset Management.

Features:
- Campus asset inventory across Classrooms, Auditoriums, and Labs
- Maintenance request ticketing with automatic downtime space blocking
- Admin verification and technician/staff assignment workflow
- Multi-state maintenance lifecycle tracking (reported -> assigned -> in_progress -> on_hold -> resolved -> closed)
- Automatic room downtime unblocking when critical tickets are resolved
- Preventive maintenance recurring schedule and overdue alerts
- Audit history logging for accreditation and facility tracking
"""

import logging
from datetime import datetime, date, timedelta
from . import db

logger = logging.getLogger(__name__)


def list_assets(category: str = None, location_type: str = None, location_id: str = None, condition: str = None) -> list[dict]:
    """Retrieve campus asset inventory with optional category and location filters."""
    conn = db.get_db()
    cursor = conn.cursor()

    query = "SELECT * FROM facility_assets WHERE 1=1"
    params = []

    if category:
        query += " AND category = ?"
        params.append(category)
    if location_type:
        query += " AND location_type = ?"
        params.append(location_type)
    if location_id:
        query += " AND location_id = ?"
        params.append(location_id)
    if condition:
        query += " AND condition = ?"
        params.append(condition)

    query += " ORDER BY location_id ASC, category ASC;"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_asset(asset_id: str) -> dict | None:
    """Fetch single asset by ID."""
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM facility_assets WHERE id = ?;", (asset_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def add_or_update_asset(data: dict) -> dict:
    """Register or update an infrastructure asset."""
    asset_id = data.get("id", "").strip().upper()
    name = data.get("asset_name", "").strip()
    cat = data.get("category", "IT/AV").strip()
    loc_type = data.get("location_type", "classroom").strip()
    loc_id = data.get("location_id", "").strip()
    sn = data.get("serial_number", "").strip()
    cond = data.get("condition", "Good").strip()
    inst_date = data.get("install_date") or str(date.today())
    last_srv = data.get("last_serviced_date") or str(date.today())

    if not asset_id or not name or not loc_id:
        raise ValueError("Asset ID, Name, and Location ID are required.")

    conn = db.get_db()
    with conn:
        conn.execute("""
            INSERT INTO facility_assets 
            (id, asset_name, category, location_type, location_id, serial_number, condition, install_date, last_serviced_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                asset_name=excluded.asset_name,
                category=excluded.category,
                location_type=excluded.location_type,
                location_id=excluded.location_id,
                serial_number=excluded.serial_number,
                condition=excluded.condition,
                last_serviced_date=excluded.last_serviced_date;
        """, (asset_id, name, cat, loc_type, loc_id, sn, cond, inst_date, last_srv))
    conn.close()
    return get_asset(asset_id)


def submit_maintenance_request(data: dict) -> dict:
    """
    Log a maintenance issue or service request.
    If priority is 'Critical' or 'High', or blocks_space=True,
    the target classroom or auditorium is marked 'under_maintenance',
    immediately preventing bookings in the shared scheduling service!
    """
    asset_id = data.get("asset_id") or None
    loc_type = data.get("location_type", "classroom").strip().lower()
    loc_id = data.get("location_id", "").strip()
    category = data.get("category", "IT/AV").strip()
    title = data.get("issue_title", "").strip()
    desc = data.get("description", "").strip()
    priority = data.get("priority", "Medium").strip().capitalize()
    blocks = bool(data.get("blocks_space", False))
    rep_by = data.get("reported_by", "Campus Staff").strip()
    rep_role = data.get("reported_by_role", "Department Staff")
    pin = data.get("pin")

    if not loc_id or not title:
        raise ValueError("Location ID and Issue Title are required.")

    # Any authenticated role can report maintenance (Staff, Maintenance, or Admin)
    if not db.verify_role_pin("staff", pin) and not db.verify_role_pin("maintenance", pin):
        raise PermissionError("Valid authorization PIN is required to submit a maintenance request.")

    # Auto-block space if Critical or High
    if priority in {"Critical", "High"}:
        blocks = True

    conn = db.get_db()
    cursor = conn.cursor()

    # Generate sequential ticket number
    cursor.execute("SELECT COUNT(*) FROM maintenance_requests;")
    seq = (cursor.fetchone()[0] or 0) + 1
    ticket_no = f"TKT-{date.today().year}-{seq:04d}"

    with conn:
        cursor.execute("""
            INSERT INTO maintenance_requests 
            (ticket_no, asset_id, location_type, location_id, category, issue_title, description, 
             priority, blocks_space, status, reported_by, reported_by_role)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'reported', ?, ?);
        """, (ticket_no, asset_id, loc_type, loc_id, category, title, desc, priority, 1 if blocks else 0, rep_by, rep_role))
        req_id = cursor.lastrowid

        # Update space status in classrooms or auditoriums if blocking downtime
        if blocks:
            if loc_type == "classroom":
                conn.execute("UPDATE classrooms SET status = 'under_maintenance' WHERE id = ?;", (loc_id,))
            elif loc_type == "auditorium":
                conn.execute("UPDATE auditoriums SET status = 'under_maintenance' WHERE id = ?;", (loc_id,))

        # Audit log
        conn.execute("""
            INSERT INTO maintenance_logs (ticket_no, action, updated_by, role, details)
            VALUES (?, 'created', ?, ?, ?);
        """, (ticket_no, rep_by, rep_role, f"Issue reported with {priority} priority. Space downtime blocked: {blocks}"))

    conn.close()

    return {
        "status": "success",
        "ticket_no": ticket_no,
        "request_id": req_id,
        "location_id": loc_id,
        "priority": priority,
        "blocks_space": blocks,
        "message": f"Maintenance ticket {ticket_no} logged. Location {loc_id} status updated."
    }


def assign_maintenance_staff(ticket_no: str, assigned_to: str, estimated_completion: str, admin_name: str, pin: str) -> dict:
    """Admin assigns ticket to maintenance technician and sets target completion date."""
    if not db.verify_role_pin("admin", pin):
        raise PermissionError("Admin PIN is required to assign maintenance staff.")

    conn = db.get_db()
    with conn:
        conn.execute("""
            UPDATE maintenance_requests 
            SET status = 'assigned', assigned_to = ?, estimated_completion = ?
            WHERE ticket_no = ?;
        """, (assigned_to, estimated_completion, ticket_no))

        conn.execute("""
            INSERT INTO maintenance_logs (ticket_no, action, updated_by, role, details)
            VALUES (?, 'assigned', ?, 'Admin', ?);
        """, (ticket_no, admin_name, f"Assigned to {assigned_to}. Target completion: {estimated_completion}"))
    conn.close()

    return {
        "status": "success",
        "ticket_no": ticket_no,
        "assigned_to": assigned_to,
        "message": f"Ticket {ticket_no} assigned to {assigned_to}."
    }


def update_maintenance_status(ticket_no: str, new_status: str, notes: str, updated_by: str, role: str, pin: str) -> dict:
    """
    Update ticket status (in_progress, on_hold, resolved, closed).
    When resolved or closed, checks if the space can be unblocked!
    """
    if not db.verify_role_pin("maintenance", pin) and not db.verify_role_pin("admin", pin):
        raise PermissionError("Maintenance Staff or Admin PIN is required to update ticket status.")

    new_st = new_status.lower().strip()
    valid_statuses = {"reported", "assigned", "in_progress", "on_hold", "resolved", "closed"}
    if new_st not in valid_statuses:
        raise ValueError(f"Invalid status '{new_st}'. Must be one of: {', '.join(valid_statuses)}")

    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM maintenance_requests WHERE ticket_no = ?;", (ticket_no,))
    ticket = cursor.fetchone()
    if not ticket:
        conn.close()
        raise ValueError(f"Ticket {ticket_no} not found.")

    with conn:
        if new_st in {"resolved", "closed"}:
            conn.execute("""
                UPDATE maintenance_requests 
                SET status = ?, resolution_notes = ?, resolved_at = CURRENT_TIMESTAMP
                WHERE ticket_no = ?;
            """, (new_st, notes, ticket_no))

            # Check if any OTHER active blocking tickets exist for this space
            cursor.execute("""
                SELECT COUNT(*) FROM maintenance_requests 
                WHERE location_id = ? 
                  AND status IN ('reported', 'assigned', 'in_progress', 'on_hold')
                  AND (priority IN ('Critical', 'High') OR blocks_space = 1)
                  AND ticket_no != ?;
            """, (ticket["location_id"], ticket_no))
            other_blocks = cursor.fetchone()[0] or 0

            # If no other blocking issues, restore space to 'available'
            if other_blocks == 0:
                if ticket["location_type"] == "classroom":
                    conn.execute("UPDATE classrooms SET status = 'available' WHERE id = ?;", (ticket["location_id"],))
                elif ticket["location_type"] == "auditorium":
                    conn.execute("UPDATE auditoriums SET status = 'available' WHERE id = ?;", (ticket["location_id"],))
        else:
            conn.execute("""
                UPDATE maintenance_requests 
                SET status = ?
                WHERE ticket_no = ?;
            """, (new_st, ticket_no))

        # Audit log
        conn.execute("""
            INSERT INTO maintenance_logs (ticket_no, action, updated_by, role, details)
            VALUES (?, ?, ?, ?, ?);
        """, (ticket_no, f"status_{new_st}", updated_by, role, notes or f"Status changed to {new_st}"))

    conn.close()

    return {
        "status": "success",
        "ticket_no": ticket_no,
        "new_status": new_st,
        "message": f"Ticket {ticket_no} status updated to {new_st}."
    }


def list_maintenance_requests(status: str = None, priority: str = None, location_id: str = None) -> list[dict]:
    """Retrieve maintenance tickets with optional status and priority filters."""
    conn = db.get_db()
    cursor = conn.cursor()

    query = "SELECT * FROM maintenance_requests WHERE 1=1"
    params = []

    if status:
        query += " AND status = ?"
        params.append(status)
    if priority:
        query += " AND priority = ?"
        params.append(priority)
    if location_id:
        query += " AND location_id = ?"
        params.append(location_id)

    query += " ORDER BY CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END, created_at DESC;"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_maintenance_ticket_details(ticket_no: str) -> dict | None:
    """Fetch ticket details along with full audit log trail."""
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM maintenance_requests WHERE ticket_no = ?;", (ticket_no,))
    ticket = cursor.fetchone()
    if not ticket:
        conn.close()
        return None

    res = dict(ticket)
    cursor.execute("SELECT * FROM maintenance_logs WHERE ticket_no = ? ORDER BY timestamp ASC;", (ticket_no,))
    res["logs"] = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return res


def list_preventive_maintenance() -> list[dict]:
    """Retrieve scheduled preventive maintenance with computed overdue flags."""
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM preventive_maintenance ORDER BY next_due_date ASC;")
    rows = cursor.fetchall()
    conn.close()

    today_str = str(date.today())
    result = []
    for r in rows:
        item = dict(r)
        if item["status"] != "completed" and item["next_due_date"] < today_str:
            item["is_overdue"] = True
            item["status"] = "overdue"
        else:
            item["is_overdue"] = False
        result.append(item)
    return result


def complete_preventive_maintenance(pm_id: int, conducted_by: str, notes: str, pin: str) -> dict:
    """Mark a preventive maintenance inspection complete and advance its next due date."""
    if not db.verify_role_pin("maintenance", pin) and not db.verify_role_pin("admin", pin):
        raise PermissionError("Maintenance Staff or Admin PIN required to complete PM task.")

    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM preventive_maintenance WHERE id = ?;", (pm_id,))
    pm = cursor.fetchone()
    if not pm:
        conn.close()
        raise ValueError(f"Preventive maintenance task #{pm_id} not found.")

    freq = pm["frequency_days"] or 30
    next_due = str(date.today() + timedelta(days=freq))
    today_str = str(date.today())

    with conn:
        conn.execute("""
            UPDATE preventive_maintenance 
            SET last_conducted = ?, next_due_date = ?, status = 'pending'
            WHERE id = ?;
        """, (today_str, next_due, pm_id))

        conn.execute("""
            INSERT INTO maintenance_logs (ticket_no, action, updated_by, role, details)
            VALUES (?, 'pm_completed', ?, 'Maintenance Staff', ?);
        """, (f"PM-{pm_id}", conducted_by, f"Preventive check '{pm['title']}' completed. Next due date set to {next_due}. Notes: {notes}"))

    conn.close()

    return {
        "status": "success",
        "pm_id": pm_id,
        "title": pm["title"],
        "next_due_date": next_due,
        "message": f"Preventive maintenance completed. Next inspection due: {next_due}."
    }


def get_facility_analytics() -> dict:
    """Compute infrastructure metrics, ticket resolution rates, and downtime tracking."""
    conn = db.get_db()
    cursor = conn.cursor()

    # Asset counts by category
    cursor.execute("""
        SELECT category, COUNT(*) as cnt,
               SUM(CASE WHEN condition = 'Good' THEN 1 ELSE 0 END) as good_cnt,
               SUM(CASE WHEN condition IN ('Needs Repair', 'Critical') THEN 1 ELSE 0 END) as repair_cnt
        FROM facility_assets
        GROUP BY category;
    """)
    asset_breakdown = [dict(r) for r in cursor.fetchall()]

    # Tickets breakdown by status
    cursor.execute("""
        SELECT status, COUNT(*) as cnt
        FROM maintenance_requests
        GROUP BY status;
    """)
    status_counts = {r["status"]: r["cnt"] for r in cursor.fetchall()}

    # Tickets breakdown by priority
    cursor.execute("""
        SELECT priority, COUNT(*) as cnt
        FROM maintenance_requests
        WHERE status IN ('reported', 'assigned', 'in_progress', 'on_hold')
        GROUP BY priority;
    """)
    priority_counts = {r["priority"]: r["cnt"] for r in cursor.fetchall()}

    # Currently blocked spaces
    cursor.execute("""
        SELECT DISTINCT location_id, location_type, priority, issue_title
        FROM maintenance_requests
        WHERE status IN ('reported', 'assigned', 'in_progress', 'on_hold')
          AND (priority IN ('Critical', 'High') OR blocks_space = 1);
    """)
    blocked_spaces = [dict(r) for r in cursor.fetchall()]

    # PM statistics
    cursor.execute("SELECT COUNT(*) FROM preventive_maintenance;")
    total_pm = cursor.fetchone()[0] or 0
    today_str = str(date.today())
    cursor.execute("SELECT COUNT(*) FROM preventive_maintenance WHERE next_due_date < ?;", (today_str,))
    overdue_pm = cursor.fetchone()[0] or 0

    conn.close()

    return {
        "total_assets": sum(a["cnt"] for a in asset_breakdown),
        "asset_breakdown": asset_breakdown,
        "open_tickets": sum(status_counts.get(s, 0) for s in ["reported", "assigned", "in_progress", "on_hold"]),
        "resolved_tickets": status_counts.get("resolved", 0) + status_counts.get("closed", 0),
        "status_counts": status_counts,
        "priority_counts": priority_counts,
        "blocked_spaces_count": len(blocked_spaces),
        "blocked_spaces": blocked_spaces,
        "preventive_maintenance_total": total_pm,
        "preventive_maintenance_overdue": overdue_pm
    }

