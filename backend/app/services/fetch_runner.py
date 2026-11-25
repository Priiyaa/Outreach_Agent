"""Runs the fetch command in a background thread so the API can answer while it works (it takes minutes).
Output and the current stage are readable while it runs, so the board can show progress and refresh as soon as
results are ready instead of waiting for the slow LLM check at the end."""
from __future__ import annotations

import contextlib
import io
import threading
from argparse import Namespace
from typing import Optional

from .. import cli


class _LiveOutput(io.TextIOBase):
    """A stdout stand-in that the API can read while the fetch is still writing to it."""

    def __init__(self, lock: threading.Lock) -> None:
        self._lock, self._parts = lock, []

    def write(self, text: str) -> int:
        with self._lock:
            self._parts.append(text)
        return len(text)

    def getvalue(self) -> str:
        with self._lock:
            return "".join(self._parts)


class FetchRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._out: Optional[_LiveOutput] = None
        self.running = False
        self.error: Optional[str] = None
        self.stage = ""
        self.results_ready = False

    @property
    def output(self) -> str:
        return self._out.getvalue() if self._out else ""

    def start(self) -> bool:
        """Start a fetch unless one is already running. Returns False if one was."""
        with self._lock:
            if self.running:
                return False
            self.running, self.error, self.stage, self.results_ready = True, None, "Starting", False
            self._out = _LiveOutput(threading.Lock())
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def _on_stage(self, text: str, ready: bool = False) -> None:
        with self._lock:
            self.stage = text
            self.results_ready = self.results_ready or ready

    def _run(self) -> None:
        error = None
        try:
            with contextlib.redirect_stdout(self._out):
                cli.cmd_fetch(Namespace(source=None, company=None), cli.load_yaml("config.yaml"), on_stage=self._on_stage)
        except BaseException as exc:  # SystemExit too: the CLI exits on a config problem
            error = str(exc) or "Fetch failed"
        with self._lock:
            self.error, self.running, self.stage = error, False, ""


fetch_runner = FetchRunner()
