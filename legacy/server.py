"""Fast front end (Flask + one static page). Run:  python server.py   then open http://127.0.0.1:5000

Same logic as app.py: all queries and edits live in src/views.py; this file only exposes them as JSON."""
import contextlib
import io
import threading
from argparse import Namespace

from flask import Flask, Response, jsonify, request

from src import main as cli
from src.classify import EXPERIENCE_VALUES, SIZE_VALUES
from src.db import DB, SPONSORSHIP_VALUES
from src.views import STATUS_LABELS, apply_company_edits, apply_job_edits, company_rows, jobs_to_csv, query_jobs

app = Flask(__name__, static_folder="static", static_url_path="/static")
PAGE_SIZE = 500  # rows sent to the browser; stats and CSV cover every match
fetch_state = {"running": False, "output": "", "error": None}


def get_db() -> DB:
    return DB(cli.ROOT / cli.load_yaml("config.yaml")["db_path"])


def list_arg(name):
    return request.args.getlist(name) or None


def run_query(limit=None):
    a = request.args
    return query_jobs(
        get_db(), us_only=a.get("us_only", "1") == "1", include_internships=a.get("internships") == "1",
        include_closed=a.get("closed") == "1", search=a.get("search", ""), location=a.get("location", ""),
        since_days=int(a.get("since_days") or 0) or None, cs_related_only=a.get("cs_only", "1") == "1",
        experience=list_arg("experience"), size=list_arg("size"), sponsorship=list_arg("sponsorship"),
        status=list_arg("status"), limit=limit,
    )


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/meta")
def meta():
    return jsonify(experience=EXPERIENCE_VALUES, size=SIZE_VALUES, sponsorship=list(SPONSORSHIP_VALUES),
                   status=STATUS_LABELS)


@app.get("/api/jobs")
def jobs():
    rows = run_query()
    keep = ("id", "company", "title", "location", "cs_role_evidence", "experience", "size", "sponsorship",
            "sponsorship_note", "status", "url", "first_seen")
    stats = {"total": len(rows), "new_grad": sum(r["experience"] == "New grad" for r in rows),
             "sponsor_yes": sum(r["sponsorship"] == "Yes" for r in rows),
             "not_applied": sum(r["status"] in ("new", "saved") for r in rows)}
    return jsonify(stats=stats, rows=[{k: r[k] for k in keep} for r in rows[:PAGE_SIZE]])


@app.get("/api/jobs.csv")
def jobs_csv():
    return Response(jobs_to_csv(run_query()), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=jobs_filtered.csv"})


@app.post("/api/jobs/edit")
def edit_jobs():
    try:
        return jsonify(saved=apply_job_edits(get_db(), request.get_json()))
    except (ValueError, KeyError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/jobs/bulk-sponsorship")
def bulk_sponsorship():
    value = request.args.get("value")
    if value not in SPONSORSHIP_VALUES:
        return jsonify(error="invalid sponsorship"), 400
    return jsonify(saved=get_db().bulk_set_sponsorship([r["id"] for r in run_query()], value))


@app.get("/api/companies")
def companies():
    return jsonify(company_rows(get_db()))


@app.post("/api/companies/edit")
def edit_companies():
    try:
        return jsonify(saved=apply_company_edits(get_db(), request.get_json()))
    except (ValueError, KeyError) as exc:
        return jsonify(error=str(exc)), 400


def _fetch():
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            cli.cmd_fetch(Namespace(source=None, company=None), cli.load_yaml("config.yaml"))
    except BaseException as exc:  # SystemExit too
        fetch_state["error"] = str(exc) or "Fetch failed"
    fetch_state.update(running=False, output=out.getvalue())


@app.post("/api/fetch")
def start_fetch():
    if fetch_state["running"]:
        return jsonify(error="already running"), 409
    fetch_state.update(running=True, output="", error=None)
    threading.Thread(target=_fetch, daemon=True).start()
    return jsonify(started=True)


@app.get("/api/fetch")
def fetch_status():
    return jsonify(fetch_state)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
