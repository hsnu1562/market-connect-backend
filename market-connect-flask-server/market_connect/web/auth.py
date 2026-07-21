from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import User
from .utils import get_or_404


bp = Blueprint("web_auth", __name__)


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/register/<role>", methods=["GET", "POST"])
@bp.route("/register/<role>/", methods=["GET", "POST"])
def register(role: str):
    if request.method == "POST":
        user = User(
            username=request.form["username"],
            first_name=request.form["fname"],
            last_name=request.form["lname"],
            password_hash=generate_password_hash(request.form["pw"]),
            phone_number=request.form.get("phone"),
            role=role,
        )
        db.session.add(user)
        db.session.commit()
        session["user_id"] = user.id
        session["user_role"] = user.role
        if role == "Landlord":
            return redirect(f"/landlord/hub/{user.id}/")
        return redirect(f"/tenant/hub/{user.id}/")
    return render_template("register.html", role=role)


@bp.route("/login/<role>", methods=["GET", "POST"])
@bp.route("/login/<role>/", methods=["GET", "POST"])
def login_view(role: str):
    error = ""
    if request.method == "POST":
        user = User.query.filter_by(username=request.form.get("username"), role=role).first()
        if user and check_password_hash(user.password_hash, request.form.get("pw", "")):
            session["user_id"] = user.id
            session["user_role"] = user.role
            if role == "Landlord":
                return redirect(f"/landlord/hub/{user.id}/")
            return redirect(f"/tenant/hub/{user.id}/")
        error = "帳號、密碼或角色選取錯誤，請重新輸入！"
    return render_template("login.html", role=role, error=error)


@bp.route("/tenant/hub/<int:user_id>/")
def tenant_hub(user_id: int):
    return render_template("tenant_hub.html", user=get_or_404(User, user_id))


@bp.route("/landlord/hub/<int:user_id>/")
def landlord_hub(user_id: int):
    return render_template("landlord_hub.html", user=get_or_404(User, user_id))
