#!/usr/bin/env python3
"""
Qualtex Asana HTML Backfill
Converts ## markdown to Asana-compatible HTML (no h1/h2 — uses strong + hr).

Usage:
    export ASANA_PAT=your_pat
    python3 backfill_html.py
"""
import json, os, re, sys, time, urllib.request, urllib.error

ASANA_PAT = os.environ.get("ASANA_PAT", "")
if not ASANA_PAT:
    print("Set ASANA_PAT environment variable first")
    sys.exit(1)

SECTION_GID = "1215246319835973"

# Asana html_notes ONLY supports: body, strong, em, u, s, ul, ol, li, p, a, hr
# h1/h2/h3/code are NOT supported and cause xml_parsing_error


def fetch_tasks(section_gid, token):
    url = (f"https://app.asana.com/api/1.0/sections/{section_gid}/tasks"
           f"?limit=100&opt_fields=gid,name,notes")
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["data"]


def sanitise(text):
    """Strip characters outside XML 1.0 valid range and normalise specials."""
    text = text.replace("\u2192", "to")   # →
    text = text.replace("\u2013", "-")    # en dash
    text = text.replace("&", "and")
    cleaned = []
    for char in text:
        code = ord(char)
        if (code == 0x9 or code == 0xA or code == 0xD
                or (0x20 <= code <= 0xD7FF)
                or (0xE000 <= code <= 0xFFFD)):
            cleaned.append(char)
        # else: drop (emoji, variation selectors, etc.)
    return "".join(cleaned)


def inline(s):
    """Apply bold formatting only (no <code> — not supported by Asana)."""
    s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'`(.+?)`', r'\1', s)   # strip backticks, keep text
    # Convert markdown links [text](url) to plain text (Asana <a> needs href attr)
    s = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', s)
    return s


def strip_ol_prefix(s):
    return re.sub(r'^\d+\.\s+', '', s)


def markdown_to_html(text):
    """Convert markdown to Asana-compatible HTML.
    Headings (##) become <p><strong>TEXT</strong></p> with a preceding <hr/>.
    """
    if not text:
        return "<body></body>"
    text = sanitise(text)
    lines = text.split("\n")
    html_parts = []
    in_ul = False
    in_ol = False
    first_heading = True

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            html_parts.append("</ul>")
            in_ul = False
        if in_ol:
            html_parts.append("</ol>")
            in_ol = False

    for line in lines:
        s = line.strip()

        if s.startswith("## ") or s.startswith("# "):
            close_lists()
            heading_text = s[3:].strip() if s.startswith("## ") else s[2:].strip()
            if not first_heading:
                html_parts.append("<hr/>")
            first_heading = False
            html_parts.append(f"<p><strong>{inline(heading_text)}</strong></p>")

        elif re.match(r'^\d+\.\s', s):
            if in_ul:
                html_parts.append("</ul>")
                in_ul = False
            if not in_ol:
                html_parts.append("<ol>")
                in_ol = True
            html_parts.append(f"<li>{inline(strip_ol_prefix(s))}</li>")

        elif s.startswith("* ") or s.startswith("- "):
            if in_ol:
                html_parts.append("</ol>")
                in_ol = False
            if not in_ul:
                html_parts.append("<ul>")
                in_ul = True
            html_parts.append(f"<li>{inline(s[2:])}</li>")

        elif s == "":
            close_lists()

        else:
            close_lists()
            html_parts.append(f"<p>{inline(s)}</p>")

    close_lists()
    return "<body>" + "\n".join(html_parts) + "</body>"


def update_task(gid, html_notes, token):
    url = f"https://app.asana.com/api/1.0/tasks/{gid}"
    payload = json.dumps({"data": {"html_notes": html_notes}}).encode()
    req = urllib.request.Request(url, data=payload, method="PUT")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return True, None
    except urllib.error.HTTPError as e:
        return False, f"{e.code}: {e.read().decode()[:150]}"


print("Fetching tasks from Asana...")
tasks = fetch_tasks(SECTION_GID, ASANA_PAT)
print(f"Found {len(tasks)} tasks\n")

ok = fail = skipped = 0
for task in tasks:
    notes = task.get("notes", "") or ""
    if not notes.strip():
        skipped += 1
        continue

    m = re.search(r"Jira:\s*(QGOMR-\d+)", notes, re.IGNORECASE)
    jira_key = m.group(1) if m else ""
    jira_ref = f"<p><strong>Jira: {jira_key}</strong></p>" if jira_key else ""

    body_html = markdown_to_html(notes)
    if jira_ref:
        html_notes = body_html.replace("<body>", f"<body>{jira_ref}\n", 1)
    else:
        html_notes = body_html

    success, err = update_task(task["gid"], html_notes, ASANA_PAT)
    if success:
        ok += 1
        print(f"  OK  {jira_key or task['gid']}: {task['name'][:55]}")
    else:
        fail += 1
        print(f"  FAIL {task['gid']}: {err}")
    time.sleep(0.25)

print(f"\n{'='*55}")
print(f"Updated: {ok} | Skipped: {skipped} | Failed: {fail}")
