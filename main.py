#!/usr/bin/env python3
"""
FamZoo to YNAB Transaction Sync CLI

Syncs transactions from FamZoo to YNAB automatically.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import click

from config import Config
from famzoo import FamZooScraper, FamZooTransaction
from ynab import YNABClient
from tracker import TransactionTracker
from payee import normalize_payee, is_transfer


def parse_date(date_str: str) -> datetime:
    """Parse a date string in various formats."""
    formats = ["%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid date format: {date_str}. Use YYYY-MM-DD format.")


def print_status(message: str, status: str = "info"):
    """Print a status message with color."""
    colors = {
        "info": "blue",
        "success": "green",
        "warning": "yellow",
        "error": "red",
    }
    click.secho(f"[{status.upper()}] {message}", fg=colors.get(status, "white"))


@click.group()
@click.option("--env-file", default=".env", help="Path to .env file")
@click.pass_context
def cli(ctx, env_file):
    """FamZoo to YNAB Transaction Sync Tool"""
    ctx.ensure_object(dict)
    ctx.obj["env_file"] = env_file


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show what would be synced without making changes")
@click.option("--max-pages", default=5, help="Maximum number of transaction pages to fetch")
@click.option("--force", is_flag=True, help="Sync all transactions, ignoring tracking state")
@click.option("--since", default=None, help="Only sync transactions after this date (YYYY-MM-DD)")
@click.pass_context
def sync(ctx, dry_run, max_pages, force, since):
    """Sync transactions from FamZoo to YNAB."""
    try:
        # Load configuration
        print_status("Loading configuration...", "info")
        config = Config.from_env(ctx.obj["env_file"])

        # Initialize tracker
        tracker = TransactionTracker()

        if not force:
            sync_info = tracker.get_last_sync_info()
            print_status(f"Last sync: {sync_info['last_sync']}", "info")
            print_status(f"Total previously imported: {sync_info['total_imported']}", "info")

        # Initialize FamZoo scraper
        print_status("Connecting to FamZoo...", "info")
        famzoo = FamZooScraper(
            family_name=config.famzoo_family_name,
            member_name=config.famzoo_member_name,
            password=config.famzoo_password,
            account_name=config.famzoo_account_name,
        )

        # Log in to FamZoo
        print_status("Logging in to FamZoo...", "info")
        if not famzoo.login():
            print_status("Failed to log in to FamZoo. Check your credentials.", "error")
            sys.exit(1)

        print_status("Successfully logged in to FamZoo!", "success")

        # Determine start date for fetching transactions
        # Use a fixed floor date to ensure we always see the same transactions
        since_date = None
        if since:
            # User explicitly provided --since date
            try:
                since_date = parse_date(since)
                print_status(f"Fetching transactions since {since_date.strftime('%Y-%m-%d')} (--since flag)...", "info")
                # Set this as the floor date if not already set
                tracker.set_first_sync_date(since_date)
            except ValueError as e:
                print_status(str(e), "error")
                sys.exit(1)
        elif not force:
            # Use fixed floor date from state (not a rolling window)
            floor_date = tracker.get_first_sync_date()
            if floor_date:
                since_date = floor_date
                print_status(f"Fetching transactions since {since_date.strftime('%Y-%m-%d')} (fixed floor date)...", "info")
            else:
                # First sync - default to 90 days ago and save as floor
                since_date = datetime.now() - timedelta(days=90)
                tracker.set_first_sync_date(since_date)
                print_status(f"Fetching transactions since {since_date.strftime('%Y-%m-%d')} (first sync, setting floor)...", "info")
        else:
            print_status(f"Fetching all transactions (--force flag)...", "info")

        # Fetch transactions with date filter applied at source
        transactions = famzoo.get_transactions(max_pages=max_pages, start_date=since_date)

        if not transactions:
            print_status("No transactions found in FamZoo.", "warning")
            return

        print_status(f"Found {len(transactions)} transactions in FamZoo", "info")

        # Filter out already imported transactions
        if force:
            new_transactions = transactions
            print_status("Force mode: syncing all transactions", "warning")
        else:
            new_transactions = tracker.filter_new_transactions(transactions)

        if not new_transactions:
            print_status("No new transactions to sync.", "success")
            return

        print_status(f"Found {len(new_transactions)} new transactions to sync", "info")

        # Display transactions with normalized payee names
        click.echo("\nTransactions to sync:")
        click.echo("-" * 80)
        for tx in new_transactions:
            amount_str = f"${tx.amount:,.2f}" if tx.amount >= 0 else f"-${abs(tx.amount):,.2f}"
            # Show normalized payee name or [TRANSFER] marker
            if is_transfer(tx.description):
                payee_display = "[TRANSFER]"
            else:
                payee_display = normalize_payee(tx.description)[:35]
            click.echo(f"  {tx.date.strftime('%Y-%m-%d')} | {amount_str:>12} | {payee_display}")
        click.echo("-" * 80)

        if dry_run:
            print_status("Dry run mode - no changes made", "warning")
            return

        # Initialize YNAB client
        print_status("Connecting to YNAB...", "info")
        ynab = YNABClient(
            api_token=config.ynab_api_token,
            budget_id=config.ynab_budget_id,
            account_id=config.ynab_account_id,
            transfer_account_id=config.ynab_transfer_account_id,
        )

        # Test YNAB connection
        if not ynab.test_connection():
            print_status("Failed to connect to YNAB. Check your API token and budget ID.", "error")
            sys.exit(1)

        print_status("Successfully connected to YNAB!", "success")

        # Sync transactions
        print_status("Syncing transactions to YNAB...", "info")
        created, duplicates = ynab.sync_famzoo_transactions(new_transactions)

        # Update tracker
        tracker.mark_imported(new_transactions)

        # Report results
        print_status(f"Created {created} new transactions in YNAB", "success")
        if duplicates:
            print_status(f"Skipped {duplicates} duplicate transactions", "info")

    except ValueError as e:
        print_status(str(e), "error")
        sys.exit(1)
    except Exception as e:
        print_status(f"Error: {e}", "error")
        sys.exit(1)


@cli.command()
@click.pass_context
def status(ctx):
    """Show sync status and configuration."""
    try:
        # Load configuration
        config = Config.from_env(ctx.obj["env_file"])

        click.echo("\n=== Configuration ===")
        click.echo(f"FamZoo Family Name: {config.famzoo_family_name}")
        click.echo(f"FamZoo Member Name: {config.famzoo_member_name}")
        click.echo(f"FamZoo Account: {config.famzoo_account_name}")
        click.echo(f"YNAB Budget ID: {config.ynab_budget_id}")
        click.echo(f"YNAB Account ID: {config.ynab_account_id}")
        click.echo(f"YNAB Transfer Account ID: {config.ynab_transfer_account_id or 'Not configured'}")

        # Show tracker status
        tracker = TransactionTracker()
        sync_info = tracker.get_last_sync_info()

        click.echo("\n=== Sync Status ===")
        click.echo(f"Last Sync: {sync_info['last_sync']}")
        click.echo(f"Last Transaction Date: {sync_info['last_transaction_date']}")
        click.echo(f"Total Imported: {sync_info['total_imported']}")
        click.echo(f"Tracked Transaction IDs: {sync_info['tracked_ids']}")

        # Test YNAB connection
        click.echo("\n=== Connection Tests ===")
        ynab = YNABClient(
            api_token=config.ynab_api_token,
            budget_id=config.ynab_budget_id,
            account_id=config.ynab_account_id,
            transfer_account_id=config.ynab_transfer_account_id,
        )

        if ynab.test_connection():
            print_status("YNAB connection: OK", "success")
        else:
            print_status("YNAB connection: FAILED", "error")

    except ValueError as e:
        print_status(str(e), "error")
        sys.exit(1)
    except Exception as e:
        print_status(f"Error: {e}", "error")
        sys.exit(1)


@cli.command()
@click.pass_context
def list_budgets(ctx):
    """List available YNAB budgets."""
    try:
        config = Config.from_env(ctx.obj["env_file"])

        ynab = YNABClient(
            api_token=config.ynab_api_token,
            budget_id="last-used",  # Temporary
            account_id="",
        )

        budgets = ynab.get_budgets()

        click.echo("\n=== Available Budgets ===")
        for budget in budgets:
            click.echo(f"  {budget['name']}")
            click.echo(f"    ID: {budget['id']}")
            click.echo()

    except Exception as e:
        print_status(f"Error: {e}", "error")
        sys.exit(1)


@cli.command()
@click.pass_context
def list_accounts(ctx):
    """List available YNAB accounts in the configured budget."""
    try:
        config = Config.from_env(ctx.obj["env_file"])

        ynab = YNABClient(
            api_token=config.ynab_api_token,
            budget_id=config.ynab_budget_id,
            account_id="",
        )

        accounts = ynab.get_accounts()

        click.echo("\n=== Available Accounts ===")
        for account in accounts:
            if not account.get("closed", False):
                balance = account.get("balance", 0) / 1000
                click.echo(f"  {account['name']}")
                click.echo(f"    ID: {account['id']}")
                click.echo(f"    Type: {account.get('type', 'unknown')}")
                click.echo(f"    Balance: ${balance:,.2f}")
                click.echo()

    except Exception as e:
        print_status(f"Error: {e}", "error")
        sys.exit(1)


@cli.command()
@click.confirmation_option(prompt="Are you sure you want to reset the sync state?")
def reset():
    """Reset the sync tracking state."""
    tracker = TransactionTracker()
    tracker.reset()
    print_status("Sync state has been reset.", "success")


@cli.command()
@click.option("--max-pages", default=3, help="Maximum number of transaction pages to fetch")
@click.pass_context
def test_famzoo(ctx, max_pages):
    """Test FamZoo connection and fetch transactions (without syncing)."""
    try:
        config = Config.from_env(ctx.obj["env_file"])

        print_status("Connecting to FamZoo...", "info")
        famzoo = FamZooScraper(
            family_name=config.famzoo_family_name,
            member_name=config.famzoo_member_name,
            password=config.famzoo_password,
            account_name=config.famzoo_account_name,
        )

        print_status("Logging in...", "info")
        if not famzoo.login():
            print_status("Login failed!", "error")
            sys.exit(1)

        print_status("Login successful!", "success")

        print_status("Fetching transactions...", "info")
        transactions = famzoo.get_transactions(max_pages=max_pages)

        if transactions:
            click.echo(f"\n=== Found {len(transactions)} Transactions ===")
            click.echo("(Showing normalized payee names)")
            for tx in transactions[:10]:  # Show first 10
                amount_str = f"${tx.amount:,.2f}" if tx.amount >= 0 else f"-${abs(tx.amount):,.2f}"
                if is_transfer(tx.description):
                    payee_display = "[TRANSFER]"
                else:
                    payee_display = normalize_payee(tx.description)[:35]
                click.echo(f"  {tx.date.strftime('%Y-%m-%d')} | {amount_str:>12} | {payee_display}")

            if len(transactions) > 10:
                click.echo(f"  ... and {len(transactions) - 10} more")
        else:
            print_status("No transactions found.", "warning")

    except Exception as e:
        print_status(f"Error: {e}", "error")
        sys.exit(1)


if __name__ == "__main__":
    cli()
