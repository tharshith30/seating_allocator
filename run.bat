@echo off
title ResourceHub — Seating & Lab Portal
cd /d "%~dp0"

echo ===================================================
echo   ResourceHub - Exam Seating & Lab Portal
echo ===================================================
echo.
echo Starting local server on http://127.0.0.1:5000 ...
echo (Press Ctrl+C to stop the server)
echo.

set "PY312=C:\Users\navya sri\AppData\Local\Programs\Python\Python312\python.exe"

if exist "%PY312%" (
    "%PY312%" app.py
) else (
    python app.py
)

pause


