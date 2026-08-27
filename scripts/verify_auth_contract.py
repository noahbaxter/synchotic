"""Check Google's real authorization rule for Drive files.list.

tests/integration/test_drive_auth_contract.py encodes a rule as a stub. This
script proves that rule against live Google, so the stub cannot quietly drift
from reality. Read-only: lists one public setlist folder, three ways.

    GOOGLE_API_KEY=<key> python3 scripts/verify_auth_contract.py <dm-sync-dir>

Needs a BYOC credentials.json + token.json in that dir, from a Cloud project
other than the key's. Prints status codes only, never credentials.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

FOLDER_ID = "1bo9XGzSa2qmvWfQRzDtLDnAzyhZnshKg"  # "Misc", a public setlist
FILES_URL = "https://www.googleapis.com/drive/v3/files"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def refresh_access_token(creds_path, token_path):
    """Refresh via credentials.json when present, else via the token's own client.

    A non-BYOC install has no credentials.json: it signed in with the embedded
    client, and token.json carries that client_id/secret. Supporting both lets
    this run on any install, which matters because the same-project case is the
    one that proves why non-BYOC users never see the bug.
    """
    saved = json.loads(open(token_path).read())
    try:
        creds = json.loads(open(creds_path).read())
        inst = creds.get("installed") or creds.get("web")
    except FileNotFoundError:
        inst = {"client_id": saved["client_id"], "client_secret": saved["client_secret"]}

    body = urllib.parse.urlencode({
        "client_id": inst["client_id"],
        "client_secret": inst["client_secret"],
        "refresh_token": saved["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()

    req = urllib.request.Request(TOKEN_URL, data=body)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["access_token"], inst["client_id"].split("-")[0]


def attempt(label, key, token):
    params = {"q": f"'{FOLDER_ID}' in parents and trashed = false", "pageSize": 1}
    if key:
        params["key"] = key
    req = urllib.request.Request(f"{FILES_URL}?{urllib.parse.urlencode(params)}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"  {label:<24} {r.status} OK")
            return r.status
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read()).get("error", {}).get("message", "")
        print(f"  {label:<24} {e.code} {detail}")
        return e.code


def main():
    key = os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        sys.exit("set GOOGLE_API_KEY to the key baked into release builds")
    if len(sys.argv) < 2:
        sys.exit(f"usage: {sys.argv[0]} <dm-sync-dir>")

    base = sys.argv[1]
    token, project = refresh_access_token(f"{base}/credentials.json", f"{base}/token.json")
    same_project = os.environ.get("SAME_PROJECT") == "1"
    print(f"token from Cloud project {project}"
          f" ({'same project as the key' if same_project else 'differs from the key'})\n")

    results = {
        "key + token": attempt("key + token", key, token),
        "token only": attempt("token only", None, token),
        "key only": attempt("key only", key, None),
        "neither": attempt("neither", None, None),
    }

    print()
    # Same-project creds are the configuration every non-BYOC user runs, and
    # Google accepts the pair there. Pass SAME_PROJECT=1 to assert that instead.
    expected = {"key + token": 200 if same_project else 400,
                "token only": 200, "key only": 200, "neither": 403}
    ok = results == expected
    for case, want in expected.items():
        got = results[case]
        print(f"  {'PASS' if got == want else 'FAIL'}  {case:<14} expected {want}, got {got}")
    print("\ncontract holds" if ok else "\nCONTRACT DIFFERS - update the stub")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
