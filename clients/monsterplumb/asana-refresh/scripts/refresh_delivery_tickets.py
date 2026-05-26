#!/usr/bin/env python3
"""Refresh Jira delivery ticket statuses in Asana requirement descriptions.

Credentials are read from environment variables:
- JIRA_EMAIL
- JIRA_API_TOKEN
- ASANA_PAT

The requirement-to-delivery-ticket mapping is loaded from a JSON config file so
future client mappings can be swapped without editing this script.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "mappings" / "delivery_ticket_mapping.monsterplumb.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "run-output"
VIEW_IN_JIRA_RE = re.compile(r"View\s+in\s+Jira:\s*(MPRB-\d+)", re.IGNORECASE)
BROWSE_RE = re.compile(r"/browse/(MPRB-\d+)")
DELIVERY_MARKER_RE = re.compile(r"<h2>\s*Delivery Tickets\s*</h2>", re.IGNORECASE)
LAST_UPDATED_CLOSE_RE = re.compile(r"(?:<p>\s*)?<em>\s*Last updated:.*?</em>(?:\s*</p>)?", re.IGNORECASE | re.DOTALL)
BODY_CLOSE_RE = re.compile(r"</body>\s*$", re.IGNORECASE)
PRECEDING_HR_RE = re.compile(r"\s*<hr\s*/?>\s*$", re.IGNORECASE)


class RefreshError(Exception):
    pass


def http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    retries: int = 4,
    timeout: int = 60,
) -> Any:
    body = None
    request_headers = dict(headers)
    request_headers.setdefault("Accept", "application/json")
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    for attempt in range(retries + 1):
        request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                response_body = response.read().decode("utf-8")
                return json.loads(response_body) if response_body else {}
        except urllib.error.HTTPError as exc:
            response_text = exc.read().decode("utf-8", errors="replace")
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if retryable and attempt < retries:
                retry_after = exc.headers.get("Retry-After")
                sleep_seconds = int(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                time.sleep(sleep_seconds)
                continue
            raise RefreshError(f"{method} {url} failed with HTTP {exc.code}: {response_text}") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            if attempt < retries:
                time.sleep(2**attempt)
                continue
            raise RefreshError(f"{method} {url} failed: {exc}") from exc
    raise RefreshError(f"{method} {url} failed after retries")


def load_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RefreshError(f"Config file not found: {path}") from exc
    if not isinstance(config.get("delivery_ticket_mapping"), dict):
        raise RefreshError("Config must contain a delivery_ticket_mapping object")
    if not config.get("jira_base_url") or not config.get("asana_section_gid"):
        raise RefreshError("Config must contain jira_base_url and asana_section_gid")
    return config


def jira_headers(email: str, token: str) -> dict[str, str]:
    encoded = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


def asana_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def paginated_asana(url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    while url:
        response = http_json("GET", url, headers=headers)
        if not isinstance(response, dict):
            raise RefreshError(f"Unexpected Asana response type: {type(response).__name__}")
        results.extend(item for item in response.get("data", []) if isinstance(item, dict))
        next_page = response.get("next_page") or {}
        url = next_page.get("uri")
    return results


def fetch_asana_tasks(section_gid: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {"limit": "100", "opt_fields": "gid,name,html_notes"}
    )
    return paginated_asana(
        f"https://app.asana.com/api/1.0/sections/{urllib.parse.quote(section_gid)}/tasks?{params}",
        headers,
    )


def parse_requirement_key(html_notes: str) -> str | None:
    match = VIEW_IN_JIRA_RE.search(html_notes or "")
    if match:
        return match.group(1).upper()
    match = BROWSE_RE.search(html_notes or "")
    if match:
        return match.group(1).upper()
    return None


def fetch_jira_ticket(base_url: str, key: str, headers: dict[str, str]) -> dict[str, str]:
    params = urllib.parse.urlencode({"fields": "summary,status,assignee"})
    url = f"{base_url.rstrip('/')}/rest/api/3/issue/{urllib.parse.quote(key)}?{params}"
    response = http_json("GET", url, headers=headers)
    fields = response.get("fields") if isinstance(response, dict) else None
    if not isinstance(fields, dict):
        raise RefreshError(f"Jira issue {key} response did not include fields")
    assignee = fields.get("assignee")
    status = fields.get("status") or {}
    return {
        "key": key,
        "summary": str(fields.get("summary") or ""),
        "status": str(status.get("name") or "Unknown"),
        "assignee": str((assignee or {}).get("displayName") or "Unassigned"),
        "url": f"{base_url.rstrip('/')}/browse/{key}",
    }


def fetch_all_delivery_tickets(
    base_url: str,
    mapping: dict[str, list[str]],
    headers: dict[str, str],
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    unique_keys = sorted({ticket for tickets in mapping.values() for ticket in tickets})
    fetched: dict[str, dict[str, str]] = {}
    failures: dict[str, str] = {}
    for key in unique_keys:
        try:
            fetched[key] = fetch_jira_ticket(base_url, key, headers)
        except Exception as exc:  # Keep the run going; requirements using this key are skipped.
            failures[key] = str(exc)
    return fetched, failures


def build_delivery_block(tickets: list[dict[str, str]], timestamp: str) -> str:
    lines = ["<hr/>", "<h2>Delivery Tickets</h2>", "<ul>"]
    for ticket in tickets:
        key = html.escape(ticket["key"], quote=False)
        url = html.escape(ticket["url"], quote=True)
        summary = html.escape(ticket["summary"], quote=False)
        status = html.escape(ticket["status"], quote=False)
        lines.append(
            f'<li><a href="{url}">{key}</a> · {summary} · <strong>{status}</strong></li>'
        )
    lines.extend(["</ul>", f"<em>Last updated: {html.escape(timestamp)}</em>"])
    return "\n".join(lines)


def strip_existing_delivery_block(html_notes: str) -> tuple[str, bool]:
    marker = DELIVERY_MARKER_RE.search(html_notes)
    if not marker:
        return html_notes, False

    start = marker.start()
    prefix = html_notes[:start]
    hr = PRECEDING_HR_RE.search(prefix)
    if hr:
        start = hr.start()

    last_updated = LAST_UPDATED_CLOSE_RE.search(html_notes, marker.end())
    if not last_updated:
        raise RefreshError("Found Delivery Tickets marker but could not find Last updated paragraph; refusing to edit description")
    end = last_updated.end()
    return html_notes[:start].rstrip() + html_notes[end:].lstrip(), True


def upsert_delivery_block(html_notes: str, block: str) -> tuple[str, bool]:
    if not html_notes:
        html_notes = "<body></body>"
    base, replaced = strip_existing_delivery_block(html_notes)
    close = BODY_CLOSE_RE.search(base)
    if close:
        before = base[: close.start()].rstrip()
        after = base[close.start() :]
        return f"{before}\n\n{block}\n{after}", replaced
    return f"{base.rstrip()}\n\n{block}", replaced


def update_asana_task(task_gid: str, html_notes: str, headers: dict[str, str]) -> None:
    http_json(
        "PUT",
        f"https://app.asana.com/api/1.0/tasks/{urllib.parse.quote(task_gid)}",
        headers=headers,
        payload={"data": {"html_notes": html_notes}},
    )


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to delivery ticket mapping JSON")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for JSON run reports")
    parser.add_argument("--dry-run", action="store_true", help="Build updates but do not write to Asana")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "dry_run": args.dry_run,
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "tasks_seen": 0,
        "tasks_with_requirement_key": 0,
        "tasks_updated": [],
        "tasks_skipped": [],
        "failures": [],
        "jira_fetch_failures": {},
        "description_preservation_checks": [],
    }

    try:
        config = load_config(Path(args.config))
        jira_email = os.environ.get("JIRA_EMAIL")
        jira_token = os.environ.get("JIRA_API_TOKEN")
        asana_pat = os.environ.get("ASANA_PAT")
        missing = [name for name, value in (("JIRA_EMAIL", jira_email), ("JIRA_API_TOKEN", jira_token), ("ASANA_PAT", asana_pat)) if not value]
        if missing:
            raise RefreshError(f"Missing required environment variable(s): {', '.join(missing)}")

        jira_base_url = config["jira_base_url"]
        section_gid = config["asana_section_gid"]
        mapping = {str(key): list(value) for key, value in config["delivery_ticket_mapping"].items()}
        skip_requirements = set(config.get("skip_requirements") or [])

        j_headers = jira_headers(jira_email, jira_token)
        a_headers = asana_headers(asana_pat)
        delivery_data, delivery_failures = fetch_all_delivery_tickets(jira_base_url, mapping, j_headers)
        report["jira_fetch_failures"] = delivery_failures

        tasks = fetch_asana_tasks(section_gid, a_headers)
        report["tasks_seen"] = len(tasks)

        for task in tasks:
            task_gid = task.get("gid")
            html_notes = task.get("html_notes") or ""
            requirement_key = parse_requirement_key(html_notes)
            if not requirement_key:
                report["tasks_skipped"].append({"task_gid": task_gid, "name": task.get("name"), "reason": "No MPRB key found in html_notes"})
                continue
            report["tasks_with_requirement_key"] += 1

            if requirement_key in skip_requirements:
                report["tasks_skipped"].append({"key": requirement_key, "task_gid": task_gid, "reason": "Requirement configured to skip; no delivery tickets"})
                continue
            ticket_keys = mapping.get(requirement_key)
            if not ticket_keys:
                report["tasks_skipped"].append({"key": requirement_key, "task_gid": task_gid, "reason": "No delivery ticket mapping"})
                continue

            missing_ticket_data = [key for key in ticket_keys if key not in delivery_data]
            if missing_ticket_data:
                report["tasks_skipped"].append({
                    "key": requirement_key,
                    "task_gid": task_gid,
                    "reason": "One or more Jira delivery tickets failed to fetch; description not overwritten",
                    "delivery_tickets": missing_ticket_data,
                })
                continue

            try:
                block = build_delivery_block([delivery_data[key] for key in ticket_keys], report["timestamp_utc"])
                before_hash = sha256(html_notes)
                updated_html, replaced_existing = upsert_delivery_block(html_notes, block)
                base_after_strip, _ = strip_existing_delivery_block(updated_html)
                base_before_strip, _ = strip_existing_delivery_block(html_notes) if DELIVERY_MARKER_RE.search(html_notes) else (html_notes, False)
                preserved = base_after_strip.strip() == base_before_strip.strip()
                report["description_preservation_checks"].append({
                    "key": requirement_key,
                    "task_gid": task_gid,
                    "preserved_existing_description": preserved,
                    "replaced_existing_block": replaced_existing,
                    "before_hash": before_hash,
                    "after_hash": sha256(updated_html),
                })
                if not preserved:
                    raise RefreshError("Preservation check failed before update; refusing to write task")
                if not args.dry_run:
                    update_asana_task(task_gid, updated_html, a_headers)
                report["tasks_updated"].append({
                    "key": requirement_key,
                    "task_gid": task_gid,
                    "delivery_ticket_count": len(ticket_keys),
                    "replaced_existing_block": replaced_existing,
                    "updated": not args.dry_run,
                })
            except Exception as exc:
                report["failures"].append({"key": requirement_key, "task_gid": task_gid, "error": str(exc)})
                continue

    except Exception as exc:
        report["fatal_error"] = str(exc)
        report_path = output_dir / "refresh_delivery_tickets_report.json"
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True), file=sys.stderr)
        return 2

    report_path = output_dir / "refresh_delivery_tickets_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["failures"] or report["jira_fetch_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
