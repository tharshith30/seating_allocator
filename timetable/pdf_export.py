"""
timetable/pdf_export.py — High-resolution ReportLab vector PDF export for Academic Timetables.
Supports both individual section timetables and consolidated multi-section booklets.
"""

import os
import sys
import logging
from io import BytesIO

_cached_site = os.path.expanduser(r"~\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages")
if os.path.isdir(_cached_site) and _cached_site not in sys.path:
    sys.path.insert(0, _cached_site)

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

from campus import db as campus_db
from .models import STANDARD_WORKING_DAYS, STANDARD_SLOTS

logger = logging.getLogger(__name__)


def generate_timetable_pdf(version_id: int, section_id: int = None, all_sections: bool = False, output_path: str = None) -> str:
    """
    Generate professional landscape A4 PDF for a published/draft timetable version.
    Returns the path to the saved PDF file.
    """
    conn = campus_db.get_db()
    cursor = conn.cursor()

    # 1. Fetch version and generation metadata
    cursor.execute("""
        SELECT tv.*, tg.academic_year_id, tg.semester_id, tg.department_id, tg.scope,
               ay.name as academic_year_name, ay.code as academic_year_code,
               sem.name as semester_name, d.name as department_name
        FROM timetable_versions tv
        JOIN timetable_generations tg ON tv.generation_id = tg.id
        LEFT JOIN academic_years ay ON tg.academic_year_id = ay.id
        LEFT JOIN semesters sem ON tg.semester_id = sem.id
        LEFT JOIN departments d ON tg.department_id = d.id
        WHERE tv.id = ?;
    """, (version_id,))
    ver_meta = cursor.fetchone()
    if not ver_meta:
        conn.close()
        raise ValueError(f"Timetable version #{version_id} not found.")

    ver_dict = dict(ver_meta)

    # 2. Determine target sections
    if section_id:
        cursor.execute("SELECT * FROM sections WHERE id = ?;", (section_id,))
        target_sections = [dict(r) for r in cursor.fetchall()]
    elif all_sections or not section_id:
        cursor.execute("""
            SELECT DISTINCT sec.* 
            FROM sections sec
            JOIN timetable_entries te ON te.section_id = sec.id
            WHERE te.version_id = ?
            ORDER BY sec.name ASC;
        """, (version_id,))
        target_sections = [dict(r) for r in cursor.fetchall()]

    if not target_sections:
        conn.close()
        raise ValueError("No sections found for this timetable version.")

    # 3. Setup PDF document
    if not output_path:
        data_dir = os.environ.get("DATA_DIR")
        if data_dir:
            out_dir = os.path.join(data_dir, "outputs")
        else:
            out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "outputs"))
        os.makedirs(out_dir, exist_ok=True)
        suffix = f"sec{section_id}" if section_id else "all_sections"
        output_path = os.path.abspath(os.path.join(out_dir, f"academic_timetable_v{version_id}_{suffix}.pdf"))

    doc = SimpleDocTemplate(
        output_path,
        pagesize=landscape(A4),
        leftMargin=0.4 * inch,
        rightMargin=0.4 * inch,
        topMargin=0.4 * inch,
        bottomMargin=0.4 * inch
    )

    styles = getSampleStyleSheet()

    # Custom styles
    header_title_style = ParagraphStyle(
        "TTHeaderTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        textColor=colors.HexColor("#0f172a"),
        alignment=1
    )

    header_sub_style = ParagraphStyle(
        "TTHeaderSub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=12,
        textColor=colors.HexColor("#334155"),
        alignment=1
    )

    cell_bold_style = ParagraphStyle(
        "TTCellBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        alignment=1,
        textColor=colors.HexColor("#0f172a")
    )

    cell_sub_style = ParagraphStyle(
        "TTCellSub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=8.5,
        alignment=1,
        textColor=colors.HexColor("#475569")
    )

    cell_fac_style = ParagraphStyle(
        "TTCellFac",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=7,
        leading=8.5,
        alignment=1,
        textColor=colors.HexColor("#0d9488")
    )

    lunch_style = ParagraphStyle(
        "TTCellLunch",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=9,
        alignment=1,
        textColor=colors.HexColor("#94a3b8")
    )

    elements = []
    days = STANDARD_WORKING_DAYS
    slots = list(range(1, 10))

    for sec_idx, sec in enumerate(target_sections):
        s_id = sec["id"]
        sec_name = sec["display_name"]

        # Fetch entries for this section
        cursor.execute("""
            SELECT te.*, s.code as subject_code, s.name as subject_name,
                   cr.name as room_name, cr.room_type
            FROM timetable_entries te
            JOIN subjects s ON te.subject_id = s.id
            LEFT JOIN classrooms cr ON te.room_id = cr.id
            WHERE te.version_id = ? AND te.section_id = ?
            ORDER BY te.day, te.slot ASC;
        """, (version_id, s_id))
        entries = [dict(r) for r in cursor.fetchall()]

        # Build grid map: grid[day][slot] = entry
        grid = {d: {s: None for s in slots} for d in days}
        for e in entries:
            d = e["day"]
            s = e["slot"]
            if d in grid and s in grid[d]:
                grid[d][s] = e

        # Header Block
        inst_name = "ICFAI Foundation for Higher Education (IFHE)"
        prog_info = f"Faculty of Science & Technology (FST) • Department of {ver_dict.get('department_name') or 'Computer Science & Engineering'}"
        sem_info = f"{ver_dict.get('academic_year_name') or 'Academic Year 2026-2027'} • {ver_dict.get('semester_name') or 'Semester 3'} • {sec_name}"

        elements.append(Paragraph(inst_name, header_title_style))
        elements.append(Paragraph(prog_info, header_sub_style))
        elements.append(Paragraph(f"<b>OFFICIAL ACADEMIC TIMETABLE — {sem_info}</b>", header_sub_style))
        elements.append(Spacer(1, 0.15 * inch))

        # Table Header Rows
        # Header Row 1: Day | Slot 1 | Slot 2 | Slot 3 | Slot 4 | Lunch | Slot 6 | Slot 7 | Slot 8 | Slot 9
        header_row_1 = ["Day / Time"]
        for s in slots:
            slot_name = STANDARD_SLOTS.get(s, {}).get("name", f"Slot {s}")
            slot_time = STANDARD_SLOTS.get(s, {}).get("time", "")
            if s == 5:
                header_row_1.append(Paragraph(f"<b>LUNCH BREAK</b><br/>{slot_time}", lunch_style))
            else:
                header_row_1.append(Paragraph(f"<b>{slot_name}</b><br/><font size=6 color='#64748b'>{slot_time}</font>", cell_bold_style))

        table_data = [header_row_1]

        # Day Rows
        day_names_long = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday", "Sat": "Saturday"}

        for d in days:
            row = [Paragraph(f"<b>{day_names_long.get(d, d)}</b>", cell_bold_style)]
            for s in slots:
                if s == 5:
                    row.append(Paragraph("<b>LUNCH</b>", lunch_style))
                    continue

                cell_entry = grid[d][s]
                if cell_entry:
                    sub_code = cell_entry["subject_code"]
                    sub_name = cell_entry["subject_name"]
                    fac = cell_entry["faculty_name"]
                    room = cell_entry["room_id"]
                    is_lab = cell_entry.get("is_lab", 0)

                    # Truncate subject name if long
                    short_title = (sub_name[:18] + "..") if len(sub_name) > 18 else sub_name
                    lab_tag = " <font color='#0284c7'>[LAB]</font>" if is_lab else ""

                    cell_html = (
                        f"<b>{sub_code}</b>{lab_tag}<br/>"
                        f"<font size=6.5 color='#334155'>{short_title}</font><br/>"
                        f"<font size=6.5 color='#0d9488'>{fac}</font><br/>"
                        f"<font size=6 color='#64748b'><b>Room: {room}</b></font>"
                    )
                    row.append(Paragraph(cell_html, cell_bold_style))
                else:
                    row.append(Paragraph("<font color='#cbd5e1'>—</font>", cell_sub_style))
            table_data.append(row)

        # Style Table
        # Column widths: Day column ~ 65pt, remaining 9 columns evenly divide remaining ~700pt -> 77pt each
        col_widths = [68] + [77] * 9
        tt_table = Table(table_data, colWidths=col_widths, repeatRows=1)

        t_style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#f8fafc")), # Day column background
            ("BACKGROUND", (5, 0), (5, -1), colors.HexColor("#f8fafc")), # Lunch column background
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]

        # Highlight Lab cells
        for r_idx, d in enumerate(days, start=1):
            for c_idx, s in enumerate(slots, start=1):
                if s == 5:
                    continue
                entry = grid[d][s]
                if entry and entry.get("is_lab"):
                    t_style.append(("BACKGROUND", (c_idx, r_idx), (c_idx, r_idx), colors.HexColor("#f0fdf4"))) # light green/cyan
                    t_style.append(("BOX", (c_idx, r_idx), (c_idx, r_idx), 1, colors.HexColor("#0284c7")))

        tt_table.setStyle(TableStyle(t_style))
        elements.append(tt_table)
        elements.append(Spacer(1, 0.15 * inch))

        # Course Legend & Faculty Mapping Box
        # Unique subjects for this section
        cursor.execute("""
            SELECT DISTINCT s.code, s.name, te.faculty_name, s.subject_type,
                   s.weekly_lecture_hours, s.weekly_lab_hours
            FROM timetable_entries te
            JOIN subjects s ON te.subject_id = s.id
            WHERE te.version_id = ? AND te.section_id = ?
            ORDER BY s.code ASC;
        """, (version_id, s_id))
        sec_subjects = [dict(r) for r in cursor.fetchall()]

        legend_data = [["Course Code", "Course Title", "Faculty In-Charge", "L-T-P", "Type"]]
        for sub in sec_subjects:
            l = sub.get("weekly_lecture_hours", 3)
            p = sub.get("weekly_lab_hours", 0)
            ltp = f"{l}-0-{p}"
            legend_data.append([
                sub["code"],
                sub["name"],
                sub["faculty_name"],
                ltp,
                sub["subject_type"].title()
            ])

        leg_table = Table(
            [[Paragraph(f"<b>{c}</b>", cell_bold_style) if r_i == 0 else Paragraph(str(c), cell_sub_style)
              for c in row] for r_i, row in enumerate(legend_data)],
            colWidths=[80, 260, 200, 60, 80]
        )
        leg_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ]))

        elements.append(Paragraph("<b>Subject Code & Faculty Directory:</b>", header_sub_style))
        elements.append(Spacer(1, 0.05 * inch))
        elements.append(leg_table)
        elements.append(Spacer(1, 0.2 * inch))

        # Institutional Signatures Block
        sig_data = [
            ["_________________________", "_________________________", "_________________________"],
            ["Class Coordinator", "Head of Department (HoD)", "Dean / Principal, FST"]
        ]
        sig_table = Table(
            [[Paragraph(f"<b>{c}</b>", cell_sub_style) for c in row] for row in sig_data],
            colWidths=[240, 240, 240]
        )
        sig_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        elements.append(KeepTogether(sig_table))

        # Add page break between sections
        if sec_idx < len(target_sections) - 1:
            elements.append(PageBreak())

    conn.close()

    # Build Document
    doc.build(elements)
    logger.info("Generated Timetable PDF for Version #%d at: %s", version_id, output_path)
    return output_path
