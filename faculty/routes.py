"""
faculty/routes.py — Flask Blueprint for Faculty Dashboard (Authorized Departmental Access).
"""

from datetime import datetime, date
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from auth.service import login_required, role_required, get_current_user
from campus import classroom_service
from campus import auditorium_service
from campus import facility_service
from lab import routes as lab_routes
from lab import booking as lab_booking

faculty_bp = Blueprint("faculty", __name__)


@faculty_bp.route("/faculty")
@login_required
@role_required("faculty")
def faculty_dashboard():
    user = get_current_user()
    dept = user.get("department") or "Computer Science & Engineering"

    # Classroom inventory and free room data
    classrooms = classroom_service.list_classrooms()
    auditoriums = auditorium_service.list_auditoriums()

    # Events submitted or campus approved
    all_events = auditorium_service.list_events()
    # Faculty can view their own requests and all approved events
    dept_events = [e for e in all_events if e.get("department") == dept or e.get("status") == "approved"]

    # Maintenance requests submitted by faculty / department
    all_maintenance = facility_service.list_maintenance_requests()
    dept_maintenance = [m for m in all_maintenance if m.get("reported_by") == user.get("username") or dept.lower() in (m.get("description") or "").lower()]

    # Labs
    labs = lab_routes._get_labs_cfg()

    # Teaching schedule sample for faculty
    teaching_schedule = [
        {"day": "Mon", "slot": 1, "time": "09:00 - 09:50", "subject": "CS203 Object Oriented Programming", "room": "G16", "section": "A"},
        {"day": "Mon", "slot": 4, "time": "11:40 - 12:30", "subject": "CS203 Object Oriented Programming", "room": "G16", "section": "A"},
        {"day": "Tue", "slot": 2, "time": "09:50 - 10:40", "subject": "CS205 Database Systems", "room": "G04", "section": "B"},
        {"day": "Wed", "slot": 3, "time": "10:50 - 11:40", "subject": "CS203 Object Oriented Programming", "room": "G16", "section": "A"},
        {"day": "Thu", "slot": 1, "time": "09:00 - 09:50", "subject": "CS205 Database Systems", "room": "G04", "section": "B"},
        {"day": "Fri", "slot": 6, "time": "01:20 - 02:10", "subject": "CS203 Laboratory Session", "room": "LAB-1", "section": "A"}
    ]

    announcements = [
        {"title": "Submission of Mid-Term Question Papers", "date": "2026-11-04", "content": "All faculty members are requested to submit draft question paper sets for Odd Semester exams to the Exam Cell by 10-Nov-2026."},
        {"title": "Auditorium Reservation Protocol for Technical Symposium", "date": "2026-11-02", "content": "Central Campus Auditorium booking requests must be submitted at least 7 days in advance for stage and AV technical checklist readiness."}
    ]

    return render_template(
        "faculty/dashboard.html",
        user=user,
        classrooms=classrooms,
        auditoriums=auditoriums,
        dept_events=dept_events,
        dept_maintenance=dept_maintenance,
        labs=labs,
        teaching_schedule=teaching_schedule,
        announcements=announcements
    )


@faculty_bp.route("/api/faculty/request-auditorium", methods=["POST"])
@login_required
@role_required("faculty")
def faculty_request_auditorium():
    """Submit auditorium booking request (Requires Admin Approval)."""
    user = get_current_user()
    data = request.get_json(silent=True) or request.form.to_dict()

    payload = {
        "auditorium_id": data.get("auditorium_id", "AUD-MAIN"),
        "event_title": data.get("event_title"),
        "event_type": data.get("event_type", "Academic Seminar"),
        "department": user.get("department", "Computer Science & Engineering"),
        "organizer_name": user.get("name"),
        "contact_email": user.get("email", "faculty@college.edu"),
        "event_date": data.get("event_date"),
        "start_time": data.get("start_time"),
        "end_time": data.get("end_time"),
        "expected_attendees": int(data.get("expected_attendees", 100)),
        "special_requirements": data.get("special_requirements", ""),
        "pin": data.get("pin") or "2345"
    }

    try:
        new_event = auditorium_service.request_event(payload)
        return jsonify({
            "success": True,
            "message": "Auditorium event request submitted successfully for administrative approval.",
            "event": new_event
        })
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except PermissionError as e:
        return jsonify({"success": False, "error": str(e)}), 403
    except Exception as e:
        return jsonify({"success": False, "error": f"Internal server error: {str(e)}"}), 500


@faculty_bp.route("/api/faculty/report-maintenance", methods=["POST"])
@login_required
@role_required("faculty")
def faculty_report_maintenance():
    """Submit facility/equipment maintenance ticket."""
    user = get_current_user()
    data = request.get_json(silent=True) or request.form.to_dict()

    payload = {
        "location_type": data.get("location_type", "classroom"),
        "location_id": data.get("location_id"),
        "category": data.get("category", "IT/AV"),
        "issue_title": data.get("issue_title"),
        "description": data.get("description", ""),
        "priority": data.get("priority", "Medium"),
        "blocks_space": bool(int(data.get("blocks_space", 0))),
        "reported_by": user.get("name") + f" ({user.get('username')})",
        "reported_by_role": "Faculty",
        "pin": data.get("pin") or "2345"
    }

    try:
        ticket = facility_service.submit_maintenance_request(payload)
        return jsonify({
            "success": True,
            "message": f"Maintenance ticket {ticket['ticket_no']} submitted successfully to Campus Maintenance.",
            "ticket": ticket
        })
    except PermissionError as e:
        return jsonify({"success": False, "error": str(e)}), 403
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@faculty_bp.route("/api/faculty/find-free-classrooms", methods=["GET"])
@login_required
@role_required("faculty")
def faculty_find_free_classrooms():
    """Find unoccupied classrooms for a target day and slot."""
    day = request.args.get("day", "Mon")
    slot = int(request.args.get("slot", 1))
    min_capacity = int(request.args.get("min_capacity", 0))

    # Map weekday abbreviation to concrete calendar date for availability checker
    day_to_date = {
        "Mon": "2026-11-09",
        "Tue": "2026-11-10",
        "Wed": "2026-11-11",
        "Thu": "2026-11-12",
        "Fri": "2026-11-13",
        "Sat": "2026-11-14",
        "Sun": "2026-11-15"
    }
    target_date = request.args.get("date") or day_to_date.get(day, "2026-11-09")

    try:
        results = classroom_service.find_available_classrooms(
            target_date=target_date,
            slot_start=slot,
            slot_end=slot,
            min_capacity=min_capacity
        )
        return jsonify({"success": True, "classrooms": results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400
