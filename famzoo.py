"""FamZoo web scraper for transaction data using Playwright."""

import re
import json
import time
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

            # Click sign in and wait for response
            with self._page.expect_response(
                lambda response: "wwv_flow" in response.url
            ) as response_info:
                self._page.click("#fzi_signin_bsignin")

            response = response_info.value
            response_body = response.text()

            # Parse the JSON response
            try:
                result = json.loads(response_body)

                # Check for errors
                if result.get("fieldErrors"):
                    errors = result["fieldErrors"]
                    if errors:
                        error_msg = errors[0].get("message", "Unknown error")
                        raise Exception(f"Login failed: {error_msg}")

                # Extract session ID from redirect URL
                if "url" in result:
                    redirect_url = result["url"]
                    session_match = re.search(r":(\d{10,})", redirect_url)
                    if session_match:
                        self._session_id = session_match.group(1)

            except json.JSONDecodeError:
                pass

            # Wait for page to load after login
            time.sleep(1)
            self._page.wait_for_load_state("networkidle")

            # Verify login by checking page title
            title = self._page.title()
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
        Fetch transactions from FamZoo using the date filter form.

        Args:
            max_pages: Maximum pages to fetch (for backwards compatibility, not used with form)
            start_date: Only fetch transactions on or after this date
            end_date: Only fetch transactions on or before this date (defaults to today)
        """
        if not self._session_id:
            raise Exception("Not logged in. Call login() first.")

        try:
            # Navigate to transactions page with current session
            tx_url = f"{self.BASE_URL}{self.TRANSACTIONS_PAGE}:{self._session_id}"
            self._page.goto(tx_url)
            self._page.wait_for_load_state("networkidle")

            # Select account from dropdown (partial match on account_name)
            accounts_select = self._page.query_selector("#P17_ACCOUNTS")
            if accounts_select:
                # Get all options and find one containing our account name
                options = self._page.query_selector_all("#P17_ACCOUNTS option")
                for option in options:
                    option_text = option.inner_text()
                    if self.account_name.lower() in option_text.lower():
                        option_value = option.get_attribute("value")
                        self._page.select_option("#P17_ACCOUNTS", option_value)
                        break

            # Set date range in the form (dismiss date picker popups with Escape)
            if start_date:
                start_str = start_date.strftime("%m/%d/%Y")
                self._page.fill("#P17_START_DATE_input", start_str)
                self._page.keyboard.press("Escape")  # Close date picker

            if end_date:
                end_str = end_date.strftime("%m/%d/%Y")
            else:
                end_str = datetime.now().strftime("%m/%d/%Y")
            self._page.fill("#P17_END_DATE_input", end_str)
            self._page.keyboard.press("Escape")  # Close date picker

            # Set rows to maximum to get all transactions in one request
            rows_select = self._page.query_selector("#P17_ROWS")
            if rows_select:
                # Try to set to highest value available
                self._page.select_option("#P17_ROWS", "1000")

            # Click GO to apply filters (button with class fzbutton)
            go_button = self._page.query_selector("button.fzbutton:has-text('GO'), a[href*='P17_GO']")
            if go_button:
                go_button.click()
                self._page.wait_for_load_state("networkidle")
                time.sleep(1)

            # Parse all transactions from the filtered results
            all_transactions = self._parse_transactions_page()

            # If there's still pagination, fetch additional pages
            page_ranges = self._get_page_ranges()
            if page_ranges and len(page_ranges) > 1:
                # Sort by start number descending to get newest first
                page_ranges.sort(key=lambda x: x[0], reverse=True)
                pages_fetched = 1

                for start, end, link_text in page_ranges[1:]:  # Skip first (already fetched)
                    if pages_fetched >= max_pages:
                        break

                    link = self._page.query_selector(f".pagination a:has-text('{link_text}')")
                    if link:
                        link.click()
                        self._page.wait_for_load_state("networkidle")
                        time.sleep(0.5)
                        transactions = self._parse_transactions_page()
                        all_transactions.extend(transactions)
                        pages_fetched += 1

            return all_transactions

        except Exception as e:
            raise e
        finally:
            self._stop_browser()

    def _get_page_ranges(self) -> list[tuple[int, int, str]]:
        """Get all available page ranges from pagination links."""
        page_ranges = []
        pagination_links = self._page.query_selector_all(".pagination a")

        for link in pagination_links:
            link_text = link.inner_text().strip()
            # Parse ranges like "1-100", "101-200", etc.
            match = re.match(r"(\d+)-(\d+)", link_text)
            if match:
                start = int(match.group(1))
                end = int(match.group(2))
                page_ranges.append((start, end, link_text))

        return page_ranges

    def _parse_transactions_page(self) -> list[FamZooTransaction]:
        """Parse transaction data from the current page."""
        transactions = []
        seen_ids = set()  # Deduplicate by transaction_id

        # Get all table rows
        rows = self._page.query_selector_all("tr")

        for row in rows:
            text = row.inner_text()

            # Look for rows with date patterns (MM/DD/YYYY)
            date_match = re.search(r"(\d{2}/\d{2}/\d{4})", text)
            if not date_match:
                continue

            # Parse the row data
            try:
                transaction = self._parse_transaction_row(text)
                if transaction and transaction.transaction_id not in seen_ids:
                    transactions.append(transaction)
                    seen_ids.add(transaction.transaction_id)
            except Exception:
                continue

        return transactions

    def _parse_transaction_row(self, row_text: str) -> Optional[FamZooTransaction]:
        """Parse a single transaction row."""
        # Split by tabs or multiple spaces
        parts = re.split(r"\t+|\n+", row_text)
        parts = [p.strip() for p in parts if p.strip()]

        if len(parts) < 3:
            return None

        # Find date (MM/DD/YYYY format, possibly with time)
        date_str = None
        date_idx = None
        for i, part in enumerate(parts):
            date_match = re.match(r"(\d{2}/\d{2}/\d{4})", part)
            if date_match:
                date_str = date_match.group(1)
                date_idx = i
                break

        if not date_str or date_idx is None:
            return None

        # Parse date
        try:
            date = datetime.strptime(date_str, "%m/%d/%Y")
        except ValueError:
            return None

        # Find amount (last part with $ sign)
        amount = None
        amount_str = None
        for part in reversed(parts):
            amount_match = re.search(r"[\-]?\$?([\d,]+\.?\d*)", part)
            if amount_match and "$" in part:
                amount_str = part
                try:
                    amount_value = amount_match.group(1).replace(",", "")
                    amount = float(amount_value)
                    # Check for negative
                    if "-" in part:
                        amount = -abs(amount)
                    break
                except ValueError:
                    continue

        if amount is None:
            return None

        # Skip zero-amount transactions (like pending authorizations)
        if amount == 0:
            return None

        # Description is typically after the date
        description = ""
        memo = ""
        if date_idx + 1 < len(parts):
            description = parts[date_idx + 1]

        # Memo might be next
        if date_idx + 2 < len(parts) and parts[date_idx + 2] != amount_str:
            memo = parts[date_idx + 2]

        # Skip "Starting Balance" entries
        if "Starting Balance" in description:
            return None

        # Generate unique transaction ID
        hash_input = f"{date_str}{description}{amount}"
        transaction_id = f"{date.strftime('%Y%m%d')}_{abs(hash(hash_input)) % 10000000000}"

        return FamZooTransaction(
            date=date,
            description=description[:100],  # Limit description length
            amount=amount,
            memo=memo[:100] if memo else "",
            transaction_id=transaction_id,
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._stop_browser()
