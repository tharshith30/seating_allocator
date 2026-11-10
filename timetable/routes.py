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
