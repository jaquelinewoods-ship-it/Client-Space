#!/usr/bin/env python3
"""
Qualtex — Jira Polaris (QGOMR) to Asana Migration Script
==========================================================
Migrates requirements from the Qualtex Jira Polaris discovery board (QGOMR)
into the Qualtex Asana project.

Reference: clients/monsterplumb/asana-refresh/ (milestone-based grouping)
Qualtex grouping dimension: Programme (P1–P36)

Usage:
    export JIRA_EMAIL=your@email.com
    export JIRA_API_TOKEN=your_jira_token
    export ASANA_PAT=your_asana_pat
    python3 migrate.py [--dry-run] [--status "Awaiting Client Approval"]

Options:
    --dry-run       Print tasks that would be created without writing to Asana
    --status        Jira status to migrate (default: "Awaiting Client Approval")
    --start-from    QGOMR key to resume from (e.g. QGOMR-80) if run was interrupted
"""

import argparse
import json
import os
import re
import sys
import time
from base64 import b64encode

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

JIRA_BASE_URL = "https://rixxo-hq.atlassian.net"
JIRA_PROJECT_KEY = "QGOMR"
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")

ASANA_BASE_URL = "https://app.asana.com/api/1.0"
ASANA_PAT = os.environ.get("ASANA_PAT", "")
ASANA_PROJECT_GID = "1215246319505493"
ASANA_SECTION_GID = "1215246319835973"  # Requirements section

# ---------------------------------------------------------------------------
# Asana field GIDs
# ---------------------------------------------------------------------------

FIELD_REQUIREMENT_STATUS = "1211730436704714"
FIELD_PROGRAMME = "1215246319835982"

STATUS_AWAITING_CLIENT_APPROVAL = "1211730436704720"

# Programme option GIDs — keyed by P-number string e.g. "P1"
PROGRAMME_OPTION_GIDS = {
    "P1":  "1215246319835983",
    "P2":  "1215246319835984",
    "P3":  "1215246319835985",
    "P4":  "1215246319835986",
    "P5":  "1215246319835987",
    "P7":  "1215246319835988",
    "P8":  "1215246319835989",
    "P9":  "1215246319835990",
    "P10": "1215246319835991",
    "P11": "1215246319835992",
    "P12": "1215246319835993",
    "P13": "1215246319835994",
    "P14": "1215246319835995",
    "P15": "1215246319835996",
    "P16": "1215246319835997",
    "P17": "1215246319835998",
    "P18": "1215246319836001",
    "P19": "1215246319836002",
    "P20": "1215246319836003",
    "P21": "1215246319836004",
    "P22": "1215246319836005",
    "P23": "1215246319836006",
    "P24": "1215246319836007",
    "P25": "1215246319836008",
    "P26": "1215246319836009",
    "P27": "1215246319836010",
    "P28": "1215246319836011",
    "P29": "1215246319836012",
    "P30": "1215246319836013",
    "P31": "1215246319836014",
    "P32": "1215246319836015",
    "P33": "1215246319836016",
    "P34": "1215246319836017",
    "P35": "1215246319836018",
    "P36": "1215246319835999",
}

# Jira status → Asana Requirement Status GID
STATUS_MAP = {
    "awaiting client approval": STATUS_AWAITING_CLIENT_APPROVAL,
    "ready for sa":             "1211730436704719",
    "needs a brief":            "1211730436704717",
    "in delivery":              "1211730436704723",
    "client review":            "1211730436704718",
    "done":                     "1215072783102973",
    "closed":                   "1215072783102974",
}

# ---------------------------------------------------------------------------
# Jira helpers
# ---------------------------------------------------------------------------

def jira_auth_header():
    token = b64encode(f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def fetch_jira_issues(status: str) -> list[dict]:
    """Fetch all issues from QGOMR with the given status."""
    jql = f'project = "{JIRA_PROJECT_KEY}" AND status = "{status}" ORDER BY created ASC'
    url = f"{JIRA_BASE_URL}/rest/api/3/search"
    fields = "summary,status,description"
    issues = []
    start_at = 0
    max_results = 100

    while True:
        params = {
            "jql": jql,
            "fields": fields,
            "startAt": start_at,
            "maxResults": max_results,
        }
        resp = requests.get(url, headers=jira_auth_header(), params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("issues", [])
        issues.extend(batch)
        print(f"  Fetched {len(issues)}/{data['total']} issues from Jira...")
        if start_at + max_results >= data["total"]:
            break
        start_at += max_results

    return issues


def extract_programme(description: str) -> str | None:
    """Extract the P-number from a Jira issue description."""
    if not description:
        return None

    # ADF plain text may come through as nested dicts or as a string
    text = _adf_to_text(description) if isinstance(description, dict) else (description or "")

    # Pattern 1: **Programme:** P3 (LabelSystem)
    m = re.search(r"Programme:\s*(P\d+)", text, re.IGNORECASE)
    if m:
        return m.group(1)

    # Pattern 2: P1 → P3 (delivering into P3)
    m = re.search(r"P\d+\s*[→->]+\s*(P\d+)", text)
    if m:
        return m.group(1)

    return None


def _adf_to_text(node: dict | list | str, _depth: int = 0) -> str:
    """Recursively extract plain text from an Atlassian Document Format node."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_to_text(n, _depth) for n in node)
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return node.get("text", "")
    parts = []
    for child in node.get("content", []):
        parts.append(_adf_to_text(child, _depth + 1))
    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Asana helpers
# ---------------------------------------------------------------------------

def asana_headers():
    return {
        "Authorization": f"Bearer {ASANA_PAT}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def get_existing_task_names() -> set[str]:
    """Return the set of task names already in the Asana project section."""
    url = f"{ASANA_BASE_URL}/sections/{ASANA_SECTION_GID}/tasks"
    params = {"opt_fields": "name", "limit": 100}
    names = set()
    while True:
        resp = requests.get(url, headers=asana_headers(), params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for task in data.get("data", []):
            names.add(task["name"])
        next_page = data.get("next_page")
        if not next_page:
            break
        params["offset"] = next_page["offset"]
    return names


def create_asana_task(name: str, notes: str, programme_gid: str | None, status_gid: str) -> dict:
    """Create a single task in Asana and return the response data."""
    custom_fields = {FIELD_REQUIREMENT_STATUS: status_gid}
    if programme_gid:
        custom_fields[FIELD_PROGRAMME] = programme_gid

    payload = {
        "data": {
            "name": name,
            "notes": notes,
            "projects": [ASANA_PROJECT_GID],
            "memberships": [
                {"project": ASANA_PROJECT_GID, "section": ASANA_SECTION_GID}
            ],
            "custom_fields": custom_fields,
        }
    }
    url = f"{ASANA_BASE_URL}/tasks"
    resp = requests.post(url, headers=asana_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"]


# ---------------------------------------------------------------------------
# Build task payload from a Jira issue
# ---------------------------------------------------------------------------

def build_task(issue: dict) -> dict:
    key = issue["key"]
    fields = issue["fields"]
    name = fields["summary"].strip()

    # Sanitise special characters that break Asana's XML parser
    name = name.replace("→", "to").replace("←", "to")

    desc = fields.get("description") or ""
    programme = extract_programme(desc)
    programme_gid = PROGRAMME_OPTION_GIDS.get(programme) if programme else None

    jira_status = fields["status"]["name"].lower()
    status_gid = STATUS_MAP.get(jira_status, STATUS_AWAITING_CLIENT_APPROVAL)

    jira_url = f"{JIRA_BASE_URL}/browse/{key}"

    # CRITICAL: Copy the Jira description verbatim — word for word, no rewriting, no summarising.
    # The description is the client-facing requirement record and must be preserved exactly as written.
    # ADF content is converted to plain text; markdown-style descriptions are used as-is.
    desc_text = _adf_to_text(desc) if isinstance(desc, dict) else (desc or "")
    desc_text = desc_text.strip()

    notes = f"Jira: {key} — {jira_url}"
    if desc_text:
        notes += f"\n\n{desc_text}"

    if not programme_gid and programme:
        notes += f"\n\n⚠️ Programme {programme} has no matching Asana option — set manually."

    return {
        "name": name,
        "notes": notes,
        "programme_gid": programme_gid,
        "status_gid": status_gid,
        "jira_key": key,
        "programme": programme,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Migrate Jira QGOMR → Asana")
    parser.add_argument("--dry-run", action="store_true", help="Print tasks without creating them")
    parser.add_argument("--status", default="Awaiting Client Approval", help="Jira status to migrate")
    parser.add_argument("--start-from", default=None, help="Resume from this Jira key (e.g. QGOMR-80)")
    args = parser.parse_args()

    # Validate credentials
    if not args.dry_run:
        missing = []
        if not JIRA_EMAIL:
            missing.append("JIRA_EMAIL")
        if not JIRA_API_TOKEN:
            missing.append("JIRA_API_TOKEN")
        if not ASANA_PAT:
            missing.append("ASANA_PAT")
        if missing:
            print(f"❌ Missing environment variables: {', '.join(missing)}")
            sys.exit(1)

    print(f"🔍 Fetching Jira issues — project={JIRA_PROJECT_KEY}, status='{args.status}'")
    issues = fetch_jira_issues(args.status)
    print(f"   Found {len(issues)} issues.\n")

    tasks = [build_task(i) for i in issues]

    # Resume support
    if args.start_from:
        keys = [t["jira_key"] for t in tasks]
        if args.start_from in keys:
            idx = keys.index(args.start_from)
            tasks = tasks[idx:]
            print(f"▶️  Resuming from {args.start_from} ({len(tasks)} tasks remaining)\n")
        else:
            print(f"⚠️  --start-from key {args.start_from} not found in results; running all tasks.\n")

    # Deduplication — skip tasks already in Asana
    if not args.dry_run:
        print("🔎 Checking for existing tasks in Asana...")
        existing = get_existing_task_names()
        print(f"   {len(existing)} tasks already present.\n")
    else:
        existing = set()

    created = 0
    skipped = 0
    failed = []
    unmapped = []

    for task in tasks:
        name = task["name"]
        key = task["jira_key"]

        if name in existing:
            print(f"   ⏭️  SKIP (already exists): {key} — {name}")
            skipped += 1
            continue

        if not task["programme_gid"] and task["programme"]:
            unmapped.append(f"{key}: programme {task['programme']} has no Asana option")

        if args.dry_run:
            prog_label = task["programme"] or "—"
            print(f"   DRY RUN: {key} [{prog_label}] — {name}")
            created += 1
            continue

        try:
            result = create_asana_task(
                name=name,
                notes=task["notes"],
                programme_gid=task["programme_gid"],
                status_gid=task["status_gid"],
            )
            print(f"   ✅ {key} — {name}")
            created += 1
            time.sleep(0.25)  # stay under Asana rate limit (150 req/min)
        except requests.HTTPError as exc:
            print(f"   ❌ FAILED {key} — {exc.response.status_code}: {exc.response.text[:120]}")
            failed.append(key)

    # Summary
    print("\n" + "=" * 60)
    print(f"Migration complete.")
    print(f"  Created : {created}")
    print(f"  Skipped : {skipped} (already existed)")
    print(f"  Failed  : {len(failed)}")
    if failed:
        print(f"  Failed keys: {', '.join(failed)}")
    if unmapped:
        print(f"\n⚠️  Unmapped programmes (set manually in Asana):")
        for u in unmapped:
            print(f"    {u}")


if __name__ == "__main__":
    main()
