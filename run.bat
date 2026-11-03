@echo off
title ResourceHub — Smart Resource Management System
cd /d "%~dp0"

echo =====================================================================
echo   🏛  ResourceHub — Smart Resource Management System
echo =====================================================================
echo.
echo   Active Modules:
echo     1. 🎓 Exam Seating Allotment
echo     2. 🧪 Laboratory Utilization
echo     3. 📚 Smart Library Utilization & Analytics
echo.
echo   Portals available once server starts:
echo     - Unified Dashboard : http://127.0.0.1:5000/
echo     - Library Analytics : http://127.0.0.1:5000/library
echo     - Student Live View : http://127.0.0.1:5000/library/student
echo     - Staff Admin Panel : http://127.0.0.1:5000/library/admin
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
