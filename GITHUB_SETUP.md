# GitHub setup checklist

The local repository is prepared at:

```bash
/home/ubuntu/my-space/rixxo-asana-refresh
```

The current environment's GitHub token is read-only for repository/secrets creation, so run these commands from an account with permission to create private repos under the desired GitHub owner.

## 1. Create the private repository and push

```bash
cd /home/ubuntu/my-space/rixxo-asana-refresh
gh repo create rixxo-asana-refresh --private --source . --remote origin --push
```

If the repo is created through the GitHub UI instead, push manually:

```bash
cd /home/ubuntu/my-space/rixxo-asana-refresh
git remote add origin https://github.com/<OWNER>/rixxo-asana-refresh.git
git push -u origin main
```

## 2. Add Actions secrets

Load the existing local env file without printing it:

```bash
cd /home/ubuntu/my-space/rixxo-asana-refresh
set -a
source /home/ubuntu/my-space/monsterplumb-migration/.env.refresh_delivery_tickets
set +a
```

Then write secrets to GitHub:

```bash
gh secret set JIRA_EMAIL --body "$JIRA_EMAIL"
gh secret set JIRA_API_TOKEN --body "$JIRA_API_TOKEN"
gh secret set ASANA_PAT --body "$ASANA_PAT"
```

Alternatively, add them through GitHub UI: **Settings -> Secrets and variables -> Actions**.

## 3. Trigger the first manual workflow run

```bash
gh workflow run refresh_monsterplumb.yml
gh run list --workflow refresh_monsterplumb.yml --limit 5
```

Open the run in GitHub Actions and confirm the `Run refresh script` step succeeds.

## 4. Remove local cron only after GitHub Actions succeeds

If this is the only cron entry:

```bash
crontab -r
```

If there are other cron jobs, edit and remove only the `run_refresh_delivery_tickets.sh` line:

```bash
crontab -e
```
