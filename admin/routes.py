"""
admin/routes.py — Flask Blueprint for Full Administration Portal.
Unifies all 6 campus resource management modules + User & Security Management.
"""

from datetime import datetime, date
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash
from auth.service import login_required, role_required, get_current_user
from campus import db as campus_db
from campus import classroom_service
from campus import auditorium_service
from campus import facility_service
from library import occupancy as lib_occupancy
from lab import routes as lab_routes
from lab import booking as lab_booking

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin")
@login_required
@role_required("admin")
def admin_dashboard():
    user = get_current_user()
    active_tab = request.args.get("tab", "overview")

    # 1. Seating Data
    rooms_file_exists = bool(classroom_service.list_classrooms())

    # 2. Lab Data
    labs = lab_routes._get_labs_cfg()
    lab_analytics = lab_routes._get_analytics()
    current_week = lab_routes._current_monday()

    # 3. Library Data
    lib_status = lib_occupancy.get_latest_observation()
    lib_config = lib_occupancy.get_config()

    # 4. Campus Modules Data
    classrooms = classroom_service.list_classrooms()
    auditoriums = auditorium_service.list_auditoriums()
    cr_analytics = classroom_service.get_classroom_utilization_analytics()
    aud_analytics = auditorium_service.get_auditorium_analytics()
    fac_analytics = facility_service.get_facility_analytics()

    # Events and Maintenance for Admin Triage
    all_events = auditorium_service.list_events()
    all_maintenance = facility_service.list_maintenance_requests()
    pm_schedules = facility_service.list_preventive_maintenance()

    # 5. User Accounts
    conn = campus_db.get_db()
    users_rows = conn.execute("""
        SELECT id, username, name, email, role, department, student_id, section, failed_attempts, locked_until, created_at
        FROM users
        ORDER BY id ASC;
    """).fetchall()
    users = [dict(u) for u in users_rows]

    # Student Seating Allocations count
    seating_count = conn.execute("SELECT COUNT(*) FROM student_exam_seating;").fetchone()[0]
    conn.close()

    return render_template(
        "admin/dashboard.html",
        user=user,
        active_tab=active_tab,
        labs=labs,
        lab_analytics=lab_analytics,
        current_week=current_week,
        lib_status=lib_status,
        lib_config=lib_config,
        classrooms=classrooms,
        auditoriums=auditoriums,
        cr_analytics=cr_analytics,
        aud_analytics=aud_analytics,
        fac_analytics=fac_analytics,
        events=all_events,
        maintenance_tickets=all_maintenance,
        pm_schedules=pm_schedules,
        users=users,
        seating_count=seating_count
    )


@admin_bp.route("/api/admin/users", methods=["GET"])
@login_required
@role_required("admin")
def api_list_users():
    """List all accounts and security statuses."""
    conn = campus_db.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, name, email, role, department, student_id, section, failed_attempts, locked_until FROM users;")
    rows = cursor.fetchall()
    conn.close()
    return jsonify({"success": True, "users": [dict(r) for r in rows]})


@admin_bp.route("/api/admin/unlock-user", methods=["POST"])
@login_required
@role_required("admin")
def api_unlock_user():
    """Clear failed attempts and unlock account."""
    data = request.get_json(silent=True) or request.form
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"success": False, "error": "user_id is required"}), 400

    conn = campus_db.get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?;", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "User account successfully unlocked."})


@admin_bp.route("/api/admin/reset-pin", methods=["POST"])
@login_required
@role_required("admin")
def api_reset_pin():
    """Reset user security PIN."""
    data = request.get_json(silent=True) or request.form
    user_id = data.get("user_id")
    new_pin = str(data.get("new_pin", "")).strip()

    if not user_id or len(new_pin) < 4:
        return jsonify({"success": False, "error": "PIN must be at least 4 digits."}), 400

    new_hash = generate_password_hash(new_pin)
    conn = campus_db.get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET pin_hash = ?, failed_attempts = 0, locked_until = NULL WHERE id = ?;", (new_hash, user_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "User PIN successfully updated."})

