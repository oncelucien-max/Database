import functools
import math
import os

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for
from werkzeug.security import check_password_hash

from db_manager import DbConfig, DbManager, UnknownTableError

app = Flask(__name__)
db = DbManager(DbConfig.from_env())

ADMIN_USER = os.environ["ADMIN_USER"]
ADMIN_PASSWORD_HASH = os.environ["ADMIN_PASSWORD_HASH"]
PAGE_SIZE = int(os.environ.get("ADMIN_PAGE_SIZE", 25))


def require_auth(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != ADMIN_USER or not check_password_hash(
            ADMIN_PASSWORD_HASH, auth.password
        ):
            return (
                "Authentification requise",
                401,
                {"WWW-Authenticate": 'Basic realm="db-admin"'},
            )
        return view(*args, **kwargs)

    return wrapped


@app.errorhandler(UnknownTableError)
def handle_unknown_table(exc):
    return jsonify({"error": f"Table inconnue: {exc}"}), 404


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
        table=table,
        rows=rows,
        columns=columns,
        pk=pk,
        page=page,
        pages=pages,
        total=total,
    )


@app.post("/table/<table>/insert")
@require_auth
def table_insert(table):
    data = {k: v for k, v in request.form.items() if v != ""}
    db.insert(table, data)
    return redirect(url_for("table_detail", table=table))


@app.post("/table/<table>/update/<pk_value>")
@require_auth
def table_update(table, pk_value):
    pk = db.primary_key(table)
    if pk is None:
        abort(400, "Table sans clé primaire")
    data = {k: v for k, v in request.form.items() if v != "" and k != pk}
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
def api_table_insert(table):
    return jsonify(db.insert(table, request.get_json(force=True)))


@app.get("/health")
def health():
    return jsonify({"ok": db.health_check()})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
