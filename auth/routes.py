"""
auth/routes.py — Flask Blueprint for Role-Based Authentication endpoints.
"""

from flask import Blueprint, request, jsonify, session, redirect, url_for
from .service import authenticate_user, login_user, logout_user, get_current_user

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/auth/login", methods=["POST"])
def api_login():
    """Verify credentials and create role-based session."""
    data = request.get_json(silent=True) or request.form
    identifier = data.get("identifier") or data.get("username")
    pin = data.get("pin")
    role = data.get("role")

    success, result = authenticate_user(identifier, pin, requested_role=role)
    if not success:
        return jsonify({
            "success": False,
            "error": result
        }), 401

    user = result
    login_user(user)

    user_role = (user.get("role") or "").lower()
    if user_role == "student":
        redirect_url = "/student"
    elif user_role == "faculty":
        redirect_url = "/faculty"
    elif user_role == "admin":
        redirect_url = "/admin"
    elif user_role == "maintenance":
        redirect_url = "/admin?tab=facility"
    else:
        redirect_url = "/"

    return jsonify({
        "success": True,
        "redirect_url": redirect_url,
        "user": user
    })


@auth_bp.route("/logout")
def logout():
    """Clear user session and redirect to landing page."""
    logout_user()
    return redirect("/")


@auth_bp.route("/api/auth/me")
def api_me():
    """Return currently active user profile and roles."""
    user = get_current_user()
    if not user:
        return jsonify({"authenticated": False, "user": None})
    return jsonify({"authenticated": True, "user": user})

