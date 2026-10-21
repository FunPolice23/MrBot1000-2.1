"""Launch-lifecycle regression tests.

Covers the adopt-existing-listener pre-flight and the conditional stop():

1. When something already serves /v1/models on a port, BrainLaunchWorker adopts it
   (reports success, sets _proc=None, marks adopted) instead of spawning a second
   llama-server — which is what produced duplicate PIDs per port and
   nondeterministic request routing.
2. stop() on an adopted worker is a no-op: it must never terminate a server the
   app did not spawn (it may be shared with another manager / external).
"""
import os
import sys
import threading
from pathlib import Path

# ARCH-ENG-151: the repo root is derived from THIS file, never hardcoded — a
# literal path made the suite import the LIVE repo's modules under a clone.
os.chdir(str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QEventLoop
from http.server import BaseHTTPRequestHandler, HTTPServer


class _FakeServer(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/v1/models"):
            body = b'{"data": []}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication(sys.argv)
    yield a


@pytest.fixture()
def live_server(app):
    srv = HTTPServer(("127.0.0.1", 0), _FakeServer)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv, port
    srv.shutdown()


def _pump(worker, timeout_ms=8000, slots=None):
    loop = QEventLoop()
    if slots:
        for sig, fn in slots:
            sig.connect(fn)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()


def test_adopts_existing_listener_instead_of_spawning(app, live_server):
    from gui.widgets.dual_brain_control import BrainLaunchWorker
    srv, port = live_server
    result = {}
    worker = BrainLaunchWorker(
        "small",
        ["python", "-c", "raise SystemExit('SHOULD NOT SPAWN')"],
        port,
    )
    worker.launch_finished.connect(
        lambda ok, msg, proc: result.update(ok=ok, msg=msg, proc=proc))
    worker.start()
    _pump(worker)
    assert result.get("ok") is True
    assert result.get("proc") is None, "must not spawn a duplicate"
    assert worker.adopted is True
    assert "adopted" in result.get("msg", "")
    srv.shutdown()


def test_stop_is_noop_for_adopted_server(app, live_server):
    from gui.widgets.dual_brain_control import BrainLaunchWorker
    srv, port = live_server
    result = {}
    worker = BrainLaunchWorker(
        "small",
        ["python", "-c", "pass"],
        port,
    )
    worker.launch_finished.connect(
        lambda ok, msg, proc: result.update(ok=ok, msg=msg, proc=proc))
    worker.start()
    _pump(worker)
    assert worker.adopted is True
    # Adopted worker must refuse to terminate the live server.
    worker.stop()
    # The fake server is still serving after stop().
    import urllib.request
    alive = True
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/v1/models", timeout=2) as resp:
            alive = resp.status == 200
    except Exception:
        alive = False
    assert alive is True, "stop() must not kill an adopted (non-spawned) server"
    srv.shutdown()