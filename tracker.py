"""Transaction tracking to prevent duplicate imports."""

import json
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
        return [tx for tx in transactions if not self.is_imported(tx)]

    def mark_imported(self, transactions: list[FamZooTransaction]):
        """Mark transactions as imported."""
        if not transactions:
            return

        # Add new transaction IDs
        new_ids = [tx.transaction_id for tx in transactions]
        self.state.imported_transaction_ids.extend(new_ids)

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

    def reset(self):
        """Reset tracking state."""
        self.state = SyncState.empty()
        self._save_state()
