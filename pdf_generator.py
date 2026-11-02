import sys
import os

_cached_site = os.path.expanduser(r"~\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages")
if os.path.isdir(_cached_site) and _cached_site not in sys.path:
    sys.path.insert(0, _cached_site)

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet


def create_pdf(allocation, output_file):

    styles = getSampleStyleSheet()

    doc = SimpleDocTemplate(
        output_file,
        pagesize=landscape(A4)
    )

    elements = []

    if not allocation:

        elements.append(
            Paragraph(
                "No seating allocation generated.",
                styles["Title"]
            )
        )

        doc.build(elements)

        return

    # =========================================================
    # GROUP BY ROOM
    # =========================================================

    rooms = {}

    for row in allocation:

        room = row["Room"]

        if room not in rooms:
            rooms[room] = []

        rooms[room].append(row)

    # =========================================================
    # CREATE ONE PAGE PER ROOM
    # =========================================================

    for room, students in rooms.items():

        elements.append(
            Paragraph(
                f"Examination Seating Allotment - Room {room}",
                styles["Title"]
            )
        )

        elements.append(
            Spacer(1, 15)
        )

        # =====================================================
        # TABLE HEADER
        # =====================================================

        data = [

            [
                "Seat No",
                "Set",
                "Exam ID",
                "Course Code",
                "Course Name",
                "Roll No",
                "Student Name"
            ]

        ]

        # =====================================================
        # STUDENTS
        # =====================================================

        for student in students:

            data.append([

                student["Seat No"],

                student["Set"],

                student["Exam ID"],

                student["Course Code"],

                student["Course Name"],

                student["RollNo"],

                student["Name"]

            ])

        # =====================================================
        # TABLE
        # =====================================================

        table = Table(
            data,
            repeatRows=1
        )

        table.setStyle(

            TableStyle([

                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.grey
                ),

                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white
                ),

                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.black
                ),

                (
                    "ALIGN",
                    (0, 0),
                    (-1, -1),
                    "CENTER"
                ),

                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE"
                ),

                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    7
                ),

                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, 0),
                    8
                )

            ])

        )

        elements.append(table)

        elements.append(
            PageBreak()
        )

    # =========================================================
    # BUILD PDF
    # =========================================================

    doc.build(elements)

    print(
        f"PDF created: {output_file}"
    )


# =========================================================
# LAB UTILIZATION REPORT
# =========================================================

def create_lab_report(analytics: dict, sessions: list, output_file: str):
    """
    Generate a Lab Utilization Report PDF.
    Reuses the same ReportLab setup as create_pdf().

    Sections:
    1. Summary table (lab, utilization %, booked/free, avg fill, over-cap, status)
    2. Per-lab heatmap (day × slot colored table)
    3. Rule-based forecast table
    4. Over-capacity sessions list
    """

    styles = getSampleStyleSheet()

    doc = SimpleDocTemplate(
        output_file,
        pagesize=landscape(A4)
    )

    elements = []

    # ─── Title ─────────────────────────────────────────────────────────────
    elements.append(Paragraph("Lab Utilization Report", styles["Title"]))
    elements.append(Spacer(1, 12))

    # Status → color mapping for the summary table
    STATUS_COLORS = {
        "Underused":  colors.HexColor("#FFF9C4"),   # pale yellow
        "Healthy":    colors.HexColor("#E8F5E9"),   # pale green
        "Overloaded": colors.HexColor("#FFEBEE"),   # pale red
        "No data":    colors.HexColor("#F5F5F5"),   # grey
    }

    # ─── 1. Summary table ──────────────────────────────────────────────────
    elements.append(Paragraph("Summary", styles["Heading2"]))
    elements.append(Spacer(1, 6))

    summary_data = [[
        "Lab", "Name", "Capacity",
        "Booked", "Free", "Utilization %",
        "Avg Fill %", "Over-Cap Sessions", "Status"
    ]]

    for lab_id, info in sorted(analytics.items()):
        if not info["has_data"]:
            summary_data.append([
                lab_id, info["lab_name"], str(info["capacity"]),
                "—", "—", "—", "—", "—", "No data"
            ])
        else:
            summary_data.append([
                lab_id,
                info["lab_name"],
                str(info["capacity"]),
                str(info["booked_count"]),
                str(info["free_count"]),
                f"{info['utilization_pct']}%",
                f"{info['avg_fill_pct']}%",
                str(info["over_cap_count"]),
                info["status"],
            ])

    summary_table = Table(summary_data, repeatRows=1)

    # Build per-row colors
    row_styles = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("GRID",       (0, 0), (-1, -1), 0.5, colors.black),
        ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE",   (0, 0), (-1, -1), 8),
    ]
    for i, (lab_id, info) in enumerate(sorted(analytics.items()), start=1):
        status = info.get("status", "No data")
        bg = STATUS_COLORS.get(status, colors.white)
        row_styles.append(("BACKGROUND", (0, i), (-1, i), bg))

    summary_table.setStyle(TableStyle(row_styles))
    elements.append(summary_table)
    elements.append(PageBreak())

    # ─── 2. Per-lab heatmaps ───────────────────────────────────────────────
    DAYS   = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    SLOTS  = [f"S{i}" for i in range(1, 10)]
    CELL_COLORS = {
        "booked": colors.HexColor("#EF9A9A"),   # red
        "empty":  colors.HexColor("#A5D6A7"),   # green
        "lunch":  colors.HexColor("#BDBDBD"),   # grey
    }

    for lab_id, info in sorted(analytics.items()):
        if not info["has_data"]:
            continue

        elements.append(Paragraph(
            f"Heatmap — {info['lab_name']} (Utilization: {info['utilization_pct']}%)",
            styles["Heading2"]
        ))
        elements.append(Spacer(1, 6))

        heatmap = info["heatmap"]
        hm_data = [["Day"] + SLOTS]
        hm_styles = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("GRID",       (0, 0), (-1, -1), 0.5, colors.black),
            ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
            ("FONTSIZE",   (0, 0), (-1, -1), 8),
        ]

        for r, (day, row_cells) in enumerate(zip(DAYS, heatmap), start=1):
            row_vals = [day]
            for c, cell in enumerate(row_cells, start=1):
                state = cell["state"]
                sess_count = len(cell["sessions"])
                label = str(sess_count) if state == "booked" else ("L" if state == "lunch" else "")
                row_vals.append(label)
                bg = CELL_COLORS.get(state, colors.white)
                hm_styles.append(("BACKGROUND", (c, r), (c, r), bg))
            hm_data.append(row_vals)

        hm_table = Table(hm_data, repeatRows=1)
        hm_table.setStyle(TableStyle(hm_styles))
        elements.append(hm_table)
        elements.append(Spacer(1, 10))

        # Forecast table (rule-based, clearly labeled)
        if info["forecast"]:
            elements.append(Paragraph(
                "Rule-Based Forecast (NOT machine learning — multiplicative model only):",
                styles["Normal"]
            ))
            fc_data = [["Week Type", "Baseline Slots", "× Attendance", "× Week Factor",
                        "Predicted Slots", "Predicted %", "Formula"]]
            for row in info["forecast"]:
                fc_data.append([
                    row["week_type"],
                    str(row["baseline_slots"]),
                    str(row["attendance_factor"]),
                    str(row["week_factor"]),
                    str(row["predicted_slots"]),
                    f"{row['predicted_pct']}%",
                    row["formula"],
                ])
            fc_table = Table(fc_data, repeatRows=1)
            fc_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
            ]))
            elements.append(fc_table)
            elements.append(Spacer(1, 6))

        # Over-capacity sessions
        if info["over_cap_count"] > 0:
            elements.append(Paragraph(
                f"Over-Capacity Sessions ({info['over_cap_count']}):",
                styles["Normal"]
            ))
            oc_data = [["Year", "Section", "Day", "Slot", "Course", "Strength", "Capacity"]]
            for s in info["over_cap_sessions"]:
                oc_data.append([
                    s.get("year", ""), s["section"], s["day"],
                    f"S{s['slot1']}", s["course"], str(s["strength"]),
                    str(info["capacity"])
                ])
            oc_table = Table(oc_data, repeatRows=1)
            oc_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EF5350")),
                ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
            ]))
            elements.append(oc_table)

        elements.append(PageBreak())

    doc.build(elements)
    print(f"Lab report PDF created: {output_file}")