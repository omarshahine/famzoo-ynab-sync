"""Unit tests for linking FamZoo transfers to ones the bank feed already imported.

Run with:  python -m unittest test_ynab
No test talks to YNAB: the client's HTTP methods are replaced with fakes.
"""
import unittest
from datetime import datetime

from famzoo import FamZooTransaction
from ynab import YNABClient, plan_transfer_links

CHECKING = "acct-checking"
FAMZOO = "acct-famzoo"
OTHER = "acct-savings"


def fz(day, amount, desc, month=11):
    return FamZooTransaction(date=datetime(2026, month, day, 9, 0), description=desc, amount=amount,
                             memo="", transaction_id=f"{day}_{amount}_{desc}", account="***1111")


def existing(tid, day, amount, transfer_account=CHECKING, import_id=None, memo=None, cleared="cleared"):
    return {"id": tid, "date": f"2026-11-{day:02d}", "amount": int(amount * 1000), "memo": memo,
            "import_id": import_id, "cleared": cleared, "transfer_account_id": transfer_account,
            "deleted": False}


class FakeClient(YNABClient):
    """YNABClient with the network replaced by in-memory fakes."""

    def __init__(self, rows):
        super().__init__("token", "budget", FAMZOO, CHECKING)
        self.rows, self.patched, self.created = rows, [], []

    def get_accounts(self):
        return [{"id": CHECKING, "transfer_payee_id": "payee-checking"}]

    def get_account_transactions(self, since):
        return [r for r in self.rows if r["date"] >= since.isoformat()]

    def update_transactions(self, updates):
        self.patched.extend(updates)
        for u in updates:  # apply like YNAB would, so re-runs see the change
            row = next(r for r in self.rows if r["id"] == u["id"])
            row.update({k: v for k, v in u.items() if k != "id"})

    def create_transactions(self, transactions):
        fresh = [t for t in transactions if t.import_id not in {c.import_id for c in self.created}]
        self.created.extend(fresh)
        return {"transactions": fresh,
                "duplicate_import_ids": [t.import_id for t in transactions if t not in fresh]}


DEPOSIT = "Direct Deposit: SCHWAB BANK"


class TransferLinkTests(unittest.TestCase):
    def test_bank_feed_first_claims_existing_transfer_instead_of_duplicating(self):
        # The 2026-11-19 bug: checking's bank import made the pair, FamZoo's record arrives on the 20th.
        row = existing("bank", 19, 2000.0, cleared="uncleared")
        client = FakeClient([row])
        created, dupes, linked = client.sync_famzoo_transactions([fz(20, 2000.0, DEPOSIT)])
        self.assertEqual((created, dupes, linked), (0, 0, 1))
        self.assertEqual(client.created, [])
        patch = client.patched[0]
        self.assertEqual(patch["id"], "bank")
        self.assertEqual(patch["cleared"], "cleared")
        self.assertIn("FZYN:20261120:", patch["memo"])

    def test_rerun_after_link_is_idempotent(self):
        client = FakeClient([existing("bank", 19, 2000.0)])
        client.sync_famzoo_transactions([fz(20, 2000.0, DEPOSIT)])
        client.patched.clear()
        self.assertEqual(client.sync_famzoo_transactions([fz(20, 2000.0, DEPOSIT)]), (0, 0, 1))
        self.assertEqual((client.patched, client.created), ([], []))

    def test_reconciled_row_is_tagged_but_not_downgraded(self):
        client = FakeClient([existing("bank", 19, 2000.0, cleared="reconciled")])
        client.sync_famzoo_transactions([fz(20, 2000.0, DEPOSIT)])
        self.assertNotIn("cleared", client.patched[0])

    def test_famzoo_first_creates_the_transfer(self):
        client = FakeClient([])
        self.assertEqual(client.sync_famzoo_transactions([fz(20, 2000.0, DEPOSIT)]), (1, 0, 0))
        made = client.created[0]
        self.assertEqual((made.payee_id, made.amount), ("payee-checking", 2000000))
        self.assertTrue(made.import_id.startswith("FZYN:20261120:"))
        # A re-run is caught by import_id dedup, and our own row is never "claimed".
        client.rows.append(existing("ours", 20, 2000.0, import_id=made.import_id))
        self.assertEqual(client.sync_famzoo_transactions([fz(20, 2000.0, DEPOSIT)]), (0, 1, 0))
        self.assertEqual(client.patched, [])

    def test_famzoo_to_checking_direction_matches_outflow_only(self):
        rows = [existing("in", 19, 300.0), existing("out", 19, -300.0)]
        client = FakeClient(rows)
        client.sync_famzoo_transactions([fz(20, -300.0, "Transfer to Family Account for Parent:")])
        self.assertEqual([p["id"] for p in client.patched], ["out"])

    def test_ordinary_purchase_is_unchanged(self):
        client = FakeClient([existing("bank", 19, -42.5)])
        self.assertEqual(client.sync_famzoo_transactions([fz(19, -42.5, "SOME STORE SEATTLE WA")]), (1, 0, 0))
        made = client.created[0]
        self.assertEqual((made.payee_name, made.payee_id, made.is_transfer), ("Some Store", None, False))
        self.assertEqual(client.patched, [])

    def test_two_equal_transfers_on_nearby_dates_pair_one_to_one(self):
        rows = [existing("b1", 3, 500.0), existing("b2", 6, 500.0)]
        client = FakeClient(rows)
        result = client.sync_famzoo_transactions([fz(4, 500.0, DEPOSIT), fz(7, 500.0, DEPOSIT)])
        self.assertEqual(result, (0, 0, 2))
        by_row = {p["id"]: p["memo"] for p in client.patched}
        self.assertIn("FZYN:20261104:", by_row["b1"])
        self.assertIn("FZYN:20261107:", by_row["b2"])

    def test_second_transfer_without_bank_row_is_created_not_overmatched(self):
        client = FakeClient([existing("b1", 3, 500.0)])
        self.assertEqual(client.sync_famzoo_transactions([fz(4, 500.0, DEPOSIT), fz(6, 500.0, DEPOSIT)]),
                         (1, 0, 1))
        self.assertEqual(client.created[0].date, "2026-11-06")
        # Next day a third equal transfer must not steal the row the first one claimed.
        client.patched.clear()
        self.assertEqual(client.sync_famzoo_transactions([fz(5, 500.0, "Direct Deposit: SCHWAB BANK ")]),
                         (1, 0, 0))
        self.assertEqual(client.patched, [])

    def test_rows_outside_window_other_accounts_or_other_amounts_are_ignored(self):
        rows = [existing("old", 13, 2000.0), existing("savings", 19, 2000.0, transfer_account=OTHER),
                existing("amount", 19, 2000.01), dict(existing("gone", 19, 2000.0), deleted=True),
                existing("tagged", 19, 2000.0, memo="moved [FZYN:20261118:abcdef0123456789]")]
        client = FakeClient(rows)
        self.assertEqual(client.sync_famzoo_transactions([fz(20, 2000.0, DEPOSIT)]), (1, 0, 0))
        self.assertEqual(client.patched, [])

    def test_plan_without_transfer_account_creates_everything(self):
        client = FakeClient([])
        client.transfer_account_id = None
        tx = client.famzoo_to_ynab(fz(20, 2000.0, DEPOSIT))
        plan = plan_transfer_links([tx], [existing("bank", 19, 2000.0)], None)
        self.assertEqual((plan.to_create, plan.links), ([tx], []))


if __name__ == "__main__":
    unittest.main()
