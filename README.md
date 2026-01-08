# FamZoo to YNAB Transaction Sync

A CLI tool that syncs transactions from FamZoo to YNAB (You Need A Budget).

## Features

- Fetches transactions from FamZoo using browser automation (Playwright)
- Creates transactions in YNAB via their API
- **Smart payee name normalization** - cleans up merchant names (removes prefixes like "SP", "SQ", location info, etc.)
- **Transfer handling** - FamZoo transfers appear as proper YNAB transfers linked to your checking account
- Tracks imported transactions to prevent duplicates
- Supports filtering by date with `--since` option
- Dry-run mode to preview changes before syncing

## Prerequisites

- Python 3.10 or higher
- A FamZoo account
- A YNAB account with API access

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/famzoo-ynab-sync.git
cd famzoo-ynab-sync
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright browsers

```bash
playwright install chromium
```

### 5. Configure environment variables

Copy the example environment file and edit it with your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your actual values:

```
# FamZoo Credentials
FAMZOO_FAMILY_NAME=YourFamilyName
FAMZOO_MEMBER_NAME=YourMemberName
FAMZOO_PASSWORD=your_password

# FamZoo Account Name (see "Finding Your FamZoo Account Name" below)
FAMZOO_ACCOUNT_NAME=Kids Spending

# YNAB Credentials
# Get your API token from: https://app.ynab.com/settings/developer
YNAB_API_TOKEN=your_ynab_api_token

# YNAB Budget and Account IDs
# Use 'list-budgets' and 'list-accounts' commands to find these
YNAB_BUDGET_ID=your_budget_id
YNAB_ACCOUNT_ID=your_account_id

# Transfer Account ID (optional)
# For FamZoo transfers like "Transfer from Family for Child:"
# Set this to your Checking account ID so transfers are properly linked
YNAB_TRANSFER_ACCOUNT_ID=your_checking_account_id
```

## Finding Your FamZoo Account Name

The `FAMZOO_ACCOUNT_NAME` tells the tool which FamZoo card's transactions to sync.

### Step-by-step instructions:

1. **Log into FamZoo** at [app.famzoo.com](https://app.famzoo.com) using your parent/admin account

2. **Go to Bank > Download Transactions** in the top menu

3. **Look at the "Accounts" dropdown** - it shows all your family's cards, like:
   - `Family Spending [***1234] (Alex)`
   - `Family Spending [***5678] (Sam)`

4. **Set `FAMZOO_ACCOUNT_NAME`** to a unique part of the account name you want to sync. For example:
   - `Alex` - matches "Family Spending [***1234] (Alex)"
   - `Sam` - matches "Family Spending [***5678] (Sam)"

The tool does a partial match, so you just need enough of the name to uniquely identify the account.

### Multiple cards:

To sync multiple family members' cards, run separate instances with different `.env` files, each with a different `FAMZOO_ACCOUNT_NAME`.

## Usage

### Using the Shell Wrapper (Recommended)

The easiest way to run the tool is using the shell wrapper script:

```bash
# Show help
./famzoo-sync.sh --help

# Sync transactions (dry-run first)
./famzoo-sync.sh sync --dry-run

# Sync transactions for real
./famzoo-sync.sh sync

# Sync only transactions after a specific date
./famzoo-sync.sh sync --since 2024-01-01

# Check status
./famzoo-sync.sh status

# List YNAB budgets (to find your budget ID)
./famzoo-sync.sh list-budgets

# List YNAB accounts (to find your account ID)
./famzoo-sync.sh list-accounts

# Test FamZoo connection
./famzoo-sync.sh test-famzoo

# Reset sync tracking (start fresh)
./famzoo-sync.sh reset
```

### Using Python Directly

If you prefer to run Python directly:

```bash
# Activate virtual environment first
source venv/bin/activate

# Run commands
python main.py sync --dry-run
python main.py sync
python main.py status
```

## Command Reference

### `sync`

Sync transactions from FamZoo to YNAB.

Options:
- `--dry-run`: Show what would be synced without making changes
- `--max-pages N`: Maximum number of transaction pages to fetch (default: 5)
- `--force`: Sync all transactions, ignoring tracking state
- `--since DATE`: Only sync transactions after this date (formats: YYYY-MM-DD, MM/DD/YYYY)

### `status`

Show current sync status and configuration.

### `list-budgets`

List available YNAB budgets to find your budget ID.

### `list-accounts`

List available YNAB accounts in the configured budget.

### `test-famzoo`

Test FamZoo connection and fetch transactions without syncing.

### `reset`

Reset the sync tracking state (will re-sync all transactions on next run).

## Automation

### macOS - Using launchd (Recommended)

Create a launchd plist to run the sync automatically:

1. Create the plist file:

```bash
mkdir -p ~/Library/LaunchAgents
```

2. Copy the included plist:

```bash
cp com.famzoo-ynab-sync.plist ~/Library/LaunchAgents/
```

3. Edit the plist to set your correct paths:

```bash
open ~/Library/LaunchAgents/com.famzoo-ynab-sync.plist
```

4. Load the agent:

```bash
launchctl load ~/Library/LaunchAgents/com.famzoo-ynab-sync.plist
```

To unload:
```bash
launchctl unload ~/Library/LaunchAgents/com.famzoo-ynab-sync.plist
```

To run immediately:
```bash
launchctl start com.famzoo-ynab-sync
```

### macOS - Using Shortcuts

You can create a Shortcut that runs the shell script:

1. Open the Shortcuts app
2. Create a new shortcut
3. Add "Run Shell Script" action
4. Set the script to:
   ```bash
   /Users/YOUR_USERNAME/famzoo-ynab-sync/famzoo-sync.sh sync
   ```
5. Save the shortcut
6. You can then run it from Shortcuts, add it to your menu bar, or set up automation triggers

### Using cron

Add a cron job to run daily:

```bash
crontab -e
```

Add this line (runs at 8 AM daily):
```
0 8 * * * /Users/YOUR_USERNAME/famzoo-ynab-sync/famzoo-sync.sh sync >> /Users/YOUR_USERNAME/famzoo-ynab-sync/sync.log 2>&1
```

## Payee Name Normalization

The tool automatically cleans up payee names before sending to YNAB:

**Before → After:**
- `SP RED WAGON TOYS, LLC SEATTLE WA` → `Red Wagon Toys`
- `SQ *COFFEE SHOP #1234` → `Coffee Shop`
- `TST* RESTAURANT NAME CITY WA` → `Restaurant Name`

**Prefixes removed:** SP, SQ, TST, PAYPAL, AMZN, UBER, LYFT, DOORDASH, etc.

**Suffixes removed:** LLC, INC, CORP, location info (CITY STATE)

### Custom Payee Mappings

You can add your own local merchant mappings via the `PAYEE_MAPPINGS` environment variable in your `.env` file. This is useful for:
- Local businesses with messy transaction names
- Personal service providers
- Any merchant you want to appear with a cleaner name in YNAB

Add mappings as a JSON object in your `.env`:

```
PAYEE_MAPPINGS={"LOCAL COFFEE": "My Coffee Shop", "JOES PIZZA": "Joe's Pizza", "DR SMITH": "Dr. Smith (Dentist)"}
```

Patterns are matched case-insensitively against the beginning of the payee name. Your personal mappings are merged with built-in defaults for common national chains (Starbucks, Target, Amazon, etc.).

## Transfer Handling

FamZoo transfers (like "Transfer from Family for Child:") are automatically converted to YNAB transfers when you configure `YNAB_TRANSFER_ACCOUNT_ID`.

1. Run `./famzoo-sync.sh list-accounts` to find your Checking account ID
2. Add `YNAB_TRANSFER_ACCOUNT_ID=<checking-account-id>` to your `.env`
3. Transfers will now appear in YNAB as proper transfers from Checking

Without this setting, transfers will appear as regular transactions with the full FamZoo description as the payee.

## Troubleshooting

### "Python not found"

Make sure you have Python 3 installed:
```bash
python3 --version
```

If not installed, install via Homebrew:
```bash
brew install python
```

### "Module not found" errors

Make sure you've activated the virtual environment:
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### FamZoo login fails

1. Verify your credentials in `.env`
2. Try running `./famzoo-sync.sh test-famzoo` to debug
3. Make sure Playwright browsers are installed: `playwright install chromium`

### YNAB API errors

1. Verify your API token is correct
2. Run `./famzoo-sync.sh list-budgets` to verify connection
3. Make sure budget and account IDs are correct

### Duplicate transactions

The tool tracks imported transactions using unique IDs. If you see duplicates:
1. YNAB also has its own duplicate detection via `import_id`
2. You can reset tracking with `./famzoo-sync.sh reset`
3. Use `--since DATE` to limit which transactions are synced

## Files

- `main.py` - Main CLI application
- `famzoo.py` - FamZoo web scraper using Playwright
- `ynab.py` - YNAB API client
- `tracker.py` - Transaction tracking to prevent duplicates
- `config.py` - Configuration management
- `payee.py` - Payee name normalization (customize merchant name mappings here)
- `famzoo-sync.sh` - Shell wrapper for easy execution
- `.famzoo_sync_state.json` - Sync state (auto-generated)

## License

MIT License
