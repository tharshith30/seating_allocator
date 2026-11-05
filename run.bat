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
echo     - Role Selection Portal : http://127.0.0.1:5000/
echo     - Student Portal (View) : http://127.0.0.1:5000/student
echo     - Faculty Portal        : http://127.0.0.1:5000/faculty
echo     - Administration Console: http://127.0.0.1:5000/admin
echo     - Legacy All-in-One     : http://127.0.0.1:5000/legacy
echo.
echo Starting local Flask server on http://127.0.0.1:5000 ...
echo (Press Ctrl+C to stop the server at any time)
echo =====================================================================
echo.

set "PYTHONPATH=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages;%PYTHONPATH%"
set "PY312=C:\Users\navya sri\AppData\Local\Programs\Python\Python312\python.exe"

if exist "%PY312%" (
    "%PY312%" app.py
) else (
    python app.py
)

pause
