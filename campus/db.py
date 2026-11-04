"""
campus/db.py — Centralized SQLite database layer for Campus Space & Facility Management.

Features:
- Thread-safe SQLite connections with Write-Ahead Logging (WAL mode)
- Automatic schema creation for Classrooms, Auditoriums, Facilities, and Schedules
- Automatic cold-start seeding of classrooms from data/roomCapacity_FST.xlsx
- Seeds default auditoriums, facility assets, and preventive maintenance rules
"""

import sqlite3
import os
import sys
import logging
from datetime import datetime, date

# Resolve dependencies if needed
_cached_site = os.path.expanduser(r"~\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages")
if os.path.isdir(_cached_site) and _cached_site not in sys.path:
    sys.path.insert(0, _cached_site)

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "campus_facility.db")
ROOMS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "roomCapacity_FST.xlsx")
TIMETABLE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "timetable.xlsx")

# Configurable PINs for RBAC
ROLE_PINS = {
    "admin": os.environ.get("ADMIN_PIN", os.environ.get("INCHARGE_PIN", "1234")),
    "staff": os.environ.get("STAFF_PIN", "2345"),
    "maintenance": os.environ.get("MAINTENANCE_PIN", "3456")
}


def verify_role_pin(role: str, pin: str) -> bool:
    """Verify submitted PIN against role permission. Admin PIN can act on any role."""
    if not pin:
        return False
    pin = str(pin).strip()
    admin_pin = ROLE_PINS.get("admin", "1234")
    if pin == admin_pin:
        return True
    
    r_clean = role.lower()
    if "admin" in r_clean:
        expected = ROLE_PINS.get("admin")
    elif "maint" in r_clean:
        expected = ROLE_PINS.get("maintenance")
    else:  # Staff / Department Staff
        expected = ROLE_PINS.get("staff")

    return pin == expected


def get_db() -> sqlite3.Connection:
    """Return an active SQLite database connection with WAL mode enabled."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all required tables for Classrooms, Auditoriums, and Facilities."""
    conn = get_db()
    with conn:
        # 1. Classrooms
        conn.execute("""
            CREATE TABLE IF NOT EXISTS classrooms (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                block TEXT NOT NULL,
                floor INTEGER DEFAULT 0,
                bench_count INTEGER NOT NULL,
                seating_capacity INTEGER NOT NULL,
                room_type TEXT DEFAULT 'Lecture Hall',
                has_projector BOOLEAN DEFAULT 1,
                has_audio BOOLEAN DEFAULT 0,
                has_ac BOOLEAN DEFAULT 0,
                status TEXT DEFAULT 'available',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 2. Classroom Timetable Schedules (Imported from Excel)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS classroom_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                classroom_id TEXT NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
                day TEXT NOT NULL,
                slot INTEGER NOT NULL,
                subject_code TEXT,
                subject_name TEXT,
                section TEXT,
                faculty_name TEXT,
                academic_year TEXT DEFAULT '2026-2027',
                UNIQUE(classroom_id, day, slot, academic_year)
            );
        """)

        # 3. Ad-hoc Classroom Bookings
        conn.execute("""
            CREATE TABLE IF NOT EXISTS classroom_bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                classroom_id TEXT NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
                booking_date DATE NOT NULL,
                slot_start INTEGER NOT NULL,
                slot_end INTEGER NOT NULL,
                department TEXT NOT NULL,
                booked_by TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'Department Staff',
                purpose TEXT NOT NULL,
                attendees INTEGER DEFAULT 0,
                status TEXT DEFAULT 'confirmed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 4. Auditoriums
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auditoriums (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                location TEXT NOT NULL,
                capacity INTEGER NOT NULL,
                stage_size TEXT,
                av_facilities TEXT,
                has_green_room BOOLEAN DEFAULT 1,
                status TEXT DEFAULT 'available',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 5. Auditorium Events
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auditorium_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                auditorium_id TEXT NOT NULL REFERENCES auditoriums(id) ON DELETE CASCADE,
                event_title TEXT NOT NULL,
                event_type TEXT NOT NULL,
                department TEXT NOT NULL,
                organizer_name TEXT NOT NULL,
                contact_email TEXT NOT NULL,
                event_date DATE NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                expected_attendees INTEGER NOT NULL,
                special_requirements TEXT,
                status TEXT DEFAULT 'pending',
                reviewed_by TEXT,
                review_remarks TEXT,
                reviewed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 6. Event Readiness Checklist
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_checklists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL REFERENCES auditorium_events(id) ON DELETE CASCADE,
                item_key TEXT NOT NULL,
                item_label TEXT NOT NULL,
                is_completed BOOLEAN DEFAULT 0,
                verified_by TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(event_id, item_key)
            );
        """)

        # 7. Facility Assets
        conn.execute("""
            CREATE TABLE IF NOT EXISTS facility_assets (
                id TEXT PRIMARY KEY,
                asset_name TEXT NOT NULL,
                category TEXT NOT NULL,
                location_type TEXT NOT NULL,
                location_id TEXT NOT NULL,
                serial_number TEXT,
                condition TEXT DEFAULT 'Good',
                install_date DATE,
                last_serviced_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 8. Maintenance Requests
        conn.execute("""
            CREATE TABLE IF NOT EXISTS maintenance_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_no TEXT UNIQUE NOT NULL,
                asset_id TEXT REFERENCES facility_assets(id) ON DELETE SET NULL,
                location_type TEXT NOT NULL,
                location_id TEXT NOT NULL,
                category TEXT NOT NULL,
                issue_title TEXT NOT NULL,
                description TEXT NOT NULL,
                priority TEXT NOT NULL,
                blocks_space BOOLEAN DEFAULT 0,
                status TEXT DEFAULT 'reported',
                reported_by TEXT NOT NULL,
                reported_by_role TEXT NOT NULL DEFAULT 'Department Staff',
                assigned_to TEXT,
                estimated_completion DATE,
                resolution_notes TEXT,
                resolved_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 9. Preventive Maintenance
        conn.execute("""
            CREATE TABLE IF NOT EXISTS preventive_maintenance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                location_id TEXT NOT NULL,
                frequency_days INTEGER NOT NULL,
                last_conducted DATE,
                next_due_date DATE NOT NULL,
                assigned_staff TEXT,
                checklist_template TEXT,
                status TEXT DEFAULT 'pending'
            );
        """)

        # 10. Maintenance Logs
        conn.execute("""
            CREATE TABLE IF NOT EXISTS maintenance_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_no TEXT NOT NULL,
                action TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                role TEXT NOT NULL,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

    conn.close()
    seed_initial_data()


def seed_initial_data():
    """Seed classrooms from roomCapacity_FST.xlsx and populate initial auditoriums, assets & PM tasks."""
    conn = get_db()
    cursor = conn.cursor()

    # 1. Seed Classrooms from roomCapacity_FST.xlsx
    cursor.execute("SELECT COUNT(*) FROM classrooms;")
    if cursor.fetchone()[0] == 0:
        logger.info("Classrooms table is empty. Seeding from %s...", ROOMS_FILE)
        try:
            import pandas as pd
            if os.path.exists(ROOMS_FILE):
                df = pd.read_excel(ROOMS_FILE)
                # Parse blocks: starts at col 0, 5, 10
                block_starts = [0, 5, 10]
                classrooms_to_insert = []

                for start_col in block_starts:
                    room_col = start_col
                    bench_col = start_col + 1
                    seat_col = start_col + 2

                    for _, row in df.iterrows():
                        room_raw = row.iloc[room_col]
                        bench_raw = row.iloc[bench_col]
                        seat_raw = row.iloc[seat_col]

                        if pd.isna(room_raw) or str(room_raw).strip() == "":
                            continue

                        room_id = str(room_raw).strip()
                        try:
                            bench_cnt = int(bench_raw) if not pd.isna(bench_raw) else 30
                        except Exception:
                            bench_cnt = 30

                        # Determine seating capacity
                        try:
                            seat_str = str(seat_raw).strip()
                            if "-" in seat_str:
                                parts = seat_str.split("-")
                                cap = int(parts[1]) - int(parts[0]) + 1
                            else:
                                cap = bench_cnt * 2
                        except Exception:
                            cap = bench_cnt * 2

                        block = "Ground Floor Wing A" if "G" in room_id.upper() else "Main Academic Block"
                        floor = 0 if "G" in room_id.upper() else 1
                        room_type = "Seminar Hall" if cap > 90 else "Lecture Hall"
                        has_ac = 1 if cap > 90 else 0
                        has_audio = 1 if cap >= 70 else 0

                        classrooms_to_insert.append((
                            room_id, f"Classroom {room_id}", block, floor,
                            bench_cnt, cap, room_type, 1, has_audio, has_ac, "available"
                        ))

                # Deduplicate by room_id
                seen = set()
                deduped = []
                for cr in classrooms_to_insert:
                    if cr[0] not in seen:
                        seen.add(cr[0])
                        deduped.append(cr)

                with conn:
                    conn.executemany("""
                        INSERT OR IGNORE INTO classrooms 
                        (id, name, block, floor, bench_count, seating_capacity, room_type, has_projector, has_audio, has_ac, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, deduped)
                logger.info("Successfully seeded %d classrooms from Excel.", len(deduped))
        except Exception as e:
            logger.error("Failed to seed classrooms from Excel: %s", e)

    # 2. Seed Auditoriums (Campus has 1 Primary Auditorium)
    cursor.execute("SELECT COUNT(*) FROM auditoriums;")
    if cursor.fetchone()[0] == 0:
        auditoriums_data = [
            ("AUD-MAIN", "Central Campus Auditorium", "Central Administration Building", 200, "40ft x 25ft Elevated Teak Stage", "Dual 4K Laser Projectors, 32-Channel Dolby Surround, Wireless Collar & Podium Mics, Intelligent Stage Lighting", 1, "available"),
        ]
        with conn:
            conn.executemany("""
                INSERT INTO auditoriums (id, name, location, capacity, stage_size, av_facilities, has_green_room, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, auditoriums_data)
        logger.info("Seeded %d campus auditorium.", len(auditoriums_data))

    # 3. Seed Facility Assets
    cursor.execute("SELECT COUNT(*) FROM facility_assets;")
    if cursor.fetchone()[0] == 0:
        sample_assets = [
            ("AST-PRJ-G16", "Epson Full-HD Laser Projector", "IT/AV", "classroom", "G-16", "SN-EPS-98214", "Good", "2024-06-15", "2026-09-10"),
            ("AST-AC-G16", "Voltas 2.0 Ton Inverter Split AC", "HVAC", "classroom", "G-16", "SN-VOL-44120", "Good", "2024-03-20", "2026-10-01"),
            ("AST-AV-AUDMAIN", "Yamaha 32-Channel Digital Mixer", "IT/AV", "auditorium", "AUD-MAIN", "SN-YAM-88123", "Good", "2023-11-10", "2026-10-15"),
            ("AST-AC-AUDMAIN", "BlueStar 15-Ton Central Chiller Unit", "HVAC", "auditorium", "AUD-MAIN", "SN-BLU-10293", "Good", "2023-08-01", "2026-09-20"),
            ("AST-PRJ-AUDMAIN2", "Sony 4K Venue Laser Projector", "IT/AV", "auditorium", "AUD-MAIN", "SN-SNY-33019", "Good", "2024-01-12", "2026-08-15"),
            ("AST-SB-G04", "ViewSonic 75-inch Interactive Smartboard", "IT/AV", "classroom", "G04", "SN-VS-77291", "Good", "2024-07-05", "2026-10-10"),
            ("AST-GEN-AUDMAIN", "Kirloskar 62.5 kVA Silent Diesel Generator", "Electrical", "auditorium", "AUD-MAIN", "SN-KIR-55201", "Fair", "2022-04-18", "2026-07-12"),
            ("AST-PLM-BLKA", "Main Academic Block Restroom Water Pump", "Plumbing", "general", "BLKA", "SN-CRI-99104", "Good", "2023-05-10", "2026-08-30"),
        ]
        with conn:
            conn.executemany("""
                INSERT INTO facility_assets (id, asset_name, category, location_type, location_id, serial_number, condition, install_date, last_serviced_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, sample_assets)
        logger.info("Seeded %d facility assets.", len(sample_assets))

    # 4. Seed Sample Preventive Maintenance Tasks
    cursor.execute("SELECT COUNT(*) FROM preventive_maintenance;")
    if cursor.fetchone()[0] == 0:
        sample_pm = [
            ("Air Conditioning Filter Cleaning & Coolant Check", "HVAC", "G-16", 30, "2026-10-01", "2026-11-01", "Ramesh (HVAC Tech)", "Filter wash, gas pressure inspection, thermostat calibration", "overdue"),
            ("Main Auditorium AV Mixer & Mic Calibration", "IT/AV", "AUD-MAIN", 60, "2026-09-15", "2026-11-15", "Kiran (Sound Engineer)", "Check stage line balance, replace wireless mic batteries, clean faders", "pending"),
            ("Interactive Smartboard Firmware & Touch Calibration", "IT/AV", "G04", 90, "2026-08-10", "2026-11-10", "Suresh (IT Support)", "Inspect HDMI cabling, apply firmware patches, align optical sensors", "pending"),
            ("Campus Generator Load Test & Fuel Top-up", "Electrical", "AUD-MAIN", 30, "2026-10-10", "2026-11-10", "Mahesh (Electrician)", "Check battery voltage, engine oil level, automatic transfer switch test", "pending"),
        ]
        with conn:
            conn.executemany("""
                INSERT INTO preventive_maintenance (title, category, location_id, frequency_days, last_conducted, next_due_date, assigned_staff, checklist_template, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, sample_pm)
        logger.info("Seeded %d preventive maintenance schedules.", len(sample_pm))

    conn.close()
