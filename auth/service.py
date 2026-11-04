"""
auth/service.py — Core authentication, credential hashing, lockout management, and RBAC helpers.
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from functools import wraps
from flask import session, redirect, url_for, jsonify, request, abort, render_template
from werkzeug.security import generate_password_hash, check_password_hash

# Resolve dependencies if needed
_cached_site = os.path.expanduser(r"~\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages")
if os.path.isdir(_cached_site) and _cached_site not in sys.path:
    sys.path.insert(0, _cached_site)

from campus import db

logger = logging.getLogger(__name__)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15


def get_user_by_identifier(identifier: str) -> dict | None:
    """Retrieve user record by username OR student_id (case-insensitive)."""
    if not identifier:
        return None
    ident = str(identifier).strip()
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM users 
        WHERE LOWER(username) = LOWER(?) OR (student_id IS NOT NULL AND LOWER(student_id) = LOWER(?));
    """, (ident, ident))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def authenticate_user(identifier: str, pin: str, requested_role: str = None) -> tuple[bool, str | dict]:
    """
    Authenticate user with identifier and PIN.
    Enforces lockout after MAX_FAILED_ATTEMPTS and validates requested role.
    Returns (True, user_dict) on success, or (False, error_message) on failure.
    """
    if not identifier or not pin:
        return False, "Please provide both username/ID and PIN."

    user = get_user_by_identifier(identifier)
    if not user:
        return False, "Invalid credentials. User not found."

    conn = db.get_db()
    cursor = conn.cursor()

    # Check for temporary lockout
    locked_until_str = user.get("locked_until")
    if locked_until_str:
        try:
            # Parse datetime string from sqlite
            locked_until = datetime.fromisoformat(locked_until_str)
            if datetime.utcnow() < locked_until:
                diff = locked_until - datetime.utcnow()
                mins = int(diff.total_seconds() / 60) + 1
                conn.close()
                return False, f"Account is temporarily locked due to repeated failed attempts. Please retry in {mins} minute(s)."
            else:
                # Lockout has expired; reset lockout
                cursor.execute("UPDATE users SET locked_until = NULL, failed_attempts = 0 WHERE id = ?;", (user["id"],))
                conn.commit()
                user["failed_attempts"] = 0
        except Exception:
            pass

    # Validate requested role if provided
    user_role = (user.get("role") or "").lower()
    if requested_role:
        req_clean = requested_role.lower()
        # Admin can access any role if needed, but otherwise roles must match
        if req_clean != user_role and user_role != "admin":
            conn.close()
            role_names = {
                "student": "Student Portal",
                "faculty": "Faculty Portal",
                "admin": "Administration Portal",
                "maintenance": "Maintenance Operations"
            }
            target_portal = role_names.get(user_role, user_role.title())
            return False, f"This account is registered for '{user_role.title()}' role. Please log in through the {target_portal} card."

    # Verify PIN hash
    pin_hash = user.get("pin_hash")
    if not pin_hash or not check_password_hash(pin_hash, str(pin).strip()):
        # Increment failed attempts
        failed = (user.get("failed_attempts") or 0) + 1
        if failed >= MAX_FAILED_ATTEMPTS:
            lockout_time = (datetime.utcnow() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)).isoformat()
            cursor.execute("""
                UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?;
            """, (failed, lockout_time, user["id"]))
            conn.commit()
            conn.close()
            return False, f"Maximum PIN attempts reached. Account locked for {LOCKOUT_DURATION_MINUTES} minutes."
        else:
            remaining = MAX_FAILED_ATTEMPTS - failed
            cursor.execute("UPDATE users SET failed_attempts = ? WHERE id = ?;", (failed, user["id"]))
            conn.commit()
            conn.close()
            return False, f"Incorrect PIN. {remaining} attempt(s) remaining before security lockout."

    # Successful authentication — reset failed counter
    cursor.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?;", (user["id"],))
    conn.commit()
    conn.close()

    # Strip sensitive hash before returning
    user.pop("pin_hash", None)
    return True, user


def login_user(user: dict):
    """Store authenticated user session."""
    session.permanent = True
    session["user"] = {
        "id": user["id"],
        "username": user["username"],
        "name": user["name"],
        "email": user.get("email"),
        "role": user["role"],
        "department": user.get("department"),
        "student_id": user.get("student_id"),
        "section": user.get("section"),
        "academic_year": user.get("academic_year"),
        "logged_in_at": datetime.utcnow().isoformat()
    }


def logout_user():
    """Clear session data."""
    session.pop("user", None)
    session.clear()


def get_current_user() -> dict | None:
    """Retrieve currently authenticated user from session."""
    return session.get("user")


def login_required(f):
    """Decorator ensuring request has an active session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_user():
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", ""):
                return jsonify({"success": False, "error": "Authentication required. Please log in."}), 401
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return decorated_function


def role_required(*allowed_roles):
    """Decorator restricting endpoint to specific user roles."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if not user:
                if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", ""):
                    return jsonify({"success": False, "error": "Authentication required."}), 401
                return redirect(url_for("home"))
            
            user_role = (user.get("role") or "").lower()
            # Normalize allowed roles
            allowed = [r.lower() for r in allowed_roles]
            if "admin" not in allowed and user_role == "admin":
                # Admin has master access
                allowed.append("admin")

            if user_role not in allowed:
                if request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", ""):
                    return jsonify({"success": False, "error": "Access denied. Insufficient role permissions."}), 403
                return render_template("403.html", user=user, allowed_roles=allowed_roles), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator
