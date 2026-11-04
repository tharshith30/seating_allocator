"""
campus/routes.py — Flask Blueprint exposing REST APIs and Views for Campus Space & Facility Management.
"""

import os
import logging
from flask import Blueprint, request, jsonify, send_file, render_template
from . import db
from . import classroom_service
from . import auditorium_service
from . import facility_service
from . import scheduling_service
from . import reports

logger = logging.getLogger(__name__)

campus_bp = Blueprint("campus_bp", __name__)
_DATA_DIR = os.environ.get("DATA_DIR")
OUTPUT_DIR = os.path.join(_DATA_DIR, "outputs") if _DATA_DIR else os.path.join(os.path.dirname(__file__), "..", "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@campus_bp.route("/campus")
@campus_bp.route("/classrooms")
@campus_bp.route("/auditoriums")
@campus_bp.route("/facilities")
def campus_index():
    """Render Campus Space & Facility Management dashboard."""
    active_sub = "classrooms"
    if "auditorium" in request.path:
        active_sub = "auditoriums"
    elif "facilit" in request.path:
        active_sub = "facilities"

    classrooms = classroom_service.list_classrooms()
    auditoriums = auditorium_service.list_auditoriums()
    cr_analytics = classroom_service.get_classroom_utilization_analytics()
    aud_analytics = auditorium_service.get_auditorium_analytics()
    fac_analytics = facility_service.get_facility_analytics()

    return render_template(
        "campus/dashboard.html",
        active_sub=active_sub,
        classrooms=classrooms,
        auditoriums=auditoriums,
        cr_analytics=cr_analytics,
        aud_analytics=aud_analytics,
        fac_analytics=fac_analytics
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLASSROOM REST APIS
# ─────────────────────────────────────────────────────────────────────────────

@campus_bp.route("/api/campus/classrooms", methods=["GET"])
def api_list_classrooms():
    block = request.args.get("block")
    floor = request.args.get("floor", type=int)
    room_type = request.args.get("room_type")
    min_cap = request.args.get("min_capacity", type=int)
    search = request.args.get("search")
    rooms = classroom_service.list_classrooms(block, floor, room_type, min_cap, search)
    return jsonify({"status": "success", "count": len(rooms), "classrooms": rooms})


@campus_bp.route("/api/campus/classrooms", methods=["POST"])
def api_add_classroom():
    data = request.get_json() or {}
    pin = data.get("pin")
    if not db.verify_role_pin("admin", pin) and not db.verify_role_pin("staff", pin):
        return jsonify({"error": "Admin or Staff PIN required to add or edit classrooms."}), 403
    try:
        room = classroom_service.add_or_update_classroom(data)
        return jsonify({
            "status": "success",
            "classroom": room,
            "message": f"Classroom {room['id']} registered successfully!"
        }), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error("Error adding classroom: %s", e)
        return jsonify({"error": f"Failed to register classroom: {str(e)}"}), 500


@campus_bp.route("/api/campus/classrooms/<classroom_id>", methods=["GET"])
def api_get_classroom(classroom_id):
    room = classroom_service.get_classroom(classroom_id)
    if not room:
        return jsonify({"error": "Classroom not found"}), 404
    return jsonify({"status": "success", "classroom": room})


@campus_bp.route("/api/campus/classrooms/<classroom_id>/schedule", methods=["GET"])
def api_get_classroom_schedule(classroom_id):
    sched = classroom_service.get_classroom_weekly_schedule(classroom_id)
    return jsonify({"status": "success", "schedule": sched})


@campus_bp.route("/api/campus/classrooms/<classroom_id>/timeline", methods=["GET"])
def api_get_classroom_timeline(classroom_id):
    target_date = request.args.get("date") or str(classroom_service.date.today())
    timeline = scheduling_service.get_classroom_daily_timeline(classroom_id, target_date)
    return jsonify({"status": "success", "classroom_id": classroom_id, "date": target_date, "timeline": timeline})


@campus_bp.route("/api/campus/classrooms/find-available", methods=["POST"])
def api_find_available_classrooms():
    data = request.get_json() or {}
    target_date = data.get("date") or str(classroom_service.date.today())
    slot_start = int(data.get("slot_start", 1))
    slot_end = int(data.get("slot_end", slot_start))
    min_cap = data.get("min_capacity", type=int) if "min_capacity" in data else None
    room_type = data.get("room_type")
    rooms = classroom_service.find_available_classrooms(target_date, slot_start, slot_end, min_cap, room_type)
    return jsonify({"status": "success", "date": target_date, "count": len(rooms), "available_classrooms": rooms})


@campus_bp.route("/api/campus/classrooms/book", methods=["POST"])
def api_book_classroom():
    data = request.get_json() or {}
    try:
        res = classroom_service.book_classroom(data)
        return jsonify(res), 201
    except (ValueError, PermissionError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error("Booking error: %s", e)
        return jsonify({"error": f"Failed to reserve classroom: {str(e)}"}), 500


@campus_bp.route("/api/campus/classrooms/bookings", methods=["GET"])
def api_list_classroom_bookings():
    room_id = request.args.get("classroom_id")
    b_date = request.args.get("booking_date")
    dept = request.args.get("department")
    bookings = classroom_service.list_classroom_bookings(room_id, b_date, dept)
    return jsonify({"status": "success", "count": len(bookings), "bookings": bookings})


@campus_bp.route("/api/campus/classrooms/bookings/<int:booking_id>", methods=["DELETE"])
def api_cancel_classroom_booking(booking_id):
    pin = request.args.get("pin") or (request.get_json() or {}).get("pin")
    try:
        res = classroom_service.cancel_classroom_booking(booking_id, pin)
        return jsonify(res)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@campus_bp.route("/api/campus/classrooms/import-timetable", methods=["POST"])
def api_import_timetable():
    pin = request.form.get("pin") or (request.get_json() or {}).get("pin")
    if not db.verify_role_pin("admin", pin):
        return jsonify({"error": "Admin PIN required to import timetables."}), 403

    # Check if a custom file was uploaded
    uploaded_file = request.files.get("timetable_file")
    temp_path = None
    if uploaded_file:
        temp_path = os.path.join(OUTPUT_DIR, f"temp_tt_{uploaded_file.filename}")
        uploaded_file.save(temp_path)

    try:
        res = classroom_service.import_timetable_from_excel(temp_path)
        return jsonify(res)
    except Exception as e:
        logger.error("Timetable import error: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


@campus_bp.route("/api/campus/classrooms/analytics", methods=["GET"])
def api_classroom_analytics():
    data = classroom_service.get_classroom_utilization_analytics()
    return jsonify({"status": "success", "analytics": data})


# ─────────────────────────────────────────────────────────────────────────────
# AUDITORIUM REST APIS
# ─────────────────────────────────────────────────────────────────────────────

@campus_bp.route("/api/campus/auditoriums", methods=["GET"])
def api_list_auditoriums():
    auds = auditorium_service.list_auditoriums()
    return jsonify({"status": "success", "count": len(auds), "auditoriums": auds})


@campus_bp.route("/api/campus/auditoriums", methods=["POST"])
def api_add_auditorium():
    data = request.get_json() or {}
    pin = data.get("pin")
    if not db.verify_role_pin("admin", pin):
        return jsonify({"error": "Admin PIN required to add or edit auditoriums."}), 403
    try:
        aud = auditorium_service.add_or_update_auditorium(data)
        return jsonify({"status": "success", "auditorium": aud}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@campus_bp.route("/api/campus/auditoriums/<aud_id>", methods=["GET"])
def api_get_auditorium(aud_id):
    aud = auditorium_service.get_auditorium(aud_id)
    if not aud:
        return jsonify({"error": "Auditorium not found"}), 404
    return jsonify({"status": "success", "auditorium": aud})


@campus_bp.route("/api/campus/auditoriums/request", methods=["POST"])
def api_request_auditorium_event():
    data = request.get_json() or {}
    try:
        res = auditorium_service.request_event(data)
        return jsonify(res), 201
    except (ValueError, PermissionError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error("Event request error: %s", e)
        return jsonify({"error": f"Failed to submit event request: {str(e)}"}), 500


@campus_bp.route("/api/campus/auditoriums/events/<int:event_id>/review", methods=["POST"])
def api_review_event_request(event_id):
    data = request.get_json() or {}
    action = data.get("action", "approve")
    reviewed_by = data.get("reviewed_by", "Campus Administrator")
    remarks = data.get("remarks", "")
    pin = data.get("pin")
    try:
        res = auditorium_service.review_event_request(event_id, action, reviewed_by, remarks, pin)
        return jsonify(res)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@campus_bp.route("/api/campus/auditoriums/events", methods=["GET"])
def api_list_auditorium_events():
    aud_id = request.args.get("auditorium_id")
    st = request.args.get("status")
    from_date = request.args.get("from_date")
    events = auditorium_service.list_events(aud_id, st, from_date)
    return jsonify({"status": "success", "count": len(events), "events": events})


@campus_bp.route("/api/campus/auditoriums/events/<int:event_id>", methods=["GET"])
def api_get_event_details(event_id):
    ev = auditorium_service.get_event_details(event_id)
    if not ev:
        return jsonify({"error": "Event not found"}), 404
    return jsonify({"status": "success", "event": ev})


@campus_bp.route("/api/campus/auditoriums/events/<int:event_id>/checklist", methods=["POST"])
def api_toggle_checklist(event_id):
    data = request.get_json() or {}
    item_key = data.get("item_key")
    is_comp = bool(data.get("is_completed", False))
    verified_by = data.get("verified_by", "Staff Member")
    pin = data.get("pin")
    try:
        res = auditorium_service.toggle_checklist_item(event_id, item_key, is_comp, verified_by, pin)
        return jsonify(res)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@campus_bp.route("/api/campus/auditoriums/calendar", methods=["GET"])
def api_auditorium_calendar():
    month = request.args.get("month", type=int)
    year = request.args.get("year", type=int)
    events = auditorium_service.get_auditorium_calendar_events(month, year)
    return jsonify({"status": "success", "events": events})


@campus_bp.route("/api/campus/auditoriums/analytics", methods=["GET"])
def api_auditorium_analytics():
    data = auditorium_service.get_auditorium_analytics()
    return jsonify({"status": "success", "analytics": data})


# ─────────────────────────────────────────────────────────────────────────────
# FACILITY REST APIS
# ─────────────────────────────────────────────────────────────────────────────

@campus_bp.route("/api/campus/facilities/assets", methods=["GET"])
def api_list_assets():
    cat = request.args.get("category")
    loc_type = request.args.get("location_type")
    loc_id = request.args.get("location_id")
    cond = request.args.get("condition")
    assets = facility_service.list_assets(cat, loc_type, loc_id, cond)
    return jsonify({"status": "success", "count": len(assets), "assets": assets})


@campus_bp.route("/api/campus/facilities/assets", methods=["POST"])
def api_add_asset():
    data = request.get_json() or {}
    pin = data.get("pin")
    if not db.verify_role_pin("admin", pin) and not db.verify_role_pin("maintenance", pin):
        return jsonify({"error": "Admin or Maintenance PIN required to manage assets."}), 403
    try:
        ast = facility_service.add_or_update_asset(data)
        return jsonify({"status": "success", "asset": ast}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@campus_bp.route("/api/campus/facilities/tickets", methods=["GET"])
def api_list_tickets():
    st = request.args.get("status")
    prio = request.args.get("priority")
    loc_id = request.args.get("location_id")
    tickets = facility_service.list_maintenance_requests(st, prio, loc_id)
    return jsonify({"status": "success", "count": len(tickets), "tickets": tickets})


@campus_bp.route("/api/campus/facilities/tickets", methods=["POST"])
def api_submit_ticket():
    data = request.get_json() or {}
    try:
        res = facility_service.submit_maintenance_request(data)
        return jsonify(res), 201
    except (ValueError, PermissionError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error("Ticket submission error: %s", e)
        return jsonify({"error": f"Failed to log maintenance ticket: {str(e)}"}), 500


@campus_bp.route("/api/campus/facilities/tickets/<ticket_no>", methods=["GET"])
def api_get_ticket_details(ticket_no):
    tk = facility_service.get_maintenance_ticket_details(ticket_no)
    if not tk:
        return jsonify({"error": "Ticket not found"}), 404
    return jsonify({"status": "success", "ticket": tk})


@campus_bp.route("/api/campus/facilities/tickets/<ticket_no>/assign", methods=["POST"])
def api_assign_ticket(ticket_no):
    data = request.get_json() or {}
    assigned_to = data.get("assigned_to", "").strip()
    est = data.get("estimated_completion", "").strip()
    admin_name = data.get("admin_name", "Administrator")
    pin = data.get("pin")
    try:
        res = facility_service.assign_maintenance_staff(ticket_no, assigned_to, est, admin_name, pin)
        return jsonify(res)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@campus_bp.route("/api/campus/facilities/tickets/<ticket_no>/status", methods=["POST"])
def api_update_ticket_status(ticket_no):
    data = request.get_json() or {}
    new_st = data.get("status")
    notes = data.get("notes", "")
    updated_by = data.get("updated_by", "Staff")
    role = data.get("role", "Maintenance Staff")
    pin = data.get("pin")
    try:
        res = facility_service.update_maintenance_status(ticket_no, new_st, notes, updated_by, role, pin)
        return jsonify(res)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@campus_bp.route("/api/campus/facilities/preventive", methods=["GET"])
def api_list_preventive():
    pm_list = facility_service.list_preventive_maintenance()
    return jsonify({"status": "success", "count": len(pm_list), "preventive_tasks": pm_list})


@campus_bp.route("/api/campus/facilities/preventive/<int:pm_id>/complete", methods=["POST"])
def api_complete_preventive(pm_id):
    data = request.get_json() or {}
    conducted_by = data.get("conducted_by", "Technician")
    notes = data.get("notes", "")
    pin = data.get("pin")
    try:
        res = facility_service.complete_preventive_maintenance(pm_id, conducted_by, notes, pin)
        return jsonify(res)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@campus_bp.route("/api/campus/facilities/analytics", methods=["GET"])
def api_facility_analytics():
    data = facility_service.get_facility_analytics()
    return jsonify({"status": "success", "analytics": data})


# ─────────────────────────────────────────────────────────────────────────────
# REPORT DOWNLOADS
# ─────────────────────────────────────────────────────────────────────────────

@campus_bp.route("/download/campus-report/excel", methods=["GET"])
def download_campus_excel():
    output_file = os.path.join(OUTPUT_DIR, "campus_facility_report.xlsx")
    try:
        reports.generate_campus_excel_report(output_file)
        return send_file(
            output_file,
            as_attachment=True,
            download_name="Campus_Space_Facility_Report.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        logger.error("Error generating campus Excel report: %s", e)
        return jsonify({"error": f"Failed to generate Excel report: {str(e)}"}), 500


@campus_bp.route("/download/campus-report/pdf", methods=["GET"])
def download_campus_pdf():
    output_file = os.path.join(OUTPUT_DIR, "campus_facility_summary.pdf")
    try:
        reports.generate_campus_pdf_report(output_file)
        return send_file(
            output_file,
            as_attachment=True,
            download_name="Campus_Space_Facility_Summary.pdf",
            mimetype="application/pdf"
        )
    except Exception as e:
        logger.error("Error generating campus PDF report: %s", e)
        return jsonify({"error": f"Failed to generate PDF report: {str(e)}"}), 500

