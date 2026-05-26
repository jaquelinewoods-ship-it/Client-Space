#!/usr/bin/env python3
"""Populate the MonsterPlumb Asana Category field for requirement tasks.

Requires ASANA_PAT in the environment. This is a one-time/backfill helper; it
fetches the Category custom field and option GIDs dynamically from the project.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ASANA_PROJECT_GID = "1214067923219560"
ASANA_SECTION_GID = "1214352266832449"
CATEGORY_MAPPING = {
    "Milestone 1 & 2": ["MPRB-7", "MPRB-8", "MPRB-9", "MPRB-10", "MPRB-11", "MPRB-12", "MPRB-13", "MPRB-14", "MPRB-15", "MPRB-16", "MPRB-17"],
    "Milestone 3": ["MPRB-39", "MPRB-40", "MPRB-41"],
    "Milestone 4": ["MPRB-25", "MPRB-26", "MPRB-27", "MPRB-28", "MPRB-29", "MPRB-30", "MPRB-31", "MPRB-32", "MPRB-33", "MPRB-36", "MPRB-37", "MPRB-43"],
    "Brightpearl": ["MPRB-44", "MPRB-45", "MPRB-46", "MPRB-47", "MPRB-48", "MPRB-49", "MPRB-50", "MPRB-51", "MPRB-52", "MPRB-53", "MPRB-54", "MPRB-55", "MPRB-56", "MPRB-57", "MPRB-58"],
    "Unassigned": ["MPRB-18", "MPRB-24", "MPRB-34", "MPRB-35", "MPRB-38", "MPRB-42"],
}
KEY_TO_CATEGORY = {key: category for category, keys in CATEGORY_MAPPING.items() for key in keys}
KEY_RE = re.compile(r"MPRB-\d+")
JIRA_URL_KEY_RE = re.compile(r"/browse/(MPRB-\d+)")


class AsanaError(Exception):
    pass


def http_json(method: str, url: str, *, headers: dict[str, str], payload: dict[str, Any] | None = None, retries: int = 4) -> Any:
    body = None
    request_headers = dict(headers)
    request_headers.setdefault("Accept", "application/json")
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                response_body = response.read().decode("utf-8")
                return json.loads(response_body) if response_body else {}
        except urllib.error.HTTPError as exc:
            response_text = exc.read().decode("utf-8", errors="replace")
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if retryable and attempt < retries:
                retry_after = exc.headers.get("Retry-After")
                time.sleep(int(retry_after) if retry_after and retry_after.isdigit() else 2**attempt)
                continue
            raise AsanaError(f"{method} {url} failed with HTTP {exc.code}: {response_text}") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            if attempt < retries:
                time.sleep(2**attempt)
                continue
            raise AsanaError(f"{method} {url} failed: {exc}") from exc
    raise AsanaError(f"{method} {url} failed after retries")


def asana_headers() -> dict[str, str]:
    token = os.environ.get("ASANA_PAT")
    if not token:
        raise AsanaError("Missing ASANA_PAT environment variable")
    return {"Authorization": f"Bearer {token}"}


def asana_url(path: str) -> str:
    return f"https://app.asana.com/api/1.0{path}"


def normalize_option_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def paginated_get(path: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    url = asana_url(path)
    results: list[dict[str, Any]] = []
    while url:
        response = http_json("GET", url, headers=headers)
        results.extend(item for item in response.get("data", []) if isinstance(item, dict))
        url = (response.get("next_page") or {}).get("uri")
    return results


def get_category_field(headers: dict[str, str]) -> tuple[str, dict[str, str]]:
    settings = paginated_get(
        f"/projects/{ASANA_PROJECT_GID}/custom_field_settings?limit=100&opt_fields=custom_field.gid,custom_field.name,custom_field.enum_options.gid,custom_field.enum_options.name",
        headers,
    )
    for setting in settings:
        field = setting.get("custom_field") or {}
        if field.get("name") != "Category":
            continue
        option_gids_by_normalized_name = {
            normalize_option_name(option["name"]): option["gid"]
            for option in field.get("enum_options", [])
            if option.get("enabled", True)
        }
        missing_options = [
            name for name in CATEGORY_MAPPING if normalize_option_name(name) not in option_gids_by_normalized_name
        ]
        if missing_options:
            raise AsanaError(f"Category field is missing expected option(s): {', '.join(missing_options)}")
        return field["gid"], {
            name: option_gids_by_normalized_name[normalize_option_name(name)] for name in CATEGORY_MAPPING
        }
    raise AsanaError("Could not find a custom field named Category on the Asana project")


def parse_mprb_key(task: dict[str, Any]) -> str | None:
    notes = task.get("notes") or ""
    match = JIRA_URL_KEY_RE.search(notes) or KEY_RE.search(notes)
    if match:
        return match.group(1) if match.lastindex else match.group(0)
    return None


def fetch_requirement_tasks(headers: dict[str, str]) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"limit": "100", "opt_fields": "gid,name,notes"})
    return paginated_get(f"/sections/{ASANA_SECTION_GID}/tasks?{params}", headers)


def update_task_category(task_gid: str, field_gid: str, option_gid: str, headers: dict[str, str]) -> None:
    http_json(
        "PUT",
        asana_url(f"/tasks/{urllib.parse.quote(task_gid)}"),
        headers=headers,
        payload={"data": {"custom_fields": {field_gid: option_gid}}},
    )


def main() -> int:
    report: dict[str, Any] = {
        "tasks_seen": 0,
        "tasks_updated": [],
        "unmatched_tasks": [],
        "update_failures": [],
        "category_field_gid": None,
        "category_option_gids": {},
    }
    try:
        headers = asana_headers()
        category_field_gid, option_gids = get_category_field(headers)
        report["category_field_gid"] = category_field_gid
        report["category_option_gids"] = option_gids
        tasks = fetch_requirement_tasks(headers)
        report["tasks_seen"] = len(tasks)
        for task in tasks:
            key = parse_mprb_key(task)
            if not key:
                report["unmatched_tasks"].append({"task_gid": task.get("gid"), "name": task.get("name"), "reason": "Could not parse MPRB key from notes"})
                continue
            category = KEY_TO_CATEGORY.get(key)
            if not category:
                report["unmatched_tasks"].append({"task_gid": task.get("gid"), "name": task.get("name"), "key": key, "reason": "MPRB key not in category mapping"})
                continue
            try:
                update_task_category(task["gid"], category_field_gid, option_gids[category], headers)
                report["tasks_updated"].append({"task_gid": task["gid"], "name": task.get("name"), "key": key, "category": category})
            except Exception as exc:
                report["update_failures"].append({"task_gid": task.get("gid"), "name": task.get("name"), "key": key, "category": category, "error": str(exc)})
                continue
    except Exception as exc:
        report["fatal_error"] = str(exc)
        print(json.dumps(report, indent=2, sort_keys=True), file=sys.stderr)
        return 2

    output_dir = Path(__file__).resolve().parents[1] / "run-output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "populate_monsterplumb_category_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["update_failures"] or report["unmatched_tasks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
