"""Transaction tracking to prevent duplicate imports."""

import json
import re
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from famzoo import FamZooTransaction


@dataclass
class SyncState:
    """State of the last sync operation."""

    last_sync_date: str  # ISO format datetime
    last_transaction_date: str  # Date of most recent transaction
    imported_transaction_ids: list[str]  # List of imported transaction IDs
    total_imported: int
    first_sync_date: str = ""  # Fixed floor date for fetching (ISO format date)
    # One settle_key per imported purchase (with repeats), so a charge that FamZoo
    # re-describes when it settles isn't imported a second time. None = not seeded yet.
    imported_settle_keys: Optional[list[str]] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SyncState":
        """Create from dictionary."""
        return cls(
            last_sync_date=data.get("last_sync_date", ""),
            last_transaction_date=data.get("last_transaction_date", ""),
            imported_transaction_ids=data.get("imported_transaction_ids", []),
            total_imported=data.get("total_imported", 0),
            first_sync_date=data.get("first_sync_date", ""),
            imported_settle_keys=data.get("imported_settle_keys"),
        )

    @classmethod
    def empty(cls) -> "SyncState":
        """Create empty initial state."""
        return cls(
            last_sync_date="",
            last_transaction_date="",
            imported_transaction_ids=[],
            total_imported=0,
        )


LOCATION_SUFFIX = re.compile(r"\s+(USA|[A-Z]{2})$")


def settle_key(transaction: FamZooTransaction) -> str:
    """Identity that survives FamZoo re-describing a charge when it settles.

    A pending charge reads "MERCHANT SEATTLE USA"; once settled the same charge
    reads "MERCHANT SEATTLE WA". The transaction ID hashes the description, so
    the two looked like different purchases and both were imported.
    """
    description = LOCATION_SUFFIX.sub("", transaction.description.strip().upper())
    card = "".join(ch for ch in transaction.account if ch.isdigit())[-4:]  # labels change owners; digits don't
    return f"{card}|{transaction.date.strftime('%Y-%m-%d')}|{transaction.amount:.2f}|{description}"


class TransactionTracker:
    """Tracks imported transactions to prevent duplicates."""

    DEFAULT_STATE_FILE = ".famzoo_sync_state.json"
    MAX_TRACKED_IDS = 1000  # Keep last N transaction IDs to prevent file bloat

    def __init__(self, state_file: Optional[str] = None):
        self.state_file = Path(state_file or self.DEFAULT_STATE_FILE)
        self.state = self._load_state()

    def _load_state(self) -> SyncState:
        """Load state from file."""
        if not self.state_file.exists():
            return SyncState.empty()

        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
                return SyncState.from_dict(data)
        except (json.JSONDecodeError, IOError):
            return SyncState.empty()

    def _save_state(self):
        """Save state to file."""
        with open(self.state_file, "w") as f:
            json.dump(self.state.to_dict(), f, indent=2)

    def is_imported(self, transaction: FamZooTransaction) -> bool:
        """Check if a transaction has already been imported."""
        return transaction.transaction_id in self.state.imported_transaction_ids

    def filter_new_transactions(
        self, transactions: list[FamZooTransaction]
    ) -> list[FamZooTransaction]:
        """Filter out transactions that have already been imported."""
        return self.split_new_transactions(transactions)[0]

    def split_new_transactions(
        self, transactions: list[FamZooTransaction]
    ) -> tuple[list[FamZooTransaction], list[FamZooTransaction]]:
        """Return (new, resettled) from a full fetch since the floor date.

        resettled are unseen IDs whose settle_key was already imported as often
        as it appears in this fetch: the settled form of a charge imported while
        pending. Callers mark them imported without creating them in YNAB.
        """
        if self.state.imported_settle_keys is None:
            # First run with settle keys: seed from what's already imported.
            self.state.imported_settle_keys = [settle_key(tx) for tx in transactions if self.is_imported(tx)]
            self._save_state()
        imported = Counter(self.state.imported_settle_keys)
        fetched = Counter(settle_key(tx) for tx in transactions)
        new, resettled = [], []
        for tx in transactions:
            if self.is_imported(tx):
                continue
            key = settle_key(tx)
            (resettled if imported[key] >= fetched[key] else new).append(tx)
        return new, resettled

    def mark_imported(self, transactions: list[FamZooTransaction], resettled: bool = False):
        """Mark transactions as imported.

        resettled=True records the IDs only: the purchase itself was already
        counted under its pending description.
        """
        if not transactions:
            return

        # Add new transaction IDs
        new_ids = [tx.transaction_id for tx in transactions]
        self.state.imported_transaction_ids.extend(new_ids)
        if not resettled:
            self.state.imported_settle_keys = (self.state.imported_settle_keys or []) + [
                settle_key(tx) for tx in transactions]

        # Trim to max size (keep most recent)
        if len(self.state.imported_transaction_ids) > self.MAX_TRACKED_IDS:
            self.state.imported_transaction_ids = self.state.imported_transaction_ids[
                -self.MAX_TRACKED_IDS :
            ]

        # Update last transaction date
        latest = max(transactions, key=lambda tx: tx.date)
        self.state.last_transaction_date = latest.date.isoformat()

        # Update sync metadata
        self.state.last_sync_date = datetime.now().isoformat()
        if not resettled:
            self.state.total_imported += len(transactions)

        # Save state
        self._save_state()

    def get_last_sync_info(self) -> dict:
        """Get information about the last sync."""
        return {
            "last_sync": self.state.last_sync_date or "Never",
            "last_transaction_date": self.state.last_transaction_date or "N/A",
            "total_imported": self.state.total_imported,
            "tracked_ids": len(self.state.imported_transaction_ids),
        }

    def get_last_transaction_date(self) -> Optional[datetime]:
        """Get the date of the most recent imported transaction."""
        if not self.state.last_transaction_date:
            return None
        try:
            return datetime.fromisoformat(self.state.last_transaction_date)
        except ValueError:
            return None

    def get_first_sync_date(self) -> Optional[datetime]:
        """Get the fixed floor date for fetching transactions."""
        if not self.state.first_sync_date:
            return None
        try:
            return datetime.fromisoformat(self.state.first_sync_date)
        except ValueError:
            return None

    def set_first_sync_date(self, date: datetime):
        """Set the fixed floor date for fetching transactions (only if not already set)."""
        if not self.state.first_sync_date:
            self.state.first_sync_date = date.strftime("%Y-%m-%d")
            self._save_state()

    def reset(self):
        """Reset tracking state."""
        self.state = SyncState.empty()
        self._save_state()
