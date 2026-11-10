"""
timetable/routes.py — Flask Blueprint for the Automatic Timetable Generation Engine.
Endpoints for generation, interactive grid inspection, manual adjustments, publishing,
maintenance ripple impact analysis, and multi-sheet Excel export.
"""

import os
from flask import Blueprint, render_template, request, jsonify, send_file, redirect, url_for
from auth.service import login_required, role_required, get_current_user
from . import service

timetable_bp = Blueprint("timetable_bp", __name__)


@timetable_bp.route("/admin/timetable")
@login_required
@role_required("admin")
def admin_timetable_view():
    """Main administrative dashboard for Automatic Timetable Generator."""
    user = get_current_user()
    meta = service.list_academic_metadata()
    generations = service.list_generations()
    
    # Active generation to display: either query param or latest published/draft
    active_gen_id = request.args.get("gen_id", type=int)
    if not active_gen_id and generations:
        active_gen_id = generations[0]["id"]

    active_gen = service.get_generation_details(active_gen_id) if active_gen_id else None
    active_ver_id = active_gen["versions"][0]["id"] if (active_gen and active_gen.get("versions")) else None

    # Default matrix to display
    sec_id = meta["sections"][0]["id"] if meta["sections"] else 1
    matrix = service.get_timetable_matrix(active_ver_id, view_type="section", target_id=str(sec_id)) if active_ver_id else None

    return render_template(
        "admin/timetable_generator.html",
        user=user,
        meta=meta,
        generations=generations,
        active_gen=active_gen,
        active_ver_id=active_ver_id,
        current_matrix=matrix,
        default_section_id=sec_id
    )


@timetable_bp.route("/api/timetable/generate", methods=["POST"])
@login_required
@role_required("admin")
def api_generate_timetable():
    """Execute CSP timetable generation for requested sections."""
    user = get_current_user()
    data = request.get_json(silent=True) or request.form.to_dict()

    section_ids = data.get("section_ids")
    if not section_ids:
        # Default to all sections in CSE
        section_ids = [s["id"] for s in service.list_academic_metadata()["sections"]]
    elif isinstance(section_ids, str):
        section_ids = [int(s.strip()) for s in section_ids.split(",") if s.strip()]
    elif isinstance(section_ids, list):
        section_ids = [int(s) for s in section_ids]

    scope = data.get("scope", "semester")
    ay_id = int(data.get("academic_year_id", 1))
    sem_id = int(data.get("semester_id", 1))
    dept_id = str(data.get("department_id", "CSE"))
    if dept_id.isdigit():
        dept_id = "CSE"

    result = service.execute_timetable_generation(
        section_ids=section_ids,
        scope=scope,
        academic_year_id=ay_id,
        semester_id=sem_id,
        department_id=dept_id,
        user_name=user.get("name", "Administrator")
    )

    if not result["success"]:
        return jsonify({
            "success": False,
            "error": result.get("message", "Generation failed."),
            "diagnostic": result.get("message")
        }), 400

    return jsonify({
        "success": True,
        "message": result["message"],
        "generation_id": result["generation_id"],
        "version_id": result["version_id"],
        "total_classes": result["total_classes"],
        "validation": result["validation"]
    })


@timetable_bp.route("/api/timetable/matrix", methods=["GET"])
@login_required
def api_get_timetable_matrix():
    """Retrieve grid matrix for section, faculty, or classroom."""
    ver_id = request.args.get("version_id", type=int)
    if not ver_id:
        # Get active published version
        conn = service.campus_db.get_db()
        r = conn.execute("SELECT id FROM timetable_versions WHERE is_published = 1 LIMIT 1;").fetchone()
        if not r:
            r = conn.execute("SELECT id FROM timetable_versions ORDER BY id DESC LIMIT 1;").fetchone()
        conn.close()
        ver_id = r[0] if r else None

    if not ver_id:
        return jsonify({"success": False, "error": "No timetable versions available."}), 404

    view_type = request.args.get("view_type", "section")
    target_id = request.args.get("target_id")

    matrix = service.get_timetable_matrix(ver_id, view_type=view_type, target_id=target_id)
    return jsonify({"success": True, "matrix": matrix})


@timetable_bp.route("/api/timetable/adjust", methods=["POST"])
@login_required
@role_required("admin")
def api_adjust_entry():
    """Manually move an entry to a new day/slot/room with on-the-fly conflict revalidation."""
    data = request.get_json(silent=True) or request.form
    entry_id = int(data.get("entry_id"))
    new_day = data.get("day")
    new_slot = int(data.get("slot"))
    new_room = data.get("room_id")

    res = service.adjust_timetable_entry(entry_id, new_day, new_slot, new_room)
    if not res["success"]:
        return jsonify(res), 400
    return jsonify(res)


@timetable_bp.route("/api/timetable/publish", methods=["POST"])
@login_required
@role_required("admin")
def api_publish_timetable():
    """Publish draft timetable and synchronize classroom_schedules across campus portals."""
    user = get_current_user()
    data = request.get_json(silent=True) or request.form
    gen_id = int(data.get("generation_id"))

    res = service.publish_timetable(gen_id, published_by=user.get("name", "Administrator"))
    if not res["success"]:
        return jsonify(res), 400
    return jsonify(res)


@timetable_bp.route("/api/timetable/maintenance-impact", methods=["GET"])
@login_required
def api_maintenance_impact():
    """Identify published sessions impacted by room maintenance and suggest substitute venues."""
    room_id = request.args.get("room_id", "G16")
    impact = service.get_maintenance_impact(room_id)
    return jsonify({"success": True, "impact": impact})


@timetable_bp.route("/download/timetable-excel/<int:version_id>")
@login_required
def download_timetable_excel(version_id: int):
    """Download multi-sheet styled Excel workbook."""
    file_path = service.export_timetable_excel(version_id)
    return send_file(file_path, as_attachment=True, download_name=f"academic_timetable_v{version_id}.xlsx")


@timetable_bp.route("/download/timetable-pdf/<int:version_id>")
@login_required
def download_timetable_pdf(version_id: int):
    """Download vector PDF of academic timetable (individual section or all sections)."""
    sec_id = request.args.get("section_id", type=int)
    all_sections = bool(request.args.get("all") == "1" or not sec_id)
    file_path = service.generate_timetable_pdf(version_id, section_id=sec_id, all_sections=all_sections)
    fname = f"academic_timetable_v{version_id}_{'all_sections' if all_sections else f'sec{sec_id}'}.pdf"
    return send_file(file_path, as_attachment=True, download_name=fname, mimetype="application/pdf")


@timetable_bp.route("/api/timetable/wizard-init", methods=["GET"])
@login_required
@role_required("admin")
def api_wizard_init():
    """Retrieve setup metadata (departments, semesters, classrooms, labs, faculty) for Dynamic Wizard."""
    data = service.get_wizard_init_data()
    return jsonify({"success": True, "data": data})


@timetable_bp.route("/api/timetable/catalog/preset", methods=["POST"])
@login_required
@role_required("admin")
def api_catalog_preset():
    """Load pre-configured IFHE B.Tech course catalog for chosen department and semester."""
    req_data = request.get_json(silent=True) or request.form
    year = int(req_data.get("year", 2))
    semester = int(req_data.get("semester", 3))
    dept = str(req_data.get("department", "CSE")).strip().upper()

    courses = service.load_preset_catalog(year=year, semester=semester, department=dept)
    return jsonify({
        "success": True,
        "department": dept,
        "semester": semester,
        "year": year,
        "courses": courses,
        "total": len(courses)
    })


@timetable_bp.route("/api/timetable/catalog/upload", methods=["POST"])
@login_required
@role_required("admin")
def api_catalog_upload():
    """Upload and parse Excel/CSV/JSON course catalog with intelligent column detection."""
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded."}), 400

    file_obj = request.files["file"]
    if not file_obj.filename:
        return jsonify({"success": False, "error": "No selected file."}), 400

    try:
        res = service.parse_course_catalog_file(file_obj)
        return jsonify({
            "success": True,
            "filename": file_obj.filename,
            "headers": res["headers"],
            "suggested_mapping": res["suggested_mapping"],
            "raw_rows": res["raw_rows"],
            "parsed_subjects": res["parsed_subjects"],
            "total_extracted": res["total_extracted"]
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@timetable_bp.route("/api/timetable/catalog/remap", methods=["POST"])
@login_required
@role_required("admin")
def api_catalog_remap():
    """Apply updated column mapping to raw rows."""
    req_data = request.get_json(silent=True) or {}
    raw_rows = req_data.get("raw_rows", [])
    mapping = req_data.get("mapping", {})

    parsed = service.convert_rows_to_subjects(raw_rows, mapping)
    return jsonify({
        "success": True,
        "parsed_subjects": parsed,
        "total": len(parsed)
    })


@timetable_bp.route("/api/timetable/generate-dynamic", methods=["POST"])
@login_required
@role_required("admin")
def api_generate_dynamic():
    """Execute dynamic multi-section timetable generation from the 5-step wizard."""
    user = get_current_user()
    payload = request.get_json(silent=True) or request.form.to_dict()

    res = service.execute_dynamic_wizard_generation(payload, user_name=user.get("name", "Administrator"))
    if not res.get("success"):
        return jsonify({
            "success": False,
            "error": res.get("message", "Timetable generation failed."),
            "diagnostic": res.get("message"),
            "validation": res.get("validation")
        }), 400

    return jsonify({
        "success": True,
        "message": res["message"],
        "generation_id": res["generation_id"],
        "version_id": res["version_id"],
        "total_classes": res["total_classes"],
        "sections_created": res.get("sections_created", 1),
        "validation": res["validation"]
    })
