Superseded code, kept for reference only. Nothing here is imported by `backend/`.

- `app.py`: the original Streamlit UI (slow: it re-ran the whole script and loaded every job on each click)
- `server.py` + `static/`: a Flask + plain-JS prototype that proved paging fixes the speed problem
- `test_streamlit_app.py`: tests for the Streamlit app
