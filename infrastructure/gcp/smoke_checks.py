#!/usr/bin/env python3
"""Run the 12 release smoke checks from OPERATIONS.md against the deployed sandbox API."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def run_checks(base_url: str) -> bool:
    base = base_url.rstrip("/")
    all_passed = True

    checks = [
        {
            "id": 1,
            "officer": "V14",
            "method": "POST",
            "path": "/assist/ask",
            "body": {"question": "How has G.O.Ms.No.109/2025 changed over time?"},
            "expected_patterns": [
                "G.O.Ms.No.295",
                "G.O.Ms.No.381",
                "G.O.Ms.No.396",
                "G.O.Ms.No.109",
                "In force on",
                "1 further link(s)",
            ],
            "description": "V14: How has G.O.Ms.No.109/2025 changed over time?",
        },
        {
            "id": 2,
            "officer": "V07",
            "method": "POST",
            "path": "/assist/ask",
            "body": {"question": "How has G.O.Ms.No.50/2021 changed over time?"},
            "expected_patterns": [
                "11-02-2016: G.O.Ms.No.19, Finance Department",
                "took effect",
            ],
            "description": "V07: How has G.O.Ms.No.50/2021 changed over time?",
        },
        {
            "id": 3,
            "officer": "V14",
            "method": "POST",
            "path": "/assist/ask",
            "body": {"question": "Which other departments refer to G.O.Ms.No.39/2019?"},
            "expected_patterns": [
                "Finance (FIN01): G.O.Ms.No.39, General Administration Department, dated 26-03-2019 amends G.O.Ms.No.150, Finance Department, dated 08-08-2016."
            ],
            "description": "V14: Which other departments refer to G.O.Ms.No.39/2019?",
        },
        {
            "id": 4,
            "officer": "V07",
            "method": "POST",
            "path": "/assist/ask",
            "body": {"question": "Which other departments refer to G.O.Ms.No.150/2016?"},
            "expected_patterns": [
                "General Administration (GAD01): G.O.Ms.No.39",
                "amends G.O.Ms.No.150",
            ],
            "description": "V07: Which other departments refer to G.O.Ms.No.150/2016?",
        },
        {
            "id": 5,
            "officer": "V21",
            "method": "POST",
            "path": "/assist/ask",
            "body": {"question": "Which other departments refer to G.O.Ms.No.20/2025?"},
            "expected_patterns": [
                "The link records show no record of another department linked to"
            ],
            "forbidden_patterns": ["GAZ"],
            "description": "V21: Which other departments refer to G.O.Ms.No.20/2025?",
        },
        {
            "id": 6,
            "officer": "V21",
            "method": "POST",
            "path": "/assist/ask",
            "body": {"question": "Which notes did B. Suresh Kumar sign?"},
            "expected_patterns": [
                "60 record(s) name B. Suresh Kumar (Joint Secretary, officer ID V20); the 12 most recent:"
            ],
            "description": "V21: Which notes did B. Suresh Kumar sign?",
        },
        {
            "id": 7,
            "officer": "V21",
            "method": "POST",
            "path": "/assist/ask",
            "body": {"question": "Notes signed by V20"},
            "expected_patterns": [
                "60 record(s) name B. Suresh Kumar (Joint Secretary, officer ID V20); the 12 most recent:"
            ],
            "description": "V21: Notes signed by V20",
        },
        {
            "id": 8,
            "officer": "V07",
            "method": "POST",
            "path": "/assist/ask",
            "body": {"question": "Which notes did B. Suresh Kumar sign?"},
            "expected_status": ["not_run"],
            "forbidden_patterns": ["60 record(s) name B. Suresh Kumar"],
            "description": "V07: Which notes did B. Suresh Kumar sign? (out of scope -> not_run)",
        },
        {
            "id": 9,
            "officer": "V21",
            "method": "POST",
            "path": "/assist/ask",
            "body": {
                "question": "How have the orders cited in File No.ESE01-EXAM0EXM/22/2017-EXAMS changed?"
            },
            "expected_patterns": [
                "File No.ESE01-EXAM0EXM/22/2017-EXAMS",
                "cites G.O.Ms.No.91",
                "G.O.Ms.No.91",
                "took effect",
                "G.O.Ms.No.1",
                "amended",
                "In force on",
            ],
            "description": "V21: How have orders cited in ESE01 file changed?",
        },
        {
            "id": 10,
            "officer": "V08",
            "method": "POST",
            "path": "/assist/ask",
            "body": {
                "question": "How have the orders cited in File No.ESE01-EXAM0EXM/22/2017-EXAMS changed?"
            },
            "expected_status": ["not_run"],
            "forbidden_patterns": ["cites G.O.Ms.No.91"],
            "description": "V08: How have orders cited in ESE01 file changed? (out of scope -> not_run)",
        },
        {
            "id": 11,
            "officer": "M01",
            "method": "GET",
            "path": "/assist/monitor?days=14",
            "body": None,
            "expected_keys": ["by_department", "by_role", "by_intent", "topics", "reasked"],
            "description": "M01: GET /assist/monitor?days=14 (200 with monitoring keys)",
        },
        {
            "id": 12,
            "officer": "V14",
            "method": "GET",
            "path": "/assist/monitor?days=14",
            "body": None,
            "expected_http_code": 404,
            "description": "V14: GET /assist/monitor?days=14 (404 unauthorized)",
        },
    ]

    for c in checks:
        print(f"\n--- Check #{c['id']}: {c['description']} ---")
        url = f"{base}{c['path']}"
        headers = {"X-Sandbox-User": c["officer"]}
        data = None
        if c["body"] is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(c["body"]).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers, method=c["method"])
        resp_code = 200
        resp_text = ""
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp_code = resp.status
                resp_text = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            resp_code = e.code
            resp_text = e.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"FAILED: Connection error: {e}")
            all_passed = False
            continue

        if "expected_http_code" in c:
            if resp_code == c["expected_http_code"]:
                print(f"PASS: HTTP {resp_code} (expected {c['expected_http_code']})")
            else:
                print(f"FAIL: Got HTTP {resp_code}, expected {c['expected_http_code']}. Response:\n{resp_text[:300]}")
                all_passed = False
            continue

        if resp_code != 200:
            print(f"FAIL: HTTP {resp_code} != 200. Response:\n{resp_text[:300]}")
            all_passed = False
            continue

        try:
            resp_json = json.loads(resp_text)
        except Exception:
            resp_json = None

        check_ok = True
        if "expected_keys" in c and resp_json:
            for k in c["expected_keys"]:
                if k not in resp_json:
                    print(f"FAIL: Missing expected key '{k}' in response")
                    check_ok = False
            if check_ok:
                print(f"PASS: All expected monitoring keys present: {c['expected_keys']}")

        if "expected_status" in c and resp_json:
            st = resp_json.get("status")
            if st in c["expected_status"]:
                print(f"PASS: Status '{st}' matches expected {c['expected_status']}")
            else:
                print(f"FAIL: Status '{st}' not in {c['expected_status']}")
                check_ok = False

        if "expected_patterns" in c:
            for pat in c["expected_patterns"]:
                if pat not in resp_text:
                    print(f"FAIL: Expected pattern not found: '{pat}'")
                    check_ok = False
                else:
                    print(f"PASS: Found pattern: '{pat}'")

        if "forbidden_patterns" in c:
            for pat in c["forbidden_patterns"]:
                if pat in resp_text:
                    print(f"FAIL: Forbidden pattern found: '{pat}'")
                    check_ok = False
                else:
                    print(f"PASS: Forbidden pattern absent: '{pat}'")

        if not check_ok:
            all_passed = False
            print(f"Response preview:\n{resp_text[:400]}")

    return all_passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8080", help="Base URL of sandbox API")
    args = parser.parse_args()
    print(f"Running 12 OPERATIONS.md smoke checks against {args.url}")
    ok = run_checks(args.url)
    if ok:
        print("\n==============================")
        print("ALL 12 SMOKE CHECKS PASSED!")
        print("==============================")
        return 0
    else:
        print("\n==============================")
        print("SOME SMOKE CHECKS FAILED.")
        print("==============================")
        return 1


if __name__ == "__main__":
    sys.exit(main())
