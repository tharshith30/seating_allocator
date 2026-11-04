"""
campus/classroom_service.py — Business logic and analytics engine for Classroom Management.

Features:
- Classroom inventory CRUD, capacity filters, and facility tags
- Timetable import from multi-sheet Excel workbooks (Second_Year, Third_Year, Final_year)
- Slot-based classroom availability search (Slots 1–9, Mon–Sat)
- Conflict-free ad-hoc booking validation against timetable, prior bookings, and maintenance
- Comprehensive classroom utilization analytics and scheduling metrics
"""

import os
import sys
import re
import logging
from datetime import datetime, date

_cached_site = os.path.expanduser(r"~\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages")
if os.path.isdir(_cached_site) and _cached_site not in sys.path:
    sys.path.insert(0, _cached_site)

from . import db
from . import scheduling_service

logger = logging.getLogger(__name__)

_DATA_DIR = os.environ.get("DATA_DIR")
if _DATA_DIR and os.path.exists(os.path.join(_DATA_DIR, "timetable.xlsx")):
    TIMETABLE_FILE = os.path.join(_DATA_DIR, "timetable.xlsx")
else:
    TIMETABLE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "timetable.xlsx")

# Regex to detect Section header with Room in parentheses, e.g. "Section:  A (G-16)" or "Section: C (R-216)"
SECTION_ROOM_RE = re.compile(r"Section\s*:\s*([A-Za-z0-9_\-\.\s]+?)(?:\s*\((.+?)\)|$)", re.IGNORECASE)


def normalize_room_id(raw_room: str) -> str:
    """Normalize room identifiers (e.g. 'G-16' vs 'G16' vs 'R 216')."""
    if not raw_room:
        return ""
    clean = str(raw_room).strip()
    clean = re.sub(r"\s+", " ", clean)
    return clean


def list_classrooms(block: str = None, floor: int = None, room_type: str = None, min_capacity: int = None, search: str = None) -> list[dict]:
    """Retrieve filtered list of classrooms with real-time maintenance and booking indicators."""
    conn = db.get_db()
    cursor = conn.cursor()

    query = "SELECT * FROM classrooms WHERE 1=1"
    params = []

    if block:
        query += " AND block LIKE ?"
        params.append(f"%{block}%")
    if floor is not None:
        query += " AND floor = ?"
        params.append(floor)
    if room_type:
        query += " AND room_type = ?"
        params.append(room_type)
    if min_capacity:
        query += " AND seating_capacity >= ?"
        params.append(min_capacity)
    if search:
        query += " AND (id LIKE ? OR name LIKE ? OR block LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term, term])

    query += " ORDER BY id ASC;"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        item = dict(r)
        # Check active maintenance block
        maint = scheduling_service.check_maintenance_block(item["id"])
        item["is_under_maintenance"] = bool(maint)
        item["maintenance_info"] = maint
        result.append(item)

    return result


def get_classroom(classroom_id: str) -> dict | None:
    """Fetch single classroom details by ID."""
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM classrooms WHERE id = ?;", (classroom_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        res = dict(row)
        res["maintenance_info"] = scheduling_service.check_maintenance_block(classroom_id)
        return res
    return None


def add_or_update_classroom(data: dict) -> dict:
    """Insert or update classroom details."""
    room_id = normalize_room_id(data.get("id"))
    if not room_id:
        raise ValueError("Classroom ID is required.")

    name = data.get("name") or f"Classroom {room_id}"
    block = data.get("block", "Main Academic Block")
    floor = int(data.get("floor", 0))
    bench_cnt = int(data.get("bench_count", 30))
    cap = int(data.get("seating_capacity", bench_cnt * 2))
    room_type = data.get("room_type", "Lecture Hall")
    has_proj = 1 if data.get("has_projector", True) else 0
    has_aud = 1 if data.get("has_audio", False) else 0
    has_ac = 1 if data.get("has_ac", False) else 0
    status = data.get("status", "available")

    conn = db.get_db()
    with conn:
        conn.execute("""
            INSERT INTO classrooms 
            (id, name, block, floor, bench_count, seating_capacity, room_type, has_projector, has_audio, has_ac, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                block=excluded.block,
                floor=excluded.floor,
                bench_count=excluded.bench_count,
                seating_capacity=excluded.seating_capacity,
                room_type=excluded.room_type,
                has_projector=excluded.has_projector,
                has_audio=excluded.has_audio,
                has_ac=excluded.has_ac,
                status=excluded.status;
        """, (room_id, name, block, floor, bench_cnt, cap, room_type, has_proj, has_aud, has_ac, status))
    conn.close()
    return get_classroom(room_id)


def import_timetable_from_excel(file_path: str = None) -> dict:
    """
    Parse academic timetable workbook and populate classroom_schedules.
    Reads year sheets (Second_Year, Third_Year, Final_year), extracts Section & Room headers,
    and maps weekly lecture slots (1 to 9 for Mon-Fri) into database.
    """
    import openpyxl

    path = file_path or TIMETABLE_FILE
    if not os.path.exists(path):
        raise FileNotFoundError(f"Timetable file not found at: {path}")

    wb = openpyxl.load_workbook(path, data_only=True)
    conn = db.get_db()
    cursor = conn.cursor()

    # Pre-load known classroom IDs to match
    cursor.execute("SELECT id FROM classrooms;")
    known_rooms = {r[0].strip().upper(): r[0] for r in cursor.fetchall()}

    total_imported = 0
    year_sheets = ["Second_Year", "Third_Year", "Final_year"]

    for sheetname in year_sheets:
        if sheetname not in wb.sheetnames:
            continue
        ws = wb[sheetname]
        max_r = ws.max_row
        r = 1

        while r <= max_r:
            cell_val = str(ws.cell(r, 1).value or "").strip()
            # Look for Section header
            if cell_val.startswith("Section"):
                m = SECTION_ROOM_RE.search(cell_val)
                sec_name = m.group(1).strip() if m else cell_val
                raw_room = m.group(2).strip() if (m and m.group(2)) else ""

                # If room is in column B
                if not raw_room:
                    cell_b = str(ws.cell(r, 2).value or "").strip()
                    if cell_b.startswith("Section"):
                        m_b = SECTION_ROOM_RE.search(cell_b)
                        if m_b and m_b.group(2):
                            raw_room = m_b.group(2).strip()

                # Match room ID against known classrooms
                matched_room_id = None
                if raw_room:
                    cand = raw_room.strip().upper()
                    if cand in known_rooms:
                        matched_room_id = known_rooms[cand]
                    else:
                        # Try without hyphens or spaces (e.g. G-16 vs G16)
                        cand_no_dash = cand.replace("-", "").replace(" ", "")
                        for kr, original_id in known_rooms.items():
                            if kr.replace("-", "").replace(" ", "") == cand_no_dash:
                                matched_room_id = original_id
                                break

                # If a valid room was identified for this section
                if matched_room_id:
                    # Find slot header row (usually r+2)
                    slot_row = r + 2
                    days_start_row = r + 3
                    days_found = ["Mon", "Tue", "Wed", "Thu", "Fri"]

                    for d_idx, day_name in enumerate(days_found):
                        cur_row = days_start_row + d_idx
                        if cur_row > max_r:
                            break

                        row_day = str(ws.cell(cur_row, 1).value or "").strip()
                        if not row_day or day_name.lower() not in row_day.lower():
                            continue

                        # Read slots S1 to S9 (columns 2 to 10)
                        for slot_num in range(1, 10):
                            col_idx = 1 + slot_num
                            content = str(ws.cell(cur_row, col_idx).value or "").strip()

                            if not content or content.upper() == "LUNCH" or content == "-":
                                continue

                            # Extract course/subject
                            subj = content.replace("<-", "").replace("->", "").strip()

                            # Insert into classroom_schedules
                            with conn:
                                conn.execute("""
                                    INSERT INTO classroom_schedules 
                                    (classroom_id, day, slot, subject_code, subject_name, section, faculty_name, academic_year)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, '2026-2027')
                                    ON CONFLICT(classroom_id, day, slot, academic_year) DO UPDATE SET
                                        subject_code=excluded.subject_code,
                                        subject_name=excluded.subject_name,
                                        section=excluded.section;
                                """, (matched_room_id, day_name, slot_num, subj, subj, sec_name, "Department Faculty"))
                                total_imported += 1

                r += 10
            else:
                r += 1

    conn.close()
    logger.info("Imported %d schedule assignments into classroom_schedules.", total_imported)
    return {
        "status": "success",
        "imported_records": total_imported,
        "message": f"Successfully parsed and imported {total_imported} timetable sessions into classrooms."
    }


def get_classroom_weekly_schedule(classroom_id: str) -> dict:
    """Retrieve full weekly (Mon-Fri x Slots 1-9) matrix for a classroom."""
    conn = db.get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT day, slot, subject_code, subject_name, section, faculty_name
        FROM classroom_schedules
        WHERE classroom_id = ?
        ORDER BY slot ASC;
    """, (classroom_id,))
    rows = cursor.fetchall()
    conn.close()

    schedule_grid = {day: {s: None for s in range(1, 10)} for day in ["Mon", "Tue", "Wed", "Thu", "Fri"]}
    for r in rows:
        d = r["day"]
        s = r["slot"]
        if d in schedule_grid and s in schedule_grid[d]:
            schedule_grid[d][s] = dict(r)

    return {
        "classroom_id": classroom_id,
        "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "slots": scheduling_service.STANDARD_SLOTS,
        "grid": schedule_grid
    }


def find_available_classrooms(target_date: str, slot_start: int, slot_end: int = None, min_capacity: int = None, room_type: str = None) -> list[dict]:
    """Search for all classrooms free between slot_start and slot_end on a given date."""
    if slot_end is None:
        slot_end = slot_start

    all_rooms = list_classrooms(min_capacity=min_capacity, room_type=room_type)
    available_rooms = []

    for room in all_rooms:
        chk = scheduling_service.check_classroom_availability(room["id"], target_date, slot_start, slot_end)
        if chk["available"]:
            room["timeline"] = scheduling_service.get_classroom_daily_timeline(room["id"], target_date)
            available_rooms.append(room)

    return available_rooms


def book_classroom(data: dict) -> dict:
    """
    Submit an ad-hoc classroom booking request.
    Enforces conflict checks against regular timetable classes, existing bookings, and maintenance downtime.
    """
    classroom_id = normalize_room_id(data.get("classroom_id"))
    booking_date = data.get("booking_date")
    slot_start = int(data.get("slot_start", 1))
    slot_end = int(data.get("slot_end", slot_start))
    department = data.get("department", "Academic Department").strip()
    booked_by = data.get("booked_by", "Faculty/Staff").strip()
    role = data.get("role", "Department Staff")
    purpose = data.get("purpose", "").strip()
    attendees = int(data.get("attendees", 0))
    pin = data.get("pin")

    # Validate inputs
    if not classroom_id or not booking_date or not purpose:
        raise ValueError("Classroom ID, Booking Date, and Purpose are required.")
    if slot_start < 1 or slot_end > 9 or slot_start > slot_end:
        raise ValueError("Invalid slot range. Must be between 1 and 9.")

    # Validate Role PIN
    if not db.verify_role_pin(role, pin):
        raise PermissionError("Invalid authorization PIN for this action.")

    # Capacity validation
    room = get_classroom(classroom_id)
    if not room:
        raise ValueError(f"Classroom {classroom_id} not found.")
    if attendees > 0 and attendees > room["seating_capacity"]:
        raise ValueError(
            f"Requested attendee count ({attendees}) exceeds room capacity ({room['seating_capacity']} seats)."
        )

    # Perform scheduling conflict validation
    chk = scheduling_service.check_classroom_availability(classroom_id, booking_date, slot_start, slot_end)
    if not chk["available"]:
        raise ValueError(f"Scheduling Conflict: {chk['reason']}")

    conn = db.get_db()
    with conn:
        cursor = conn.execute("""
            INSERT INTO classroom_bookings 
            (classroom_id, booking_date, slot_start, slot_end, department, booked_by, role, purpose, attendees, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed');
        """, (classroom_id, booking_date, slot_start, slot_end, department, booked_by, role, purpose, attendees))
        booking_id = cursor.lastrowid
    conn.close()

    return {
        "status": "success",
        "booking_id": booking_id,
        "classroom_id": classroom_id,
        "booking_date": booking_date,
        "slots": f"Slot {slot_start} - {slot_end}",
        "message": f"Successfully reserved Classroom {classroom_id} for {purpose}."
    }


def list_classroom_bookings(classroom_id: str = None, booking_date: str = None, department: str = None) -> list[dict]:
    """Retrieve ad-hoc classroom reservations."""
    conn = db.get_db()
    cursor = conn.cursor()

    query = """
        SELECT b.*, c.name as classroom_name, c.seating_capacity
        FROM classroom_bookings b
        JOIN classrooms c ON b.classroom_id = c.id
        WHERE b.status = 'confirmed'
    """
    params = []

    if classroom_id:
        query += " AND b.classroom_id = ?"
        params.append(classroom_id)
    if booking_date:
        query += " AND b.booking_date = ?"
        params.append(booking_date)
    if department:
        query += " AND b.department LIKE ?"
        params.append(f"%{department}%")

    query += " ORDER BY b.booking_date DESC, b.slot_start ASC;"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cancel_classroom_booking(booking_id: int, pin: str) -> dict:
    """Cancel a confirmed classroom booking."""
    if not db.verify_role_pin("staff", pin) and not db.verify_role_pin("admin", pin):
        raise PermissionError("Valid authorization PIN is required to cancel a booking.")

    conn = db.get_db()
    with conn:
        conn.execute("UPDATE classroom_bookings SET status = 'cancelled' WHERE id = ?;", (booking_id,))
    conn.close()
    return {"status": "success", "message": f"Booking #{booking_id} cancelled."}


def get_classroom_utilization_analytics() -> dict:
    """
    Compute campus-wide classroom utilization metrics:
    - Weekly scheduled lecture hours
    - Utilization percentage across all rooms
    - Top 5 utilized vs underutilized classrooms
    - Day of week and slot distributions
    """
    conn = db.get_db()
    cursor = conn.cursor()

    # Total rooms & total seats
    cursor.execute("SELECT COUNT(*), SUM(seating_capacity), AVG(seating_capacity) FROM classrooms;")
    r_stat = cursor.fetchone()
    total_rooms = r_stat[0] or 0
    total_seats = r_stat[1] or 0
    avg_capacity = round(r_stat[2] or 0, 1)

    # Weekly teaching slots per room: 8 slots/day (excluding S5 lunch) * 5 days = 40 slots/week
    MAX_WEEKLY_SLOTS_PER_ROOM = 40
    total_campus_capacity_slots = total_rooms * MAX_WEEKLY_SLOTS_PER_ROOM

    # Count scheduled lecture slots in classroom_schedules
    cursor.execute("SELECT COUNT(*) FROM classroom_schedules WHERE slot != 5;")
    total_scheduled_slots = cursor.fetchone()[0] or 0

    utilization_rate = round((total_scheduled_slots / total_campus_capacity_slots * 100), 1) if total_campus_capacity_slots > 0 else 0.0

    # Per-room utilization ranking
    cursor.execute("""
        SELECT c.id, c.name, c.seating_capacity, c.room_type,
               COUNT(s.id) as scheduled_count
        FROM classrooms c
        LEFT JOIN classroom_schedules s ON c.id = s.classroom_id AND s.slot != 5
        GROUP BY c.id
        ORDER BY scheduled_count DESC;
    """)
    room_util_rows = cursor.fetchall()

    room_rankings = []
    for r in room_util_rows:
        cnt = r["scheduled_count"]
        pct = round((cnt / MAX_WEEKLY_SLOTS_PER_ROOM) * 100, 1)
        room_rankings.append({
            "id": r["id"],
            "name": r["name"],
            "seating_capacity": r["seating_capacity"],
            "room_type": r["room_type"],
            "scheduled_slots": cnt,
            "free_slots": max(0, MAX_WEEKLY_SLOTS_PER_ROOM - cnt),
            "utilization_pct": pct,
            "status": "High" if pct >= 70 else ("Moderate" if pct >= 40 else "Underutilized")
        })

    # Day-of-week distribution
    cursor.execute("""
        SELECT day, COUNT(*) as slot_count
        FROM classroom_schedules
        WHERE slot != 5
        GROUP BY day;
    """)
    day_counts = {row["day"]: row["slot_count"] for row in cursor.fetchall()}
    days_data = [
        {"day": d, "slots": day_counts.get(d, 0)}
        for d in ["Mon", "Tue", "Wed", "Thu", "Fri"]
    ]

    # Slot-of-day distribution
    cursor.execute("""
        SELECT slot, COUNT(*) as slot_count
        FROM classroom_schedules
        WHERE slot != 5
        GROUP BY slot
        ORDER BY slot ASC;
    """)
    slot_counts = {row["slot"]: row["slot_count"] for row in cursor.fetchall()}
    slots_data = [
        {"slot": s, "name": f"Slot {s}", "count": slot_counts.get(s, 0)}
        for s in [1, 2, 3, 4, 6, 7, 8, 9]
    ]

    conn.close()

    return {
        "total_rooms": total_rooms,
        "total_seats": total_seats,
        "avg_capacity": avg_capacity,
        "total_scheduled_slots": total_scheduled_slots,
        "total_free_slots": max(0, total_campus_capacity_slots - total_scheduled_slots),
        "utilization_rate_pct": utilization_rate,
        "most_utilized": room_rankings[:5],
        "underutilized": [r for r in reversed(room_rankings) if r["scheduled_slots"] < 15][:5],
        "all_rankings": room_rankings,
        "day_distribution": days_data,
        "slot_distribution": slots_data
    }

