def generate_seating(students, exams, rooms):

    # =========================================================
    # GROUP STUDENTS BY EXAM
    # =========================================================

    exam_students = {}

    for exam_id in exams:

        exam_students[exam_id] = []

    for student in students:

        exam_id = student.get("Exam ID")

        if not exam_id:
            exam_id = student.get("Exam")

        if not exam_id:

            raise ValueError(
                "Student data does not contain 'Exam ID'."
            )

        exam_id = str(exam_id).strip()

        if exam_id not in exam_students:

            raise ValueError(
                f"Exam ID '{exam_id}' exists in STUDENTS "
                f"but not in EXAMS sheet."
            )

        exam_students[exam_id].append(student)

    # =========================================================
    # REMOVE EMPTY EXAMS
    # =========================================================

    remaining = {

        exam_id: list(student_list)

        for exam_id, student_list
        in exam_students.items()

        if student_list
    }

    allocation = []

    # =========================================================
    # PROCESS ROOMS
    # =========================================================

    for room in rooms:

        if not remaining:
            break

        room_name = room["Room"]

        start_seat = int(
            room["StartSeat"]
        )

        end_seat = int(
            room["EndSeat"]
        )

        # =====================================================
        # ODD / EVEN SEATS
        # =====================================================

        odd_seats = [

            seat

            for seat in range(
                start_seat,
                end_seat + 1
            )

            if seat % 2 == 1
        ]

        even_seats = [

            seat

            for seat in range(
                start_seat,
                end_seat + 1
            )

            if seat % 2 == 0
        ]

        # =====================================================
        # SORT EXAMS BY REMAINING STUDENTS
        # =====================================================

        active_exams = sorted(

            remaining.keys(),

            key=lambda exam_id:
                len(remaining[exam_id]),

            reverse=True
        )

        # =====================================================
        # ODD SET
        # =====================================================

        odd_exam = active_exams[0]

        for seat in odd_seats:

            if not remaining[odd_exam]:
                break

            student = remaining[
                odd_exam
            ].pop(0)

            allocation.append({

                "Room": room_name,

                "Set": "Odd",

                "Seat No": seat,

                "Exam ID": odd_exam,

                "Course Code":
                    exams[odd_exam]["Course Code"],

                "Course Name":
                    exams[odd_exam]["Course Name"],

                "RollNo":
                    student["Enrolment No"],

                "Name":
                    student["Student Name"]
            })

        if not remaining[odd_exam]:

            del remaining[odd_exam]

        # =====================================================
        # EVEN SET
        # =====================================================

        if remaining:

            active_exams = sorted(

                remaining.keys(),

                key=lambda exam_id:
                    len(remaining[exam_id]),

                reverse=True
            )

            # This will always be a DIFFERENT exam because
            # odd_exam was removed if it became empty.
            #
            # If odd_exam still has students, another exam
            # will be selected because there are multiple exams.

            even_exam = active_exams[0]

            for seat in even_seats:

                if not remaining[even_exam]:
                    break

                student = remaining[
                    even_exam
                ].pop(0)

                allocation.append({

                    "Room": room_name,

                    "Set": "Even",

                    "Seat No": seat,

                    "Exam ID": even_exam,

                    "Course Code":
                        exams[even_exam]["Course Code"],

                    "Course Name":
                        exams[even_exam]["Course Name"],

                    "RollNo":
                        student["Enrolment No"],

                    "Name":
                        student["Student Name"]
                })

            if not remaining[even_exam]:

                del remaining[even_exam]

    # =========================================================
    # CHECK UNALLOCATED STUDENTS
    # =========================================================

    unallocated = []

    for exam_id, student_list in remaining.items():

        unallocated.extend(
            student_list
        )

    if unallocated:

        raise ValueError(

            f"Not enough seating capacity. "
            f"{len(unallocated)} students "
            f"could not be allocated."
        )

    return allocation