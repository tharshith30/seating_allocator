import pandas as pd


def create_excel(
    allocation,
    output_file
):

    df = pd.DataFrame(
        allocation
    )

    with pd.ExcelWriter(
        output_file,
        engine="openpyxl"
    ) as writer:

        # =====================================================
        # MAIN ALLOTMENT
        # =====================================================

        df.to_excel(

            writer,

            sheet_name="Seating Allotment",

            index=False
        )

        # =====================================================
        # ROOM SUMMARY
        # =====================================================

        room_summary = (

            df.groupby(

                [
                    "Room",
                    "Set",
                    "Exam ID",
                    "Course Code",
                    "Course Name"
                ]

            )

            .size()

            .reset_index(

                name="Students"
            )
        )

        room_summary.to_excel(

            writer,

            sheet_name="Room Summary",

            index=False
        )

        # =====================================================
        # EXAM SUMMARY
        # =====================================================

        exam_summary = (

            df.groupby(

                [
                    "Exam ID",
                    "Course Code",
                    "Course Name"
                ]

            )

            .size()

            .reset_index(

                name="Allocated Students"
            )
        )

        exam_summary.to_excel(

            writer,

            sheet_name="Exam Summary",

            index=False
        )

        # =====================================================
        # ROOM-WISE SHEETS
        # =====================================================

        for room in df["Room"].unique():

            room_df = df[
                df["Room"] == room
            ]

            sheet_name = str(
                room
            )[:31]

            room_df.to_excel(

                writer,

                sheet_name=sheet_name,

                index=False
            )

    print(
        f"Excel created: {output_file}"
    )