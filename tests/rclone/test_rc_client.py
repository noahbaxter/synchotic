# tests/rclone/test_rc_client.py
import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import pytest
from src.rclone.rc_client import RcClient

class Handler(BaseHTTPRequestHandler):
    routes = {}
    def log_message(self, *a): pass
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        resp = Handler.routes.get(self.path, lambda b: {})(body)
        data = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()

def test_copyid_async_returns_jobid(server):
    Handler.routes["/backend/command"] = lambda b: {"jobid": 7} if b.get("_async") else {}
    c = RcClient(server)
    jobid = c.copyid_async("drive:", "FILEID", "/tmp/out/")
    assert jobid == 7

def test_job_status_and_acknowledge_abuse_opt(server):
    seen = {}
    def cmd(b): seen.update(b); return {"jobid": 1}
    Handler.routes["/backend/command"] = cmd
    Handler.routes["/job/status"] = lambda b: {"finished": True, "success": True}
    c = RcClient(server)
    c.copyid_async("drive:", "ID", "/tmp/")
    assert seen["opt"]["drive-acknowledge-abuse"] == "true"
    st = c.job_status(1)
    assert st["finished"] and st["success"]
