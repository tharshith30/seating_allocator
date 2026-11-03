@echo off
title ResourceHub — Smart Resource Management System
cd /d "%~dp0"

echo =====================================================================
echo   🏛  ResourceHub — Smart Resource Management System
echo =====================================================================
echo.
echo   Active Modules:
echo     1. 🎓 Exam Seating Allotment
echo     2. 🧪 Laboratory Utilization & Booking
echo     3. 📚 Smart Library Utilization & Analytics
echo     4. 🏛️ Campus Space & Facility Management
echo        - Classroom Inventory, Timetables & Analytics
echo        - Auditorium Event Scheduling & Readiness Checklists
echo        - Facility Asset Tracking, Downtime Locks & PM Reminders
echo.
echo   Portals available once server starts:
echo     - Unified Dashboard : http://127.0.0.1:5000/
echo     - Campus Facilities : http://127.0.0.1:5000/campus
echo     - Classrooms Portal : http://127.0.0.1:5000/classrooms
echo     - Auditorium Portal : http://127.0.0.1:5000/auditoriums
echo     - Facility Portal   : http://127.0.0.1:5000/facilities
echo     - Library Analytics : http://127.0.0.1:5000/library
echo.
echo Starting local Flask server on http://127.0.0.1:5000 ...
echo (Press Ctrl+C to stop the server at any time)
echo =====================================================================
echo.

set "PY312=C:\Users\navya sri\AppData\Local\Programs\Python\Python312\python.exe"

if exist "%PY312%" (
    "%PY312%" app.py
) else (
    python app.py
)

pause
