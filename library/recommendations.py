"""
library/recommendations.py — Intelligent operational advice and administrative decision support.

Generates actionable recommendations strictly based on recorded observations:
- Persistent peak-hour warnings and capacity alerts
- Underutilized time windows suitable for maintenance or energy conservation
- Student study advisories for less-crowded study sessions
- Seating expansion advisories based on saturation frequency
"""

from collections import defaultdict
from . import occupancy
from . import analytics
from . import predictor


def generate_recommendations() -> list[dict]:
    """
    Synthesize recorded occupancy data and predictive trends into clear,
    categorized administrative recommendations.
    """
    stats = analytics.compute_library_analytics(date_filter="30d")
    cfg = occupancy.get_config()
    total_capacity = cfg["total_capacity"]

    recommendations = []

    if not stats.get("has_data") or stats["total_observations"] < 5:
        recommendations.append({
            "type": "info",
            "category": "Data Collection",
            "tag": "Provisional Notice",
            "title": "Initial Data Collection in Progress",
            "description": "Fewer than 5 occupancy observations have been recorded. Log additional headcounts across different operating hours to unlock advanced machine-learning insights.",
            "action": "Continue recording hourly headcounts."
        })
        return recommendations

    total_obs = stats["total_observations"]
    dist = stats["distribution"]["counts"]
    full_count = dist.get("full", 0)
    high_count = dist.get("high", 0)
    low_count = dist.get("low", 0)

    # 1. Capacity Saturation Alert (Overcrowding)
    saturation_rate = round(((full_count + high_count) / total_obs) * 100.0, 1)
    if saturation_rate >= 35.0:
        recommendations.append({
            "type": "danger",
            "category": "Capacity Advisory",
            "tag": "Data-Based Insight",
            "title": "High Seat Saturation Frequency Detected",
            "description": f"The library was at High or Full capacity during {saturation_rate}% of recorded observations. Available seating frequently falls below {cfg.get('high_threshold_pct', 90)}% capacity threshold.",
            "action": f"Consider expanding seating or deploying temporary study desks during peak mid-day windows."
        })
    elif saturation_rate < 15.0:
        recommendations.append({
            "type": "success",
            "category": "Capacity Health",
            "tag": "Data-Based Insight",
            "title": "Healthy Overall Seating Capacity",
            "description": f"Seating capacity is well-proportioned to the student population. Saturation occurs in only {saturation_rate}% of observations.",
            "action": "Maintain existing seating layout of 250 desks."
        })

    # 2. Peak Hours Operational Planning
    peak_hours = stats.get("peak_hours", [])
    if peak_hours:
        top_hours = ", ".join([p["hour"] for p in peak_hours[:2]])
        top_avg = peak_hours[0]["avg_pct"]
        recommendations.append({
            "type": "warning",
            "category": "Peak Hours",
            "tag": "Statistical Estimate",
            "title": f"Recurring Peak Occupancy: {top_hours}",
            "description": f"Peak demand consistently concentrates around {top_hours} with average seating occupancy exceeding {top_avg}%.",
            "action": "Schedule library student support staff and ensure air conditioning is active during these high-traffic hours."
        })

    # 3. Low Occupancy / Optimal Maintenance Window
    hourly_chart = stats.get("hourly_chart", {})
    labels = hourly_chart.get("labels", [])
    data = hourly_chart.get("data", [])

    underused_slots = []
    for lbl, val in zip(labels, data):
        if val > 0 and val <= cfg.get("low_threshold_pct", 35.0):
            underused_slots.append(lbl)

    if underused_slots:
        maint_window = f"{underused_slots[0]} or {underused_slots[-1]}" if len(underused_slots) > 1 else underused_slots[0]
        recommendations.append({
            "type": "info",
            "category": "Facility Maintenance",
            "tag": "Data-Based Insight",
            "title": f"Optimal Maintenance Window: {maint_window}",
            "description": f"Library occupancy is consistently low (< {cfg.get('low_threshold_pct', 35)}%) at {', '.join(underused_slots[:3])}.",
            "action": f"Recommended time for routine vacuuming, shelf re-indexing, book restocking, and HVAC servicing without student disruption."
        })

    # 4. Day of the Week Trend Insight
    busiest = stats.get("busiest_days", [])
    if len(busiest) >= 2:
        busiest_day = busiest[0]
        quietest_day = busiest[-1]
        recommendations.append({
            "type": "info",
            "category": "Weekly Pattern",
            "tag": "Statistical Estimate",
            "title": f"Weekly Usage Divergence ({busiest_day['day']} vs {quietest_day['day']})",
            "description": f"{busiest_day['day']} experiences peak demand (avg {busiest_day['avg_pct']}%), while {quietest_day['day']} is the least crowded day of the week (avg {quietest_day['avg_pct']}%).",
            "action": f"Advise students seeking quiet study spaces to prioritize {quietest_day['day']} visits."
        })

    # 5. Machine Learning Forecast Advisory
    try:
        fc = predictor.predict_upcoming_hours(horizon_hours=6)
        peaks = fc.get("predicted_peaks", [])
        if peaks:
            recommendations.append({
                "type": "warning",
                "category": "Predictive Outlook",
                "tag": "ML Prediction",
                "title": f"Anticipated Surge: {peaks[0]}",
                "description": f"Our regression model projects heavy student occupancy approaching {peaks[0]}.",
                "action": "Post student crowd advisories on digital campus noticeboards."
            })
    except Exception:
        pass

    return recommendations
