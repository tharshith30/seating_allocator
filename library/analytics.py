"""
library/analytics.py — Statistical aggregation and usage pattern analytics for the library.

Processes raw occupancy observations into actionable metrics:
- Overall KPIs (total observations, avg/max/min occupancy, avg daily count)
- Hourly distributions (8 AM – 8 PM)
- Day-of-week trends and busiest days
- Peak-hour heatmap matrix (Day × Hour)
- Crowd distribution breakdown (Low, Moderate, High, Full)
"""

from collections import defaultdict
from datetime import datetime, date, timedelta
from . import occupancy


def compute_library_analytics(date_filter: str = "30d", start_date: str = None, end_date: str = None) -> dict:
    """
    Compute comprehensive analytics from stored occupancy observations.
    Respects date filtering and provides data structures ready for UI charting.
    """
    records = occupancy.get_observations(date_filter=date_filter, start_date=start_date, end_date=end_date, limit=2000)
    cfg = occupancy.get_config()
    total_capacity = cfg["total_capacity"]

    if not records:
        return {
            "has_data": False,
            "total_observations": 0,
            "simulated_count": 0,
            "actual_count": 0,
            "avg_occupancy_pct": 0.0,
            "max_occupancy_seats": 0,
            "max_occupancy_pct": 0.0,
            "min_occupancy_seats": 0,
            "min_occupancy_pct": 0.0,
            "peak_hours": [],
            "busiest_days": [],
            "hourly_chart": {"labels": [], "data": []},
            "daily_trend": {"labels": [], "data": []},
            "distribution": {"low": 0, "moderate": 0, "high": 0, "full": 0},
            "heatmap": [],
            "capacity": total_capacity
        }

    total_obs = len(records)
    actual_count = sum(1 for r in records if r.get("recorded_by") != "system_baseline")
    simulated_count = total_obs - actual_count

    all_pcts = [r["occupancy_pct"] for r in records]
    all_seats = [r["occupied_seats"] for r in records]

    avg_pct = round(sum(all_pcts) / total_obs, 1)
    max_seats = max(all_seats)
    max_pct = max(all_pcts)
    min_seats = min(all_seats)
    min_pct = min(all_pcts)

    # 1. Distribution by crowd status
    dist_counts = {"low": 0, "moderate": 0, "high": 0, "full": 0}
    for r in records:
        status_label = r["status"]
        if status_label == "Full capacity":
            dist_counts["full"] += 1
        elif status_label == "High occupancy":
            dist_counts["high"] += 1
        elif status_label == "Moderate occupancy":
            dist_counts["moderate"] += 1
        else:
            dist_counts["low"] += 1

    dist_pct = {
        k: round((v / total_obs) * 100.0, 1) for k, v in dist_counts.items()
    }

    # 2. Hourly analysis (8 AM to 8 PM)
    hourly_sums = defaultdict(list)
    for r in records:
        try:
            hour = int(r["recorded_time"].split(":")[0])
            hourly_sums[hour].append(r["occupancy_pct"])
        except Exception:
            continue

    standard_hours = list(range(8, 21)) # 8 to 20
    hourly_labels = []
    hourly_data = []

    for h in standard_hours:
        h_label = f"{h:02d}:00"
        hourly_labels.append(h_label)
        if h in hourly_sums and hourly_sums[h]:
            hourly_data.append(round(sum(hourly_sums[h]) / len(hourly_sums[h]), 1))
        else:
            hourly_data.append(0.0)

    # Peak hours: top 3 hours with highest average
    hourly_avg_list = [(h, round(sum(vals)/len(vals), 1)) for h, vals in hourly_sums.items() if vals]
    hourly_avg_list.sort(key=lambda x: x[1], reverse=True)
    peak_hours = [
        {"hour": f"{h:02d}:00", "avg_pct": avg, "estimated_seats": int(round((avg / 100.0) * total_capacity))}
        for h, avg in hourly_avg_list[:3]
    ]

    # 3. Day of week analysis
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_short = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    dow_sums = defaultdict(list)

    for r in records:
        try:
            d_obj = datetime.strptime(r["recorded_date"], "%Y-%m-%d").date()
            dow = d_obj.weekday()
            dow_sums[dow].append(r["occupancy_pct"])
        except Exception:
            continue

    dow_ranked = []
    for dow in range(7):
        if dow in dow_sums and dow_sums[dow]:
            avg_d = round(sum(dow_sums[dow]) / len(dow_sums[dow]), 1)
            dow_ranked.append({"day": day_names[dow], "short": day_short[dow], "avg_pct": avg_d})
        else:
            dow_ranked.append({"day": day_names[dow], "short": day_short[dow], "avg_pct": 0.0})

    busiest_days = sorted(dow_ranked, key=lambda x: x["avg_pct"], reverse=True)

    # 4. Daily trend (chronological)
    daily_sums = defaultdict(list)
    for r in records:
        daily_sums[r["recorded_date"]].append(r["occupancy_pct"])

    sorted_dates = sorted(daily_sums.keys())
    daily_labels = sorted_dates[-30:] # up to last 30 days
    daily_data = [round(sum(daily_sums[d]) / len(daily_sums[d]), 1) for d in daily_labels]

    # 5. Day × Hour Heatmap Matrix
    # Days Mon–Fri (0–4) + Sat (5), Hours 8–20
    heatmap_matrix = []
    cell_sums = defaultdict(list)

    for r in records:
        try:
            d_obj = datetime.strptime(r["recorded_date"], "%Y-%m-%d").date()
            dow = d_obj.weekday()
            hour = int(r["recorded_time"].split(":")[0])
            if 8 <= hour <= 20 and dow < 6:
                cell_sums[(dow, hour)].append(r["occupancy_pct"])
        except Exception:
            continue

    for dow in range(6): # Mon to Sat
        day_row = {
            "day": day_short[dow],
            "day_name": day_names[dow],
            "slots": []
        }
        for h in standard_hours:
            vals = cell_sums.get((dow, h), [])
            avg_val = round(sum(vals) / len(vals), 1) if vals else 0.0
            day_row["slots"].append({
                "hour": f"{h:02d}:00",
                "avg_pct": avg_val,
                "count": len(vals)
            })
        heatmap_matrix.append(day_row)

    return {
        "has_data": True,
        "total_observations": total_obs,
        "simulated_count": simulated_count,
        "actual_count": actual_count,
        "capacity": total_capacity,
        "avg_occupancy_pct": avg_pct,
        "max_occupancy_seats": max_seats,
        "max_occupancy_pct": max_pct,
        "min_occupancy_seats": min_seats,
        "min_occupancy_pct": min_pct,
        "peak_hours": peak_hours,
        "busiest_days": busiest_days,
        "hourly_chart": {
            "labels": hourly_labels,
            "data": hourly_data
        },
        "daily_trend": {
            "labels": daily_labels,
            "data": daily_data
        },
        "distribution": {
            "counts": dist_counts,
            "percentages": dist_pct
        },
        "heatmap": heatmap_matrix
    }

