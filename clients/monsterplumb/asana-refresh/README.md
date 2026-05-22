# Rixxo Asana Refresh

Scheduled refresh jobs for surfacing Jira delivery-ticket statuses on Asana requirement tasks.

## MonsterPlumb daily refresh

The MonsterPlumb job updates the `Delivery Tickets` block in each mapped Asana requirement task description. It preserves the rest of the description and only replaces the block marked by `<h2>Delivery Tickets</h2>`.

Schedule: daily at **07:00 UTC** via GitHub Actions.

Workflow:

- `.github/workflows/refresh_monsterplumb.yml`

Script and mapping:

- `scripts/refresh_delivery_tickets.py`
- `mappings/delivery_ticket_mapping.monsterplumb.json`

## Required GitHub Actions secrets

Add these in the repository settings under **Secrets and variables -> Actions**:

- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `ASANA_PAT`

Do not commit `.env` files, API tokens, PATs, or other credentials.

## Manual run in GitHub

1. Open the repository on GitHub.
2. Go to **Actions**.
3. Select **Refresh MonsterPlumb Delivery Tickets**.
4. Click **Run workflow**.

The workflow uploads `run-output/refresh_delivery_tickets_report.json` as an artifact.

## Manual local run

```bash
export JIRA_EMAIL="name@example.com"
export JIRA_API_TOKEN="..."
export ASANA_PAT="..."
python scripts/refresh_delivery_tickets.py
```

Dry run:

```bash
python scripts/refresh_delivery_tickets.py --dry-run
```

## Rotating credentials

When tokens are rotated, update the repository Actions secrets. No code changes are needed.

## Adding future clients

1. Add a mapping JSON file to `mappings/`. It must include:

```json
{
  "jira_base_url": "https://example.atlassian.net",
  "asana_section_gid": "123",
  "delivery_ticket_mapping": {
    "REQ-1": ["DEL-1", "DEL-2"]
  },
  "skip_requirements": []
}
```

2. Add a workflow file under `.github/workflows/`, using the same script with the client mapping:

```yaml
- name: Run refresh script
  env:
    JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
    JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
    ASANA_PAT: ${{ secrets.ASANA_PAT }}
  run: python scripts/refresh_delivery_tickets.py --config mappings/delivery_ticket_mapping.client.json
```

3. Add or reuse suitable GitHub Actions secrets for that client.

## Safety behavior

- If a Jira delivery ticket fetch fails, the corresponding Asana requirement task is skipped and its description is not overwritten.
- The script continues after individual failures.
- The script reports updated tasks, skipped tasks, Jira fetch failures, and Asana update failures.
- Existing description content is checked before update so only the Delivery Tickets block is replaced/appended.
