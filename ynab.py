"""YNAB API client for creating transactions."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import hashlib

import requests

from famzoo import FamZooTransaction
from payee import normalize_payee, is_transfer


@dataclass
class YNABTransaction:
    """Represents a transaction for YNAB API."""

    account_id: str
    date: str  # YYYY-MM-DD format
    amount: int  # In milliunits (1000 = $1.00)
    payee_name: Optional[str] = None
    payee_id: Optional[str] = None  # For transfers, this is the target account ID
    memo: Optional[str] = None
    cleared: str = "cleared"
    approved: bool = True
    import_id: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to YNAB API format."""
        data = {
            "account_id": self.account_id,
            "date": self.date,
            "amount": self.amount,
            "cleared": self.cleared,
            "approved": self.approved,
        }

        # For transfers, use payee_id (which is the transfer account ID)
        # For regular transactions, use payee_name
        if self.payee_id:
            data["payee_id"] = self.payee_id
        elif self.payee_name:
            data["payee_name"] = self.payee_name

        if self.memo:
            data["memo"] = self.memo

        if self.import_id:
            data["import_id"] = self.import_id

        return data


class YNABClient:
    """Client for YNAB API."""

    BASE_URL = "https://api.ynab.com/v1"

    def __init__(self, api_token: str, budget_id: str, account_id: str, transfer_account_id: Optional[str] = None):
        self.api_token = api_token
        self.budget_id = budget_id
        self.account_id = account_id
        self.transfer_account_id = transfer_account_id
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        })

    def _make_request(self, method: str, endpoint: str, data: dict = None) -> dict:
        """Make an API request."""
        url = f"{self.BASE_URL}{endpoint}"

        if method == "GET":
            response = self.session.get(url)
        elif method == "POST":
            response = self.session.post(url, json=data)
        else:
            raise ValueError(f"Unsupported method: {method}")

        if response.status_code == 401:
            raise Exception("Invalid YNAB API token")
        elif response.status_code == 404:
            raise Exception("Budget or account not found")
        elif response.status_code >= 400:
            error_msg = response.json().get("error", {}).get("detail", response.text)
            raise Exception(f"YNAB API error: {error_msg}")

        return response.json()

    def test_connection(self) -> bool:
        """Test the API connection and validate budget/account."""
        try:
            # Test by fetching budget info
            self._make_request("GET", f"/budgets/{self.budget_id}")
            return True
        except Exception:
            return False

    def get_budgets(self) -> list[dict]:
        """Get list of available budgets."""
        response = self._make_request("GET", "/budgets")
        return response.get("data", {}).get("budgets", [])

    def get_accounts(self) -> list[dict]:
        """Get list of accounts in the budget."""
        response = self._make_request("GET", f"/budgets/{self.budget_id}/accounts")
        return response.get("data", {}).get("accounts", [])

    def create_transactions(self, transactions: list[YNABTransaction]) -> dict:
        """Create multiple transactions in YNAB."""
        if not transactions:
            return {"created": [], "duplicates": []}

        endpoint = f"/budgets/{self.budget_id}/transactions"
        data = {
            "transactions": [t.to_dict() for t in transactions]
        }

        response = self._make_request("POST", endpoint, data)
        return response.get("data", {})

    def famzoo_to_ynab(self, famzoo_tx: FamZooTransaction) -> YNABTransaction:
        """Convert a FamZoo transaction to YNAB format."""
        # YNAB uses milliunits (1000 = $1.00)
        amount_milliunits = int(famzoo_tx.amount * 1000)

        # Create a unique import_id to prevent duplicates
        # Format: FZYN:date:hash (max 36 chars)
        hash_input = f"{famzoo_tx.date.isoformat()}{famzoo_tx.description}{famzoo_tx.amount}"
        tx_hash = hashlib.md5(hash_input.encode()).hexdigest()[:16]
        import_id = f"FZYN:{famzoo_tx.date.strftime('%Y%m%d')}:{tx_hash}"

        # Check if this is a transfer
        is_transfer_tx = is_transfer(famzoo_tx.description)

        # Build memo from FamZoo memo or description
        memo = famzoo_tx.memo if famzoo_tx.memo else ""
        if not memo:
            memo = f"FamZoo: {famzoo_tx.description[:80]}"

        # Handle transfers differently
        if is_transfer_tx and self.transfer_account_id:
            # For transfers, use payee_id which points to the transfer account
            # YNAB expects the payee_id to be "transfer:account_id" format
            return YNABTransaction(
                account_id=self.account_id,
                date=famzoo_tx.date.strftime("%Y-%m-%d"),
                amount=amount_milliunits,
                payee_id=f"transfer:{self.transfer_account_id}",
                memo=memo[:200],
                import_id=import_id,
            )
        else:
            # Normalize the payee name for regular transactions
            payee_name = normalize_payee(famzoo_tx.description)

            return YNABTransaction(
                account_id=self.account_id,
                date=famzoo_tx.date.strftime("%Y-%m-%d"),
                amount=amount_milliunits,
                payee_name=payee_name[:50],  # YNAB payee name limit
                memo=memo[:200],  # YNAB memo limit
                import_id=import_id,
            )

    def sync_famzoo_transactions(
        self, famzoo_transactions: list[FamZooTransaction]
    ) -> tuple[int, int]:
        """
        Sync FamZoo transactions to YNAB.

        Returns:
            Tuple of (created_count, duplicate_count)
        """
        if not famzoo_transactions:
            return 0, 0

        # Convert all transactions
        ynab_transactions = [
            self.famzoo_to_ynab(tx) for tx in famzoo_transactions
        ]

        # Create transactions in YNAB
        result = self.create_transactions(ynab_transactions)

        created = len(result.get("transactions", []))
        duplicates = len(result.get("duplicate_import_ids", []))

        return created, duplicates
