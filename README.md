# 🎓 ResourceHub — Smart Resource Management System

> A unified, intelligent campus resource management portal integrating automated conflict-free exam seating distribution, computer lab utilization analytics & slot booking, and smart library utilization with machine learning forecasting.

[![Python Version](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/Framework-Flask%203.x-lightgrey.svg)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](#license)

---

## 📌 Table of Contents
- [Overview](#-overview)
- [Key Modules & Features](#-key-modules--features)
  - [1. 🪑 Exam Seating Allotment](#1--exam-seating-allotment)
  - [2. 📊 Laboratory Utilization & Booking](#2--laboratory-utilization--booking)
  - [3. 📚 Smart Library Utilization & Analytics](#3--smart-library-utilization--analytics)
- [Project Architecture](#-project-architecture)
- [Input File Specifications](#-input-file-specifications)
- [Installation & Quickstart](#-installation--quickstart)
  - [One-Click Start (Windows)](#one-click-start-windows)
  - [Manual Terminal Start](#manual-terminal-start)
- [API Reference](#-api-reference)
- [Configuration & Security](#-configuration--security)
- [Git Branching](#-git-branching)

---

## 🌟 Overview

**ResourceHub** centralizes institutional academic infrastructure management across three integrated modules within a single responsive web interface:

1. **Exam Seating Allotment**: Conflict-free student seat distribution across **34 examination halls (1,300+ seats)** preventing adjacent same-subject seating.
2. **Laboratory Utilization**: Live slot occupancy tracking, weekly heatmaps, smart auto-allocation, PIN-protected maintenance overrides, and dynamic lab registration across campus computer facilities.
3. **Smart Library Utilization & Analytics**: Independent seating occupancy monitoring, crowd level categorization, statistical usage analytics, machine learning predictive forecasting, and administrative report generation.
4. **Campus Space & Facility Management**: Integrated Classroom inventory & timetable schedules, Auditorium event requests & admin approvals with readiness checklists, Facility asset inventory, maintenance ticketing with automated downtime space blocking, and preventive maintenance reminders.

---

## 🚀 Key Modules & Features

### 1. 🪑 Exam Seating Allotment
* **Anti-Malpractice Interleaving Engine**: Alternates exam codes row-by-row and seat-by-seat to eliminate adjacent same-subject seating in all directions.
* **Capacity-First Optimization**: Intelligently packs high-capacity exam halls first before filling auxiliary rooms.
* **Dual Export Capabilities**:
  * 📊 **Excel Spreadsheet (`.xlsx`)**: Comprehensive allotment roster sorted by hall and roll number.
  * 📄 **Printable PDF Notice (`.pdf`)**: Formatted door charts ready for immediate posting outside examination halls.
* **Modern Web Interface**: Drag-and-drop file upload with live AJAX generation progress and inline download buttons without full-page reloads.

### 2. 📊 Laboratory Utilization & Booking
* **Interactive Weekly Heatmaps**: Visualizes slot occupancy (S1 to S9) across Monday through Friday for all laboratories.
* **Lab KPI Overview Cards**: Real-time metrics on utilization percentage, visual progress fill bars, booked vs. free slots, average seat fill, over-capacity warnings, and status badges (`Healthy`, `Underused`, `Overloaded`).
* **🔍 Find a Free Lab**: Real-time lookup tool finding completely free laboratories for any specified day and slot.
* **📅 Lab Slot Booking**: Student and faculty slot booking with conflict detection and automated validation.
* **➕ Dynamic Lab Registration**: Instantly registers new lab facilities directly through the UI, persisting to `labs.json` without server restarts.

### 3. 📚 Smart Library Utilization & Analytics
* **Independent Occupancy Monitoring**:
  * Standalone observation recording mechanism operating independently of existing entrance turnstiles.
  * Captures occupied seat headcounts, available capacity, and occupancy percentage.
  * Categorizes crowd levels: **Low occupancy** (<35%), **Moderate occupancy** (35–70%), **High occupancy** (70–90%), and **Full capacity** (≥90%).
  * Automated **Stale Data Warning** if the last recorded observation is older than 2 hours.
  * **Strict Data Privacy**: Aggregates seating counts only; **zero student IDs, roll numbers, or personal names** are collected or stored.
* **Usage Pattern Analytics**:
  * Hourly occupancy breakdown (8:00 AM – 8:00 PM).
  * Day-of-week demand trends and busiest day identification.
  * Interactive Day × Hour peak heatmap matrix.
  * Configurable date filters: *Today*, *Last 7 Days*, *Last 30 Days*, and *All Time*.
* **Machine Learning Predictive Analytics**:
  * Regression model (Random Forest / Weighted Pattern Engine) forecasting seating occupancy for upcoming operating hours.
  * Rigorous 80/20 train/test evaluation reporting **Mean Absolute Error (MAE)** and **Root Mean Squared Error (RMSE)**.
  * Identifies projected rush hours and upcoming crowd surges.
  * Displays provisional status notices when training points are under calibration threshold.
* **Smart Resource Recommendations**:
  * Actionable administrative insights distinguishing between `Data-Based Insights`, `Statistical Estimates`, and `ML Predictions`.
  * Flags recurring peak-hour saturation, identifies optimal maintenance windows during quiet hours, and provides seating capacity advisories.
* **Dual Role Views**:
  * **Student Live View**: Simplified crowd indicator, available seats counter, "Last updated" indicator, and best visiting time suggestions. No seat booking or seat ownership.
  * **Admin Occupancy Recorder**: PIN-protected observation recording, capacity configuration, and record correction.
* **Administrative Reports**:
  * 📊 **Excel Workbook (`.xlsx`)**: Multi-sheet export including Executive Summary, Hourly Distributions, Day-of-Week Trends, Observation Logs, and Recommendations.
  * 📄 **Executive PDF Document (`.pdf`)**: Print-ready report with institutional headings, metric summaries, and analytical tables.

### 4. 🏛️ Campus Space & Facility Management
* **Classroom Management**:
  * **Classroom Inventory**: Complete record of 34 classrooms with bench count, capacity, room type, projector, audio, and AC flags.
  * **Excel Timetable Import**: Parses semester timetables mapping academic lecture slots (1 to 9, Mon–Fri) to classrooms.
  * **Timetable-Based Availability**: Instant search finding completely free classrooms for specified dates, slots, and capacities.
  * **Classroom Utilization Analytics**: Tracks scheduled lecture hours, free hours, utilization percentages, and room rankings.
  * **Scheduling Conflict Detection**: Validates ad-hoc bookings against academic timetables, prior reservations, and active maintenance downtime blocks.
* **Auditorium Management**:
  * **Auditorium Inventory**: Tracks 4 campus venues (Grand Auditorium, Mini Auditorium, Seminar Hall, Open Air Theatre) with capacities up to 1,400 seats, stage dimensions, and AV specs.
  * **Event Scheduling Requests**: Department staff event submission with attendee capacity verification and automated readiness checklists.
  * **Admin Approval Workflow**: Multi-state approval cycle (`pending` -> `approved` / `rejected` / `cancelled`) with administrative remarks.
  * **Event Readiness Checklist**: Interactive verification covering AV systems, stage lighting, HVAC pre-cooling, seating hygiene, power backup, and hospitality.
  * **Event Utilization Analytics**: Tracks hosted events, attendee reach, and department participation.
* **Facility Management**:
  * **Asset Inventory**: Infrastructure equipment (Projectors, ACs, Sound Mixers, Generators, Pumps) linked to campus spaces.
  * **Maintenance Work Orders**: Ticket submission with categories (IT/AV, Electrical, HVAC, Civil, Plumbing) and priority levels (Low, Medium, High, Critical).
  * **Automated Downtime Space Blocking**: Critical and High priority maintenance issues automatically lock the room or auditorium, instantly preventing conflicting reservations.
  * **Dynamic Space Unblocking**: Resolving or closing the ticket automatically restores the space to `available` status.
  * **Preventive Maintenance Reminders**: Recurring inspection schedules with overdue alerts.
* **Role-Based Access Control (RBAC)**:
  * 👑 **Admin** (`PIN: 1234`): Approvals, staff assignments, inventory updates, timetable imports.
  * 👔 **Department Staff** (`PIN: 2345`): Room reservations, event booking requests, maintenance reporting.
  * 🛠️ **Maintenance Staff** (`PIN: 3456`): Work order tracking, status updates, preventive maintenance completion.

---

## 📂 Project Architecture

```
seating_allocator/
├── app.py                      # Main Flask application & Blueprint registration
├── seating_engine.py           # Core exam seat allocation algorithm (interleaving)
├── room_loader.py              # Exam hall capacity loader (OpenPyXL)
├── excel_generator.py          # Excel generator for seating rosters
├── pdf_generator.py            # ReportLab PDF generator for seating and lab reports
├── run.bat                     # Windows one-click launcher script
│
├── campus/                     # Module 4: Campus Space & Facility Management
│   ├── db.py                   # SQLite connection, schema creation & seed loader
│   ├── classroom_service.py    # Classroom inventory, timetable parser, booking & analytics
│   ├── auditorium_service.py   # Auditorium inventory, event workflow & checklists
│   ├── facility_service.py     # Asset inventory, maintenance tickets & PM scheduler
│   ├── scheduling_service.py   # Shared conflict detection & downtime space blocking
│   ├── reports.py              # Multi-tab Excel and ReportLab PDF generator
│   └── routes.py               # Flask Blueprint exposing all REST APIs & views
│
├── lab/                        # Module 2: Laboratory Utilization
│   ├── routes.py               # REST API endpoints & lab routes
│   ├── booking.py              # SQLite status manager & slot reservation logic
│   ├── parser.py               # Merged-cell aware timetable parser (OpenPyXL)
│   ├── allocator.py            # Smart auto-allocator recommendation engine
│   └── analytics.py            # Lab utilization metrics & load calculations
│
├── library/                    # Module 3: Smart Library Utilization & Analytics
│   ├── routes.py               # Flask Blueprint for library endpoints
│   ├── occupancy.py            # SQLite observation recorder, capacity config, crowd levels
│   ├── analytics.py            # Hourly distribution, daily trend, heatmap matrix
│   ├── predictor.py            # ML regression model, train/test split, MAE evaluation
│   ├── recommendations.py      # Intelligent operational advice & capacity alerts
│   └── reports.py              # Excel (.xlsx) and PDF (.pdf) utilization report generation
│
├── static/                     # Frontend Assets (Vanilla JS & CSS)
│   ├── campus.js               # Campus Space & Facility client-side controller
│   ├── library.js              # Library live polling, charts & prediction controller
│   ├── lab.js                  # Lab heatmap, booking & slot search controller
│   └── style.css               # Unified styling for all modules
│
├── templates/                  # Jinja2 HTML Templates
│   ├── index.html              # Unified primary portal dashboard
│   ├── campus/
│   │   └── dashboard.html      # Campus Space & Facility Management portal
│   └── library/
│       ├── dashboard.html      # Standalone Library analytics dashboard
│       ├── student.html        # Simplified student crowd level portal
│       └── admin.html          # Staff occupancy logger & capacity settings
│
├── data/                       # Datasets & Persistent Storage
│   ├── campus_facility.db      # SQLite database for classrooms, auditoriums & facilities
│   ├── lab_bookings.db         # SQLite database for computer lab slot bookings
│   ├── library.db              # SQLite database for library headcount observations
│   ├── labs.json               # JSON configuration for computer laboratories
│   ├── roomCapacity_FST.xlsx   # Classroom capacities (34 halls)
│   └── timetable.xlsx          # Semester timetable workbook
```
│   ├── roomCapacity_FST.xlsx   # 34 examination room capacities & seat ranges
│   ├── timetable.xlsx          # Weekly master timetable across academic departments
│   ├── labs.json               # Registered computer lab configurations & capacities
│   ├── extra_sessions.csv      # Supplemental lab sessions not in timetable
│   ├── lab_bookings.db         # SQLite database storing lab bookings & overrides
│   └── library.db              # SQLite database storing library observations & config
│
├── static/                     # Frontend Assets
│   ├── style.css               # Shared CSS design system (Light/Dark themes)
│   ├── lab.js                  # Lab controller (heatmap, booking grid, auto-allocator)
│   └── library.js              # Library controller (live crowd meter, charts, ML forecasts)
│
└── templates/                  # Jinja2 Single-Page Dashboard
    ├── index.html              # Unified Dashboard (Seating + Labs + Library)
    ├── lab_dashboard.html      # Standalone lab analytics template
    └── lab_booking.html        # Standalone lab booking template
```

---

## ⚡ Installation & Quickstart

### Prerequisites
* **Python 3.12+** installed on your system.

### Install Dependencies
```bash
pip install flask pandas openpyxl reportlab pillow
```
*(Optional for ML component: `pip install scikit-learn` — system includes an automated fallback regression engine if omitted).*

### Running the Application

#### One-Click Start (Windows)
Double-click **`run.bat`** in the project directory, or execute in CMD:
```cmd
cd C:\sp\sp\seating_allocator
run.bat
```

#### Manual Terminal Start
In **PowerShell**:
```powershell
cd C:\sp\sp\seating_allocator
& "C:\Users\navya sri\AppData\Local\Programs\Python\Python312\python.exe" app.py
```

In **Command Prompt (CMD)**:
```cmd
cd /d C:\sp\sp\seating_allocator
"C:\Users\navya sri\AppData\Local\Programs\Python\Python312\python.exe" app.py
```

Open your browser at:
👉 **[http://127.0.0.1:5000](http://127.0.0.1:5000)**

---

## 🔗 Deep Links & Navigation

| Module / View | Direct URL |
| :--- | :--- |
| **Unified Portal (Default)** | [http://127.0.0.1:5000/](http://127.0.0.1:5000/) |
| **Exam Seating View** | [http://127.0.0.1:5000/#seating](http://127.0.0.1:5000/#seating) |
| **Lab Analytics View** | [http://127.0.0.1:5000/#analytics](http://127.0.0.1:5000/#analytics) |
| **Lab Booking View** | [http://127.0.0.1:5000/#booking](http://127.0.0.1:5000/#booking) |
| **Library Analytics View** | [http://127.0.0.1:5000/#library](http://127.0.0.1:5000/#library) |

---

## 🔌 API Reference

### Library Module Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/library/status` | Returns latest occupancy reading, available seats, crowd level, and staleness details |
| `POST` | `/api/library/occupancy` | Record a periodic headcount observation (requires admin PIN) |
| `PUT` | `/api/library/occupancy/<id>` | Correct an inaccurate observation record (requires admin PIN) |
| `DELETE` | `/api/library/occupancy/<id>` | Delete an observation record (requires admin PIN) |
| `GET` | `/api/library/records` | Retrieve historical observation logs with date filtering (`today`, `7d`, `30d`, `all`) |
| `GET` | `/api/library/analytics` | Returns computed KPIs, hourly distributions, day-of-week trends, and peak heatmap |
| `GET` | `/api/library/predictions` | Generates ML forward forecast for upcoming hours with MAE evaluation metrics |
| `GET` | `/api/library/recommendations` | Returns synthesized data-driven administrative recommendations |
| `POST` | `/api/library/config` | Update library seating capacity and crowd threshold percentages (requires admin PIN) |
| `GET` | `/download/library-report/excel` | Export complete library analytics workbook (`.xlsx`) |
| `GET` | `/download/library-report/pdf` | Export executive PDF utilization report (`.pdf`) |

### Core & Lab Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/generate` | Generate conflict-free exam seating allocation from uploaded Excel workbook |
| `GET` | `/download/excel` | Download generated exam seating spreadsheet |
| `GET` | `/download/pdf` | Download generated exam seating printable PDF |
| `GET` | `/api/labs` | Returns list of registered computer labs and capacities |
| `POST` | `/api/labs/add` | Dynamically register a new computer lab |
| `GET` | `/api/week` | Returns 5×9 slot state grid for a specified lab and week |
| `POST` | `/api/book` | Reserve empty laboratory slot(s) |
| `GET` | `/download/lab-report` | Download computer lab utilization report PDF |

---

## 🔐 Configuration & Security

- **In-Charge Administrator PIN**: Administrative mutations (adding labs, recording library headcounts, updating capacities, maintenance overrides) require an authorization PIN.
  - Set via environment variable: `INCHARGE_PIN=your_custom_pin`
  - Default development fallback: `1234`
- **Data Privacy**: The library module does not access, collect, or store student IDs, names, or turnstile entry records.
- **Concurrency & Reliability**: SQLite databases run with Write-Ahead Logging (`PRAGMA journal_mode=WAL`) for high concurrency and resilience.

---

## 🌿 Git Branching

All current features, unified dashboard enhancements, and the new Smart Library Utilization module are maintained on branch:
```bash
git checkout navya
```
Remote repository: `https://github.com/tharshith30/seating_allocator.git`

---

## 📄 License
This project is developed for institutional academic scheduling and resource management. Released under the MIT License.
