"""
library/routes.py — Flask Blueprint for the Smart Library Utilization and Analytics module.

Routes:
- Page: /library -> redirects to /?tab=library#library
- APIs:
  - GET  /api/library/status
  - POST /api/library/occupancy
  - PUT  /api/library/occupancy/<id>
  - DELETE /api/library/occupancy/<id>
  - GET  /api/library/records
  - GET  /api/library/analytics
  - GET  /api/library/predictions
  - GET  /api/library/recommendations
  - POST /api/library/config
- Downloads:
  - GET  /download/library-report/excel
  - GET  /download/library-report/pdf
"""

import os
import logging
from flask import Blueprint, request, jsonify, send_file, redirect
from . import occupancy
from . import analytics
from . import predictor
from . import recommendations
from . import reports

logger = logging.getLogger(__name__)

library_bp = Blueprint("library_bp", __name__)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


@library_bp.route("/library")
def library_index():
    """Redirect to unified dashboard with library tab active."""
    return redirect("/?tab=library#library")


# ─── Status & Latest Reading ──────────────────────────────────────────────────

@library_bp.route("/api/library/status")
def api_library_status():
    """Return latest occupancy, crowd level, and staleness details for student and admin displays."""
    latest = occupancy.get_latest_observation()
    cfg = occupancy.get_config()
    stats = analytics.compute_library_analytics(date_filter="30d")

    return jsonify({
        "status": "success",
        "latest": latest,
        "config": cfg,
        "peak_hours": stats.get("peak_hours", [])[:2],
        "busiest_day": stats.get("busiest_days", [{}])[0].get("day", "N/A"),
        "best_visiting_hours": "Early morning (8:00 AM – 9:30 AM) or evenings after 6:30 PM"
    })


# ─── Occupancy Observation CRUD ───────────────────────────────────────────────

@library_bp.route("/api/library/occupancy", methods=["POST"])
def api_add_occupancy():
    """Record an independent periodic occupancy observation."""
    data = request.get_json(silent=True) or request.form.to_dict()
    if not data:
        return jsonify({"error": "JSON body or form data required"}), 400

    pin = request.headers.get("X-Pin") or data.get("pin", "")

    try:
        occupied = int(data.get("occupied_seats", -1))
    except (ValueError, TypeError):
        return jsonify({"error": "Occupied seats must be a valid non-negative number"}), 400

    notes = str(data.get("notes", "")).strip()

    try:
        rec = occupancy.add_observation(occupied_seats=occupied, pin=pin, notes=notes)
        return jsonify({"success": True, "message": "Occupancy observation recorded successfully!", "record": rec}), 201
    except PermissionError as pe:
        return jsonify({"error": str(pe)}), 403
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        logger.error("Error adding occupancy record: %s", e)
        return jsonify({"error": f"Server error: {str(e)}"}), 500


@library_bp.route("/api/library/occupancy/<int:record_id>", methods=["PUT"])
def api_update_occupancy(record_id):
    """Correct an existing observation record."""
    data = request.get_json(silent=True) or request.form.to_dict()
    if not data:
        return jsonify({"error": "JSON body or form data required"}), 400

    pin = request.headers.get("X-Pin") or data.get("pin", "")

    try:
        occupied = int(data.get("occupied_seats", -1))
    except (ValueError, TypeError):
        return jsonify({"error": "Occupied seats must be a valid non-negative number"}), 400

    notes = data.get("notes")

    try:
        rec = occupancy.update_observation(record_id=record_id, occupied_seats=occupied, pin=pin, notes=notes)
        return jsonify({"success": True, "message": "Observation updated successfully!", "record": rec})
    except PermissionError as pe:
        return jsonify({"error": str(pe)}), 403
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        logger.error("Error updating occupancy record: %s", e)
        return jsonify({"error": f"Server error: {str(e)}"}), 500


@library_bp.route("/api/library/occupancy/<int:record_id>", methods=["DELETE"])
def api_delete_occupancy(record_id):
    """Delete an observation record."""
    pin = request.headers.get("X-Pin") or request.args.get("pin", "")
    try:
        occupancy.delete_observation(record_id=record_id, pin=pin)
        return jsonify({"success": True, "message": f"Record #{record_id} deleted successfully."})
    except PermissionError as pe:
        return jsonify({"error": str(pe)}), 403
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@library_bp.route("/api/library/records")
def api_get_records():
    """Retrieve filtered observation records."""
    date_filter = request.args.get("filter", "30d")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    limit = int(request.args.get("limit", 500))

    records = occupancy.get_observations(
        date_filter=date_filter,
        start_date=start_date,
        end_date=end_date,
        limit=limit
    )
    return jsonify({"records": records, "count": len(records)})


# ─── Analytics, Predictions & Recommendations ─────────────────────────────────

@library_bp.route("/api/library/analytics")
def api_get_analytics():
    """Return comprehensive statistical and trend analysis."""
    date_filter = request.args.get("filter", "30d")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    stats = analytics.compute_library_analytics(
        date_filter=date_filter,
        start_date=start_date,
        end_date=end_date
    )
    return jsonify(stats)


@library_bp.route("/api/library/predictions")
def api_get_predictions():
    """Return machine learning predictive occupancy forecast."""
    horizon = int(request.args.get("horizon", 12))
    horizon = max(1, min(24, horizon))
    data = predictor.predict_upcoming_hours(horizon_hours=horizon)
    return jsonify(data)


@library_bp.route("/api/library/recommendations")
def api_get_recommendations():
    """Return actionable data-driven administrative recommendations."""
    recs = recommendations.generate_recommendations()
    return jsonify({"recommendations": recs})


# ─── Configuration ────────────────────────────────────────────────────────────

@library_bp.route("/api/library/config", methods=["POST"])
def api_update_config():
    """Update library seating capacity and threshold configuration."""
    data = request.get_json(silent=True) or request.form.to_dict()
    if not data:
        return jsonify({"error": "JSON body or form data required"}), 400

    pin = request.headers.get("X-Pin") or data.get("pin", "")

    try:
        capacity = int(data.get("total_capacity", 0))
        low = float(data.get("low_threshold_pct", 35.0))
        mod = float(data.get("mod_threshold_pct", 70.0))
        high = float(data.get("high_threshold_pct", 90.0))
    except (ValueError, TypeError):
        return jsonify({"error": "Capacity and thresholds must be valid numbers"}), 400

    try:
        cfg = occupancy.update_config(capacity=capacity, low_th=low, mod_th=mod, high_th=high, pin=pin)
        return jsonify({"success": True, "message": "Library configuration updated successfully!", "config": cfg})
    except PermissionError as pe:
        return jsonify({"error": str(pe)}), 403
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Report Downloads ─────────────────────────────────────────────────────────

@library_bp.route("/download/library-report/excel")
def download_library_excel():
    """Download full Excel analytics report."""
    date_filter = request.args.get("filter", "30d")
    out_file = os.path.join(OUTPUT_DIR, "library_utilization_report.xlsx")
    try:
        reports.generate_library_excel_report(out_file, date_filter=date_filter)
        return send_file(out_file, as_attachment=True, download_name="Library_Utilization_Report.xlsx")
    except Exception as e:
        logger.error("Error generating library Excel report: %s", e)
        return jsonify({"error": f"Failed to generate Excel report: {str(e)}"}), 500


@library_bp.route("/download/library-report/pdf")
def download_library_pdf():
    """Download executive PDF utilization report."""
    date_filter = request.args.get("filter", "30d")
    out_file = os.path.join(OUTPUT_DIR, "library_utilization_report.pdf")
    try:
        reports.generate_library_pdf_report(out_file, date_filter=date_filter)
        return send_file(out_file, as_attachment=True, download_name="Library_Utilization_Report.pdf")
    except Exception as e:
        logger.error("Error generating library PDF report: %s", e)
        return jsonify({"error": f"Failed to generate PDF report: {str(e)}"}), 500
