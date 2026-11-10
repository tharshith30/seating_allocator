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

logger = logging.getLogger(__name__)


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
    Format timetable entries into a weekly matrix (Mon-Fri x Slots 1-9) for a section, faculty, or room.
    """
    conn = campus_db.get_db()
    cursor = conn.cursor()

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
    elif view_type == "classroom" and target_id:
        query += " AND LOWER(te.room_id) = LOWER(?)"
        params.append(target_id.strip())

    query += " ORDER BY te.day, te.slot ASC;"
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
    for r in rows:
        item = dict(r)
        d = item["day"]
        s = item["slot"]
        if d in grid and s in grid[d]:
            grid[d][s] = item
        entries_list.append(item)

    return {
        "view_type": view_type,
        "target_id": target_id,
        "days": days,
        "slots": slots,
        "grid": grid,
        "entries": entries_list,
        "slot_times": STANDARD_SLOTS
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
