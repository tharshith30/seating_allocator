import sys
import os

_cached_site = os.path.expanduser(r"~\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages")
if os.path.isdir(_cached_site) and _cached_site not in sys.path:
    sys.path.insert(0, _cached_site)

import pandas as pd
import re


def parse_seat_range(seat_range):

    seat_range = str(
        seat_range
    ).strip()

    match = re.search(
        r"(\d+)\s*-\s*(\d+)",
        seat_range
    )

    if not match:

        raise ValueError(
            f"Invalid seat range: {seat_range}"
        )

    start = int(
        match.group(1)
    )

    end = int(
        match.group(2)
    )

    return start, end


def load_rooms(file_path):

    df = pd.read_excel(
        file_path
    )

    rooms = []

    # =========================================================
    # YOUR ACTUAL EXCEL HAS 3 BLOCKS
    # =========================================================

    block_starts = [
        0,
        5,
        10
    ]

    for start_col in block_starts:

        room_col = start_col

        seat_col = start_col + 2

        for _, row in df.iterrows():

            room_value = row.iloc[
                room_col
            ]

            seat_value = row.iloc[
                seat_col
            ]

            if (
                pd.isna(room_value)
                or
                pd.isna(seat_value)
            ):
                continue

            room = str(
                room_value
            ).strip()

            try:

                start_seat, end_seat = (
                    parse_seat_range(
                        seat_value
                    )
                )

            except ValueError:

                continue

            rooms.append({

                "Room": room,

                "StartSeat":
                    start_seat,

                "EndSeat":
                    end_seat
            })

    return rooms