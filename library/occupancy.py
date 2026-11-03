"""
library/occupancy.py — Independent seating occupancy recording and database layer.

Operates independently of the existing student entry turnstile system.
Tracks periodic headcount observations, available seats, occupancy percentage,
and crowd categories (Low, Moderate, High, Full) without storing any personal student data.
"""

import sqlite3
import os
import logging
from datetime import datetime, date, timedelta

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "library.db")


def _get_pin() -> str:
    """Retrieve administrator PIN from environment or fallback to default."""
    pin = os.environ.get("INCHARGE_PIN")
    if not pin:
        pin = "1234"
    return pin


def get_db() -> sqlite3.Connection:
    """Return a SQLite connection with WAL mode and row factory."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create database tables and seed baseline sample data if empty."""
    conn = get_db()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS library_config (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                total_capacity INTEGER NOT NULL CHECK(total_capacity > 0),
                low_threshold_pct REAL DEFAULT 35.0,
                mod_threshold_pct REAL DEFAULT 70.0,
                high_threshold_pct REAL DEFAULT 90.0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS occupancy_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occupied_seats INTEGER NOT NULL CHECK(occupied_seats >= 0),
                total_capacity INTEGER NOT NULL CHECK(total_capacity > 0),
                available_seats INTEGER NOT NULL,
                occupancy_pct REAL NOT NULL,
                recorded_date DATE NOT NULL,
                recorded_time TIME NOT NULL,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                recorded_by TEXT DEFAULT 'admin',
                notes TEXT
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS library_admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                record_id INTEGER,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Ensure default configuration exists
        cur = conn.cursor()
        cur.execute("SELECT id FROM library_config WHERE id = 'MAIN_LIB'")
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO library_config (id, name, total_capacity, low_threshold_pct, mod_threshold_pct, high_threshold_pct)
                VALUES ('MAIN_LIB', 'Central University Library', 250, 35.0, 70.0, 90.0)
            """)

    conn.close()
    seed_baseline_if_empty()


def get_config() -> dict:
    """Return current library capacity and threshold configuration."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM library_config WHERE id = 'MAIN_LIB'")
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {
        "id": "MAIN_LIB",
        "name": "Central University Library",
        "total_capacity": 250,
        "low_threshold_pct": 35.0,
        "mod_threshold_pct": 70.0,
        "high_threshold_pct": 90.0
    }


def update_config(capacity: int, low_th: float = 35.0, mod_th: float = 70.0, high_th: float = 90.0, pin: str = "") -> dict:
    """Update library capacity and thresholds if PIN matches."""
    if pin != _get_pin():
        raise PermissionError("Invalid In-Charge PIN")

    if capacity <= 0:
        raise ValueError("Library capacity must be greater than zero")

    if not (0 < low_th < mod_th < high_th <= 100):
        raise ValueError("Thresholds must follow: 0 < low < moderate < high <= 100")

    conn = get_db()
    with conn:
        conn.execute("""
            UPDATE library_config
            SET total_capacity = ?, low_threshold_pct = ?, mod_threshold_pct = ?, high_threshold_pct = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = 'MAIN_LIB'
        """, (capacity, low_th, mod_th, high_th))
        conn.execute("""
            INSERT INTO library_admin_logs (action, details)
            VALUES ('UPDATE_CONFIG', ?)
        """, (f"Capacity set to {capacity}, thresholds: {low_th}/{mod_th}/{high_th}",))
    conn.close()
    return get_config()


def classify_crowd_level(occupancy_pct: float, cfg: dict = None) -> tuple[str, str]:
    """
    Categorize crowd level into:
    - Low occupancy (< low_threshold)
    - Moderate occupancy (low_threshold to mod_threshold)
    - High occupancy (mod_threshold to high_threshold)
    - Full capacity (>= high_threshold)
    Returns (status_label, badge_color_code).
    """
    if cfg is None:
        cfg = get_config()

    low = cfg.get("low_threshold_pct", 35.0)
    mod = cfg.get("mod_threshold_pct", 70.0)
    high = cfg.get("high_threshold_pct", 90.0)

    if occupancy_pct >= 98.0:
        return "Full capacity", "danger"
    elif occupancy_pct >= high:
        return "High occupancy", "warning"
    elif occupancy_pct >= low:
        return "Moderate occupancy", "info"
    else:
        return "Low occupancy", "success"


def add_observation(occupied_seats: int, pin: str = "", notes: str = "", custom_dt: datetime = None) -> dict:
    """
    Record an independent periodic occupancy observation.
    Requires admin PIN authorization.
    """
    if pin != _get_pin():
        raise PermissionError("Invalid Administrator PIN")

    cfg = get_config()
    total_capacity = cfg["total_capacity"]

    if occupied_seats < 0:
        raise ValueError("Occupied seats cannot be negative")
    if occupied_seats > total_capacity:
        raise ValueError(f"Occupied seats ({occupied_seats}) cannot exceed total capacity ({total_capacity})")

    now = custom_dt or datetime.now()
    recorded_date = now.strftime("%Y-%m-%d")
    recorded_time = now.strftime("%H:%M:%S")
    recorded_at = now.strftime("%Y-%m-%d %H:%M:%S")

    available_seats = max(0, total_capacity - occupied_seats)
    occupancy_pct = round((occupied_seats / total_capacity) * 100.0, 1)

    conn = get_db()
    with conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO occupancy_records
            (occupied_seats, total_capacity, available_seats, occupancy_pct, recorded_date, recorded_time, recorded_at, recorded_by, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'admin', ?)
        """, (occupied_seats, total_capacity, available_seats, occupancy_pct, recorded_date, recorded_time, recorded_at, notes))
        record_id = cur.lastrowid
        conn.execute("""
            INSERT INTO library_admin_logs (action, record_id, details)
            VALUES ('ADD_OBSERVATION', ?, ?)
        """, (record_id, f"Recorded {occupied_seats}/{total_capacity} seats ({occupancy_pct}%)"))
    conn.close()

    status_label, badge_color = classify_crowd_level(occupancy_pct, cfg)

    return {
        "id": record_id,
        "occupied_seats": occupied_seats,
        "total_capacity": total_capacity,
        "available_seats": available_seats,
        "occupancy_pct": occupancy_pct,
        "recorded_date": recorded_date,
        "recorded_time": recorded_time,
        "recorded_at": recorded_at,
        "status": status_label,
        "badge_color": badge_color,
        "notes": notes
    }


def update_observation(record_id: int, occupied_seats: int, pin: str = "", notes: str = None) -> dict:
    """Correct an inaccurate occupancy observation."""
    if pin != _get_pin():
        raise PermissionError("Invalid Administrator PIN")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM occupancy_records WHERE id = ?", (record_id,))
    existing = cur.fetchone()
    if not existing:
        conn.close()
        raise ValueError(f"Observation record #{record_id} not found")

    total_capacity = existing["total_capacity"]
    if occupied_seats < 0 or occupied_seats > total_capacity:
        conn.close()
        raise ValueError(f"Occupied seats must be between 0 and {total_capacity}")

    available_seats = total_capacity - occupied_seats
    occupancy_pct = round((occupied_seats / total_capacity) * 100.0, 1)
    new_notes = notes if notes is not None else existing["notes"]

    with conn:
        conn.execute("""
            UPDATE occupancy_records
            SET occupied_seats = ?, available_seats = ?, occupancy_pct = ?, notes = ?
            WHERE id = ?
        """, (occupied_seats, available_seats, occupancy_pct, new_notes, record_id))
        conn.execute("""
            INSERT INTO library_admin_logs (action, record_id, details)
            VALUES ('UPDATE_OBSERVATION', ?, ?)
        """, (record_id, f"Corrected to {occupied_seats} seats ({occupancy_pct}%)"))
    conn.close()

    cfg = get_config()
    status_label, badge_color = classify_crowd_level(occupancy_pct, cfg)

    return {
        "id": record_id,
        "occupied_seats": occupied_seats,
        "total_capacity": total_capacity,
        "available_seats": available_seats,
        "occupancy_pct": occupancy_pct,
        "recorded_date": existing["recorded_date"],
        "recorded_time": existing["recorded_time"],
        "status": status_label,
        "badge_color": badge_color,
        "notes": new_notes
    }


def delete_observation(record_id: int, pin: str = "") -> bool:
    """Delete an observation record."""
    if pin != _get_pin():
        raise PermissionError("Invalid Administrator PIN")

    conn = get_db()
    with conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM occupancy_records WHERE id = ?", (record_id,))
        if cur.rowcount == 0:
            conn.close()
            raise ValueError(f"Observation record #{record_id} not found")
        conn.execute("""
            INSERT INTO library_admin_logs (action, record_id, details)
            VALUES ('DELETE_OBSERVATION', ?, 'Deleted observation')
        """, (record_id,))
    conn.close()
    return True


def get_latest_observation() -> dict:
    """
    Retrieve the most recent periodic observation.
    Calculates staleness: if last reading is older than 2 hours (120 min),
    it is marked as stale to prevent misleading real-time claims.
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM occupancy_records ORDER BY recorded_at DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()

    cfg = get_config()
    total_capacity = cfg["total_capacity"]

    if not row:
        return {
            "has_data": False,
            "total_capacity": total_capacity,
            "occupied_seats": 0,
            "available_seats": total_capacity,
            "occupancy_pct": 0.0,
            "status": "No observation recorded",
            "badge_color": "secondary",
            "is_stale": True,
            "stale_reason": "No occupancy observations recorded yet.",
            "last_updated_human": "Never"
        }

    rec = dict(row)
    status_label, badge_color = classify_crowd_level(rec["occupancy_pct"], cfg)

    # Compute staleness
    try:
        dt = datetime.strptime(rec["recorded_at"], "%Y-%m-%d %H:%M:%S")
    except Exception:
        dt = datetime.now()

    diff = datetime.now() - dt
    diff_minutes = int(diff.total_seconds() // 60)
    is_stale = diff_minutes > 120

    if diff_minutes < 1:
        human_time = "Just now"
    elif diff_minutes < 60:
        human_time = f"{diff_minutes} minute{'s' if diff_minutes != 1 else ''} ago"
    elif diff_minutes < 1440:
        hours = diff_minutes // 60
        human_time = f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        days = diff_minutes // 1440
        human_time = f"{days} day{'s' if days != 1 else ''} ago"

    rec.update({
        "has_data": True,
        "status": status_label,
        "badge_color": badge_color,
        "is_stale": is_stale,
        "stale_minutes": diff_minutes,
        "last_updated_human": human_time
    })
    return rec


def get_observations(date_filter: str = "30d", start_date: str = None, end_date: str = None, limit: int = 500) -> list[dict]:
    """
    Retrieve observations filtered by date.
    Supported filters: 'today', '7d', '30d', 'all', 'custom'.
    """
    conn = get_db()
    cur = conn.cursor()

    query = "SELECT * FROM occupancy_records"
    params = []

    today = date.today()

    if date_filter == "today":
        query += " WHERE recorded_date = ?"
        params.append(today.isoformat())
    elif date_filter == "7d":
        since = today - timedelta(days=7)
        query += " WHERE recorded_date >= ?"
        params.append(since.isoformat())
    elif date_filter == "30d":
        since = today - timedelta(days=30)
        query += " WHERE recorded_date >= ?"
        params.append(since.isoformat())
    elif date_filter == "custom" and start_date and end_date:
        query += " WHERE recorded_date BETWEEN ? AND ?"
        params.extend([start_date, end_date])

    query += " ORDER BY recorded_at DESC LIMIT ?"
    params.append(limit)

    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    cfg = get_config()
    for r in rows:
        label, badge = classify_crowd_level(r["occupancy_pct"], cfg)
        r["status"] = label
        r["badge_color"] = badge

    return rows


def seed_baseline_if_empty():
    """
    Seed 14 days of realistic hourly observation data if database has no records.
    Every record is explicitly tagged as '[Simulated Baseline Data]' so administrators
    can clearly distinguish between simulated and real-world recorded counts.
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM occupancy_records")
    count = cur.fetchone()[0]
    if count > 0:
        conn.close()
        return

    logger.info("Seeding initial 14-day simulated library occupancy data for cold-start...")
    cfg = get_config()
    cap = cfg["total_capacity"]

    # Typical daily occupancy pattern by hour (8 AM to 8 PM)
    # Peak at 10-12 AM and 3-5 PM
    pattern = {
        8: 0.15,
        9: 0.32,
        10: 0.65,
        11: 0.82,
        12: 0.74,
        13: 0.48, # lunch lull
        14: 0.58,
        15: 0.78,
        16: 0.85, # peak
        17: 0.68,
        18: 0.45,
        19: 0.28,
        20: 0.18
    }

    import random
    random.seed(42)  # Deterministic seed for reproducible baseline

    today = date.today()
    records = []

    for d in range(14, -1, -1):
        day_date = today - timedelta(days=d)
        is_weekend = day_date.weekday() >= 5
        day_factor = 0.55 if is_weekend else 1.0

        # Don't seed future hours for today
        current_hour = datetime.now().hour if d == 0 else 23

        for hour, base_factor in pattern.items():
            if d == 0 and hour > current_hour:
                continue

            # Add minor random noise (+/- 8%)
            noise = random.uniform(-0.08, 0.08)
            occ_pct = max(0.08, min(0.96, (base_factor * day_factor) + noise))
            occupied = int(round(occ_pct * cap))
            available = cap - occupied
            pct_val = round((occupied / cap) * 100.0, 1)

            dt = datetime(day_date.year, day_date.month, day_date.day, hour, random.randint(0, 15), 0)
            records.append((
                occupied,
                cap,
                available,
                pct_val,
                day_date.isoformat(),
                dt.strftime("%H:%M:%S"),
                dt.strftime("%Y-%m-%d %H:%M:%S"),
                'system_baseline',
                '[Simulated Baseline Data] Hourly monitoring observation'
            ))

    with conn:
        conn.executemany("""
            INSERT INTO occupancy_records
            (occupied_seats, total_capacity, available_seats, occupancy_pct, recorded_date, recorded_time, recorded_at, recorded_by, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records)

    conn.close()
    logger.info("Successfully seeded %d baseline occupancy observations.", len(records))
