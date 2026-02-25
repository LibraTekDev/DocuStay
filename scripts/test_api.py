"""
Backend API test script – pings each endpoint per module requirements.
Run with: python scripts/test_api.py (app must be running on http://127.0.0.1:8000)
"""
import sys
import os
import json
import time
import atexit
import subprocess
import urllib.request
import urllib.error
from urllib.parse import urljoin

BASE = "http://127.0.0.1:8000"
_server_process = None
passed = 0
failed = 0
owner_token = None
guest_token = None
property_id = None
stay_id = None
# Unique suffix per run so register doesn't hit "Email already registered"
SUFFIX = str(int(time.time()))
OWNER_EMAIL = f"owner_{SUFFIX}@test.docustay.demo"
GUEST_EMAIL = f"guest_{SUFFIX}@test.docustay.demo"


def req(method, path, body=None, token=None):
    url = urljoin(BASE, path)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        raise RuntimeError(f"HTTP {e.code}: {body}") from e


def test(name, fn):
    global passed, failed
    try:
        result = fn()
        if result is not None:
            print("  Response:", json.dumps(result, indent=2))
        print(f"  OK  {name}")
        passed += 1
        return True
    except Exception as e:
        print(f"  FAIL {name}: {e}")
        failed += 1
        return False


def wait_for_server(timeout=15):
    for _ in range(timeout):
        try:
            urllib.request.urlopen(BASE + "/health", timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def main():
    global owner_token, guest_token, property_id, stay_id, _server_process
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    # Optionally start server if not running
    if os.environ.get("USE_SERVER") != "1":
        try:
            urllib.request.urlopen(BASE + "/health", timeout=2)
        except Exception:
            print("Starting app on http://127.0.0.1:8000 ...")
            _server_process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
                cwd=root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            def kill():
                if _server_process:
                    _server_process.terminate()
            atexit.register(kill)
            if not wait_for_server():
                print("ERROR: Server did not start in time")
                sys.exit(1)

    print("DocuStay Backend API Tests\n" + "=" * 50)

    # Root & health (no auth)
    test("GET /", lambda: req("GET", "/"))
    test("GET /health", lambda: req("GET", "/health"))

    # Ensure DB tables exist (dev: run if startup had failed)
    try:
        req("POST", "/db-setup")
        print("  OK  POST /db-setup (tables/seed)")
    except Exception:
        pass  # may already exist

    # --- Module A: Auth ---
    print("\n--- Module A: Auth & Role Selection ---")
    test("POST /auth/register (owner)", lambda: req("POST", "/auth/register", {
        "email": OWNER_EMAIL,
        "password": "testpass123",
        "role": "owner",
    }))
    test("POST /auth/register (guest)", lambda: req("POST", "/auth/register", {
        "email": GUEST_EMAIL,
        "password": "testpass123",
        "role": "guest",
    }))

    resp = req("POST", "/auth/login", {"email": OWNER_EMAIL, "password": "testpass123"})
    owner_token = (resp.get("access_token") or "").strip()
    test("POST /auth/login (owner)", lambda: resp if owner_token else 1/0)

    resp = req("POST", "/auth/login", {"email": GUEST_EMAIL, "password": "testpass123"})
    guest_token = (resp.get("access_token") or "").strip()
    test("POST /auth/login (guest)", lambda: resp if guest_token else 1/0)

    test("GET /auth/me (owner)", lambda: req("GET", "/auth/me", token=owner_token))
    test("GET /auth/me (guest)", lambda: req("GET", "/auth/me", token=guest_token))

    # --- Module B1: Owner onboarding ---
    print("\n--- Module B1: Owner Onboarding ---")
    def add_property():
        global property_id
        r = req("POST", "/owners/properties", {
            "street": "123 Main St",
            "city": "Brooklyn",
            "state": "NY",
            "region_code": "NYC",
            "owner_occupied": False,
            "property_type": "entire_home",
        }, token=owner_token)
        property_id = r["id"]
        return r
    test("POST /owners/properties", add_property)
    test("GET /owners/properties", lambda: req("GET", "/owners/properties", token=owner_token))
    test("GET /owners/properties/{id}", lambda: req("GET", f"/owners/properties/{property_id}", token=owner_token))
    test("GET /owners/properties/{id}/utilities (Utility Bucket)", lambda: req("GET", f"/owners/properties/{property_id}/utilities", token=owner_token))

    # --- Module B2: Guest onboarding ---
    print("\n--- Module B2: Guest Onboarding ---")
    test("PUT /guests/profile", lambda: req("PUT", "/guests/profile", {
        "full_legal_name": "Jane Guest",
        "permanent_home_address": "456 Other Ave, Los Angeles, CA",
        "gps_checkin_acknowledgment": True,
    }, token=guest_token))
    test("GET /guests/profile", lambda: req("GET", "/guests/profile", token=guest_token))

    # --- Module C: Stay creation ---
    print("\n--- Module C: Stay Creation & Storage ---")
    def create_stay():
        global stay_id
        r = req("POST", "/stays/", {
            "property_id": property_id,
            "stay_start_date": "2025-02-01",
            "stay_end_date": "2025-02-14",
            "purpose_of_stay": "travel",
            "relationship_to_owner": "friend",
            "region_code": "NYC",
        }, token=guest_token)
        stay_id = r["id"]
        return r
    test("POST /stays/", create_stay)
    test("GET /stays/ (as guest)", lambda: req("GET", "/stays/?as_guest=true", token=guest_token))
    test("GET /stays/ (as owner)", lambda: req("GET", "/stays/?as_guest=false", token=owner_token))
    test("GET /stays/{id}", lambda: req("GET", f"/stays/{stay_id}", token=guest_token))

    # --- Module D: Region rules ---
    print("\n--- Module D: Region Rules ---")
    test("GET /region-rules/", lambda: req("GET", "/region-rules/", token=owner_token))
    test("GET /region-rules/NYC", lambda: req("GET", "/region-rules/NYC", token=owner_token))
    test("GET /region-rules/CA", lambda: req("GET", "/region-rules/CA", token=owner_token))

    # --- Module E: JLE ---
    print("\n--- Module E: Mini Jurisdiction Logic Resolver ---")
    test("POST /jle/resolve", lambda: req("POST", "/jle/resolve", {
        "region_code": "NYC",
        "stay_duration_days": 14,
        "owner_occupied": False,
        "property_type": "entire_home",
        "guest_has_permanent_address": True,
    }, token=owner_token))

    # --- Module F: Dashboard ---
    print("\n--- Module F: Legal Restrictions & Law Display ---")
    test("GET /dashboard/owner/stays", lambda: req("GET", "/dashboard/owner/stays", token=owner_token))
    test("GET /dashboard/guest/stays", lambda: req("GET", "/dashboard/guest/stays", token=guest_token))

    # --- Module G/H: Notifications ---
    print("\n--- Module G & H: Stay Timer / Notifications ---")
    test("POST /notifications/run-stay-warnings", lambda: req("POST", "/notifications/run-stay-warnings", token=owner_token))

    # --- Summary ---
    print("\n" + "=" * 50)
    print(f"Passed: {passed}  Failed: {failed}  Total: {passed + failed}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
