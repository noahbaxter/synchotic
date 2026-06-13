"""Thin requests-based client for the rclone rc API."""
from typing import Optional
import requests


class RcClient:
    def __init__(self, address: str, timeout: float = 30.0):
        self.address = address.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, payload: dict) -> dict:
        r = requests.post(f"{self.address}{path}", json=payload, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def copyid_async(self, fs: str, file_id: str, dest: str) -> int:
        """Queue a copyid job. dest ending in '/' means 'into this dir, keep name'."""
        resp = self._post("/backend/command", {
            "command": "copyid",
            "fs": fs,
            "arg": [file_id, dest],
            "opt": {"drive-acknowledge-abuse": "true"},
            "_async": True,
        })
        return resp["jobid"]

    def job_status(self, jobid: int) -> dict:
        return self._post("/job/status", {"jobid": jobid})

    def core_stats(self, group: Optional[str] = None) -> dict:
        return self._post("/core/stats", {"group": group} if group else {})

    def stop_job(self, jobid: int) -> None:
        try:
            self._post("/job/stop", {"jobid": jobid})
        except Exception:
            pass
