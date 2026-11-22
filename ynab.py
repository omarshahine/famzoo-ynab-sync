"""YNAB API client for creating transactions."""

from dataclasses import dataclass, field
from datetime import date, timedelta
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
    cleared: str = "uncleared"
    # Imported unapproved, like a bank feed, so ynab-auto-approve categorizes them.
    # Created approved, a row YNAB couldn't categorize sat as approved-but-Uncategorized
    # where no approval pass ever looks.
    approved: bool = False
    import_id: Optional[str] = None
    # Not sent to YNAB: marks a FamZoo transfer to/from the configured transfer account.
    is_transfer: bool = field(default=False, compare=False)

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
        self.transfer_payee_id: Optional[str] = None  # resolved lazily from the transfer account
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
        elif method == "PATCH":
            response = self.session.patch(url, json=data)
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

    def get_account_transactions(self, since: date) -> list[dict]:
        """Transactions in the FamZoo YNAB account on or after `since` (read-only)."""
        endpoint = f"/budgets/{self.budget_id}/accounts/{self.account_id}/transactions?since_date={since.isoformat()}"
        response = self._make_request("GET", endpoint)
        return response.get("data", {}).get("transactions", [])

    def update_transactions(self, updates: list[dict]) -> dict:
        """Patch existing transactions (each dict carries its `id`)."""
        if not updates:
            return {}
        endpoint = f"/budgets/{self.budget_id}/transactions"
        response = self._make_request("PATCH", endpoint, {"transactions": updates})
        return response.get("data", {})

    def resolve_transfer_payee(self) -> Optional[str]:
        """The transfer payee of the configured transfer account, so transfers link by ID, not by name."""
        if self.transfer_payee_id or not self.transfer_account_id:
            return self.transfer_payee_id
        for account in self.get_accounts():
            if account.get("id") == self.transfer_account_id:
                self.transfer_payee_id = account.get("transfer_payee_id")
        return self.transfer_payee_id

    def famzoo_to_ynab(self, famzoo_tx: FamZooTransaction) -> YNABTransaction:
        """Convert a FamZoo transaction to YNAB format."""
        # YNAB uses milliunits (1000 = $1.00)
        amount_milliunits = int(round(famzoo_tx.amount * 1000))

        # Create a unique import_id to prevent duplicates
        # Format: FZYN:date:hash (max 36 chars)
        hash_input = f"{famzoo_tx.date.isoformat()}{famzoo_tx.description}{famzoo_tx.amount}"
        tx_hash = hashlib.md5(hash_input.encode()).hexdigest()[:16]
        import_id = f"{IMPORT_PREFIX}{famzoo_tx.date.strftime('%Y%m%d')}:{tx_hash}"

        # Check if this is a transfer
        is_transfer_tx = is_transfer(famzoo_tx.description)

        # Build memo from FamZoo memo or description
        memo = famzoo_tx.memo if famzoo_tx.memo else ""
        if not memo:
            memo = f"FamZoo: {famzoo_tx.description[:80]}"

        # Handle transfers differently
        if is_transfer_tx and self.transfer_account_id:
            # Link by the transfer account's own payee when known. The name fallback
            # relies on YNAB matching "Transfer: Checking" to the right account.
            return YNABTransaction(
                account_id=self.account_id,
                date=famzoo_tx.date.strftime("%Y-%m-%d"),
                amount=amount_milliunits,
                payee_id=self.transfer_payee_id,
                payee_name=None if self.transfer_payee_id else "Transfer: Checking",
                memo=memo[:200],
                import_id=import_id,
                is_transfer=True,
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

    def plan_sync(self, famzoo_transactions: list[FamZooTransaction]) -> "SyncPlan":
        """Decide what to create and which transfers YNAB already has (read-only)."""
        if self.transfer_account_id:
            self.resolve_transfer_payee()
        ynab_transactions = [self.famzoo_to_ynab(tx) for tx in famzoo_transactions]
        transfers = [t for t in ynab_transactions if t.is_transfer]
        if not transfers:
            return SyncPlan(to_create=ynab_transactions)
        earliest = min(date.fromisoformat(t.date) for t in transfers)
        existing = self.get_account_transactions(earliest - timedelta(days=MATCH_WINDOW_DAYS))
        return plan_transfer_links(ynab_transactions, existing, self.transfer_account_id)

    def sync_famzoo_transactions(
        self, famzoo_transactions: list[FamZooTransaction]
    ) -> tuple[int, int, int]:
        """
        Sync FamZoo transactions to YNAB.

        Returns:
            Tuple of (created_count, duplicate_count, linked_count)
        """
        if not famzoo_transactions:
            return 0, 0, 0

        plan = self.plan_sync(famzoo_transactions)

        # Claim the transfers the bank feed already imported instead of adding a second pair.
        self.update_transactions(plan.updates())

        result = self.create_transactions(plan.to_create)

        created = len(result.get("transactions", []))
        duplicates = len(result.get("duplicate_import_ids", []))

        return created, duplicates, len(plan.links)


IMPORT_PREFIX = "FZYN:"
# How far apart the bank feed and FamZoo may date the same transfer (FamZoo posts a day or more later).
MATCH_WINDOW_DAYS = 5


@dataclass
class TransferLink:
    """A FamZoo transfer that YNAB already holds, so it is claimed rather than created."""

    new: YNABTransaction
    existing: dict

    def update(self) -> Optional[dict]:
        """The PATCH body that marks the existing row cleared and tags it with the FamZoo import_id.

        YNAB doesn't let the API set import_id on an existing transaction, so the
        tag goes in the memo. It stops a later FamZoo transfer from claiming the
        same row and keeps re-runs from claiming it twice.
        """
        memo = self.existing.get("memo") or ""
        if self.new.import_id in memo:
            return None  # linked on an earlier run
        tag = f"[{self.new.import_id}]"
        base = memo or self.new.memo or ""
        base = base[: 200 - len(tag) - 1].rstrip()
        body = {"id": self.existing["id"], "memo": f"{base} {tag}".strip()}
        if self.existing.get("cleared") == "uncleared":
            body["cleared"] = "cleared"  # FamZoo has confirmed it; never downgrade a reconciled row
        return body


@dataclass
class SyncPlan:
    to_create: list[YNABTransaction]
    links: list[TransferLink] = field(default_factory=list)

    def updates(self) -> list[dict]:
        return [u for u in (link.update() for link in self.links) if u]


def _is_famzoo_linked(existing: dict) -> bool:
    return (existing.get("import_id") or "").startswith(IMPORT_PREFIX) or IMPORT_PREFIX in (existing.get("memo") or "")


def plan_transfer_links(
    ynab_transactions: list[YNABTransaction], existing: list[dict], transfer_account_id: Optional[str]
) -> SyncPlan:
    """Pair FamZoo transfers with transfers already in the FamZoo account.

    When the bank feed on the checking account imports a move first, YNAB adds
    the FamZoo side itself. FamZoo's own record of the move (for example
    "Direct Deposit: SCHWAB BANK") arrives days later and must claim that row,
    not create a second transfer pair.

    A row qualifies when it is a live transfer with the same account, the same
    amount and sign, dated within MATCH_WINDOW_DAYS, and no FamZoo import is
    tied to it yet. Each row is claimed at most once, closest date first, so
    two equal transfers a few days apart pair up one to one.
    """
    live = [e for e in existing if not e.get("deleted")]
    present_ids = {e.get("import_id") for e in live if e.get("import_id")}
    links, linked = [], set()
    pending = []
    for tx in ynab_transactions:
        if not tx.is_transfer or not transfer_account_id or tx.import_id in present_ids:
            continue  # not a transfer, or YNAB's import_id dedup already covers it
        already = next((e for e in live if tx.import_id in (e.get("memo") or "")), None)
        if already:
            links.append(TransferLink(tx, already))  # claimed on an earlier run
            linked.add(id(tx))
            live = [e for e in live if e["id"] != already["id"]]
        else:
            pending.append(tx)

    candidates = []
    for tx in pending:
        tx_date = date.fromisoformat(tx.date)
        for e in live:
            if (e.get("transfer_account_id") != transfer_account_id or e.get("amount") != tx.amount
                    or _is_famzoo_linked(e)):
                continue
            gap = abs((date.fromisoformat(e["date"]) - tx_date).days)
            if gap <= MATCH_WINDOW_DAYS:
                candidates.append((gap, tx.date, e["date"], id(tx), tx, e))

    claimed = set()
    for gap, _, _, key, tx, e in sorted(candidates, key=lambda c: c[:3]):
        if key in linked or e["id"] in claimed:
            continue
        links.append(TransferLink(tx, e))
        linked.add(key)
        claimed.add(e["id"])

    to_create = [tx for tx in ynab_transactions if id(tx) not in linked]
    return SyncPlan(to_create=to_create, links=links)
