"""
lab/booking.py — SQLite-backed slot status management and booking system.

Design decisions:
- SQLite is kept in data/lab_bookings.db alongside other data files.
- The `status` table only stores *overridden* states. If a (lab, week, day, slot)
  is absent, the default state is derived from the timetable:
    • timetable says it's a lab session → "in_use"
    • otherwise → "empty"
  This keeps the DB small and avoids regenerating data every week.
- Bookings are separate from status. A booking only exists on an "empty" slot.
  Marking a slot in_use or maintenance deletes existing bookings on it.
- The in-charge PIN is read from the INCHARGE_PIN environment variable.
  A hardcoded default "1234" is used only when the env var is missing,
  with a clear warning logged at startup. Never store secrets in code.
- All user-supplied strings (name, purpose) are HTML-escaped before storage.
- Multi-slot booking is atomic: we insert all or nothing (rolled back on conflict).
"""

import sqlite3
import html
import os
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "lab_bookings.db")

# Valid slot states
VALID_STATES = {"in_use", "empty", "maintenance", "exam", "booked"}
# States that block new bookings
NON_BOOKABLE_STATES = {"in_use", "maintenance", "exam", "booked"}
# Lunch slot (S5)
LUNCH_SLOT = 5
# Days
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
# Valid roles
VALID_ROLES = {"student", "faculty"}


def _get_pin() -> str:
    """Read in-charge PIN from environment. Warn if using default."""
    pin = os.environ.get("INCHARGE_PIN")
    if not pin:
        logger.warning(
            "INCHARGE_PIN environment variable not set. "
            "Using default PIN '1234' — change this before deployment!"
        )
        pin = "1234"
    return pin


def get_db() -> sqlite3.Connection:
    """Open and return a SQLite connection with WAL mode for concurrency."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist. Called once at app startup."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS status (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                lab         TEXT    NOT NULL,
                week_monday TEXT    NOT NULL,  -- ISO date of the Monday of that week
                day         TEXT    NOT NULL,  -- Mon/Tue/Wed/Thu/Fri
                slot        INTEGER NOT NULL,  -- 1-9
                state       TEXT    NOT NULL,  -- in_use / empty / maintenance / exam
                note        TEXT,
                updated_at  TEXT    DEFAULT (datetime('now')),
                UNIQUE(lab, week_monday, day, slot)
            );

            CREATE TABLE IF NOT EXISTS bookings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                lab         TEXT    NOT NULL,
                week_monday TEXT    NOT NULL,
                day         TEXT    NOT NULL,
                slot        INTEGER NOT NULL,
                name        TEXT    NOT NULL,
                role        TEXT    NOT NULL,  -- student / faculty
                purpose     TEXT    NOT NULL,
                group_size  INTEGER NOT NULL,
                created_at  TEXT    DEFAULT (datetime('now')),
                UNIQUE(lab, week_monday, day, slot)
            );

            CREATE TABLE IF NOT EXISTS exam_blocks (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                lab       TEXT NOT NULL,
                exam_date TEXT NOT NULL,  -- ISO date
                slot      INTEGER NOT NULL,
                exam_id   TEXT,
                UNIQUE(lab, exam_date, slot)
            );
        """)


def _monday_of_week(iso_date: str) -> str:
    """Given any ISO date string, return the Monday of that week."""
    d = date.fromisoformat(iso_date)
    return (d - timedelta(days=d.weekday())).isoformat()


def _slot_default_state(lab: str, week_monday: str, day: str, slot: int,
                        timetable_busy: set) -> str:
    """
    Return default state for a slot not in the status table.
    timetable_busy is a set of (lab, day, slot) tuples of booked timetable slots.
    """
    if slot == LUNCH_SLOT:
        return "lunch"
    if (lab, day, slot) in timetable_busy:
        return "in_use"
    return "empty"


def get_week_grid(lab: str, week_monday: str, timetable_busy: set,
                  lab_capacity: int) -> list[list[dict]]:
    """
    Return the 5×9 week grid for a lab.
    Each cell: {day, slot, state, note, booking, capacity}
    state is the effective state (status override > timetable default).
    """
    with get_db() as conn:
        overrides = {}
        rows = conn.execute(
            "SELECT day, slot, state, note FROM status WHERE lab=? AND week_monday=?",
            (lab, week_monday)
        ).fetchall()
        for row in rows:
            overrides[(row["day"], row["slot"])] = {"state": row["state"], "note": row["note"]}

        bookings = {}
        brows = conn.execute(
            "SELECT day, slot, name, role, purpose, group_size, id FROM bookings "
            "WHERE lab=? AND week_monday=?",
            (lab, week_monday)
        ).fetchall()
        for row in brows:
            bookings[(row["day"], row["slot"])] = dict(row)

    grid = []
    for day in DAYS:
        row_cells = []
        for slot in range(1, 10):
            key = (day, slot)
            if slot == LUNCH_SLOT:
                cell = {"day": day, "slot": slot, "state": "lunch", "note": None, "booking": None}
            elif key in overrides:
                override = overrides[key]
                state = override["state"]
                booking = bookings.get(key) if state == "booked" else None
                cell = {"day": day, "slot": slot, "state": state,
                        "note": override["note"], "booking": booking}
            else:
                state = _slot_default_state(lab, week_monday, day, slot, timetable_busy)
                booking = bookings.get(key) if state == "booked" else None
                cell = {"day": day, "slot": slot, "state": state, "note": None, "booking": booking}
            cell["capacity"] = lab_capacity
            row_cells.append(cell)
        grid.append(row_cells)
    return grid


def set_slot_state(lab: str, week_monday: str, day: str, slot: int,
                   state: str, note: str, pin: str) -> None:
    """
    In-charge action: override slot state. Cancels existing bookings if state
    becomes in_use or maintenance. Requires valid PIN.
    """
    if pin != _get_pin():
        raise PermissionError("Invalid PIN.")
    if state not in {"in_use", "empty", "maintenance"}:
        raise ValueError(f"Invalid state '{state}'. Must be in_use, empty, or maintenance.")
    if day not in DAYS:
        raise ValueError(f"Invalid day '{day}'.")
    if slot == LUNCH_SLOT:
        raise ValueError("Cannot override lunch slot.")

    note = html.escape(note or "")
    with get_db() as conn:
        conn.execute(
            """INSERT INTO status(lab, week_monday, day, slot, state, note, updated_at)
               VALUES(?,?,?,?,?,?, datetime('now'))
               ON CONFLICT(lab, week_monday, day, slot)
               DO UPDATE SET state=excluded.state, note=excluded.note, updated_at=excluded.updated_at""",
            (lab, week_monday, day, slot, state, note)
        )
        # Cancel existing bookings if slot becomes non-bookable
        if state in ("in_use", "maintenance"):
            conn.execute(
                "DELETE FROM bookings WHERE lab=? AND week_monday=? AND day=? AND slot=?",
                (lab, week_monday, day, slot)
            )


def reset_slot(lab: str, week_monday: str, day: str, slot: int, pin: str) -> None:
    """In-charge action: remove override so slot reverts to timetable default."""
    if pin != _get_pin():
        raise PermissionError("Invalid PIN.")
    with get_db() as conn:
        conn.execute(
            "DELETE FROM status WHERE lab=? AND week_monday=? AND day=? AND slot=?",
            (lab, week_monday, day, slot)
        )


def book_slots(lab: str, week_monday: str, day: str, slots: list[int],
               name: str, role: str, purpose: str, group_size: int,
               timetable_busy: set, lab_capacity: int) -> list[int]:
    """
    Book one or more slots atomically. All-or-nothing.
    Returns list of assigned booking IDs.

    Rules enforced:
    - slot must be effectively "empty"
    - no double booking (UNIQUE constraint → 409 in route)
    - lunch not bookable
    - group_size <= lab_capacity
    - role must be valid
    """
    if not name or not name.strip():
        raise ValueError("Name is required.")
    if role not in VALID_ROLES:
        raise ValueError(f"Role must be one of {VALID_ROLES}.")
    if not purpose or not purpose.strip():
        raise ValueError("Purpose is required.")
    if group_size <= 0:
        raise ValueError("Group size must be positive.")
    if group_size > lab_capacity:
        raise ValueError(
            f"Group size {group_size} exceeds lab capacity {lab_capacity}."
        )
    if not slots:
        raise ValueError("At least one slot must be specified.")

    name = html.escape(name.strip())
    purpose = html.escape(purpose.strip())

    with get_db() as conn:
        # Verify each slot is empty right now (within transaction)
        overrides = {}
        for row in conn.execute(
            "SELECT day, slot, state FROM status WHERE lab=? AND week_monday=? AND day=?",
            (lab, week_monday, day)
        ).fetchall():
            overrides[(row["day"], row["slot"])] = row["state"]

        for slot in slots:
            if slot == LUNCH_SLOT:
                raise ValueError(f"Slot {slot} is the lunch slot and cannot be booked.")
            state = overrides.get((day, slot)) or \
                    _slot_default_state(lab, week_monday, day, slot, timetable_busy)
            if state != "empty":
                raise ValueError(
                    f"Slot {slot} is not available (state: {state}). "
                    "Only 'empty' slots can be booked."
                )

        # Insert all bookings atomically
        ids = []
        for slot in slots:
            cursor = conn.execute(
                """INSERT INTO bookings(lab, week_monday, day, slot, name, role, purpose, group_size)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (lab, week_monday, day, slot, name, role, purpose, group_size)
            )
            ids.append(cursor.lastrowid)
            # Also insert status override so the grid shows "booked"
            conn.execute(
                """INSERT INTO status(lab, week_monday, day, slot, state, note, updated_at)
                   VALUES(?,?,?,?,'booked',?,datetime('now'))
                   ON CONFLICT(lab, week_monday, day, slot)
                   DO UPDATE SET state='booked', updated_at=excluded.updated_at""",
                (lab, week_monday, day, slot, f"Booked by {name}")
            )
    return ids


def cancel_booking(booking_id: int, requester_name: str, pin: str | None,
                   timetable_busy: set) -> None:
    """
    Cancel a booking. Allowed if:
    - The pin matches the in-charge PIN, OR
    - The requester_name matches the booking's name.
    Restores the slot to its timetable-derived default state.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM bookings WHERE id=?", (booking_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"Booking {booking_id} not found.")

        is_incharge = pin and pin == _get_pin()
        name_match = html.escape(requester_name.strip()) == row["name"] if requester_name else False

        if not is_incharge and not name_match:
            raise PermissionError("Only the in-charge or the person who booked can cancel.")

        conn.execute("DELETE FROM bookings WHERE id=?", (booking_id,))

        # Restore slot status to timetable default (remove the 'booked' override)
        lab, week_monday, day, slot = row["lab"], row["week_monday"], row["day"], row["slot"]
        default = _slot_default_state(lab, week_monday, day, slot, timetable_busy)
        if default == "in_use":
            conn.execute(
                """INSERT INTO status(lab, week_monday, day, slot, state, note, updated_at)
                   VALUES(?,?,?,?,'in_use','Restored from timetable',datetime('now'))
                   ON CONFLICT(lab, week_monday, day, slot)
                   DO UPDATE SET state='in_use', updated_at=excluded.updated_at""",
                (lab, week_monday, day, slot)
            )
        else:
            # Remove the status override so it goes back to the empty default
            conn.execute(
                "DELETE FROM status WHERE lab=? AND week_monday=? AND day=? AND slot=?",
                (lab, week_monday, day, slot)
            )


def list_bookings(lab: str, week_monday: str) -> list[dict]:
    """Return all bookings for a lab in a given week."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM bookings WHERE lab=? AND week_monday=? ORDER BY day, slot",
            (lab, week_monday)
        ).fetchall()
    return [dict(r) for r in rows]


def mark_exam_slots(lab: str, exam_date: str, slots: list[int],
                    exam_id: str, pin: str) -> None:
    """
    Hook for the exam seat allocation system: mark lab slots as 'exam' state
    for a specific date. Called via POST /api/exam_blocks or directly from
    the seating system's Python code.
    """
    if pin != _get_pin():
        raise PermissionError("Invalid PIN.")
    week_monday = _monday_of_week(exam_date)
    # Determine day of week from exam_date
    d = date.fromisoformat(exam_date)
    day = DAYS[d.weekday()]

    with get_db() as conn:
        for slot in slots:
            conn.execute(
                """INSERT INTO exam_blocks(lab, exam_date, slot, exam_id)
                   VALUES(?,?,?,?)
                   ON CONFLICT(lab, exam_date, slot) DO NOTHING""",
                (lab, exam_date, slot, exam_id)
            )
            # Set status to 'exam' for that week/day/slot
            conn.execute(
                """INSERT INTO status(lab, week_monday, day, slot, state, note, updated_at)
                   VALUES(?,?,?,?,'exam',?,datetime('now'))
                   ON CONFLICT(lab, week_monday, day, slot)
                   DO UPDATE SET state='exam', updated_at=excluded.updated_at""",
                (lab, week_monday, day, slot, f"Exam: {exam_id}")
            )
            # Cancel any existing bookings
            conn.execute(
                "DELETE FROM bookings WHERE lab=? AND week_monday=? AND day=? AND slot=?",
                (lab, week_monday, day, slot)
            )


def get_slot_state(lab: str, week_monday: str, day: str, slot: int,
                   timetable_busy: set) -> str:
    """Return effective state of a single slot (used by allocator)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT state FROM status WHERE lab=? AND week_monday=? AND day=? AND slot=?",
            (lab, week_monday, day, slot)
        ).fetchone()
    if row:
        return row["state"]
    return _slot_default_state(lab, week_monday, day, slot, timetable_busy)
