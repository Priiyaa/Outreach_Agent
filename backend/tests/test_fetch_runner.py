import threading

from app import cli
from app.services.fetch_runner import FetchRunner


def test_progress_and_output_are_visible_before_the_run_ends(monkeypatch):
    ranked, finish = threading.Event(), threading.Event()

    def fake_fetch(args, cfg, on_stage):
        print("120 jobs fetched")
        on_stage("New jobs are on the board", ready=True)
        ranked.set()
        finish.wait(5)
        on_stage("Re-ranking", ready=False)  # a later stage never takes 'ready' back

    monkeypatch.setattr(cli, "cmd_fetch", fake_fetch)
    monkeypatch.setattr(cli, "load_yaml", lambda name: {})
    runner = FetchRunner()
    assert runner.start() and not runner.start()  # one at a time
    assert ranked.wait(5)
    assert runner.running and runner.results_ready and runner.stage == "New jobs are on the board"
    assert "120 jobs fetched" in runner.output
    finish.set()
    for _ in range(100):
        if not runner.running:
            break
        threading.Event().wait(0.02)
    assert not runner.running and runner.results_ready and runner.error is None and runner.stage == ""
