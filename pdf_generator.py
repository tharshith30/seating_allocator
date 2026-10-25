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