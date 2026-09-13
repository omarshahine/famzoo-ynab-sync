"""Unit tests for transfer classification.

Run with:  python -m unittest test_payee
"""
import unittest
from datetime import datetime

from famzoo import FamZooTransaction
from payee import find_internal_transfers


def tx(tid, day, amount, desc, account):
    return FamZooTransaction(date=datetime(2026, 9, day, 18, 56), description=desc, amount=amount,
                             memo="", transaction_id=tid, account=account)


class InternalTransferTests(unittest.TestCase):
    def test_move_between_two_synced_cards_pairs_both_legs(self):
        txs = [tx("out", 1, -697.08, "Transfer to Kids Spending for Sam:", "***1111"),
               tx("in", 1, 697.08, "Transfer from Kids Spending for Alex:", "***2222"),
               tx("buy", 1, -697.08, "SOME STORE SEATTLE WA", "***2222")]
        self.assertEqual(find_internal_transfers(txs), {"out", "in"})

    def test_one_sided_transfer_from_family_account_stays_external(self):
        txs = [tx("load", 3, 200.0, "Transfer from Family Account for Parent:", "***1111")]
        self.assertEqual(find_internal_transfers(txs), set())

    def test_opposite_legs_on_the_same_card_are_not_paired(self):
        txs = [tx("a", 5, -50.0, "Transfer to Family Account for Parent:", "***1111"),
               tx("b", 5, 50.0, "Transfer from Family Account for Parent:", "***1111")]
        self.assertEqual(find_internal_transfers(txs), set())

    def test_different_days_are_not_paired(self):
        txs = [tx("a", 5, -50.0, "Transfer to Kids Spending for Sam:", "***1111"),
               tx("b", 6, 50.0, "Transfer from Kids Spending for Alex:", "***2222")]
        self.assertEqual(find_internal_transfers(txs), set())


if __name__ == "__main__":
    unittest.main()
