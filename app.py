import functools
import math
import os

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman

from db_manager import DbConfig, DbManager, UnknownTableError

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_ENV") != "development"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = int(os.environ.get("SESSION_LIFETIME_SECONDS", 3600))

csrf = CSRFProtect(app)
limiter = Limiter(app=app, key_func=get_remote_address, default_limits=[])

Talisman(
    app,
    force_https=os.environ.get("FLASK_ENV") != "development",
    strict_transport_security=True,
    content_security_policy={"default-src": "'self'", "style-src": "'self' 'unsafe-inline'"},
)

db = DbManager(DbConfig.from_env())

ADMIN_USER = os.environ["ADMIN_USER"]
ADMIN_PASSWORD_HASH = os.environ["ADMIN_PASSWORD_HASH"]
PAGE_SIZE = int(os.environ.get("ADMIN_PAGE_SIZE", 25))


def require_auth(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentification requise"}), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.errorhandler(UnknownTableError)
def handle_unknown_table(exc):
    return jsonify({"error": f"Table inconnue: {exc}"}), 404


@app.errorhandler(CSRFError)
def handle_csrf_error(exc):
    return jsonify({"error": "Session expirée, rechargez la page"}), 400


@app.get("/login")
def login():
    if session.get("authenticated"):
        return redirect(url_for("index"))
    return render_template("login.html", next=request.args.get("next", ""))


@app.post("/login")
@limiter.limit("5 per minute")
def login_submit():
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    if username != ADMIN_USER or not check_password_hash(ADMIN_PASSWORD_HASH, password):
        return render_template("login.html", error="Identifiants incorrects", next=request.form.get("next", "")), 401
    session.clear()
    session["authenticated"] = True
    session.permanent = True
    return redirect(request.form.get("next") or url_for("index"))


@app.post("/logout")
@require_auth
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@require_auth
def index():
    tables = db.list_tables()
    return render_template("tables.html", tables=tables)


@app.get("/table/<table>")
@require_auth
def table_detail(table):
    page = max(int(request.args.get("page", 1)), 1)
    offset = (page - 1) * PAGE_SIZE
    rows = db.select(table, limit=PAGE_SIZE, offset=offset)
    total = db.count(table)
    columns = db.list_columns(table)
    pk = db.primary_key(table)
    pages = max(math.ceil(total / PAGE_SIZE), 1)
    return render_template(
        "table_detail.html",
        table=table, rows=rows, columns=columns, pk=pk, page=page, pages=pages, total=total,
    )


@app.post("/table/<table>/insert")
@require_auth
def table_insert(table):
    data = {k: v for k, v in request.form.items() if v != "" and k != "csrf_token"}
    db.insert(table, data)
    return redirect(url_for("table_detail", table=table))


@app.post("/table/<table>/update/<pk_value>")
@require_auth
def table_update(table, pk_value):
    pk = db.primary_key(table)
    if pk is None:
        abort(400, "Table sans clé primaire")
    data = {k: v for k, v in request.form.items() if v != "" and k not in (pk, "csrf_token")}
    db.update(table, data, {pk: pk_value})
    return redirect(url_for("table_detail", table=table))


@app.post("/table/<table>/delete/<pk_value>")
@require_auth
def table_delete(table, pk_value):
    pk = db.primary_key(table)
    if pk is None:
        abort(400, "Table sans clé primaire")
    db.delete(table, {pk: pk_value})
    return redirect(url_for("table_detail", table=table))


@app.get("/api/tables")
@require_auth
def api_list_tables():
    return jsonify(db.list_tables())


@app.get("/api/table/<table>")
@require_auth
def api_table_select(table):
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    return jsonify(db.select(table, limit=limit, offset=offset))


@app.post("/api/table/<table>")
@require_auth
@csrf.exempt
def api_table_insert(table):
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        abort(403)
    return jsonify(db.insert(table, request.get_json(force=True)))


@app.get("/health")
def health():
    return jsonify({"ok": db.health_check()})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
