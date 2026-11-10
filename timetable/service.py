"""
timetable/service.py — Business logic, versioning, publishing, manual adjustments,
maintenance impact analysis, and Excel curriculum import/export.
"""

import os
import json
import logging
from datetime import datetime
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from campus import db as campus_db
from campus import scheduling_service
from .models import STANDARD_WORKING_DAYS, STANDARD_SLOTS
from .engine import generate_academic_timetable
from .validator import validate_timetable
from .pdf_export import generate_timetable_pdf

logger = logging.getLogger(__name__)


def get_wizard_init_data() -> dict:
    """Retrieve all prerequisites for the Dynamic Timetable Generation Wizard."""
    conn = campus_db.get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM academic_years ORDER BY is_current DESC, id DESC;")
    ay_list = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM departments ORDER BY name ASC;")
    dept_list = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM semesters ORDER BY number ASC;")
    sem_list = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM classrooms ORDER BY block, floor, id ASC;")
    all_rooms = [dict(r) for r in cursor.fetchall()]

    classrooms = []
    labs = []
    for r in all_rooms:
        r_type = (r.get("room_type") or "").lower()
        r_id = r["id"].upper()
        if "lab" in r_type or r_id.startswith("L") or r_id.startswith("LAB"):
            labs.append(r)
        else:
            classrooms.append(r)

    # Distinct faculty list
    cursor.execute("SELECT DISTINCT name FROM users WHERE role = 'faculty' AND name IS NOT NULL;")
    f_users = [r[0] for r in cursor.fetchall()]
    cursor.execute("SELECT DISTINCT faculty_name FROM faculty_subject_assignments WHERE faculty_name IS NOT NULL;")
    f_asgns = [r[0] for r in cursor.fetchall()]
    core_faculty = [
        "Dr. T. Bharat Kumar", "Prof. P. Sunitha", "Dr. R. V. Sharma",
        "Dr. K. Srinivas", "Prof. Anjali Nair", "Dr. Manoj Gupta", "Prof. K. Ramesh"
    ]
    faculty_list = sorted(list(set(f_users + f_asgns + core_faculty)))

    conn.close()
    return {
        "academic_years": ay_list,
        "departments": dept_list,
        "semesters": sem_list,
        "classrooms": classrooms,
        "labs": labs,
        "faculty": faculty_list,
        "standard_days": STANDARD_WORKING_DAYS,
        "standard_slots": STANDARD_SLOTS
    }


def load_preset_catalog(year: int = 2, semester: int = 3, department: str = "CSE") -> list[dict]:
    """Load authentic IFHE B.Tech course catalog for selected year, semester, and department."""
    catalog_path = os.path.join(os.path.dirname(__file__), "..", "data", "ifhe_course_catalog.json")
    if not os.path.exists(catalog_path):
        return []

    try:
        with open(catalog_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        dept_clean = (department or "CSE").strip().upper()
        dept_name_map = {
            "CSE": "Computer Science & Engineering",
            "AIDS": "Artificial Intelligence & Data Science",
            "AIML": "Artificial Intelligence & Machine Learning"
        }
        full_dept_name = dept_name_map.get(dept_clean, dept_clean)

        matched_courses = []
        for y_obj in data.get("years", []):
            if year and y_obj.get("year") != int(year):
                continue
            for d_obj in y_obj.get("departments", []):
                cur_dept = d_obj.get("department", "").strip()
                cur_dept_id = d_obj.get("departmentId", "").strip().upper()
                if dept_clean in (cur_dept_id, cur_dept.upper()) or full_dept_name.lower() in cur_dept.lower():
                    for c in d_obj.get("courses", []):
                        if str(c.get("semester")) == str(semester):
                            l_hrs = int(c.get("L") or 0)
                            t_hrs = int(c.get("T") or 0)
                            p_hrs = int(c.get("P") or 0)
                            lec_total = l_hrs + t_hrs
                            cr = int(c.get("credits") or 0)
                            is_audit = bool(c.get("isAudit", False))
                            req_lab = (p_hrs > 0)
                            c_slots = 2 if p_hrs >= 2 else (1 if p_hrs == 1 else 1)

                            matched_courses.append({
                                "code": c.get("courseCode"),
                                "name": c.get("courseName"),
                                "subject_type": c.get("courseType", "Core").lower(),
                                "credits": cr,
                                "weekly_lecture_hours": lec_total,
                                "weekly_lab_hours": p_hrs,
                                "consecutive_slots": c_slots,
                                "requires_lab": req_lab,
                                "is_audit": is_audit,
                                "status": "valid"
                            })
        return matched_courses
    except Exception as e:
        logger.error("Failed to load preset course catalog: %s", e)
        return []


def detect_column_mapping(headers: list[str]) -> dict:
    """Intelligently map file headers to standard system fields."""
    mapping = {
        "code_col": "",
        "name_col": "",
        "type_col": "",
        "credits_col": "",
        "lecture_col": "",
        "tutorial_col": "",
        "lab_col": "",
        "faculty_col": ""
    }
    for h in headers:
        hl = h.lower().replace("_", " ").replace("-", " ").strip()
        if not mapping["code_col"] and any(k in hl for k in ["code", "subject code", "course code", "sub code", "id"]):
            mapping["code_col"] = h
        elif not mapping["name_col"] and any(k in hl for k in ["name", "title", "subject name", "course name"]):
            mapping["name_col"] = h
        elif not mapping["type_col"] and any(k in hl for k in ["type", "category", "subject type", "course type"]):
            mapping["type_col"] = h
        elif not mapping["credits_col"] and any(k in hl for k in ["credit", "credits", "cr"]):
            mapping["credits_col"] = h
        elif not mapping["lecture_col"] and hl in ("l", "lec", "lecture", "lectures", "lecture hours", "weekly lecture"):
            mapping["lecture_col"] = h
        elif not mapping["tutorial_col"] and hl in ("t", "tut", "tutorial", "tutorials", "tutorial hours"):
            mapping["tutorial_col"] = h
        elif not mapping["lab_col"] and hl in ("p", "prac", "practical", "practicals", "lab", "lab hours", "weekly lab"):
            mapping["lab_col"] = h
        elif not mapping["faculty_col"] and any(k in hl for k in ["faculty", "teacher", "instructor", "professor", "in charge"]):
            mapping["faculty_col"] = h
    return mapping


def convert_rows_to_subjects(raw_rows: list[dict], mapping: dict) -> list[dict]:
    """Standardize extracted rows into validated subject dictionaries."""
    subjects = []
    seen_codes = set()

    for idx, r in enumerate(raw_rows):
        code_key = mapping.get("code_col")
        name_key = mapping.get("name_col")
        type_key = mapping.get("type_col")
        cr_key = mapping.get("credits_col")
        lec_key = mapping.get("lecture_col")
        tut_key = mapping.get("tutorial_col")
        lab_key = mapping.get("lab_col")
        fac_key = mapping.get("faculty_col")

        code = str(r.get(code_key, "")).strip().upper() if code_key else ""
        name = str(r.get(name_key, "")).strip() if name_key else ""
        stype = str(r.get(type_key, "theory")).strip().lower() if type_key else "theory"

        def _to_int(val, default=0):
            try:
                if val is None or str(val).strip() == "":
                    return default
                return int(float(str(val).strip()))
            except Exception:
                return default

        l_val = _to_int(r.get(lec_key), 0) if lec_key else 0
        t_val = _to_int(r.get(tut_key), 0) if tut_key else 0
        p_val = _to_int(r.get(lab_key), 0) if lab_key else 0
        cr_val = _to_int(r.get(cr_key), 3) if cr_key else 3
        fac_val = str(r.get(fac_key, "")).strip() if fac_key else ""

        # Auto-heuristics if L and P both 0
        if l_val == 0 and p_val == 0:
            if "lab" in stype or "practical" in stype:
                p_val = 2
            else:
                l_val = 3

        weekly_lec = l_val + t_val
        weekly_lab = p_val
        req_lab = (weekly_lab > 0 or "lab" in stype or "practical" in stype)
        c_slots = 2 if weekly_lab >= 2 else 1

        # Validation status
        status = "valid"
        issues = []

        if not code:
            status = "error"
            issues.append("Missing course code")
        elif code in seen_codes:
            status = "error"
            issues.append(f"Duplicate course code '{code}'")
        else:
            seen_codes.add(code)

        if not name:
            status = "error"
            issues.append("Missing course name")

        if (weekly_lec + weekly_lab) <= 0:
            status = "error"
            issues.append("Zero weekly hours")

        subjects.append({
            "id": idx + 1,
            "code": code,
            "name": name,
            "subject_type": stype,
            "credits": cr_val,
            "weekly_lecture_hours": weekly_lec,
            "weekly_lab_hours": weekly_lab,
            "consecutive_slots": c_slots,
            "requires_lab": req_lab,
            "faculty_name": fac_val,
            "status": status,
            "issues": issues
        })

    return subjects


def parse_course_catalog_file(file_storage) -> dict:
    """Parse uploaded Excel, CSV, or JSON course details file."""
    filename = (file_storage.filename or "").lower()
    df = None

    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        df = pd.read_excel(file_storage)
    elif filename.endswith(".csv"):
        df = pd.read_csv(file_storage)
    elif filename.endswith(".json"):
        content = json.load(file_storage)
        if isinstance(content, dict) and "courses" in content:
            df = pd.DataFrame(content["courses"])
        elif isinstance(content, list):
            df = pd.DataFrame(content)
        else:
            raise ValueError("Unsupported JSON format. Expected list of courses.")
    else:
        raise ValueError("Unsupported file format. Please upload .xlsx, .xls, .csv, or .json")

    df = df.dropna(how="all")
    headers = [str(c).strip() for c in df.columns]
    raw_rows = df.fillna("").to_dict(orient="records")

    mapping = detect_column_mapping(headers)
    parsed_subjects = convert_rows_to_subjects(raw_rows, mapping)

    return {
        "headers": headers,
        "suggested_mapping": mapping,
        "raw_rows": raw_rows[:100], # preview sample
        "parsed_subjects": parsed_subjects,
        "total_extracted": len(parsed_subjects)
    }


def execute_dynamic_wizard_generation(payload: dict, user_name: str = "Administrator") -> dict:
    """
    Execute full constraint satisfaction generation from the 5-step dynamic wizard.
    Dynamically creates/updates sections, subjects, faculty mappings, room selections,
    and runs global multi-section CSP solver.
    """
    academic_year_id = int(payload.get("academic_year_id", 1))
    semester_id = int(payload.get("semester_id", 1))
    department_id = str(payload.get("department_id", "CSE")).strip().upper()

    sections_data = payload.get("sections", [])
    if not sections_data:
        sections_data = [
            {"name": "A", "display_name": f"{department_id} Section A", "student_count": 60},
            {"name": "B", "display_name": f"{department_id} Section B", "student_count": 60}
        ]

    subjects_data = payload.get("subjects", [])
    if not subjects_data:
        # Fallback to loading preset catalog for this department/semester
        subjects_data = load_preset_catalog(year=2, semester=semester_id, department=department_id)
        if not subjects_data:
            return {"success": False, "error": "No course catalog provided or available for this semester."}

    working_days = payload.get("working_days") or STANDARD_WORKING_DAYS
    num_periods = int(payload.get("num_periods", 9))
    lunch_slot = int(payload.get("lunch_slot", 5))

    prefs = payload.get("preferences", {})
    max_daily = int(prefs.get("max_daily_periods", 7))
    max_consec = int(prefs.get("max_consecutive_periods", 3))
    is_provisional = bool(prefs.get("is_provisional", False))

    selected_rooms = payload.get("selected_rooms")
    selected_labs = payload.get("selected_labs")
    faculty_assignments = payload.get("faculty_assignments", [])

    conn = campus_db.get_db()
    cursor = conn.cursor()

    sec_ids = []
    sec_name_to_id = {}

    with conn:
        # 1. Sync dynamic sections
        for s in sections_data:
            s_name = str(s.get("name", "A")).strip().upper()
            s_disp = str(s.get("display_name", f"Section {s_name}")).strip()
            s_cnt = int(s.get("student_count", 60))

            cursor.execute("""
                INSERT INTO sections (department_id, semester_id, name, display_name, student_count)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(department_id, semester_id, name) DO UPDATE SET
                    display_name = excluded.display_name,
                    student_count = excluded.student_count;
            """, (department_id, semester_id, s_name, s_disp, s_cnt))
            cursor.execute("SELECT id FROM sections WHERE department_id = ? AND semester_id = ? AND name = ?;",
                           (department_id, semester_id, s_name))
            sec_id = cursor.fetchone()[0]
            sec_ids.append(sec_id)
            sec_name_to_id[s_name] = sec_id

        # 2. Sync subjects
        subj_code_to_id = {}
        for sub in subjects_data:
            code = str(sub.get("code")).strip().upper()
            name = str(sub.get("name")).strip()
            stype = str(sub.get("subject_type", "theory")).strip().lower()
            cr = int(sub.get("credits", 3))
            l_hrs = int(sub.get("weekly_lecture_hours", 3))
            p_hrs = int(sub.get("weekly_lab_hours", 0))
            c_slots = int(sub.get("consecutive_slots", 2 if p_hrs >= 2 else 1))
            req_lab = "computer_lab" if (p_hrs > 0 or sub.get("requires_lab")) else None
            is_audit = int(bool(sub.get("is_audit", False)))

            cursor.execute("""
                INSERT INTO subjects (code, name, department_id, subject_type, weekly_lecture_hours, weekly_lab_hours, consecutive_slots, requires_lab_type, credits, is_audit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name,
                    subject_type = excluded.subject_type,
                    weekly_lecture_hours = excluded.weekly_lecture_hours,
                    weekly_lab_hours = excluded.weekly_lab_hours,
                    consecutive_slots = excluded.consecutive_slots,
                    requires_lab_type = excluded.requires_lab_type,
                    credits = excluded.credits,
                    is_audit = excluded.is_audit;
            """, (code, name, department_id, stype, l_hrs, p_hrs, c_slots, req_lab, cr, is_audit))
            cursor.execute("SELECT id FROM subjects WHERE code = ?;", (code,))
            sub_id = cursor.fetchone()[0]
            subj_code_to_id[code] = sub_id

            cursor.execute("""
                INSERT OR IGNORE INTO subject_semester_mapping (subject_id, semester_id, is_elective)
                VALUES (?, ?, ?);
            """, (sub_id, semester_id, 1 if "elective" in stype else 0))

        # 3. Sync Faculty Assignments
        for sec_id in sec_ids:
            cursor.execute("DELETE FROM faculty_subject_assignments WHERE section_id = ?;", (sec_id,))

        for fa in faculty_assignments:
            code = str(fa.get("subject_code", "")).strip().upper()
            sub_id = subj_code_to_id.get(code)
            if not sub_id:
                continue

            fac_name = str(fa.get("faculty_name", "")).strip()
            if not fac_name:
                fac_name = "Provisional Faculty" if is_provisional else f"Faculty - {code}"

            assigned_secs = fa.get("sections", [])
            if not assigned_secs or "ALL" in [s.upper() for s in assigned_secs]:
                target_s_ids = sec_ids
            else:
                target_s_ids = [sec_name_to_id[s.upper()] for s in assigned_secs if s.upper() in sec_name_to_id]
                if not target_s_ids:
                    target_s_ids = sec_ids

            for s_id in target_s_ids:
                cursor.execute("""
                    INSERT OR REPLACE INTO faculty_subject_assignments (faculty_name, subject_id, section_id, is_primary)
                    VALUES (?, ?, ?, 1);
                """, (fac_name, sub_id, s_id))

        # Ensure all subjects have at least one faculty assignment in each section
        for s_id in sec_ids:
            for code, sub_id in subj_code_to_id.items():
                cursor.execute("SELECT COUNT(*) FROM faculty_subject_assignments WHERE section_id = ? AND subject_id = ?;", (s_id, sub_id))
                if cursor.fetchone()[0] == 0:
                    default_fac = "Provisional Faculty" if is_provisional else f"Faculty - {code}"
                    cursor.execute("""
                        INSERT INTO faculty_subject_assignments (faculty_name, subject_id, section_id, is_primary)
                        VALUES (?, ?, ?, 1);
                    """, (default_fac, sub_id, s_id))

        # 4. Save Faculty Unavailability overrides
        for un in payload.get("faculty_unavailability", []):
            f_name = un.get("faculty_name", "").strip()
            u_day = un.get("day")
            u_slot = int(un.get("slot", 1))
            if f_name and u_day:
                cursor.execute("""
                    INSERT OR REPLACE INTO faculty_availability (faculty_name, day, slot, is_available, reason)
                    VALUES (?, ?, ?, 0, 'Configured in wizard');
                """, (f_name, u_day, u_slot))

    conn.close()

    # 5. Run Global CSP Scheduling Engine across all sections
    gen_result = generate_academic_timetable(
        section_ids=sec_ids,
        working_days=working_days,
        num_periods=num_periods,
        lunch_slot=lunch_slot,
        max_daily_periods=max_daily,
        max_consecutive_periods=max_consec,
        allowed_room_ids=selected_rooms,
        allowed_lab_ids=selected_labs,
        is_provisional=is_provisional
    )

    if not gen_result["success"]:
        return gen_result

    entries = gen_result["entries"]
    val_report = gen_result["validation"]

    conn = campus_db.get_db()
    cursor = conn.cursor()

    with conn:
        # Create Timetable Generation Record
        cursor.execute("""
            INSERT INTO timetable_generations 
            (academic_year_id, semester_id, department_id, scope, target_section_ids, status,
             algorithm_used, total_classes_scheduled, total_slots_requested, conflict_count,
             validation_report, diagnostic_message, config_json)
            VALUES (?, ?, ?, ?, ?, 'draft', 'CSP-Backtracking-MRV', ?, ?, ?, ?, ?, ?);
        """, (
            academic_year_id, semester_id, department_id, "dynamic_wizard",
            json.dumps(sec_ids), len(entries), len(entries),
            val_report.get("conflict_count", 0),
            json.dumps(val_report), gen_result.get("message", "Generated successfully via Dynamic Wizard"),
            json.dumps(payload)
        ))
        gen_id = cursor.lastrowid

        # Create Initial Version
        ver_remarks = "Provisional automated generation" if is_provisional else "Automated CSP generation via Dynamic Wizard"
        cursor.execute("""
            INSERT INTO timetable_versions (generation_id, version_number, is_published, created_by, remarks)
            VALUES (?, 1, 0, ?, ?);
        """, (gen_id, user_name, ver_remarks))
        ver_id = cursor.lastrowid

        # Insert Entries
        entry_rows = [
            (gen_id, ver_id, e["section_id"], e["subject_id"], e["faculty_name"],
             e["room_id"], e["day"], e["slot"], e["is_lab"], "ALL", "valid", 0, int(is_provisional))
            for e in entries
        ]
        cursor.executemany("""
            INSERT INTO timetable_entries 
            (generation_id, version_id, section_id, subject_id, faculty_name, room_id, day, slot, is_lab, lab_group, status, is_manually_adjusted, is_provisional)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, entry_rows)

    conn.close()

    gen_result["generation_id"] = gen_id
    gen_result["version_id"] = ver_id
    gen_result["sections_created"] = len(sec_ids)
    return gen_result


def list_academic_metadata() -> dict:
    """Retrieve lists of academic years, semesters, departments, sections, and subjects."""
    conn = campus_db.get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM academic_years ORDER BY id DESC;")
    ay_list = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM semesters ORDER BY number ASC;")
    sem_list = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM departments ORDER BY id ASC;")
    dept_list = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM sections ORDER BY department_id, name ASC;")
    sec_list = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM subjects ORDER BY code ASC;")
    subj_list = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT fa.*, s.code as subject_code, s.name as subject_name, sec.display_name as section_name
        FROM faculty_subject_assignments fa
        JOIN subjects s ON fa.subject_id = s.id
        JOIN sections sec ON fa.section_id = sec.id
        ORDER BY sec.display_name, s.code ASC;
    """)
    asgn_list = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return {
        "academic_years": ay_list,
        "semesters": sem_list,
        "departments": dept_list,
        "sections": sec_list,
        "subjects": subj_list,
        "assignments": asgn_list
    }


def execute_timetable_generation(section_ids: list[int], scope: str = "section",
                                  academic_year_id: int = 1, semester_id: int = 1,
                                  department_id: str = "CSE", user_name: str = "Administrator") -> dict:
    """
    Run CSP generation engine and persist generated schedule as 'draft' version.
    """
    gen_result = generate_academic_timetable(section_ids=section_ids)

    if not gen_result["success"]:
        return gen_result

    entries = gen_result["entries"]
    val_report = gen_result["validation"]

    conn = campus_db.get_db()
    cursor = conn.cursor()

    with conn:
        # 1. Create Timetable Generation Record
        cursor.execute("""
            INSERT INTO timetable_generations 
            (academic_year_id, semester_id, department_id, scope, target_section_ids, status,
             algorithm_used, total_classes_scheduled, total_slots_requested, conflict_count,
             validation_report, diagnostic_message)
            VALUES (?, ?, ?, ?, ?, 'draft', 'CSP-Backtracking-MRV', ?, ?, ?, ?, ?);
        """, (
            academic_year_id, semester_id, department_id, scope,
            json.dumps(section_ids), len(entries), len(entries),
            val_report.get("conflict_count", 0),
            json.dumps(val_report), gen_result.get("message", "Generated successfully")
        ))
        gen_id = cursor.lastrowid

        # 2. Create Initial Version (Version 1)
        cursor.execute("""
            INSERT INTO timetable_versions (generation_id, version_number, is_published, created_by, remarks)
            VALUES (?, 1, 0, ?, 'Initial automated CSP generation');
        """, (gen_id, user_name))
        ver_id = cursor.lastrowid

        # 3. Insert Entries
        entry_rows = [
            (gen_id, ver_id, e["section_id"], e["subject_id"], e["faculty_name"],
             e["room_id"], e["day"], e["slot"], e["is_lab"], "ALL", "valid", 0)
            for e in entries
        ]
        cursor.executemany("""
            INSERT INTO timetable_entries 
            (generation_id, version_id, section_id, subject_id, faculty_name, room_id, day, slot, is_lab, lab_group, status, is_manually_adjusted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, entry_rows)

    conn.close()

    gen_result["generation_id"] = gen_id
    gen_result["version_id"] = ver_id
    return gen_result


def get_generation_details(generation_id: int) -> dict | None:
    """Retrieve full details, versions, and validation report for a generation."""
    conn = campus_db.get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM timetable_generations WHERE id = ?;", (generation_id,))
    gen = cursor.fetchone()
    if not gen:
        conn.close()
        return None

    gen_dict = dict(gen)
    if gen_dict.get("validation_report"):
        try:
            gen_dict["validation_report"] = json.loads(gen_dict["validation_report"])
        except Exception:
            pass

    cursor.execute("SELECT * FROM timetable_versions WHERE generation_id = ? ORDER BY version_number DESC;", (generation_id,))
    gen_dict["versions"] = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return gen_dict


def list_generations() -> list[dict]:
    """Retrieve list of all timetable generations."""
    conn = campus_db.get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT tg.*, ay.code as academic_year_code, s.name as semester_name, d.name as department_name
        FROM timetable_generations tg
        LEFT JOIN academic_years ay ON tg.academic_year_id = ay.id
        LEFT JOIN semesters s ON tg.semester_id = s.id
        LEFT JOIN departments d ON tg.department_id = d.id
        ORDER BY tg.id DESC;
    """)
    rows = cursor.fetchall()
    conn.close()

    res = []
    for r in rows:
        item = dict(r)
        if item.get("validation_report"):
            try:
                item["validation_report"] = json.loads(item["validation_report"])
            except Exception:
                pass
        res.append(item)
    return res


def get_timetable_matrix(version_id: int, view_type: str = "section", target_id: str = None) -> dict:
    """
    Format timetable entries into a weekly matrix (Mon-Fri x Slots 1-9) for a section, faculty, room, or all sections.
    """
    conn = campus_db.get_db()
    cursor = conn.cursor()

    # Dynamic section tabs available for this version
    cursor.execute("""
        SELECT DISTINCT sec.id, sec.name, sec.display_name
        FROM timetable_entries te
        JOIN sections sec ON te.section_id = sec.id
        WHERE te.version_id = ?
        ORDER BY sec.name ASC;
    """, (version_id,))
    sec_tabs = [dict(r) for r in cursor.fetchall()]

    # Faculty tabs available
    cursor.execute("""
        SELECT DISTINCT te.faculty_name
        FROM timetable_entries te
        WHERE te.version_id = ? AND te.faculty_name IS NOT NULL
        ORDER BY te.faculty_name ASC;
    """, (version_id,))
    faculty_tabs = [r[0] for r in cursor.fetchall()]

    # Classroom tabs available
    cursor.execute("""
        SELECT DISTINCT te.room_id
        FROM timetable_entries te
        WHERE te.version_id = ? AND te.room_id IS NOT NULL AND te.is_lab = 0
        ORDER BY te.room_id ASC;
    """, (version_id,))
    room_tabs = [r[0] for r in cursor.fetchall()]

    # Lab tabs available
    cursor.execute("""
        SELECT DISTINCT te.room_id
        FROM timetable_entries te
        WHERE te.version_id = ? AND te.is_lab = 1
        ORDER BY te.room_id ASC;
    """, (version_id,))
    lab_tabs = [r[0] for r in cursor.fetchall()]

    query = """
        SELECT te.*, s.code as subject_code, s.name as subject_name,
               sec.name as section_name, sec.display_name as section_display,
               cr.name as room_name, cr.room_type
        FROM timetable_entries te
        JOIN subjects s ON te.subject_id = s.id
        JOIN sections sec ON te.section_id = sec.id
        LEFT JOIN classrooms cr ON te.room_id = cr.id
        WHERE te.version_id = ?
    """
    params = [version_id]

    if view_type == "section" and target_id:
        query += " AND te.section_id = ?"
        params.append(int(target_id))
    elif view_type == "faculty" and target_id:
        query += " AND LOWER(te.faculty_name) = LOWER(?)"
        params.append(target_id.strip())
    elif (view_type == "classroom" or view_type == "lab") and target_id:
        query += " AND LOWER(te.room_id) = LOWER(?)"
        params.append(target_id.strip())

    query += " ORDER BY te.day, te.slot, sec.name ASC;"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    # Build blank grid
    days = STANDARD_WORKING_DAYS
    slots = list(range(1, 10))
    grid = {d: {s: None for s in slots} for d in days}

    # Mark lunch in grid
    for d in days:
        grid[d][5] = {"is_lunch": True, "subject_code": "LUNCH", "subject_name": "Lunch Break"}

    entries_list = []
    all_sections_grid = {d: {s: [] for s in slots} for d in days}

    for r in rows:
        item = dict(r)
        d = item["day"]
        s = item["slot"]
        entries_list.append(item)

        if d in all_sections_grid and s in all_sections_grid[d]:
            all_sections_grid[d][s].append(item)

        if view_type != "all_sections":
            if d in grid and s in grid[d]:
                grid[d][s] = item

    if view_type == "all_sections":
        for d in days:
            for s in slots:
                if s == 5:
                    grid[d][s] = {"is_lunch": True, "subject_code": "LUNCH", "subject_name": "Lunch Break"}
                else:
                    grid[d][s] = all_sections_grid[d][s]

    return {
        "view_type": view_type,
        "target_id": target_id,
        "days": days,
        "slots": slots,
        "grid": grid,
        "entries": entries_list,
        "slot_times": STANDARD_SLOTS,
        "sec_tabs": sec_tabs,
        "faculty_tabs": faculty_tabs,
        "room_tabs": room_tabs,
        "lab_tabs": lab_tabs
    }


def adjust_timetable_entry(entry_id: int, new_day: str, new_slot: int, new_room_id: str) -> dict:
    """
    Manually adjust a timetable entry to a new day, slot, or room.
    Automatically re-validates the schedule and ensures no conflict is introduced.
    """
    conn = campus_db.get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM timetable_entries WHERE id = ?;", (entry_id,))
    entry = cursor.fetchone()
    if not entry:
        conn.close()
        return {"success": False, "error": f"Entry {entry_id} not found."}

    entry_dict = dict(entry)
    ver_id = entry_dict["version_id"]

    # Lunch break check
    if new_slot == 5:
        conn.close()
        return {"success": False, "error": "Cannot assign a lecture or lab to Slot 5 (Lunch Break)."}

    # Fetch all entries for this version
    cursor.execute("SELECT * FROM timetable_entries WHERE version_id = ?;", (ver_id,))
    all_entries = [dict(r) for r in cursor.fetchall()]

    # Fetch metadata for validation
    cursor.execute("SELECT * FROM sections;")
    sections = [dict(r) for r in cursor.fetchall()]
    cursor.execute("SELECT * FROM subjects;")
    subjects = [dict(r) for r in cursor.fetchall()]
    cursor.execute("SELECT * FROM classrooms;")
    classrooms = [dict(r) for r in cursor.fetchall()]

    # Simulate modification
    for e in all_entries:
        if e["id"] == entry_id:
            e["day"] = new_day
            e["slot"] = new_slot
            e["room_id"] = new_room_id.strip()

    # Re-validate simulated schedule
    val_report = validate_timetable(all_entries, sections, subjects, classrooms)
    if not val_report["is_valid"]:
        conn.close()
        err_msg = val_report["conflicts"][0]["message"] if val_report["conflicts"] else "Adjustment violates scheduling constraints."
        return {
            "success": False,
            "error": f"Cannot move class: {err_msg}",
            "conflicts": val_report["conflicts"]
        }

    # If valid, commit modification
    with conn:
        cursor.execute("""
            UPDATE timetable_entries 
            SET day = ?, slot = ?, room_id = ?, is_manually_adjusted = 1
            WHERE id = ?;
        """, (new_day, new_slot, new_room_id.strip(), entry_id))

        # Update generation validation report
        cursor.execute("""
            UPDATE timetable_generations 
            SET conflict_count = ?, validation_report = ?
            WHERE id = ?;
        """, (val_report["conflict_count"], json.dumps(val_report), entry_dict["generation_id"]))

    conn.close()
    return {
        "success": True,
        "message": f"Successfully moved to {new_day} Slot {new_slot} (Room {new_room_id}). Schedule re-validated with 0 conflicts.",
        "entry_id": entry_id,
        "validation": val_report
    }


def publish_timetable(generation_id: int, published_by: str = "Administrator") -> dict:
    """
    Publish an approved draft timetable:
    1. Preserves and archives the previously published timetable.
    2. Sets current generation and version as 'published'.
    3. Synchronizes published classes into 'classroom_schedules' so that
       student portals, faculty portals, and classroom availability checkers update immediately!
    """
    conn = campus_db.get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM timetable_generations WHERE id = ?;", (generation_id,))
    gen = cursor.fetchone()
    if not gen:
        conn.close()
        return {"success": False, "error": f"Generation {generation_id} not found."}

    # Fetch latest version
    cursor.execute("""
        SELECT * FROM timetable_versions 
        WHERE generation_id = ? ORDER BY version_number DESC LIMIT 1;
    """, (generation_id,))
    ver = cursor.fetchone()
    if not ver:
        conn.close()
        return {"success": False, "error": "No version found for this generation."}

    ver_id = ver["id"]

    # Fetch all entries for this version
    cursor.execute("""
        SELECT te.*, s.code as subject_code, s.name as subject_name, sec.name as section_letter,
               ay.code as academic_year_code
        FROM timetable_entries te
        JOIN subjects s ON te.subject_id = s.id
        JOIN sections sec ON te.section_id = sec.id
        JOIN timetable_generations tg ON te.generation_id = tg.id
        LEFT JOIN academic_years ay ON tg.academic_year_id = ay.id
        WHERE te.version_id = ?;
    """, (ver_id,))
    entries = [dict(r) for r in cursor.fetchall()]

    now_iso = datetime.now().isoformat()

    with conn:
        # 1. Archive previous published generation
        cursor.execute("""
            UPDATE timetable_generations 
            SET status = 'archived' 
            WHERE status = 'published' AND id != ?;
        """, (generation_id,))
        cursor.execute("UPDATE timetable_versions SET is_published = 0 WHERE generation_id != ?;", (generation_id,))

        # 2. Mark this generation as published
        cursor.execute("""
            UPDATE timetable_generations 
            SET status = 'published', published_at = CURRENT_TIMESTAMP, published_by = ?
            WHERE id = ?;
        """, (published_by, generation_id))

        cursor.execute("""
            UPDATE timetable_versions 
            SET is_published = 1 
            WHERE id = ?;
        """, (ver_id,))

        # 3. Synchronize with legacy / shared classroom_schedules table
        # Delete existing entries for the affected sections
        sec_letters = list(set(e["section_letter"] for e in entries))
        for sec in sec_letters:
            cursor.execute("DELETE FROM classroom_schedules WHERE section = ?;", (sec,))

        # Ensure all referenced rooms exist in classrooms table to prevent FK errors
        for e in entries:
            r_id = e["room_id"]
            cursor.execute("SELECT id FROM classrooms WHERE id = ?;", (r_id,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT OR IGNORE INTO classrooms (id, name, block, floor, bench_count, seating_capacity, room_type, status)
                    VALUES (?, ?, 'Main Block', 1, 35, 70, 'Computer Lab', 'available');
                """, (r_id, f"Laboratory Facility {r_id}"))

        sync_rows = []
        for e in entries:
            sync_rows.append((
                e["room_id"], e["day"], e["slot"], e["subject_code"], e["subject_name"],
                e["section_letter"], e["faculty_name"], e.get("academic_year_code") or "2026-2027"
            ))

        cursor.executemany("""
            INSERT OR REPLACE INTO classroom_schedules 
            (classroom_id, day, slot, subject_code, subject_name, section, faculty_name, academic_year)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, sync_rows)

    conn.close()

    logger.info("Published Timetable Generation #%d (Version #%d) with %d synchronized sessions.",
                generation_id, ver["version_number"], len(entries))

    return {
        "success": True,
        "message": f"Timetable published successfully! Synchronized {len(entries)} academic sessions to student and faculty portals.",
        "generation_id": generation_id,
        "version_id": ver_id,
        "synced_to_campus": len(entries),
        "published_at": now_iso
    }


def get_maintenance_impact(room_id: str) -> dict:
    """
    Analyze the ripple impact of a room undergoing maintenance.
    Identifies affected published sessions and suggests free replacement classrooms.
    """
    conn = campus_db.get_db()
    cursor = conn.cursor()

    # Find active published version
    cursor.execute("SELECT id FROM timetable_versions WHERE is_published = 1 LIMIT 1;")
    pub_ver = cursor.fetchone()
    if not pub_ver:
        # Fallback to latest version
        cursor.execute("SELECT id FROM timetable_versions ORDER BY id DESC LIMIT 1;")
        pub_ver = cursor.fetchone()

    if not pub_ver:
        conn.close()
        return {"room_id": room_id, "affected_classes": [], "suggestions": []}

    ver_id = pub_ver["id"]

    cursor.execute("""
        SELECT te.*, s.code as subject_code, s.name as subject_name, sec.display_name as section_name, sec.student_count
        FROM timetable_entries te
        JOIN subjects s ON te.subject_id = s.id
        JOIN sections sec ON te.section_id = sec.id
        WHERE te.version_id = ? AND LOWER(te.room_id) = LOWER(?)
        ORDER BY te.day, te.slot ASC;
    """, (ver_id, room_id.strip()))
    affected = [dict(r) for r in cursor.fetchall()]

    # For each affected class, find vacant classrooms with sufficient capacity
    results = []
    for cls in affected:
        day = cls["day"]
        slot = cls["slot"]
        min_cap = cls.get("student_count", 60)

        # Query classrooms not occupied at (day, slot) in this published version
        cursor.execute("""
            SELECT id, name, seating_capacity, block, floor, room_type
            FROM classrooms
            WHERE seating_capacity >= ?
              AND LOWER(id) != LOWER(?)
              AND id NOT IN (
                  SELECT room_id FROM timetable_entries WHERE version_id = ? AND day = ? AND slot = ?
              )
            ORDER BY seating_capacity ASC
            LIMIT 3;
        """, (min_cap, room_id.strip(), ver_id, day, slot))
        vacant_rooms = [dict(r) for r in cursor.fetchall()]

        results.append({
            "entry_id": cls["id"],
            "subject": f"{cls['subject_code']} - {cls['subject_name']}",
            "section": cls["section_name"],
            "faculty": cls["faculty_name"],
            "day": day,
            "slot": slot,
            "time_range": STANDARD_SLOTS.get(slot, {}).get("time", f"Slot {slot}"),
            "vacant_substitutes": vacant_rooms
        })

    conn.close()
    return {
        "room_id": room_id,
        "affected_count": len(results),
        "impact_schedule": results
    }


def export_timetable_excel(version_id: int, output_path: str = None) -> str:
    """Generate styled multi-sheet Excel workbook with Section-wise and Faculty-wise sheets."""
    conn = campus_db.get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, display_name FROM sections ORDER BY name ASC;")
    sections = [dict(r) for r in cursor.fetchall()]

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # Remove default sheet

    header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    lunch_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    lab_fill = PatternFill(start_color="E0F2FE", end_color="E0F2FE", fill_type="solid")
    cell_border = Border(left=Side(style='thin', color='CBD5E1'),
                         right=Side(style='thin', color='CBD5E1'),
                         top=Side(style='thin', color='CBD5E1'),
                         bottom=Side(style='thin', color='CBD5E1'))
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # 1. Create a sheet for each Section
    for sec in sections:
        ws = wb.create_sheet(title=f"Sec {sec['name']}")
        ws.column_dimensions['A'].width = 12
        for col_letter in ['B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']:
            ws.column_dimensions[col_letter].width = 18

        # Title
        ws.merge_cells("A1:J1")
        ws["A1"] = f"Academic Timetable — {sec['display_name']}"
        ws["A1"].font = Font(name="Arial", size=14, bold=True, color="0284C7")
        ws["A1"].alignment = Alignment(horizontal="center", vertical="center")

        # Headers
        headers = ["Day", "Slot 1\n09:00-09:50", "Slot 2\n09:50-10:40", "Slot 3\n10:50-11:40",
                   "Slot 4\n11:40-12:30", "Lunch\n12:30-01:20", "Slot 6\n01:20-02:10",
                   "Slot 7\n02:10-03:00", "Slot 8\n03:00-03:50", "Slot 9\n03:50-04:40"]
        for col_idx, h_text in enumerate(headers, 1):
            cell = ws.cell(row=3, column=col_idx, value=h_text)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center_align

        # Fetch matrix data
        matrix = get_timetable_matrix(version_id, view_type="section", target_id=str(sec["id"]))

        for row_idx, day_name in enumerate(STANDARD_WORKING_DAYS, 4):
            day_cell = ws.cell(row=row_idx, column=1, value=day_name)
            day_cell.font = Font(name="Arial", bold=True)
            day_cell.border = cell_border
            day_cell.alignment = center_align

            for slot_num in range(1, 10):
                col_idx = slot_num + 1
                cell_val = matrix["grid"][day_name].get(slot_num)
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.border = cell_border
                cell.alignment = center_align

                if slot_num == 5:
                    cell.value = "LUNCH"
                    cell.fill = lunch_fill
                    cell.font = Font(name="Arial", size=9, color="64748B", italic=True)
                elif cell_val:
                    cell.value = f"{cell_val['subject_code']}\n({cell_val['room_id']})\n{cell_val['faculty_name']}"
                    cell.font = Font(name="Arial", size=9, bold=True)
                    if cell_val.get("is_lab"):
                        cell.fill = lab_fill
                else:
                    cell.value = "—"
                    cell.font = Font(name="Arial", size=10, color="94A3B8")

    conn.close()

    if not output_path:
        out_dir = os.path.join(os.path.dirname(__file__), "..", "outputs")
        os.makedirs(out_dir, exist_ok=True)
        output_path = os.path.join(out_dir, f"academic_timetable_v{version_id}.xlsx")

    wb.save(output_path)
    return output_path
