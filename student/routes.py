"""
student/routes.py — Flask Blueprint for Student Portal (Strict View-Only).
"""

from datetime import datetime, date
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from auth.service import login_required, role_required, get_current_user
from campus import db as campus_db
from campus import auditorium_service
from library import occupancy as lib_occupancy
from lab import routes as lab_routes

student_bp = Blueprint("student", __name__)

SLOT_TIMES = {
    1: "09:00 - 09:50",
    2: "09:50 - 10:40",
    3: "10:50 - 11:40",
    4: "11:40 - 12:30",
    5: "12:30 - 01:20 (Lunch)",
    6: "01:20 - 02:10",
    7: "02:10 - 03:00",
    8: "03:00 - 03:50",
    9: "03:50 - 04:40"
}


def _get_student_timetable(section: str = "A"):
    """Fetch timetable from classroom_schedules organized by day and slot."""
    conn = campus_db.get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT day, slot, subject_code, subject_name, classroom_id, faculty_name 
        FROM classroom_schedules 
        WHERE section = ? OR section IS NULL
        ORDER BY slot ASC;
    """, (section,))
    rows = cursor.fetchall()
    conn.close()

    weekly = {"Mon": [], "Tue": [], "Wed": [], "Thu": [], "Fri": []}
    for r in rows:
        item = dict(r)
        item["time_range"] = SLOT_TIMES.get(item["slot"], f"Slot {item['slot']}")
        d = item["day"]
        if d in weekly:
            weekly[d].append(item)

    # Determine today's day abbreviation
    today_code = datetime.now().strftime("%a")
    if today_code not in weekly:
        today_code = "Mon"  # Default to Monday on weekends

    daily = weekly.get(today_code, [])
    return daily, weekly, today_code


def _get_student_seating(roll_no: str):
    """Retrieve isolated exam seating for the logged-in student ONLY."""
    if not roll_no:
        return []
    conn = campus_db.get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT roll_no, student_name, course_code, course_name, room_id, seat_no, desk_set, exam_date, exam_session, building
        FROM student_exam_seating
        WHERE LOWER(roll_no) = LOWER(?);
    """, (roll_no.strip(),))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


@student_bp.route("/student")
@login_required
@role_required("student")
def student_dashboard():
    user = get_current_user()
    section = user.get("section") or "A"
    roll_no = user.get("student_id") or user.get("username")

    daily_tt, weekly_tt, current_day = _get_student_timetable(section)
    my_seating = _get_student_seating(roll_no)

    # Library verified observation (Zero PII, View Only)
    lib_obs = lib_occupancy.get_latest_observation()
    lib_cfg = lib_occupancy.get_config()

    # Approved campus auditorium events only
    events = auditorium_service.list_events(status="approved")

    # Lab schedules view-only
    labs = lab_routes._get_labs_cfg()

    # Official Announcements
    announcements = [
        {
            "id": 1,
            "title": "Odd Semester End Examinations Schedule Announced",
            "date": "2026-11-04",
            "category": "Examinations",
            "badge": "badge-danger",
            "content": "The End Semester examinations commence on 25-Nov-2026. Students must verify their individual seating allocations on this portal. Cell phones and unauthorized materials are strictly prohibited."
        },
        {
            "id": 2,
            "title": "Central Library Extended Hours During Exam Season",
            "date": "2026-11-03",
            "category": "Library",
            "badge": "badge-info",
            "content": "The Central Library will remain open from 08:00 AM to 10:00 PM on all working days. Check the verified occupancy counter below before visiting to find available study seats."
        },
        {
            "id": 3,
            "title": "National AI & Cloud Computing Symposium 2026",
            "date": "2026-11-02",
            "category": "Events",
            "badge": "badge-primary",
            "content": "Approved by Academic Council. Scheduled at the Central Campus Auditorium on 20-Nov-2026. Student paper presentation slots open until 12-Nov-2026."
        }
    ]

    # Upcoming Exam Timetable schedule
    exam_schedule = [
        {
            "course_code": "BS105",
            "course_name": "Probability & Statistics",
            "date": "2026-11-25",
            "time": "09:30 AM - 12:30 PM",
            "type": "Theory Exam",
            "status": "Scheduled"
        },
        {
            "course_code": "CS201",
            "course_name": "Data Structures & Algorithms",
            "date": "2026-11-27",
            "time": "09:30 AM - 12:30 PM",
            "type": "Theory Exam",
            "status": "Scheduled"
        },
        {
            "course_code": "CS203",
            "course_name": "Object Oriented Programming (Java/C++)",
            "date": "2026-11-29",
            "time": "09:30 AM - 12:30 PM",
            "type": "Theory Exam",
            "status": "Scheduled"
        },
        {
            "course_code": "CS205",
            "course_name": "Database Management Systems",
            "date": "2026-12-01",
            "time": "09:30 AM - 12:30 PM",
            "type": "Theory Exam",
            "status": "Scheduled"
        }
    ]

    return render_template(
        "student/dashboard.html",
        user=user,
        daily_timetable=daily_tt,
        weekly_timetable=weekly_tt,
        current_day=current_day,
        my_seating=my_seating,
        lib_status=lib_obs,
        lib_config=lib_cfg,
        campus_events=events,
        labs=labs,
        announcements=announcements,
        exam_schedule=exam_schedule
    )
