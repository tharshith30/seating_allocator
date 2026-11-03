"""
campus/reports.py — Multi-format reporting engine (Excel & PDF) for Campus Space & Facility Management.

Uses:
- OpenPyXL for multi-sheet workbook generation (.xlsx)
- ReportLab for audit-grade executive PDF summaries (.pdf)
"""

import os
import sys
import logging
from datetime import datetime, date

_cached_site = os.path.expanduser(r"~\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages")
if os.path.isdir(_cached_site) and _cached_site not in sys.path:
    sys.path.insert(0, _cached_site)

from . import db
from . import classroom_service
from . import auditorium_service
from . import facility_service

logger = logging.getLogger(__name__)


def generate_campus_excel_report(output_path: str) -> str:
    """Generate comprehensive multi-tab Excel workbook for campus spaces and facilities."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # Remove default sheet

    # Common styles
    header_fill = PatternFill(start_color="1A237E", end_color="1A237E", fill_type="solid")
    header_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    title_font = Font(name="Segoe UI", size=13, bold=True, color="1A237E")
    body_font = Font(name="Segoe UI", size=9)
    bold_font = Font(name="Segoe UI", size=9, bold=True)
    center_align = Alignment(horizontal="center", vertical="center")
    left_align = Alignment(horizontal="left", vertical="center")
    border_thin = Side(style="thin", color="CCCCCC")
    cell_border = Border(left=border_thin, right=border_thin, top=border_thin, bottom=border_thin)

    # ─────────────────────────────────────────────────────────────────────────
    # Sheet 1: Classroom Inventory
    # ─────────────────────────────────────────────────────────────────────────
    ws_cr = wb.create_sheet("Classroom Inventory")
    ws_cr.views.sheetView[0].showGridLines = True
    ws_cr.append(["Smart Resource Management System — Classroom Inventory"])
    ws_cr.cell(1, 1).font = title_font
    ws_cr.append([f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Campus Space & Facility Management"])
    ws_cr.cell(2, 1).font = Font(name="Segoe UI", size=9, italic=True, color="666666")
    ws_cr.append([])

    cr_headers = ["Room ID", "Name", "Block", "Floor", "Benches", "Capacity", "Room Type", "Projector", "Audio", "AC", "Status"]
    ws_cr.append(cr_headers)
    for col_idx in range(1, len(cr_headers) + 1):
        cell = ws_cr.cell(4, col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_align

    rooms = classroom_service.list_classrooms()
    for r in rooms:
        row_data = [
            r["id"], r["name"], r["block"], f"Floor {r['floor']}",
            r["bench_count"], r["seating_capacity"], r["room_type"],
            "Yes" if r["has_projector"] else "No",
            "Yes" if r["has_audio"] else "No",
            "Yes" if r["has_ac"] else "No",
            r["status"].capitalize()
        ]
        ws_cr.append(row_data)

    # ─────────────────────────────────────────────────────────────────────────
    # Sheet 2: Timetable Schedule
    # ─────────────────────────────────────────────────────────────────────────
    ws_tt = wb.create_sheet("Academic Timetable")
    ws_tt.views.sheetView[0].showGridLines = True
    ws_tt.append(["Classroom Weekly Lecture Timetable"])
    ws_tt.cell(1, 1).font = title_font
    ws_tt.append([])

    tt_headers = ["Classroom", "Day", "Slot", "Subject Code", "Subject Name", "Section", "Faculty", "Academic Year"]
    ws_tt.append(tt_headers)
    for col_idx in range(1, len(tt_headers) + 1):
        cell = ws_tt.cell(3, col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_align

    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM classroom_schedules ORDER BY classroom_id ASC, day ASC, slot ASC;")
    for row in cursor.fetchall():
        ws_tt.append([
            row["classroom_id"], row["day"], f"Slot {row['slot']}",
            row["subject_code"], row["subject_name"], row["section"],
            row["faculty_name"], row["academic_year"]
        ])

    # ─────────────────────────────────────────────────────────────────────────
    # Sheet 3: Auditorium Events
    # ─────────────────────────────────────────────────────────────────────────
    ws_aud = wb.create_sheet("Auditorium Events")
    ws_aud.views.sheetView[0].showGridLines = True
    ws_aud.append(["Campus Auditorium Bookings & Events"])
    ws_aud.cell(1, 1).font = title_font
    ws_aud.append([])

    aud_headers = ["Event ID", "Auditorium", "Event Title", "Type", "Department", "Date", "Start", "End", "Attendees", "Status"]
    ws_aud.append(aud_headers)
    for col_idx in range(1, len(aud_headers) + 1):
        cell = ws_aud.cell(3, col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_align

    events = auditorium_service.list_events()
    for ev in events:
        ws_aud.append([
            f"EV-{ev['id']}", ev["auditorium_id"], ev["event_title"],
            ev["event_type"], ev["department"], ev["event_date"],
            ev["start_time"], ev["end_time"], ev["expected_attendees"],
            ev["status"].capitalize()
        ])

    # ─────────────────────────────────────────────────────────────────────────
    # Sheet 4: Facility Maintenance Tickets
    # ─────────────────────────────────────────────────────────────────────────
    ws_fac = wb.create_sheet("Maintenance Requests")
    ws_fac.views.sheetView[0].showGridLines = True
    ws_fac.append(["Facility Maintenance Work Orders & Tracking"])
    ws_fac.cell(1, 1).font = title_font
    ws_fac.append([])

    fac_headers = ["Ticket No", "Space Type", "Location", "Category", "Issue Title", "Priority", "Status", "Reported By", "Assigned To", "Logged At"]
    ws_fac.append(fac_headers)
    for col_idx in range(1, len(fac_headers) + 1):
        cell = ws_fac.cell(3, col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_align

    tickets = facility_service.list_maintenance_requests()
    for tk in tickets:
        ws_fac.append([
            tk["ticket_no"], tk["location_type"].capitalize(), tk["location_id"],
            tk["category"], tk["issue_title"], tk["priority"],
            tk["status"].capitalize(), tk["reported_by"], tk["assigned_to"] or "Unassigned",
            tk["created_at"]
        ])
    conn.close()

    # Auto-fit columns across all sheets
    for ws in wb.worksheets:
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    wb.save(output_path)
    return output_path


def generate_campus_pdf_report(output_path: str) -> str:
    """Generate executive summary PDF covering Campus Space & Facility Management."""
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("CampusTitle", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=colors.HexColor("#1A237E"))
    sub_style = ParagraphStyle("CampusSub", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=12, textColor=colors.HexColor("#555555"))
    h2_style = ParagraphStyle("CampusH2", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=12, leading=16, textColor=colors.HexColor("#283593"))
    body_style = ParagraphStyle("CampusBody", parent=styles["Normal"], fontName="Helvetica", fontSize=8, leading=11)
    center_style = ParagraphStyle("CampusCenter", parent=styles["Normal"], fontName="Helvetica", fontSize=8, leading=11, alignment=1)
    bold_center = ParagraphStyle("CampusBoldCenter", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=11, alignment=1)

    elements = []

    # Header
    elements.append(Paragraph("🏛 Smart Resource Management System", title_style))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph("Campus Space & Facility Management — Executive Audit Briefing", sub_style))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')} | Confidential Institutional Audit", sub_style))
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1A237E"), spaceAfter=14))

    # Pull analytics
    cr_analytics = classroom_service.get_classroom_utilization_analytics()
    aud_analytics = auditorium_service.get_auditorium_analytics()
    fac_analytics = facility_service.get_facility_analytics()

    # KPI summary grid
    kpi_data = [
        [
            Paragraph(f"<b>Classrooms</b><br/><font size='14' color='#1A237E'><b>{cr_analytics['total_rooms']}</b></font><br/>{cr_analytics['total_seats']} Total Desks", center_style),
            Paragraph(f"<b>Utilization</b><br/><font size='14' color='#2E7D32'><b>{cr_analytics['utilization_rate_pct']}%</b></font><br/>{cr_analytics['total_scheduled_slots']} Weekly Slots", center_style),
            Paragraph(f"<b>Auditoriums</b><br/><font size='14' color='#0277BD'><b>{aud_analytics['total_auditoriums']}</b></font><br/>{aud_analytics['total_capacity']} Total Seats", center_style),
            Paragraph(f"<b>Events Approved</b><br/><font size='14' color='#4527A0'><b>{aud_analytics['approved_events']}</b></font><br/>{aud_analytics['total_attendees']} Attendees", center_style),
            Paragraph(f"<b>Open Work Orders</b><br/><font size='14' color='#C62828'><b>{fac_analytics['open_tickets']}</b></font><br/>{fac_analytics['blocked_spaces_count']} DOWNTIME BLOCKS", center_style)
        ]
    ]
    kpi_table = Table(kpi_data, colWidths=[108, 108, 108, 108, 108])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F5F7FA")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#D1D5DB")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(kpi_table)
    elements.append(Spacer(1, 16))

    # Section 1: Classroom Utilization
    elements.append(Paragraph("1. Classroom Utilization Profile (Top Utilized vs Underutilized)", h2_style))
    elements.append(Spacer(1, 6))

    cr_table_data = [
        [Paragraph("<b>Room ID</b>", bold_center), Paragraph("<b>Room Type</b>", bold_center), Paragraph("<b>Capacity</b>", bold_center),
         Paragraph("<b>Scheduled Slots</b>", bold_center), Paragraph("<b>Utilization %</b>", bold_center), Paragraph("<b>Status</b>", bold_center)]
    ]
    for r in cr_analytics["all_rankings"][:8]:
        st_color = "#2E7D32" if r["status"] == "High" else ("#0277BD" if r["status"] == "Moderate" else "#757575")
        cr_table_data.append([
            Paragraph(f"<b>{r['id']}</b>", center_style),
            Paragraph(r["room_type"], center_style),
            Paragraph(str(r["seating_capacity"]), center_style),
            Paragraph(str(r["scheduled_slots"]), center_style),
            Paragraph(f"{r['utilization_pct']}%", center_style),
            Paragraph(f"<font color='{st_color}'><b>{r['status']}</b></font>", center_style),
        ])

    cr_table = Table(cr_table_data, colWidths=[80, 110, 80, 90, 90, 90])
    cr_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A237E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E0E0E0")),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(cr_table)
    elements.append(Spacer(1, 16))

    # Section 2: Active Maintenance Work Orders & Downtime
    elements.append(Paragraph("2. Active Facility Maintenance Tickets & Space Downtime", h2_style))
    elements.append(Spacer(1, 6))

    tickets = facility_service.list_maintenance_requests()
    if tickets:
        fac_table_data = [
            [Paragraph("<b>Ticket No</b>", bold_center), Paragraph("<b>Location</b>", bold_center), Paragraph("<b>Category</b>", bold_center),
             Paragraph("<b>Issue Title</b>", bold_center), Paragraph("<b>Priority</b>", bold_center), Paragraph("<b>Status</b>", bold_center)]
        ]
        for tk in tickets[:6]:
            p_color = "#C62828" if tk["priority"] == "Critical" else ("#EF6C00" if tk["priority"] == "High" else "#2E7D32")
            fac_table_data.append([
                Paragraph(f"<b>{tk['ticket_no']}</b>", center_style),
                Paragraph(tk["location_id"], center_style),
                Paragraph(tk["category"], center_style),
                Paragraph(tk["issue_title"][:32], body_style),
                Paragraph(f"<font color='{p_color}'><b>{tk['priority']}</b></font>", center_style),
                Paragraph(tk["status"].capitalize(), center_style)
            ])
        fac_table = Table(fac_table_data, colWidths=[85, 75, 80, 160, 70, 70])
        fac_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#37474F")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E0E0E0")),
            ("PADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(fac_table)
    else:
        elements.append(Paragraph("<i>No active maintenance issues recorded. Campus infrastructure operating normally.</i>", body_style))

    doc.build(elements)
    return output_path
