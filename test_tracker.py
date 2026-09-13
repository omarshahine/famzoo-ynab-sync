"""Unit tests for duplicate protection in the tracker.

Run with:  python -m unittest test_tracker
"""
import os
import tempfile
import unittest
from datetime import datetime

from famzoo import FamZooTransaction
from tracker import TransactionTracker


def tx(tid, desc, amount=-15.0, day=7, account="***1111"):
    return FamZooTransaction(date=datetime(2026, 7, day, 12, 0), description=desc, amount=amount,
                             memo="", transaction_id=tid, account=account)


class SettledRedescriptionTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "state.json")
        self.tracker = TransactionTracker(self.path)

    def test_pending_then_settled_description_is_imported_once(self):
        pending = tx("p", "PHARMACY SEATTLE USA")
        self.tracker.mark_imported(self.tracker.split_new_transactions([pending])[0])
        settled = tx("s", "PHARMACY SEATTLE WA")  # pending row is gone from the fetch
        new, resettled = self.tracker.split_new_transactions([settled])
        self.assertEqual((new, [t.transaction_id for t in resettled]), ([], ["s"]))

    def test_second_identical_purchase_same_day_still_imports(self):
        first = tx("a", "COFFEE SEATTLE WA", -5.5)
        self.tracker.mark_imported(self.tracker.split_new_transactions([first])[0])
        second = tx("b", "COFFEE SEATTLE USA", -5.5)
        new, resettled = self.tracker.split_new_transactions([first, second])
        self.assertEqual(([t.transaction_id for t in new], resettled), (["b"], []))

    def test_same_purchase_on_another_card_is_not_a_duplicate(self):
        self.tracker.mark_imported(self.tracker.split_new_transactions([tx("a", "STORE SEATTLE USA")])[0])
        new, _ = self.tracker.split_new_transactions([tx("b", "STORE SEATTLE WA", account="***2222")])
        self.assertEqual([t.transaction_id for t in new], ["b"])

    def test_existing_state_is_seeded_without_reimporting(self):
        self.tracker.state.imported_transaction_ids = ["old"]
        new, resettled = self.tracker.split_new_transactions([tx("old", "STORE SEATTLE WA")])
        self.assertEqual((new, resettled), ([], []))
        self.assertEqual(len(TransactionTracker(self.path).state.imported_settle_keys), 1)


if __name__ == "__main__":
    unittest.main()
