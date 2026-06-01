# Qualtex — Jira Polaris to Asana Migration & Refresh

Migrates and refreshes requirements from Jira Polaris board `QGOMR` in the Qualtex Asana project.

**Pattern:** Programme-based grouping (P1–P36). See `clients/monsterplumb/asana-refresh/` for the milestone-based equivalent used on MonsterPlumb.

---

## Folder structure

```
asana-refresh/
├── .github/
│   └── workflows/
│       └── refresh_qualtex.yml       # Daily GitHub Actions workflow
├── mappings/
│   └── delivery_ticket_mapping.qualtex.json  # QGOMR → QGOMD links
├── scripts/
│   ├── migrate.py                    # One-time migration: Jira → Asana
│   └── refresh_delivery_tickets.py  # Daily refresh: QGOMD statuses → Asana
├── .gitignore
├── README.md
└── requirements.txt
```

---

## Setup

```bash
cd clients/qualtex/asana-refresh
pip install -r requirements.txt
```

Set environment variables:

```bash
export JIRA_EMAIL=your@rixxo.com
export JIRA_API_TOKEN=your_jira_api_token   # id.atlassian.net → Security → API tokens
export ASANA_PAT=your_asana_pat             # app.asana.com → My Settings → Apps → Personal Access Token
```

---

## Daily refresh (delivery ticket statuses)

Runs automatically at 07:00 UTC via GitHub Actions. Uses secrets `JIRA_EMAIL`, `JIRA_API_TOKEN`, `ASANA_PAT` set on the repo.

To run manually:

```bash
# Dry run
python scripts/refresh_delivery_tickets.py --dry-run

# Live run
python scripts/refresh_delivery_tickets.py
```

The script reads `mappings/delivery_ticket_mapping.qualtex.json`, fetches the current status of each QGOMD ticket from Jira, and writes a Delivery Tickets block into each matched Asana task. It is safe to re-run — existing blocks are replaced, not duplicated.

**Adding new delivery ticket links:** Edit `delivery_ticket_mapping.qualtex.json` and add the QGOMR key with its QGOMD ticket(s).

---

## One-time migration (Jira → Asana)

The initial migration of 70 requirements (QGOMR-54 to QGOMR-123) was run on 2026-05-29. Use `migrate.py` if requirements are added to the Jira board or for future client migrations.

```bash
# Dry run
python scripts/migrate.py --dry-run

# Migrate a specific status (default: Awaiting Client Approval)
python scripts/migrate.py --status "Awaiting Client Approval"

# Resume after interruption
python scripts/migrate.py --start-from QGOMR-80
```

The script is idempotent — skips tasks already present in Asana by name.

---

## Asana project config

| Item | Value |
|---|---|
| Project GID | `1215246319505493` |
| Section | Requirements (`1215246319835973`) |
| Requirement Status field | `1211730436704714` |
| Programme field | `1215246319835982` |

---

## GitHub Actions secrets required

Set these on the `jaquelinewoods-ship-it/Client-Space` repo (Settings → Secrets → Actions):

- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `ASANA_PAT`
