# FamZoo to YNAB Sync

## Quick Commands

```bash
# Activate venv
source venv/bin/activate

# Run sync manually
python main.py sync

# Check sync status
python main.py status

# List YNAB budgets/accounts (for config)
python main.py list-budgets
python main.py list-accounts

# Test FamZoo connection
python main.py test-famzoo

# Reset sync state (re-sync from floor date)
python main.py reset

# Install Playwright browser (after fresh venv)
playwright install chromium
```

## Project Overview

CLI tool that syncs transactions from FamZoo prepaid cards to YNAB (You Need A Budget). Runs daily via macOS launchd at 8 AM.

## Architecture

| File | Purpose |
|------|---------|
| `main.py` | Click CLI with commands: `sync`, `status`, `list-budgets`, `list-accounts`, `test-famzoo`, `reset`, `skip` |
| `famzoo.py` | FamZoo web scraper (Playwright headless Chromium, CSV download) |
| `ynab.py` | YNAB API client (REST, creates transactions) |
| `tracker.py` | Dedup tracker using `.famzoo_sync_state.json` (fixed floor date, transaction IDs) |
| `config.py` | Loads config from macOS Keychain + `.env` |
| `keychain.py` | macOS Keychain helper (`security find-generic-password`) |
| `payee.py` | Payee name normalization and transfer detection |
| `famzoo-sync.sh` | Shell wrapper: activates venv, runs CLI, sends notification via macOS Shortcuts |

## Runtime

- **Python**: 3.9+ (venv at `./venv/`)
- **Daily automation**: launchd plist `com.famzoo-ynab-sync.plist` runs `famzoo-sync.sh sync`
- **Logs**: `./logs/sync.log`
- **Notifications**: `famzoo-sync.sh` pipes result messages to `shortcuts run "FamZoo Notification"`

## Secrets

Secrets are stored in macOS Keychain (not in `.env`):

| Keychain Key | Env Var |
|--------------|---------|
| `env/FAMZOO_PASSWORD` | `FAMZOO_PASSWORD` |
| `env/YNAB_API_TOKEN` | `YNAB_API_TOKEN` |

Non-secret config lives in `.env` (family name, member name, account name, budget/account IDs).

## Key Design Decisions

- **Fixed floor date**: First sync sets a floor date (default 90 days back). All subsequent syncs fetch from this same date to prevent duplicates from sliding windows.
- **CSV download**: Transactions are fetched via FamZoo's CSV export (not HTML scraping) for reliability.
- **Transfer detection**: FamZoo transfers (e.g., "Transfer from Family for Child:") are converted to proper YNAB transfers when `YNAB_TRANSFER_ACCOUNT_ID` is configured.
- **Notification shortcut**: The `FamZoo Notification.shortcut` file is included in the repo. It must be installed in macOS Shortcuts app to receive sync notifications.

## Notification System

After each sync, `famzoo-sync.sh` sends a message to the "FamZoo Notification" Shortcut:

| Scenario | Message |
|----------|---------|
| Transactions created | `FamZoo Sync: Created N new transactions` |
| No new transactions | `FamZoo Sync: No new transactions` |
| No transactions found | `FamZoo Sync: No transactions found` |
| Error | `FamZoo Sync Error: <error message>` |

The Shortcut file (`FamZoo Notification.shortcut`) is checked into the repo. To install on a new Mac: double-click to import into Shortcuts app.

## Code Hygiene

- No hardcoded user paths (`/Users/[name]/`) - use `~/` or `${HOME}`
- No personal email addresses in tracked files (allowed: `@example.com`, `@anthropic.com`, `@noreply`)
- No API keys or secrets in code - use environment variables or macOS Keychain
- No phone numbers or PII in examples - use generic placeholders

## Development Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium

# Copy and fill in config
cp .env.example .env
# Edit .env with YNAB budget/account IDs (non-secret config)

# Store secrets in macOS Keychain
security add-generic-password -s 'env/FAMZOO_PASSWORD' -a "$USER" -w 'YOUR_PASSWORD'
security add-generic-password -s 'env/YNAB_API_TOKEN' -a "$USER" -w 'YOUR_TOKEN'
```

## Development Notes

- Do not modify `.famzoo_sync_state.json` manually - use `reset` or `skip` commands
- The `.env` file is gitignored; use `.env.example` as a template
- Virtual environments (`venv/`, `.venv/`) are gitignored
- Playwright requires `playwright install chromium` after fresh venv setup
## Claude Code GitHub Actions

This repo uses Claude Code GitHub Actions for PR automation:

- **`claude-code-review.yml`** - Auto-reviews PRs when marked "Ready for review" (draft → ready triggers review)
- **`claude.yml`** - Responds to `@claude` mentions in PR/issue comments for manual reviews

**Workflow:** Open PRs as draft → push commits → mark "Ready for review" to trigger auto-review. Use `@claude` in comments for follow-up reviews.
