"""
timetable/models.py — Schema definition and persistence layer for the Automatic Timetable Generation Engine.

Supports all 14 entity specifications:
- academic_years, semesters, departments, sections
- subjects, subject_semester_mapping, faculty_subject_assignments, faculty_availability
- room_availability, timetable_generations, timetable_versions, timetable_entries, timetable_constraints
"""

import sqlite3
import os
import sys
import logging
from datetime import datetime, date

_cached_site = os.path.expanduser(r"~\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages")
if os.path.isdir(_cached_site) and _cached_site not in sys.path:
    sys.path.insert(0, _cached_site)

from campus import db as campus_db

logger = logging.getLogger(__name__)

STANDARD_WORKING_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
STANDARD_SLOTS = {
    1: {"name": "Slot 1", "time": "09:00 - 09:50", "is_lunch": False},
    2: {"name": "Slot 2", "time": "09:50 - 10:40", "is_lunch": False},
    3: {"name": "Slot 3", "time": "10:50 - 11:40", "is_lunch": False},
    4: {"name": "Slot 4", "time": "11:40 - 12:30", "is_lunch": False},
    5: {"name": "Slot 5 (Lunch)", "time": "12:30 - 01:20", "is_lunch": True},
    6: {"name": "Slot 6", "time": "01:20 - 02:10", "is_lunch": False},
    7: {"name": "Slot 7", "time": "02:10 - 03:00", "is_lunch": False},
    8: {"name": "Slot 8", "time": "03:00 - 03:50", "is_lunch": False},
    9: {"name": "Slot 9", "time": "03:50 - 04:40", "is_lunch": False}
}


def init_timetable_db():
    """Create all relational tables required for timetable generation."""
    conn = campus_db.get_db()
    with conn:
        # 1. Academic Years
        conn.execute("""
            CREATE TABLE IF NOT EXISTS academic_years (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                is_current BOOLEAN DEFAULT 1,
                start_date DATE,
                end_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 2. Semesters
        conn.execute("""
            CREATE TABLE IF NOT EXISTS semesters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                academic_year_id INTEGER NOT NULL REFERENCES academic_years(id) ON DELETE CASCADE,
                code TEXT NOT NULL,
                number INTEGER NOT NULL,
                name TEXT NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(academic_year_id, number)
            );
        """)

        # 3. Departments
        conn.execute("""
            CREATE TABLE IF NOT EXISTS departments (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                code TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 4. Sections
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_id TEXT NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
                semester_id INTEGER NOT NULL REFERENCES semesters(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                display_name TEXT NOT NULL,
                student_count INTEGER DEFAULT 60 NOT NULL,
                preferred_classroom_id TEXT REFERENCES classrooms(id) ON DELETE SET NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(department_id, semester_id, name)
            );
        """)

        # 5. Subjects
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                short_name TEXT,
                department_id TEXT NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
                subject_type TEXT DEFAULT 'theory',
                weekly_lecture_hours INTEGER DEFAULT 3 NOT NULL,
                weekly_lab_hours INTEGER DEFAULT 0 NOT NULL,
                consecutive_slots INTEGER DEFAULT 1 NOT NULL,
                requires_lab_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 6. Subject-Semester Mapping
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subject_semester_mapping (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                semester_id INTEGER NOT NULL REFERENCES semesters(id) ON DELETE CASCADE,
                is_elective BOOLEAN DEFAULT 0,
                UNIQUE(subject_id, semester_id)
            );
        """)

        # 7. Faculty-Subject Assignments
        conn.execute("""
            CREATE TABLE IF NOT EXISTS faculty_subject_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                faculty_name TEXT NOT NULL,
                faculty_id TEXT,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
                is_primary BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(faculty_name, subject_id, section_id)
            );
        """)

        # 8. Faculty Availability
        conn.execute("""
            CREATE TABLE IF NOT EXISTS faculty_availability (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                faculty_name TEXT NOT NULL,
                day TEXT NOT NULL,
                slot INTEGER NOT NULL,
                is_available BOOLEAN DEFAULT 1,
                reason TEXT,
                UNIQUE(faculty_name, day, slot)
            );
        """)

        # 9. Room Availability (Overrides)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS room_availability (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id TEXT NOT NULL,
                day TEXT NOT NULL,
                slot INTEGER NOT NULL,
                is_available BOOLEAN DEFAULT 1,
                reason TEXT,
                UNIQUE(room_id, day, slot)
            );
        """)

        # 10. Timetable Generations
        conn.execute("""
            CREATE TABLE IF NOT EXISTS timetable_generations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                academic_year_id INTEGER REFERENCES academic_years(id) ON DELETE SET NULL,
                semester_id INTEGER REFERENCES semesters(id) ON DELETE SET NULL,
                department_id TEXT REFERENCES departments(id) ON DELETE SET NULL,
                scope TEXT NOT NULL,
                target_section_ids TEXT,
                status TEXT DEFAULT 'draft',
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                published_at TIMESTAMP,
                published_by TEXT,
                algorithm_used TEXT DEFAULT 'CSP-Backtracking-MRV',
                solve_time_seconds REAL DEFAULT 0.0,
                total_classes_scheduled INTEGER DEFAULT 0,
                total_slots_requested INTEGER DEFAULT 0,
                conflict_count INTEGER DEFAULT 0,
                validation_report TEXT,
                diagnostic_message TEXT
            );
        """)

        # 11. Timetable Versions
        conn.execute("""
            CREATE TABLE IF NOT EXISTS timetable_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                generation_id INTEGER NOT NULL REFERENCES timetable_generations(id) ON DELETE CASCADE,
                version_number INTEGER NOT NULL DEFAULT 1,
                is_published BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by TEXT,
                remarks TEXT,
                UNIQUE(generation_id, version_number)
            );
        """)

        # 12. Timetable Entries
        conn.execute("""
            CREATE TABLE IF NOT EXISTS timetable_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                generation_id INTEGER NOT NULL REFERENCES timetable_generations(id) ON DELETE CASCADE,
                version_id INTEGER NOT NULL REFERENCES timetable_versions(id) ON DELETE CASCADE,
                section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                faculty_name TEXT NOT NULL,
                room_id TEXT NOT NULL,
                day TEXT NOT NULL,
                slot INTEGER NOT NULL,
                is_lab BOOLEAN DEFAULT 0,
                lab_group TEXT DEFAULT 'ALL',
                status TEXT DEFAULT 'valid',
                is_manually_adjusted BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(version_id, section_id, day, slot)
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tt_entries_lookup ON timetable_entries(version_id, day, slot);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tt_faculty_lookup ON timetable_entries(version_id, faculty_name, day, slot);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tt_room_lookup ON timetable_entries(version_id, room_id, day, slot);")

        # 13. Timetable Constraints
        conn.execute("""
            CREATE TABLE IF NOT EXISTS timetable_constraints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                constraint_type TEXT NOT NULL,
                rule_code TEXT UNIQUE NOT NULL,
                parameters TEXT,
                is_active BOOLEAN DEFAULT 1
            );
        """)

    # Ensure institutional computer labs are registered in classrooms inventory
    lab_rooms = [
        ('L1', 'Computer Lab L1 (LIVIA)', 'Block-G', 1, 35, 70, 'Computer Lab'),
        ('L2', 'Computer Lab L2 (LART)', 'Block-R', 1, 35, 70, 'Computer Lab'),
        ('L3', 'Computer Lab L3 (VLSI)', 'Block-G', 2, 35, 70, 'Computer Lab'),
        ('L4', 'Computer Lab L4 (LLOCK)', 'Block-L', 1, 35, 70, 'Computer Lab'),
        ('LAB-1', 'Central Computing Facility Lab 1', 'Main Block', 1, 35, 70, 'Computer Lab'),
        ('LAB-2', 'Central Computing Facility Lab 2', 'Main Block', 1, 35, 70, 'Computer Lab'),
        ('LAB-3', 'Central Computing Facility Lab 3', 'Main Block', 2, 35, 70, 'Computer Lab'),
        ('LAB-4', 'Central Computing Facility Lab 4', 'Main Block', 2, 35, 70, 'Computer Lab')
    ]
    with conn:
        for l_id, l_name, l_blk, l_flr, l_bch, l_cap, l_type in lab_rooms:
            conn.execute("""
                INSERT OR IGNORE INTO classrooms (id, name, block, floor, bench_count, seating_capacity, room_type, has_projector, has_ac, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, 'available');
            """, (l_id, l_name, l_blk, l_flr, l_bch, l_cap, l_type))

    conn.close()
    seed_master_curriculum_data()


def seed_master_curriculum_data():
    """Seed authentic academic master data for CSE & ECE departments if not present."""
    conn = campus_db.get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM academic_years;")
    if cursor.fetchone()[0] == 0:
        logger.info("Seeding academic curriculum master data for timetable engine...")
        with conn:
            # 1. Academic Year
            cursor.execute("""
                INSERT INTO academic_years (code, name, is_current, start_date, end_date)
                VALUES ('2026-2027', 'Academic Year 2026-2027', 1, '2026-07-01', '2027-05-31');
            """)
            ay_id = cursor.lastrowid

            # 2. Semesters
            cursor.execute("""
                INSERT INTO semesters (academic_year_id, code, number, name, is_active)
                VALUES (?, 'SEM-3', 3, 'Semester 3 (Fall / Odd 2026)', 1);
            """, (ay_id,))
            sem_id = cursor.lastrowid

            # 3. Departments
            dept_data = [
                ('CSE', 'Computer Science & Engineering', 'CSE'),
                ('ECE', 'Electronics & Communication Engineering', 'ECE')
            ]
            cursor.executemany("INSERT INTO departments (id, name, code) VALUES (?, ?, ?);", dept_data)

            # 4. Sections
            sections_data = [
                ('CSE', sem_id, 'A', 'CSE Year II - Section A', 60, 'G16'),
                ('CSE', sem_id, 'B', 'CSE Year II - Section B', 60, 'G04')
            ]
            cursor.executemany("""
                INSERT INTO sections (department_id, semester_id, name, display_name, student_count, preferred_classroom_id)
                VALUES (?, ?, ?, ?, ?, ?);
            """, sections_data)
            cursor.execute("SELECT id, name FROM sections WHERE department_id = 'CSE';")
            sec_map = {row['name']: row['id'] for row in cursor.fetchall()}

            # 5. Subjects
            # Lecture hours + lab hours + consecutive slots for practicals
            subjects_data = [
                ('CS201', 'Data Structures & Algorithms', 'DSA', 'CSE', 'theory', 4, 0, 1, None),
                ('CS203', 'Object Oriented Programming', 'OOP', 'CSE', 'theory', 3, 2, 2, 'computer_lab'),
                ('CS205', 'Database Management Systems', 'DBMS', 'CSE', 'theory', 3, 2, 2, 'computer_lab'),
                ('BS105', 'Probability & Statistics', 'P&S', 'CSE', 'theory', 4, 0, 1, None),
                ('CS207', 'Computer Organization & Architecture', 'COA', 'CSE', 'theory', 3, 0, 1, None),
                ('HS101', 'Professional Ethics & Soft Skills', 'Ethics', 'CSE', 'theory', 2, 0, 1, None)
            ]
            cursor.executemany("""
                INSERT INTO subjects (code, name, short_name, department_id, subject_type, weekly_lecture_hours, weekly_lab_hours, consecutive_slots, requires_lab_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, subjects_data)
            cursor.execute("SELECT id, code FROM subjects;")
            subj_map = {row['code']: row['id'] for row in cursor.fetchall()}

            # 6. Map subjects to semester
            mapping_data = [(s_id, sem_id, 0) for s_id in subj_map.values()]
            cursor.executemany("""
                INSERT INTO subject_semester_mapping (subject_id, semester_id, is_elective)
                VALUES (?, ?, ?);
            """, mapping_data)

            # 7. Faculty Assignments
            # Realistic institutional faculty assignments sharing teachers across sections A & B
            sec_a = sec_map.get('A')
            sec_b = sec_map.get('B')

            assignments = [
                # Section A
                ('Dr. T. Bharat Kumar', 'faculty', subj_map['CS203'], sec_a, 1), # OOP Sec A
                ('Dr. K. Srinivas', 'srinivas', subj_map['CS205'], sec_a, 1),   # DBMS Sec A
                ('Prof. P. Sunitha', 'sunitha', subj_map['CS201'], sec_a, 1),    # DSA Sec A
                ('Dr. R. V. Sharma', 'sharma', subj_map['BS105'], sec_a, 1),     # P&S Sec A
                ('Prof. Anjali Nair', 'anjali', subj_map['CS207'], sec_a, 1),    # COA Sec A
                ('Prof. Anjali Nair', 'anjali', subj_map['HS101'], sec_a, 1),    # Ethics Sec A

                # Section B (Shares Dr. Bharat for OOP, Sunitha for DSA, Dr. Gupta for DBMS)
                ('Dr. T. Bharat Kumar', 'faculty', subj_map['CS203'], sec_b, 1), # OOP Sec B (Shared Teacher!)
                ('Dr. Manoj Gupta', 'mgupta', subj_map['CS205'], sec_b, 1),     # DBMS Sec B
                ('Prof. P. Sunitha', 'sunitha', subj_map['CS201'], sec_b, 1),    # DSA Sec B (Shared Teacher!)
                ('Dr. R. V. Sharma', 'sharma', subj_map['BS105'], sec_b, 1),     # P&S Sec B (Shared Teacher!)
                ('Prof. Anjali Nair', 'anjali', subj_map['CS207'], sec_b, 1),    # COA Sec B (Shared Teacher!)
                ('Prof. K. Ramesh', 'kramesh', subj_map['HS101'], sec_b, 1)      # Ethics Sec B
            ]
            cursor.executemany("""
                INSERT INTO faculty_subject_assignments (faculty_name, faculty_id, subject_id, section_id, is_primary)
                VALUES (?, ?, ?, ?, ?);
            """, assignments)

            # 8. Constraints configuration
            default_constraints = [
                ('No Section Overlap', 'hard', 'C_NO_SECTION_OVERLAP', '{"description": "A section cannot attend multiple classes in the same period"}', 1),
                ('No Faculty Collision', 'hard', 'C_NO_FACULTY_OVERLAP', '{"description": "A faculty member cannot teach multiple sections in the same period"}', 1),
                ('No Room Double Booking', 'hard', 'C_NO_ROOM_OVERLAP', '{"description": "A room cannot host multiple classes in the same period"}', 1),
                ('Room Capacity Constraint', 'hard', 'C_ROOM_CAPACITY', '{"description": "Room seating capacity must be >= section student count"}', 1),
                ('Satisfy Weekly Subject Hours', 'hard', 'C_WEEKLY_HOURS', '{"description": "Exact weekly hours must be scheduled"}', 1),
                ('Respect Lunch Break', 'hard', 'C_LUNCH_BREAK', '{"description": "No academic classes in Slot 5"}', 1),
                ('Consecutive Lab Practical Slots', 'hard', 'C_CONSECUTIVE_LAB_SLOTS', '{"description": "Lab practical sessions must occupy consecutive slots"}', 1),
                ('Lab Resource Suitability', 'hard', 'C_LAB_ROOM_SUITABILITY', '{"description": "Labs must be allocated in designated computer/hardware labs"}', 1),
                ('Respect Faculty Unavailability', 'hard', 'C_FACULTY_AVAILABILITY', '{"description": "Do not schedule faculty in unavailable periods"}', 1),
                ('Respect Maintenance Blocks', 'hard', 'C_MAINTENANCE_DOWNTIME', '{"description": "Rooms under critical maintenance are blocked"}', 1),
                ('Distribute Subjects Across Week', 'soft', 'C_SUBJECT_SPREAD', '{"description": "Avoid scheduling the same theory subject repeatedly on the same day"}', 1),
                ('Minimize Faculty Idle Gaps', 'soft', 'C_FACULTY_GAPS', '{"description": "Group faculty lecture hours to avoid large fragmented breaks"}', 1)
            ]
            cursor.executemany("""
                INSERT INTO timetable_constraints (name, constraint_type, rule_code, parameters, is_active)
                VALUES (?, ?, ?, ?, ?);
            """, default_constraints)

        logger.info("Successfully seeded academic curriculum master data.")

    conn.close()
