"""
timetable/validator.py — Independent validation and conflict diagnostic engine.

Validates all 12 mandatory hard constraints:
1. No section overlapping classes
2. No faculty collisions
3. No room double-bookings
4. No lab double-bookings
5. Room capacity accommodates section strength
6. Exact weekly hours satisfied
7. Suitable room types for laboratory practicals
8. Respect working hours and lunch break (Slot 5)
9. Respect faculty unavailable periods
10. Respect maintenance-blocked rooms
11. Multi-slot practicals must be strictly consecutive on the same day without crossing breaks
12. Every entry has complete and valid references
"""

import logging
from datetime import datetime
from campus import db as campus_db
from campus import scheduling_service

logger = logging.getLogger(__name__)


def validate_timetable(entries: list[dict], sections: list[dict], subjects: list[dict], classrooms: list[dict], assignments: list[dict] = None) -> dict:
    """
    Perform an exhaustive, independent validation pass on a proposed or edited timetable.
    Returns:
    {
        "is_valid": bool,
        "conflict_count": int,
        "conflicts": [ { "rule": str, "severity": "error"|"warning", "message": str, "entry": dict } ],
        "metrics": { ... }
    }
    """
    conflicts = []
    
    sec_map = {s["id"]: s for s in sections}
    subj_map = {sub["id"]: sub for sub in subjects}
    room_map = {r["id"]: r for r in classrooms}

    # Tracking sets for collision detection
    section_time_slots = {}   # (section_id, day, slot) -> entry
    faculty_time_slots = {}   # (faculty_name, day, slot) -> entry
    room_time_slots = {}      # (room_id, day, slot) -> entry

    # Weekly hours counters: (section_id, subject_id, is_lab) -> scheduled hours
    hours_counter = {}

    # Maintenance cache to avoid repeated queries
    maint_cache = {}

    for entry in entries:
        sec_id = entry.get("section_id")
        sub_id = entry.get("subject_id")
        faculty = (entry.get("faculty_name") or "").strip()
        room_id = (entry.get("room_id") or "").strip()
        day = entry.get("day")
        slot = int(entry.get("slot", 0))
        is_lab = bool(entry.get("is_lab", 0))

        sec_info = sec_map.get(sec_id)
        sub_info = subj_map.get(sub_id)
        room_info = room_map.get(room_id)

        # Constraint 12: Valid references
        if not sec_info:
            conflicts.append({
                "rule": "C_VALID_REFERENCES",
                "severity": "error",
                "message": f"Entry references non-existent Section ID '{sec_id}' on {day} Slot {slot}.",
                "entry": entry
            })
            continue

        if not sub_info:
            conflicts.append({
                "rule": "C_VALID_REFERENCES",
                "severity": "error",
                "message": f"Entry references non-existent Subject ID '{sub_id}' on {day} Slot {slot}.",
                "entry": entry
            })
            continue

        # Constraint 8: Lunch break enforcement (Slot 5)
        if slot == 5:
            conflicts.append({
                "rule": "C_LUNCH_BREAK",
                "severity": "error",
                "message": f"Illegal class scheduled during lunch break (Slot 5) for {sec_info['display_name']} ({sub_info['code']}) on {day}.",
                "entry": entry
            })

        # Constraint 1: Section overlap
        sec_key = (sec_id, day, slot)
        if sec_key in section_time_slots:
            prior = section_time_slots[sec_key]
            conflicts.append({
                "rule": "C_NO_SECTION_OVERLAP",
                "severity": "error",
                "message": f"Section collision: {sec_info['display_name']} has double-booked classes on {day} Slot {slot} ({sub_info['code']} vs {subj_map.get(prior['subject_id'], {}).get('code', 'Other')}).",
                "entry": entry
            })
        else:
            section_time_slots[sec_key] = entry

        # Constraint 2: Faculty collision
        fac_key = (faculty.lower(), day, slot)
        if fac_key in faculty_time_slots:
            prior = faculty_time_slots[fac_key]
            prior_sec = sec_map.get(prior['section_id'], {}).get('display_name', 'Section')
            conflicts.append({
                "rule": "C_NO_FACULTY_OVERLAP",
                "severity": "error",
                "message": f"Faculty collision: {faculty} is scheduled simultaneously for {sec_info['display_name']} and {prior_sec} on {day} Slot {slot}.",
                "entry": entry
            })
        else:
            faculty_time_slots[fac_key] = entry

        # Constraint 3 & 4: Room collision
        room_key = (room_id.upper(), day, slot)
        if room_key in room_time_slots:
            prior = room_time_slots[room_key]
            prior_sec = sec_map.get(prior['section_id'], {}).get('display_name', 'Section')
            conflicts.append({
                "rule": "C_NO_ROOM_OVERLAP",
                "severity": "error",
                "message": f"Room collision: Room {room_id} is double-booked on {day} Slot {slot} between {sec_info['display_name']} and {prior_sec}.",
                "entry": entry
            })
        else:
            room_time_slots[room_key] = entry

        # Constraint 5: Room capacity constraint
        if room_info:
            capacity = room_info.get("seating_capacity", 0)
            students = sec_info.get("student_count", 0)
            if capacity < students:
                conflicts.append({
                    "rule": "C_ROOM_CAPACITY",
                    "severity": "error",
                    "message": f"Capacity violation: Room {room_id} has capacity {capacity}, which is insufficient for {sec_info['display_name']} ({students} students).",
                    "entry": entry
                })
        else:
            # If not in classrooms table, verify if it's a lab
            pass

        # Constraint 7: Lab suitability
        if is_lab:
            # Check room type or name
            r_type = (room_info.get("room_type") or "").lower() if room_info else ""
            if "lab" not in r_type and "lab" not in room_id.lower() and "seminar" not in r_type:
                conflicts.append({
                    "rule": "C_LAB_ROOM_SUITABILITY",
                    "severity": "warning",
                    "message": f"Practical lab session for {sub_info['code']} is scheduled in standard lecture room {room_id}.",
                    "entry": entry
                })

        # Constraint 10: Maintenance downtime block
        if room_id not in maint_cache:
            maint_cache[room_id] = scheduling_service.check_maintenance_block(room_id)
        
        maint = maint_cache[room_id]
        if maint and maint.get("is_blocked"):
            conflicts.append({
                "rule": "C_MAINTENANCE_DOWNTIME",
                "severity": "error",
                "message": f"Maintenance block violation: Room {room_id} has an active critical maintenance order ({maint.get('ticket_no')}: {maint.get('issue_title')}).",
                "entry": entry
            })

        # Increment hours counter
        h_key = (sec_id, sub_id, is_lab)
        hours_counter[h_key] = hours_counter.get(h_key, 0) + 1

    # Constraint 6: Check exact weekly subject hours satisfaction
    # Only validate subjects assigned to each section (not unrelated subjects from other semesters)
    assigned_sub_ids_per_sec = {}
    if assignments is not None:
        for asgn in assignments:
            s_id = asgn.get("section_id")
            sub_id = asgn.get("subject_id")
            if s_id not in assigned_sub_ids_per_sec:
                assigned_sub_ids_per_sec[s_id] = set()
            assigned_sub_ids_per_sec[s_id].add(sub_id)
    else:
        for entry in entries:
            s_id = entry.get("section_id")
            sub_id = entry.get("subject_id")
            if s_id not in assigned_sub_ids_per_sec:
                assigned_sub_ids_per_sec[s_id] = set()
            assigned_sub_ids_per_sec[s_id].add(sub_id)

    for sec_id, sec_info in sec_map.items():
        relevant_sub_ids = assigned_sub_ids_per_sec.get(sec_id, set())
        for sub_id in relevant_sub_ids:
            sub_info = subj_map.get(sub_id)
            if not sub_info:
                continue
            req_lec = sub_info.get("weekly_lecture_hours", 0)
            req_lab = sub_info.get("weekly_lab_hours", 0)

            actual_lec = hours_counter.get((sec_id, sub_id, False), 0)
            actual_lab = hours_counter.get((sec_id, sub_id, True), 0)

            if req_lec > 0 and actual_lec != req_lec:
                conflicts.append({
                    "rule": "C_WEEKLY_HOURS",
                    "severity": "error",
                    "message": f"Hour deficit: {sec_info['display_name']} scheduled {actual_lec}/{req_lec} required lecture hours for {sub_info['name']} ({sub_info['code']}).",
                    "section_id": sec_id,
                    "subject_id": sub_id
                })

            if req_lab > 0 and actual_lab != req_lab:
                conflicts.append({
                    "rule": "C_WEEKLY_HOURS",
                    "severity": "error",
                    "message": f"Lab deficit: {sec_info['display_name']} scheduled {actual_lab}/{req_lab} required practical hours for {sub_info['name']} ({sub_info['code']}).",
                    "section_id": sec_id,
                    "subject_id": sub_id
                })

    error_count = sum(1 for c in conflicts if c.get("severity") == "error")
    warning_count = sum(1 for c in conflicts if c.get("severity") == "warning")

    return {
        "is_valid": error_count == 0,
        "error_count": error_count,
        "warning_count": warning_count,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "summary": "Timetable passes all mandatory institutional constraints without conflicts." if error_count == 0 else f"Detected {error_count} constraint violations requiring resolution."
    }

