"""
campus — Campus Space & Facility Management Module for Smart Resource Management System.

Components:
- Classroom Management (inventory, timetable import, slot availability, utilization analytics, conflict detection)
- Auditorium Management (inventory, event request workflow, admin approvals, calendar, readiness checklist)
- Facility Management (asset inventory, maintenance ticketing, technician assignment, status tracking, preventive maintenance)
- Shared Scheduling & Conflict Engine (maintenance downtime space blocking)
"""

from . import db
from . import classroom_service
from . import auditorium_service
from . import facility_service
from . import scheduling_service
from . import reports
from .routes import campus_bp
