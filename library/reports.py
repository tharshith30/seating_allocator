"""
library/reports.py — Administrative Excel and PDF report generation for the library module.

Reuses OpenPyXL and ReportLab to export:
- Excel spreadsheets (.xlsx) with multi-sheet analytical summaries and observation logs.
- Executive PDF reports (.pdf) ready for administration archiving and review.
"""

import os
import sys
from datetime import datetime

# Fallback path inclusion for reportlab/openpyxl if cached in user profile
_cached_site = os.path.expanduser(r"~\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages")
if os.path.isdir(_cached_site) and _cached_site not in sys.path:
    sys.path.insert(0, _cached_site)

import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from . import occupancy
from . import analytics
from . import recommendations


def generate_library_excel_report(output_file: str, date_filter: str = "30d") -> str:
    """
    Generate an Excel workbook (.xlsx) detailing library occupancy metrics,
    hourly distribution, day-of-week trends, and recent observation logs.
    """
    stats = analytics.compute_library_analytics(date_filter=date_filter)
    records = occupancy.get_observations(date_filter=date_filter, limit=1000)
    cfg = occupancy.get_config()
    recs = recommendations.generate_recommendations()

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        # Sheet 1: Executive Summary & KPIs
        kpi_data = [
            {"Metric": "Library Facility", "Value": cfg.get("name", "Central Library")},
            {"Metric": "Total Seating Capacity", "Value": f"{cfg.get('total_capacity', 250)} seats"},
            {"Metric": "Analysis Period", "Value": f"Filter: {date_filter.upper()}"},
            {"Metric": "Total Observations Logged", "Value": stats.get("total_observations", 0)},
            {"Metric": "Average Seating Occupancy", "Value": f"{stats.get('avg_occupancy_pct', 0)}%"},
            {"Metric": "Maximum Recorded Occupancy", "Value": f"{stats.get('max_occupancy_seats', 0)} seats ({stats.get('max_occupancy_pct', 0)}%)"},
            {"Metric": "Minimum Recorded Occupancy", "Value": f"{stats.get('min_occupancy_seats', 0)} seats ({stats.get('min_occupancy_pct', 0)}%)"},
            {"Metric": "Report Generated", "Value": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
        ]
        pd.DataFrame(kpi_data).to_excel(writer, sheet_name="Executive Summary", index=False)

        # Sheet 2: Hourly Occupancy Distribution
        hourly = stats.get("hourly_chart", {})
        h_rows = [
            {"Hour Slot": lbl, "Average Occupancy %": val, "Est. Occupied Seats": int(round((val/100)*cfg['total_capacity']))}
            for lbl, val in zip(hourly.get("labels", []), hourly.get("data", []))
        ]
        pd.DataFrame(h_rows).to_excel(writer, sheet_name="Hourly Distribution", index=False)

        # Sheet 3: Day of Week Analysis
        dow_rows = [
            {"Day of Week": d["day"], "Average Occupancy %": d["avg_pct"]}
            for d in stats.get("busiest_days", [])
        ]
        pd.DataFrame(dow_rows).to_excel(writer, sheet_name="Day of Week Trends", index=False)

        # Sheet 4: Observation Logs
        log_rows = [
            {
                "Record ID": r["id"],
                "Date": r["recorded_date"],
                "Time": r["recorded_time"],
                "Occupied Seats": r["occupied_seats"],
                "Capacity": r["total_capacity"],
                "Available Seats": r["available_seats"],
                "Occupancy %": r["occupancy_pct"],
                "Status Category": r["status"],
                "Recorded By": r["recorded_by"],
                "Notes": r["notes"] or ""
            }
            for r in records
        ]
        pd.DataFrame(log_rows).to_excel(writer, sheet_name="Observation Log", index=False)

        # Sheet 5: Strategic Recommendations
        rec_rows = [
            {
                "Category": r.get("category", ""),
                "Type": r.get("tag", ""),
                "Title": r.get("title", ""),
                "Insight & Description": r.get("description", ""),
                "Recommended Action": r.get("action", "")
            }
            for r in recs
        ]
        pd.DataFrame(rec_rows).to_excel(writer, sheet_name="Recommendations", index=False)

    return output_file


def generate_library_pdf_report(output_file: str, date_filter: str = "30d") -> str:
    """
    Generate an executive PDF report (.pdf) using ReportLab.
    Includes college branding, KPI summaries, hourly analysis, recent logs,
    and administrative recommendations.
    """
    stats = analytics.compute_library_analytics(date_filter=date_filter)
    records = occupancy.get_observations(date_filter=date_filter, limit=25)
    cfg = occupancy.get_config()
    recs = recommendations.generate_recommendations()

    doc = SimpleDocTemplate(
        output_file,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "LibTitle",
        parent=styles["Title"],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1769aa"),
        alignment=0,
        spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        "LibSubtitle",
        parent=styles["Normal"],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#555577"),
        spaceAfter=14
    )
    section_style = ParagraphStyle(
        "LibSection",
        parent=styles["Heading2"],
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#0d47a1"),
        spaceBefore=12,
        spaceAfter=6
    )
    body_style = ParagraphStyle(
        "LibBody",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#1a1a2e")
    )

    elements = []

    # Title & Header
    elements.append(Paragraph("Smart Resource Management System", subtitle_style))
    elements.append(Paragraph("Central Library Seating Utilization & Analytics Report", title_style))
    elements.append(Paragraph(
        f"Generated: <b>{datetime.now().strftime('%B %d, %Y at %I:%M %p')}</b> &nbsp;|&nbsp; Period Filter: <b>{date_filter.upper()}</b> &nbsp;|&nbsp; Facility Capacity: <b>{cfg['total_capacity']} Seats</b>",
        subtitle_style
    ))
    elements.append(Spacer(1, 8))

    # Executive KPI Summary Table
    elements.append(Paragraph("1. Executive Summary &amp; Key Utilization Metrics", section_style))
    kpi_table_data = [
        ["Metric", "Value", "Metric", "Value"],
        [
            "Total Observations", str(stats.get("total_observations", 0)),
            "Average Occupancy", f"{stats.get('avg_occupancy_pct', 0)}%"
        ],
        [
            "Peak Capacity Reached", f"{stats.get('max_occupancy_seats', 0)} seats ({stats.get('max_occupancy_pct', 0)}%)",
            "Minimum Occupancy", f"{stats.get('min_occupancy_seats', 0)} seats ({stats.get('min_occupancy_pct', 0)}%)"
        ],
        [
            "Top Peak Hours", ", ".join([p["hour"] for p in stats.get("peak_hours", [])[:2]]) or "N/A",
            "Busiest Day", stats.get("busiest_days", [{}])[0].get("day", "N/A")
        ]
    ]

    t_kpi = Table(kpi_table_data, colWidths=[120, 140, 120, 140])
    t_kpi.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1769aa")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d0d8e8")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f8fe")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(t_kpi)
    elements.append(Spacer(1, 14))

    # Hourly Distribution Table
    elements.append(Paragraph("2. Hourly Seating Occupancy Breakdown (8:00 AM – 8:00 PM)", section_style))
    hourly = stats.get("hourly_chart", {})
    labels = hourly.get("labels", [])
    vals = hourly.get("data", [])

    # Format into 2 columns for neat display
    half = len(labels) // 2
    h_table_data = [["Hour Slot", "Avg %", "Est. Seats", "Hour Slot", "Avg %", "Est. Seats"]]
    for i in range(half):
        l1, v1 = labels[i], vals[i]
        s1 = int(round((v1 / 100.0) * cfg["total_capacity"]))
        j = i + half
        if j < len(labels):
            l2, v2 = labels[j], vals[j]
            s2 = int(round((v2 / 100.0) * cfg["total_capacity"]))
        else:
            l2, v2, s2 = "", "", ""
        h_table_data.append([l1, f"{v1}%", str(s1), l2, f"{v2}%", str(s2)])

    t_hourly = Table(h_table_data, colWidths=[85, 85, 90, 85, 85, 90])
    t_hourly.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#252840")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d0d8e8")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(t_hourly)
    elements.append(Spacer(1, 14))

    # Recommendations
    elements.append(Paragraph("3. Strategic Operational Recommendations", section_style))
    rec_table_data = [["Type", "Insight & Operational Action"]]
    for r in recs[:4]:
        rec_table_data.append([
            r.get("tag", "Insight"),
            f"<b>{r.get('title', '')}</b>: {r.get('description', '')}\n<i>Action:</i> {r.get('action', '')}"
        ])

    t_rec = Table(rec_table_data, colWidths=[110, 410])
    t_rec.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1769aa")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d0d8e8")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(t_rec)
    elements.append(Spacer(1, 14))

    # Recent Observations Table
    elements.append(Paragraph("4. Recent Periodic Headcount Observations Log", section_style))
    obs_table_data = [["Date", "Time", "Occupied", "Available", "Occupancy %", "Status", "Notes"]]
    for o in records[:12]:
        obs_table_data.append([
            o["recorded_date"],
            o["recorded_time"][:5],
            str(o["occupied_seats"]),
            str(o["available_seats"]),
            f"{o['occupancy_pct']}%",
            o["status"],
            (o.get("notes") or "")[:28]
        ])

    t_obs = Table(obs_table_data, colWidths=[65, 45, 55, 55, 65, 85, 150])
    t_obs.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#252840")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d0d8e8")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    elements.append(t_obs)
    elements.append(Spacer(1, 12))

    # Data Notice / Disclaimer
    disclaimer_text = (
        "<b>Notice on Data Collection &amp; Privacy:</b> This report reflects independent, periodic seating occupancy headcounts. "
        "No personally identifiable student records, entry swipes, or individual IDs are collected or stored. "
        "Baseline readings are statistically simulated for cold-start calibration until continuous periodic observations accumulate."
    )
    elements.append(Paragraph(disclaimer_text, ParagraphStyle(
        "Disclaimer",
        parent=styles["Normal"],
        fontSize=7,
        leading=10,
        textColor=colors.HexColor("#777799")
    )))

    doc.build(elements)
    return output_file

