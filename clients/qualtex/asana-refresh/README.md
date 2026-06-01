# Qualtex — Jira Polaris to Asana Migration

Migrates requirements from Jira Polaris board `QGOMR` into the Qualtex Asana project.

**Pattern:** Programme-based grouping (P1–P36). See `clients/monsterplumb/asana-refresh/` for the milestone-based equivalent used on MonsterPlumb.

---

## Setup

```bash
cd clients/qualtex/asana-refresh
pip install requests
```

Set environment variables:

```bash
export JIRA_EMAIL=your@rixxo.com
export JIRA_API_TOKEN=your_jira_api_token   # from id.atlassian.net → Security → API tokens
export ASANA_PAT=your_asana_pat             # from app.asana.com → My Settings → Apps → Personal Access Token
```

---

## Usage

### Dry run (no writes — safe to run anytime)
```bash
python3 migrate.py --dry-run
```

### Full migration
```bash
python3 migrate.py
```

### Migrate a specific status (default is "Awaiting Client Approval")
```bash
python3 migrate.py --status "Needs a Brief"
```

### Resume after interruption
```bash
python3 migrate.py --start-from QGOMR-80
```

The script is **idempotent** — it checks for existing task names before creating and skips duplicates, so it's safe to re-run.

---

## What it migrates

| Filter | Value |
|---|---|
| Jira project | `QGOMR` |
| Status | `Awaiting Client Approval` (default) |
| Excludes | Done, Needs a Brief, archived items |

| Field | Source |
|---|---|
| Task name | Jira summary |
| Notes | Jira key + link to Polaris board |
| Requirement Status | Mapped from Jira status |
| Programme | Extracted from `**Programme:**` in Jira description |

Fields left blank for manual population post-migration: **MoSCoW**, **Business Value**, VHO fields, QA Results, Target Start/End.

---

## Asana project config

| Item | Value |
|---|---|
| Project GID | `1215246319505493` |
| Section | Requirements (`1215246319835973`) |
| Requirement Status field | `1211730436704714` |
| Programme field | `1215246319835982` |

Programme option GIDs are hardcoded in `migrate.py` — update if new programmes are added to the Asana field.

---

## Adding new programmes

1. Add the new option to the Programme field in Asana
2. Copy the GID from the field editor URL or API
3. Add it to `PROGRAMME_OPTION_GIDS` in `migrate.py`

---

## Initial migration

The initial migration of 70 requirements (QGOMR-54 to QGOMR-123) was performed manually via Claude on 2026-05-29. This script is provided for:
- Re-running if requirements are added to the Jira board
- Migrating requirements in other statuses
- Reference for future client board migrations
