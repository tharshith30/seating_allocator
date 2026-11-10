import sys
import os

# Automatically resolve dependencies from local runtime cache if needed
_cached_site = os.path.expanduser(r"~\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages")
if os.path.isdir(_cached_site) and _cached_site not in sys.path:
    sys.path.insert(0, _cached_site)

from flask import Flask, render_template, request, send_file, jsonify, redirect
import pandas as pd

from seating_engine import generate_seating
from room_loader import load_rooms
from excel_generator import create_excel
from pdf_generator import create_pdf

# Lab module Blueprint
from lab.routes import lab_bp, _get_analytics, _get_labs_cfg, _current_monday
from lab import booking as bm

# Library module Blueprint
from library.routes import library_bp
from library import occupancy as lib_occupancy

# Campus Space & Facility Management Blueprint
from campus.routes import campus_bp
from campus import db as campus_db
from campus import classroom_service
from campus import auditorium_service
from campus import facility_service

# Role-Based Authentication & Portal Blueprints
from auth.routes import auth_bp
from auth.service import get_current_user
from student.routes import student_bp
from faculty.routes import faculty_bp
from admin.routes import admin_bp

# Automatic Timetable Generation Engine Blueprint & DB
from timetable.routes import timetable_bp
from timetable.models import init_timetable_db


app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "smart-campus-resource-2026-secure-session-key")

# Storage paths with Render persistent disk support via DATA_DIR
DATA_DIR = os.environ.get("DATA_DIR")
if DATA_DIR:
    os.makedirs(DATA_DIR, exist_ok=True)
    ROOM_FILE = os.path.join(DATA_DIR, "roomCapacity_FST.xlsx")
    if not os.path.exists(ROOM_FILE):
        ROOM_FILE = "data/roomCapacity_FST.xlsx"
    OUTPUT_FOLDER = os.path.join(DATA_DIR, "outputs")
else:
    ROOM_FILE = "data/roomCapacity_FST.xlsx"
    OUTPUT_FOLDER = "outputs"

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# =========================================================
# REGISTER MODULE BLUEPRINTS
# =========================================================
# Auth routes (/api/auth/login, /logout, /api/auth/me)
# Student portal (/student)
# Faculty portal (/faculty, /api/faculty/*)
# Admin portal (/admin, /api/admin/*)
# Lab routes (/lab/*, /api/labs*, /api/week*, /api/book*)
# Library routes (/library, /api/library/*, /download/library-report/*)
# Campus routes (/classrooms, /auditoriums, /facilities, /api/campus/*)

app.register_blueprint(auth_bp)
app.register_blueprint(student_bp)
app.register_blueprint(faculty_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(lab_bp)
app.register_blueprint(library_bp)
app.register_blueprint(campus_bp)
app.register_blueprint(timetable_bp)

# Initialize SQLite DBs on startup (creates tables if missing)
with app.app_context():
    bm.init_db()
    lib_occupancy.init_db()
    campus_db.init_db()
    init_timetable_db()


@app.route("/")
def home():
    """First Page — Role Selection Landing Page with automatic authenticated redirection."""
    # If user wants to switch role or landing is explicitly requested
    if request.args.get("landing") == "1":
        return render_template("landing.html")

    user = get_current_user()
    if user:
        role = (user.get("role") or "").lower()
        if role == "student":
            return redirect("/student")
        elif role == "faculty":
            return redirect("/faculty")
        elif role == "admin":
            return redirect("/admin")
        elif role == "maintenance":
            return redirect("/admin?tab=facility")

    return render_template("landing.html")


@app.route("/landing")
def landing():
    """Direct route to Role Selection Landing Page."""
    return render_template("landing.html")


@app.route("/legacy")
def legacy_dashboard():
    """Preserved legacy all-in-one console for backwards compatibility."""
    tab = request.args.get("tab", "seating")
    return render_template(
        "index.html",
        labs=_get_labs_cfg(),
        analytics=_get_analytics(),
        current_week=_current_monday(),
        lib_status=lib_occupancy.get_latest_observation(),
        lib_config=lib_occupancy.get_config(),
        campus_classrooms=classroom_service.list_classrooms(),
        campus_auditoriums=auditorium_service.list_auditoriums(),
        campus_cr_analytics=classroom_service.get_classroom_utilization_analytics(),
        campus_aud_analytics=auditorium_service.get_auditorium_analytics(),
        campus_fac_analytics=facility_service.get_facility_analytics(),
        active_tab=tab
    )


@app.route("/generate", methods=["POST"])
def generate():

    uploaded_file = request.files.get("student_file")
    is_ajax = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.args.get("ajax") == "1"
        or "application/json" in request.headers.get("Accept", "")
    )

    if not uploaded_file:
        error_msg = "Please upload the seating input Excel file."
        if is_ajax:
            return jsonify({"success": False, "error": error_msg}), 400
        return render_template(
            "index.html",
            labs=_get_labs_cfg(),
            analytics=_get_analytics(),
            current_week=_current_monday(),
            lib_status=lib_occupancy.get_latest_observation(),
            lib_config=lib_occupancy.get_config(),
            error=error_msg,
            active_tab="seating"
        )

    try:

        # =====================================================
        # READ EXCEL
        # =====================================================

        excel = pd.ExcelFile(uploaded_file)

        required_sheets = ["EXAMS", "STUDENTS"]

        for sheet in required_sheets:

            if sheet not in excel.sheet_names:

                return render_template(
                    "index.html",
                    error=f"Missing sheet: {sheet}"
                )

        exams_df = pd.read_excel(
            uploaded_file,
            sheet_name="EXAMS"
        )

        students_df = pd.read_excel(
            uploaded_file,
            sheet_name="STUDENTS"
        )

        # =====================================================
        # READ EXAMS
        # =====================================================

        exams = {}

        for _, row in exams_df.iterrows():

            exam_id = str(
                row["Exam ID"]
            ).strip()

            exams[exam_id] = {

                "Course Code": str(
                    row["Course Code"]
                ).strip(),

                "Course Name": str(
                    row["Course Name"]
                ).strip()
            }

        # =====================================================
        # READ STUDENTS
        # =====================================================

        students = []

        for _, row in students_df.iterrows():

            exam_id = str(
                row["Exam ID"]
            ).strip()

            enrolment = str(
                row["Enrolment No"]
            ).strip()

            name = str(
                row["Student Name"]
            ).strip()

            students.append({

                "Exam ID": exam_id,

                "Enrolment No": enrolment,

                "Student Name": name
            })

        # =====================================================
        # LOAD ROOMS
        # =====================================================

        rooms = load_rooms(
            ROOM_FILE
        )

        # =====================================================
        # GENERATE SEATING
        # =====================================================

        allocation = generate_seating(
            students,
            exams,
            rooms
        )

        # =====================================================
        # CREATE EXCEL
        # =====================================================

        excel_file = os.path.join(
            OUTPUT_FOLDER,
            "seating_allotment.xlsx"
        )

        create_excel(
            allocation,
            excel_file
        )

        # =====================================================
        # CREATE PDF
        # =====================================================

        pdf_file = os.path.join(
            OUTPUT_FOLDER,
            "seating_allotment.pdf"
        )

        create_pdf(
            allocation,
            pdf_file
        )

        # =====================================================
        # SYNCHRONIZE STUDENT EXAM SEATING (Real-time student portal sync)
        # =====================================================
        try:
            conn = campus_db.get_db()
            with conn:
                conn.execute("DELETE FROM student_exam_seating;")
                sync_records = []
                for row in allocation:
                    r_room = str(row.get("Room", "")).strip()
                    r_bldg = "Ground Floor Wing A" if "G" in r_room.upper() else "Main Academic Block"
                    sync_records.append((
                        str(row.get("RollNo", "")).strip(),
                        str(row.get("Name", "")).strip(),
                        str(row.get("Exam ID", "")).strip(),
                        str(row.get("Course Code", "")).strip(),
                        str(row.get("Course Name", "")).strip(),
                        r_room,
                        int(row.get("Seat No", 0)),
                        str(row.get("Set", "")).strip(),
                        "2026-11-25",
                        "Morning (09:30 AM - 12:30 PM)",
                        r_bldg
                    ))
                if sync_records:
                    conn.executemany("""
                        INSERT INTO student_exam_seating 
                        (roll_no, student_name, exam_id, course_code, course_name, room_id, seat_no, desk_set, exam_date, exam_session, building)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, sync_records)
            conn.close()
        except Exception as sync_err:
            app.logger.warning("Could not sync student_exam_seating: %s", sync_err)

        # =====================================================
        # STATISTICS
        # =====================================================

        total_students = len(students)

        rooms_used = len(
            set(
                row["Room"]
                for row in allocation
            )
        )

        if is_ajax:
            return jsonify({
                "success": True,
                "total_students": total_students,
                "rooms_used": rooms_used,
                "excel_url": "/download/excel",
                "pdf_url": "/download/pdf"
            })

        return render_template(
            "index.html",
            labs=_get_labs_cfg(),
            analytics=_get_analytics(),
            current_week=_current_monday(),
            lib_status=lib_occupancy.get_latest_observation(),
            lib_config=lib_occupancy.get_config(),
            success=True,
            total_students=total_students,
            rooms_used=rooms_used,
            active_tab="seating"
        )

    except Exception as e:

        if is_ajax:
            return jsonify({"success": False, "error": str(e)}), 400

        return render_template(
            "index.html",
            labs=_get_labs_cfg(),
            analytics=_get_analytics(),
            current_week=_current_monday(),
            lib_status=lib_occupancy.get_latest_observation(),
            lib_config=lib_occupancy.get_config(),
            error=str(e),
            active_tab="seating"
        )


@app.route("/download/excel")
def download_excel():
    excel_path = os.path.join(OUTPUT_FOLDER, "seating_allotment.xlsx")
    if not os.path.exists(excel_path) and os.path.exists("outputs/seating_allotment.xlsx"):
        excel_path = "outputs/seating_allotment.xlsx"
    return send_file(
        excel_path,
        as_attachment=True
    )


@app.route("/download/pdf")
def download_pdf():
    pdf_path = os.path.join(OUTPUT_FOLDER, "seating_allotment.pdf")
    if not os.path.exists(pdf_path) and os.path.exists("outputs/seating_allotment.pdf"):
        pdf_path = "outputs/seating_allotment.pdf"
    return send_file(
        pdf_path,
        as_attachment=True
    )


if __name__ == "__main__":

    app.run(
        debug=True
    )
