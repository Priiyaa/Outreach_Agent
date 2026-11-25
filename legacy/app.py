"""Streamlit front end. Run:  streamlit run app.py

All logic lives in src/ (src/views.py for queries and edits); this file only draws the page."""
import contextlib
import io
from argparse import Namespace

import streamlit as st

from src import main as cli
from src.classify import EXPERIENCE_VALUES, SIZE_VALUES
from src.db import DB, SPONSORSHIP_VALUES
from src.views import (
    LABEL_TO_STATUS, STATUS_LABELS, apply_company_edits, apply_job_edits, company_rows, jobs_to_csv, query_jobs,
)

st.set_page_config(page_title="Job search", layout="wide")


def get_db() -> DB:
    return DB(cli.ROOT / cli.load_yaml("config.yaml")["db_path"])


def ss_default(key, value):
    if key not in st.session_state:
        st.session_state[key] = value


ss_default("gen", 0)          # bumping this resets the editors after a save (new widget key = no pending edits)
ss_default("cgen", 0)
ss_default("flash", None)     # (level, message) shown after a save
ss_default("job_ids", [])     # row position -> job id for the table drawn on the previous run
ss_default("company_keys", [])


# ---- save callbacks: run before the rerun, so job_ids/company_keys still describe the table the user edited ----

def save_job_edits():
    edited = st.session_state.get(f"jobs_editor_{st.session_state.gen}", {}).get("edited_rows", {})
    changes = {}
    for pos, delta in edited.items():
        change = {}
        if "Status" in delta:
            change["status"] = delta["Status"]
        if "Sponsors?" in delta:
            change["sponsorship"] = delta["Sponsors?"]
        if "Sponsorship note" in delta:
            change["sponsorship_note"] = delta["Sponsorship note"]
        if change:
            changes[st.session_state.job_ids[int(pos)]] = change
    try:
        n = apply_job_edits(get_db(), changes)
        st.session_state.flash = ("success", f"Saved changes to {n} job(s).") if n else None
    except Exception as exc:  # show it instead of crashing the app
        st.session_state.flash = ("error", f"Nothing saved: {exc}")
    st.session_state.gen += 1


def save_company_edits():
    edited = st.session_state.get(f"companies_editor_{st.session_state.cgen}", {}).get("edited_rows", {})
    changes = {st.session_state.company_keys[int(pos)]: {"size": d["Size"]} for pos, d in edited.items() if "Size" in d}
    try:
        n = apply_company_edits(get_db(), changes)
        st.session_state.flash = ("success", f"Saved size for {n} company(ies). Their jobs moved to the new bucket.") if n else None
    except Exception as exc:
        st.session_state.flash = ("error", f"Nothing saved: {exc}")
    st.session_state.cgen += 1


# ---- sidebar: fetch + filters ------------------------------------------------------------------------------

with st.sidebar:
    st.header("Fetch")
    if st.button("Fetch new jobs now", help="Runs the same thing as `python -m src.main fetch`, then labels the jobs."):
        out = io.StringIO()
        with st.spinner("Fetching every board and list. This can take a few minutes..."):
            try:
                with contextlib.redirect_stdout(out):
                    cli.cmd_fetch(Namespace(source=None, company=None), cli.load_yaml("config.yaml"))
                st.success("Done.")
            except SystemExit as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(f"Fetch failed: {exc}")
        st.code(out.getvalue() or "(no output)")

    st.header("Filters")
    experience = st.multiselect("Experience", EXPERIENCE_VALUES, default=EXPERIENCE_VALUES[:2],
                                help="New grad = 0-3 years, Experienced = 3+. 'Unclear' = no signal in the posting.")
    size = st.multiselect("Company size", SIZE_VALUES, default=SIZE_VALUES,
                          help="Under 200 = Startup/Small, 200-5,000 = Mid-size, over 5,000 = Big.")
    sponsorship = st.multiselect("Sponsors visas?", list(SPONSORSHIP_VALUES), default=list(SPONSORSHIP_VALUES))
    status = st.multiselect("Status", list(STATUS_LABELS), default=["new", "saved", "applied"],
                            format_func=STATUS_LABELS.get)
    cs_related_only = st.toggle(
        "Computer Science-related roles only", value=True,
        help="Matches technical responsibilities in full job descriptions when available; title and department are used when a feed has no description.",
    )
    search = st.text_input("Search title or company")
    location = st.text_input("Location contains", help="Comma-separated, e.g. seattle, chicago, remote")
    since_days = st.number_input("First seen in the last N days (0 = any)", min_value=0, value=0, step=1)
    us_only = st.toggle("US jobs only", value=True, help="Remote and blank locations are kept.")
    include_internships = st.toggle("Include internships", value=False)
    include_closed = st.toggle("Include closed postings", value=False)

db = get_db()
rows = query_jobs(
    db, us_only=us_only, include_internships=include_internships, include_closed=include_closed,
    search=search, location=location, since_days=int(since_days) or None,
    cs_related_only=cs_related_only,
    experience=experience, size=size, sponsorship=sponsorship, status=status,
)

st.title("Job search")
if st.session_state.flash:
    level, message = st.session_state.flash
    getattr(st, level)(message)
    st.session_state.flash = None

tab_jobs, tab_companies = st.tabs(["Jobs", "Companies"])

with tab_jobs:
    if not rows:
        st.info("No jobs match. Loosen the filters, or press 'Fetch new jobs now' if the database is empty.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Jobs shown", len(rows))
        c2.metric("New grad", sum(r["experience"] == "New grad" for r in rows))
        c3.metric("Sponsor: Yes", sum(r["sponsorship"] == "Yes" for r in rows))
        c4.metric("Not yet applied", sum(r["status"] in ("new", "saved") for r in rows))

        st.session_state.job_ids = [r["id"] for r in rows]
        table = [
            {
                "Company": r["company"], "Title": r["title"], "Location": r["location"] or "-",
                "CS role evidence": r["cs_role_evidence"],
                "Experience": r["experience"], "Size": r["size"],
                "Sponsors?": r["sponsorship"], "Sponsorship note": r["sponsorship_note"],
                "Status": STATUS_LABELS.get(r["status"], r["status"]),
                "Link": r["url"], "First seen": (r["first_seen"] or "")[:10],
            }
            for r in rows
        ]
        st.caption("Edit Sponsors?, Sponsorship note or Status in the table, then press Save. A sponsorship you set "
                   "is locked: later fetches never change it. It applies to that one job only.")
        st.data_editor(
            table, key=f"jobs_editor_{st.session_state.gen}", hide_index=True, use_container_width=True,
            height=560, num_rows="fixed",
            disabled=["Company", "Title", "CS role evidence", "Location", "Experience", "Size", "Link", "First seen"],
            column_config={
                "Sponsors?": st.column_config.SelectboxColumn(options=list(SPONSORSHIP_VALUES), required=True),
                "Status": st.column_config.SelectboxColumn(options=list(LABEL_TO_STATUS), required=True),
                "Sponsorship note": st.column_config.TextColumn(width="medium"),
                "Link": st.column_config.LinkColumn(display_text="open"),
            },
        )
        pending = st.session_state.get(f"jobs_editor_{st.session_state.gen}", {}).get("edited_rows", {})
        left, right, _ = st.columns([1, 1, 3])
        left.button(f"Save changes ({len(pending)})" if pending else "Save changes", type="primary",
                    disabled=not pending, on_click=save_job_edits)
        right.download_button("Download filtered CSV", jobs_to_csv(rows), file_name="jobs_filtered.csv", mime="text/csv")

        with st.expander("Set Sponsors? for every job currently shown"):
            st.write(f"This changes all {len(rows)} jobs in the table above, and locks them as manual.")
            value = st.selectbox("Set to", list(SPONSORSHIP_VALUES), key="bulk_value")
            sure = st.checkbox(f"Yes, set {len(rows)} jobs to '{value}'", key="bulk_sure")
            if st.button("Apply to all shown", disabled=not sure):
                db.bulk_set_sponsorship([r["id"] for r in rows], value)
                st.session_state.flash = ("success", f"Set {len(rows)} jobs to {value}.")
                st.session_state.gen += 1
                st.rerun()

with tab_companies:
    st.caption("Sizes come from company_sizes.yaml, headcount in job text, then Claude, then default to Startup/Small. "
               "Change one here and it sticks (source becomes 'manual'); its jobs move bucket immediately.")
    only_guessed = st.toggle("Only show defaults and guesses", value=False,
                             help="Hides sizes you set by hand or that came from your seed list.")
    crows = company_rows(db)
    if only_guessed:
        crows = [r for r in crows if r["size_source"] in ("default", "unknown", "claude", "openings", "unsized")]
    st.session_state.company_keys = [r["key"] for r in crows]
    st.data_editor(
        [{"Company": r["company"], "Size": r["size"], "Source": r["size_source"],
          "Employees": r["employees"], "Open jobs": r["open_jobs"]} for r in crows],
        key=f"companies_editor_{st.session_state.cgen}", hide_index=True, use_container_width=True, height=560,
        disabled=["Company", "Source", "Employees", "Open jobs"], num_rows="fixed",
        column_config={"Size": st.column_config.SelectboxColumn(options=SIZE_VALUES, required=True)},
    )
    cpending = st.session_state.get(f"companies_editor_{st.session_state.cgen}", {}).get("edited_rows", {})
    st.button("Save company sizes", type="primary", disabled=not cpending, on_click=save_company_edits)
