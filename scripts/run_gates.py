#!/usr/bin/env python3
"""Run every pre-merge gate in one command.

  scripts/run_gates.py                      unit + cancel/resume + anonymous auth
  scripts/run_gates.py --dev-repo ../../synchotic    also parity against dev
  scripts/run_gates.py --quick              unit tests only, no network

Exits non-zero if any gate fails. Roughly 35 MB of downloads for the full set.
"""

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent


def python_bin() -> str:
    """Prefer the repo venv so this works via ssh with no shell activation."""
    venv = REPO / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def run(name: str, argv: list[str], verbose: bool) -> tuple[str, float, str]:
    print(f"\n=== {name} ===", flush=True)
    start = time.time()
    proc = subprocess.run(argv, cwd=REPO, capture_output=not verbose, text=True)
    elapsed = time.time() - start
    out = "" if verbose else (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        print(f"  PASS ({elapsed:.0f}s)")
    else:
        print(f"  FAIL ({elapsed:.0f}s)")
        for line in out.strip().splitlines()[-25:]:
            print(f"  | {line}")
    return ("PASS" if proc.returncode == 0 else "FAIL"), elapsed, out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dev-repo", type=Path, help="checkout to compare against for parity")
    ap.add_argument("--quick", action="store_true", help="unit tests only, no network")
    ap.add_argument("--verbose", action="store_true", help="stream child output live")
    args = ap.parse_args()

    py = python_bin()
    print(f"repo:   {REPO}")
    print(f"python: {py}")

    gates = [("unit tests", [py, "-m", "pytest", "tests/", "-q"])]
    if not args.quick:
        gates += [
            ("cancel and resume", [py, str(SCRIPTS / "cancel_resume_test.py")]),
            ("auth, anonymous tier", [py, str(SCRIPTS / "manual_auth_test.py"),
                                      "--mode", "anonymous"]),
        ]
        if args.dev_repo:
            tmp = Path(tempfile.mkdtemp(prefix="gates-parity-"))
            a, b = tmp / "dev.json", tmp / "branch.json"
            pc = str(SCRIPTS / "parity_check.py")
            gates += [
                ("parity, snapshot dev", [py, pc, "--snapshot", str(a),
                                          "--repo", str(args.dev_repo.resolve())]),
                ("parity, snapshot branch", [py, pc, "--snapshot", str(b), "--repo", str(REPO)]),
                ("parity, compare", [py, pc, "--compare", str(a), str(b)]),
            ]

    results = [(name, *run(name, argv, args.verbose)) for name, argv in gates]

    print("\n" + "=" * 52)
    for name, status, elapsed, _ in results:
        print(f"  {status}  {name:28s} {elapsed:5.0f}s")
    failed = [r for r in results if r[1] == "FAIL"]
    print("=" * 52)
    print(f"{len(results) - len(failed)}/{len(results)} gates passed")
    if args.quick:
        print("quick mode: network gates skipped, this is NOT a release gate")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
