"""
lab/parser.py — Merged-cell-aware timetable parser for lab sessions.

Design decisions:
- We use openpyxl (not pandas) because pandas cannot represent merged cells;
  a merged cell's value lives only in its top-left cell, and we need to know
  which slots are covered by the merge to determine slot numbers.
- Each year sheet has two timetable blocks side by side. We describe each block
  as (col_offset, slot_col_start) so the same parse_block() function handles
  all of them.
- The per-lab timetable blocks in Second_Year (rows ~120+) list sessions by lab.
  We parse them identically and union the results with the section-sheet sessions.
  Duplicates are removed by (lab, day, slot) key before returning.
- Strengths come from the Room plan sheet. Final-year strengths are missing there
  (use DEFAULT_STRENGTH=70).
- _a_ or _b_ in a session name means half-section; effective strength = ceil(strength / HALF_SECTION_DIVISOR).
- extra_sessions.csv lets operators add rows for labs not in the timetable.
"""

import re
import csv
import math
import json
import os
import sys

_cached_site = os.path.expanduser(r"~\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages")
if os.path.isdir(_cached_site) and _cached_site not in sys.path:
    sys.path.insert(0, _cached_site)

import openpyxl

# ─── Configurable constants ────────────────────────────────────────────────────

# Slot numbers (1-indexed). S5 is always lunch.
LUNCH_SLOT = 5
TOTAL_SLOTS = 9
TEACHING_SLOTS = [s for s in range(1, TOTAL_SLOTS + 1) if s != LUNCH_SLOT]  # 8 slots

# When a session name contains _a_ or _b_, treat the section as split in half.
HALF_SECTION_DIVISOR = 2

# Default strength when the room plan has no entry for a section.
DEFAULT_STRENGTH = 70

# Days in order as they appear in timetable rows.
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]

# Regex to extract lab ID (L1–L4) from the end of a merged-cell value.
# Matches: <-CN-A-L2>, <--DL-LAB-A-L4->, PS-III-A-L3, CN_H-L1, <ML-J-L4>
LAB_TAG_RE = re.compile(r"L([1-4])\s*[->\s]*$", re.IGNORECASE)

# Also match tags that have the lab in the middle, e.g. "DBMS-F_b_L2"
LAB_TAG_ANY_RE = re.compile(r"[_\-]L([1-4])(?:[_\-]|$)", re.IGNORECASE)

# Detect half-section flag
HALF_SECTION_RE = re.compile(r"[_\-](a|b)[_\-]", re.IGNORECASE)

# Section name extractor from header like "Section:  C (R-216)"
SECTION_HEADER_RE = re.compile(r"Section\s*:\s*(.+)", re.IGNORECASE)

# Strength from room plan: "III-A(75)" → section=A, strength=75
ROOM_PLAN_RE = re.compile(r"([IVX]+(?:-BCA|-BSC\S*)?)-([A-Z]+)\s*\((\d+)\)", re.IGNORECASE)

# ─── Helper functions ──────────────────────────────────────────────────────────

def _extract_lab_tag(text: str) -> str | None:
    """Return 'L1'–'L4' from a merged-cell value, or None if not a lab session."""
    if not text:
        return None
    text = text.strip()
    # Try end-of-string match first (most reliable)
    m = LAB_TAG_RE.search(text)
    if m:
        return f"L{m.group(1)}"
    # Fallback: tag anywhere
    m = LAB_TAG_ANY_RE.search(text)
    if m:
        return f"L{m.group(1)}"
    return None


def _is_half_section(text: str) -> bool:
    """Return True if the session name contains _a_ or _b_ (half-section flag)."""
    return bool(HALF_SECTION_RE.search(text))


def _col_to_slot(col: int, block_start_col: int) -> int:
    """Convert a 1-indexed openpyxl column to a slot number (1–9)."""
    return col - block_start_col + 1


def _load_strengths(ws_room_plan) -> dict[str, int]:
    """
    Parse the Room plan sheet's D column to build section → strength map.
    E.g. "III-A(75)" → {"III-A": 75, "A": 75}.
    We store both the full key and just the section letter for easier lookup.
    """
    strengths = {}
    for row in ws_room_plan.iter_rows(values_only=True):
        for cell_val in row:
            if not cell_val:
                continue
            text = str(cell_val).strip()
            m = ROOM_PLAN_RE.match(text)
            if m:
                year_prefix = m.group(1)
                section = m.group(2).upper()
                strength = int(m.group(3))
                strengths[f"{year_prefix}-{section}"] = strength
                # Also store by bare section letter for simpler lookup
                strengths[section] = strength
    return strengths


def _parse_block(ws, block_start_col: int, header_rows: list[int],
                 year: str, strengths: dict) -> list[dict]:
    """
    Parse one timetable block (left or right side of a sheet).

    A block is a set of rows structured as:
      [section header row]
      [slot header row: S1 S2 S3 S4 S5 S6 S7 S8 S9]
      [Mon row]
      [Tue row]
      ...
      [Fri row]

    We find section header rows by scanning for "Section:" in the anchor column.
    For each section block we then look at the day rows for merged cells.

    Args:
        ws:              openpyxl worksheet
        block_start_col: 1-indexed column of S1 for this block (e.g. col B=2)
        header_rows:     list of row numbers that are section headers
        year:            "Second_Year" / "Third_Year" / "Final_year"
        strengths:       section → strength dict from room plan
    """
    sessions = []

    # Build a lookup: (row, col) → merged-range value for this worksheet
    # openpyxl merged cells: the top-left cell holds the value; all others are MergedCell.
    # We pre-build a map so we can resolve quickly.
    merged_map: dict[tuple[int, int], str] = {}
    for rng in ws.merged_cells.ranges:
        top_left = ws.cell(rng.min_row, rng.min_col)
        if top_left.value:
            val = str(top_left.value).strip()
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    merged_map[(r, c)] = (val, rng.min_col, rng.max_col, rng.min_row, rng.max_row)

    # Scan for section-header rows in the anchor column
    # The anchor column for the block header in Second_Year left block is col A (1),
    # but the slot headers start at col B (2). We scan the entire row for "Section:".
    for row_idx in range(1, ws.max_row + 1):
        # Look for section header in this row
        section_name = None
        for col_idx in range(1, min(ws.max_column + 1, 30)):
            cell = ws.cell(row_idx, col_idx)
            val = cell.value
            if val and "Section:" in str(val):
                m = SECTION_HEADER_RE.search(str(val))
                if m:
                    section_name = m.group(1).strip()
                    break

        if section_name is None:
            continue

        # Skip per-lab blocks (they have names like "LIVIA(L1)", "LART(L2)" etc.)
        # Those are handled separately in parse_per_lab_blocks().
        if re.search(r"L[1-4]\b", section_name):
            continue
        # Skip BCA/BSc/DF/numeric-only section names that are not BTech sections
        # (they are "other" labs like 213, 104, DF, BCA-A(AIDS) etc.)
        # We only skip if they clearly are not section timetables
        if re.match(r"^\d+$", section_name.strip()):
            continue

        # Expect: slot header row = row_idx + 1, day rows = row_idx+2 .. row_idx+6
        slot_header_row = row_idx + 1
        day_start_row = row_idx + 2

        # Extract section letter from name like "C (R-216)" → "C"
        sec_letter_m = re.match(r"([A-Z](?:-[A-Z]+)?)", section_name)
        sec_letter = sec_letter_m.group(1) if sec_letter_m else section_name

        # Look up strength; try several forms
        strength = (strengths.get(f"II-{sec_letter}")
                    or strengths.get(f"III-{sec_letter}")
                    or strengths.get(f"IV-{sec_letter}")
                    or strengths.get(sec_letter)
                    or DEFAULT_STRENGTH)

        # Parse Mon–Fri rows
        for day_offset, day in enumerate(DAYS):
            row = day_start_row + day_offset
            if row > ws.max_row:
                break

            # Scan all columns in this row for merged-cell lab sessions
            visited_merges = set()
            for col in range(block_start_col, block_start_col + TOTAL_SLOTS):
                key = (row, col)
                if key not in merged_map:
                    continue
                val, mc, mC, mr, mR = merged_map[key]
                merge_id = (mr, mc, mR, mC)
                if merge_id in visited_merges:
                    continue
                visited_merges.add(merge_id)

                # Only consider merges that span exactly 2 columns (1 lab period = 2 slots)
                if mC - mc != 1:
                    continue
                # Must be in the same row
                if mr != mR:
                    continue

                lab = _extract_lab_tag(val)
                if not lab:
                    continue

                slot1 = _col_to_slot(mc, block_start_col)
                slot2 = _col_to_slot(mC, block_start_col)

                # Skip if crossing lunch
                if LUNCH_SLOT in (slot1, slot2):
                    continue

                half = _is_half_section(val)
                eff_strength = math.ceil(strength / HALF_SECTION_DIVISOR) if half else strength

                # Extract course name: everything before the lab tag
                course = re.sub(r"[<>\-]+", " ", val).strip()
                course = re.sub(r"\s+L[1-4]\s*$", "", course, flags=re.IGNORECASE).strip()
                course = re.sub(r"\s+", "-", course).strip("-")

                sessions.append({
                    "year": year,
                    "section": sec_letter,
                    "day": day,
                    "lab": lab,
                    "slot1": slot1,
                    "slot2": slot2,
                    "course": course,
                    "strength": eff_strength,
                    "raw_strength": strength,
                    "half_section": half,
                    "source": "section_sheet",
                })

    return sessions


def parse_per_lab_blocks(ws, year: str, strengths: dict) -> list[dict]:
    """
    Parse the per-lab timetable blocks that appear at the bottom of Second_Year
    (Section: LIVIA(L1)-G11, LART(L2), VLSI(L3), LLOCK(L4)).

    These blocks list which sessions happen in each lab. They use the same
    merged-cell format as the section timetables.
    The block_start_col for these is col B (2) for the left block,
    col O (15) for the right block.
    """
    sessions = []

    # Build merged map (same as _parse_block)
    merged_map: dict[tuple[int, int], str] = {}
    for rng in ws.merged_cells.ranges:
        top_left = ws.cell(rng.min_row, rng.min_col)
        if top_left.value:
            val = str(top_left.value).strip()
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    merged_map[(r, c)] = (val, rng.min_col, rng.max_col, rng.min_row, rng.max_row)

    for row_idx in range(1, ws.max_row + 1):
        # Look for per-lab header: "Section: LIVIA(L1)..." or "Section: LART(L2)..."
        lab_id = None
        block_start_col = None
        for col_idx in range(1, min(ws.max_column + 1, 30)):
            cell = ws.cell(row_idx, col_idx)
            val = cell.value
            if not val:
                continue
            val_str = str(val).strip()
            if "Section:" not in val_str:
                continue
            # Must contain an L1–L4 tag
            m = re.search(r"\bL([1-4])\b", val_str)
            if not m:
                continue
            lab_id = f"L{m.group(1)}"
            # The slot header starts at the next column after the section header cell
            # In Second_Year these are at col B (2) and col O (15)
            block_start_col = 2 if col_idx <= 13 else 15
            break

        if lab_id is None:
            continue

        day_start_row = row_idx + 2  # header row + slot header row

        for day_offset, day in enumerate(DAYS):
            row = day_start_row + day_offset
            if row > ws.max_row:
                break

            visited_merges = set()
            for col in range(block_start_col, block_start_col + TOTAL_SLOTS):
                key = (row, col)
                if key not in merged_map:
                    continue
                val, mc, mC, mr, mR = merged_map[key]
                merge_id = (mr, mc, mR, mC)
                if merge_id in visited_merges:
                    continue
                visited_merges.add(merge_id)

                if mC - mc != 1:
                    continue
                if mr != mR:
                    continue

                # Check that this cell's lab tag matches the current lab block
                cell_lab = _extract_lab_tag(val)
                if cell_lab and cell_lab != lab_id:
                    # Different lab tag — skip (belongs to another block)
                    pass  # still record, the section-sheet is authoritative for lab assignment

                slot1 = _col_to_slot(mc, block_start_col)
                slot2 = _col_to_slot(mC, block_start_col)

                if LUNCH_SLOT in (slot1, slot2):
                    continue

                # Extract section from the value, e.g. "<-CN-A-L2>" → section "A"
                # Pattern: course-SECTION-Lx or course_SECTION_Lx
                sec_m = re.search(r"[_\-]([A-Z])[_\-](?:(?:a|b)[_\-])?L[1-4]", val, re.IGNORECASE)
                section = sec_m.group(1).upper() if sec_m else "?"

                # Strength lookup
                half = _is_half_section(val)
                raw = (strengths.get(f"II-{section}")
                       or strengths.get(f"III-{section}")
                       or strengths.get(section)
                       or DEFAULT_STRENGTH)
                eff_strength = math.ceil(raw / HALF_SECTION_DIVISOR) if half else raw

                course = re.sub(r"[<>\-]+", " ", val).strip()
                course = re.sub(r"\s+L[1-4]\s*$", "", course, flags=re.IGNORECASE).strip()
                course = re.sub(r"\s+", "-", course).strip("-")

                sessions.append({
                    "year": year,
                    "section": section,
                    "day": day,
                    "lab": lab_id,
                    "slot1": slot1,
                    "slot2": slot2,
                    "course": course,
                    "strength": eff_strength,
                    "raw_strength": raw,
                    "half_section": half,
                    "source": "per_lab_block",
                })

    return sessions


def load_extra_sessions(csv_path: str, known_labs: set[str]) -> list[dict]:
    """
    Load extra sessions from extra_sessions.csv.
    Format: lab,day,slot,year,section,course,strength
    slot can be "3" or "3-4" (range means a 2-period lab).
    Lines starting with # are ignored.
    Raises ValueError for unknown lab IDs.
    """
    sessions = []
    if not os.path.exists(csv_path):
        return sessions

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            reader = csv.reader([line])
            for parts in reader:
                if len(parts) < 7:
                    raise ValueError(f"extra_sessions.csv line {lineno}: expected 7 fields, got {len(parts)}")
                lab, day, slot_spec, year, section, course, strength_str = (p.strip() for p in parts[:7])
                if lab not in known_labs:
                    raise ValueError(
                        f"extra_sessions.csv line {lineno}: unknown lab '{lab}'. "
                        f"Known labs: {sorted(known_labs)}"
                    )
                day = day.capitalize()[:3]  # "monday" → "Mon"
                if day not in DAYS:
                    raise ValueError(f"extra_sessions.csv line {lineno}: invalid day '{day}'")
                # Parse slot spec
                if "-" in slot_spec:
                    s1, s2 = slot_spec.split("-", 1)
                    slot1, slot2 = int(s1.strip()), int(s2.strip())
                else:
                    slot1 = slot2 = int(slot_spec)
                if slot1 == LUNCH_SLOT or slot2 == LUNCH_SLOT:
                    raise ValueError(f"extra_sessions.csv line {lineno}: slot {LUNCH_SLOT} is lunch, not bookable")
                sessions.append({
                    "year": year,
                    "section": section,
                    "day": day,
                    "lab": lab,
                    "slot1": slot1,
                    "slot2": slot2,
                    "course": course,
                    "strength": int(strength_str),
                    "raw_strength": int(strength_str),
                    "half_section": False,
                    "source": "extra_sessions",
                })
    return sessions


# ─── Sheet-specific block definitions ─────────────────────────────────────────
# Each entry: (sheet_name, block_start_col)
# block_start_col is the 1-indexed column of S1 for that block.
# Second_Year: left block S1=col B(2), right block S1=col O(15)
# Third_Year : left block S1=col C(3), right block S1=col P(16)
# Final_year : similar — we detect dynamically.

SHEET_BLOCKS = {
    "Second_Year": [2, 15],
    "Third_Year":  [3, 16],
    "Final_year":  [3, 16],   # best guess; parser handles missing gracefully
}


def parse_timetable(xlsx_path: str, labs_json_path: str, extra_csv_path: str) -> list[dict]:
    """
    Main entry point. Returns a deduplicated list of session records.
    Each record: {year, section, day, lab, slot1, slot2, course, strength,
                  raw_strength, half_section, occupancy_pct, source}
    """
    # Load lab definitions to know valid IDs and capacities
    with open(labs_json_path, encoding="utf-8-sig") as f:
        labs_cfg = json.load(f)
    lab_capacity = {lab["id"]: lab["capacity"] for lab in labs_cfg["labs"]}
    known_labs = set(lab_capacity.keys())
    timetabled_labs = {lab["id"] for lab in labs_cfg["labs"] if lab.get("timetable")}

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)

    # Load section strengths from Room plan
    strengths = {}
    if "Room plan" in wb.sheetnames:
        strengths = _load_strengths(wb["Room plan"])

    all_sessions: list[dict] = []

    # Parse each year sheet
    for sheet_name, block_starts in SHEET_BLOCKS.items():
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        for bsc in block_starts:
            sessions = _parse_block(ws, bsc, [], sheet_name, strengths)
            all_sessions.extend(sessions)

        # Parse per-lab blocks (only Second_Year has them per the spec)
        if sheet_name == "Second_Year":
            lab_sessions = parse_per_lab_blocks(ws, sheet_name, strengths)
            all_sessions.extend(lab_sessions)

    # Load extra sessions
    extra = load_extra_sessions(extra_csv_path, known_labs)
    all_sessions.extend(extra)

    # Deduplicate: keep one record per (lab, day, slot1) key.
    # Prefer section_sheet source over per_lab_block; extra_sessions always additive.
    seen: dict[tuple, dict] = {}
    source_priority = {"section_sheet": 0, "per_lab_block": 1, "extra_sessions": 2}
    for s in all_sessions:
        if s["lab"] not in timetabled_labs and s["source"] != "extra_sessions":
            continue  # skip sessions for labs not in config
        key = (s["lab"], s["day"], s["slot1"])
        existing = seen.get(key)
        if existing is None:
            seen[key] = s
        elif source_priority.get(s["source"], 9) < source_priority.get(existing["source"], 9):
            seen[key] = s

    # Enrich with occupancy_pct
    result = []
    for s in seen.values():
        cap = lab_capacity.get(s["lab"], DEFAULT_STRENGTH)
        s["capacity"] = cap
        s["occupancy_pct"] = round(s["strength"] / cap * 100, 1)
        result.append(s)

    # Sort for readability
    day_order = {d: i for i, d in enumerate(DAYS)}
    result.sort(key=lambda s: (s["lab"], day_order.get(s["day"], 9), s["slot1"]))
    return result
