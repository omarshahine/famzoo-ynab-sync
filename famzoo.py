"""FamZoo web scraper for transaction data using Playwright."""

import csv
import os
import re
import time
import hashlib
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page


@dataclass
class FamZooTransaction:
    """Represents a transaction from FamZoo."""

    date: datetime
    description: str
    amount: float  # Negative for debits, positive for credits
    memo: str
    transaction_id: str

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "date": self.date.isoformat(),
            "description": self.description,
            "amount": self.amount,
            "memo": self.memo,
            "transaction_id": self.transaction_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FamZooTransaction":
        """Create from dictionary."""
        return cls(
            date=datetime.fromisoformat(data["date"]),
            description=data["description"],
            amount=data["amount"],
            memo=data.get("memo", ""),
            transaction_id=data["transaction_id"],
        )


class FamZooScraper:
    """Scraper for FamZoo web portal using Playwright."""

    BASE_URL = "https://app.famzoo.com/ords/f"
    TRANSACTIONS_PAGE = "?p=197:17"

    def __init__(self, family_name: str, member_name: str, password: str, account_name: str):
        self.family_name = family_name
        self.member_name = member_name
        self.password = password
        self.account_name = account_name  # Name to match in Accounts dropdown
        self._session_id: Optional[str] = None
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    def _start_browser(self):
        """Start the Playwright browser."""
        if self._playwright is None:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
            self._context = self._browser.new_context()
            self._page = self._context.new_page()

    def _stop_browser(self):
        """Stop the Playwright browser."""
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None

    def login(self) -> bool:
        """Log in to FamZoo and establish a session."""
        self._start_browser()

        try:
            # Load login page
            self._page.goto(f"{self.BASE_URL}?p=197:101")
            self._page.wait_for_load_state("networkidle")

            # Fill login form
            self._page.fill("#fzi_signin_famname", self.family_name)
            self._page.fill("#fzi_signin_memname", self.member_name)
            self._page.fill("#fzi_signin_password", self.password)

            # Click sign in and wait for navigation
            self._page.click("#fzi_signin_bsignin")

            # Wait for login to complete - APEX apps can do multi-step redirects,
            # so we retry the title check if the execution context is destroyed
            # mid-navigation.
            time.sleep(3)
            self._page.wait_for_load_state("networkidle")

            # Verify login by checking page title (retry on navigation race)
            for attempt in range(3):
                try:
                    self._page.wait_for_load_state("domcontentloaded")
                    title = self._page.title()
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(2)
                    self._page.wait_for_load_state("networkidle")

            if "Sign In" in title:
                return False

            # Get session from current URL if not already set
            if not self._session_id:
                current_url = self._page.url
                session_match = re.search(r":(\d{10,})", current_url)
                if session_match:
                    self._session_id = session_match.group(1)

            # If still no session ID, extract from page content (links contain session)
            if not self._session_id:
                content = self._page.content()
                session_matches = re.findall(r"p=197:\d+:(\d{10,})", content)
                if session_matches:
                    self._session_id = session_matches[0]

            return self._session_id is not None

        except Exception as e:
            self._stop_browser()
            raise e

    def get_transactions(
        self,
        max_pages: int = 5,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> list[FamZooTransaction]:
        """
        Fetch transactions from FamZoo by downloading CSV export.

        Args:
            max_pages: Not used (kept for backwards compatibility)
            start_date: Only fetch transactions on or after this date
            end_date: Only fetch transactions on or before this date (defaults to today)
        """
        if not self._session_id:
            raise Exception("Not logged in. Call login() first.")

        try:
            # Navigate to transactions page with current session
            tx_url = f"{self.BASE_URL}{self.TRANSACTIONS_PAGE}:{self._session_id}"
            self._page.goto(tx_url, wait_until="domcontentloaded")
            self._page.wait_for_load_state("networkidle")

            # Select account from dropdown (partial match on account_name)
            accounts_select = self._page.query_selector("#P17_ACCOUNTS")
            if accounts_select:
                options = self._page.query_selector_all("#P17_ACCOUNTS option")
                for option in options:
                    option_text = option.inner_text()
                    if self.account_name.lower() in option_text.lower():
                        option_value = option.get_attribute("value")
                        self._page.select_option("#P17_ACCOUNTS", option_value)
                        break

            # Set date range in the form
            if start_date:
                start_str = start_date.strftime("%m/%d/%Y")
                self._page.fill("#P17_START_DATE_input", start_str)
                self._page.keyboard.press("Escape")

            if end_date:
                end_str = end_date.strftime("%m/%d/%Y")
            else:
                end_str = datetime.now().strftime("%m/%d/%Y")
            self._page.fill("#P17_END_DATE_input", end_str)
            self._page.keyboard.press("Escape")

            # Set rows to maximum
            rows_select = self._page.query_selector("#P17_ROWS")
            if rows_select:
                self._page.select_option("#P17_ROWS", "1000")

            # Click GO to apply filters
            go_button = self._page.query_selector("button.fzbutton:has-text('GO'), a[href*='P17_GO']")
            if go_button:
                go_button.click()
                self._page.wait_for_load_state("networkidle")
                time.sleep(1)

            # Download CSV using the actions menu
            transactions = self._download_and_parse_csv()
            return transactions

        except Exception as e:
            raise e
        finally:
            self._stop_browser()

    def _download_and_parse_csv(self) -> list[FamZooTransaction]:
        """Click 'Download Spreadsheet' link and parse the results."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp:
            tmp_path = tmp.name

        # Set up download handler and click the Download Spreadsheet link
        with self._page.expect_download(timeout=30000) as download_info:
            download_link = self._page.query_selector("a:has-text('Download Spreadsheet')")
            if download_link:
                download_link.click()
            else:
                raise Exception("Could not find 'Download Spreadsheet' link")

        download = download_info.value
        download.save_as(tmp_path)

        # Parse the downloaded file
        transactions = self._parse_csv_file(tmp_path)

        # Clean up temp file
        os.unlink(tmp_path)

        return transactions

    def _parse_csv_file(self, csv_path: str) -> list[FamZooTransaction]:
        """Parse transactions from a CSV file."""
        transactions = []
        seen_ids = set()

        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                try:
                    transaction = self._parse_csv_row(row)
                    if transaction and transaction.transaction_id not in seen_ids:
                        transactions.append(transaction)
                        seen_ids.add(transaction.transaction_id)
                except Exception:
                    continue

        return transactions

    def _parse_csv_row(self, row: dict) -> Optional[FamZooTransaction]:
        """Parse a single CSV row into a transaction."""
        # FamZoo CSV columns: Transaction Date, Description, Memo, Amount
        date_str = row.get('Transaction Date', '').strip()
        description = row.get('Description', '').strip()
        memo = row.get('Memo', '').strip()
        amount_str = row.get('Amount', '').strip()

        if not date_str or not amount_str:
            return None

        # Parse date - FamZoo format: "MM/DD/YYYY HH:MM:SS AM/PM"
        try:
            # Try with time first, then without
            for fmt in ["%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"]:
                try:
                    date = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
        except Exception:
            return None

        # Parse amount - FamZoo format: "$X.XX" or "-$X.XX" or just "X.XX"
        try:
            clean_amount = re.sub(r'[,$]', '', amount_str)
            amount = float(clean_amount)
        except ValueError:
            return None

        # Skip zero amounts (pending transactions)
        if amount == 0:
            return None

        # Skip "Starting Balance" entries
        if "Starting Balance" in description:
            return None

        # Generate unique transaction ID using date (without time) + description + amount
        date_only = date.strftime("%m/%d/%Y")
        hash_input = f"{date_only}{description}{amount}"
        hash_digest = hashlib.md5(hash_input.encode()).hexdigest()[:10]
        transaction_id = f"{date.strftime('%Y%m%d')}_{hash_digest}"

        return FamZooTransaction(
            date=date,
            description=description[:100],
            amount=amount,
            memo=memo[:100] if memo else "",
            transaction_id=transaction_id,
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._stop_browser()
