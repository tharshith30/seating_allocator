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


app = Flask(__name__)

ROOM_FILE = "data/roomCapacity_FST.xlsx"

OUTPUT_FOLDER = "outputs"

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# =========================================================
# REGISTER LAB BLUEPRINT
# =========================================================
# All lab routes (/lab/*, /api/*) are handled by the Blueprint.
# The existing seating routes below are completely unchanged.

app.register_blueprint(lab_bp)

# Initialize SQLite DB on startup (creates tables if missing)
with app.app_context():
    bm.init_db()


@app.route("/")
def home():
    tab = request.args.get("tab", "seating")
    return render_template(
        "index.html",
        labs=_get_labs_cfg(),
        analytics=_get_analytics(),
        current_week=_current_monday(),
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
            error=str(e),
            active_tab="seating"
        )


@app.route("/download/excel")
def download_excel():

    return send_file(
        "outputs/seating_allotment.xlsx",
        as_attachment=True
    )


@app.route("/download/pdf")
def download_pdf():

    return send_file(
        "outputs/seating_allotment.pdf",
        as_attachment=True
    )


if __name__ == "__main__":

    app.run(
        debug=True
    )
