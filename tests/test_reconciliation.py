import pytest

import db

""" 
Helper function to check for the status of a specific transaction hash - to be used in the pytests.
"""
def status_of(tx_hash):
    rows = db.query_transactions(transaction_hash=tx_hash)["results"]
    assert rows, f"{tx_hash} not in table"
    return rows[0]["transaction_pending"], rows[0]["num_confirmations"]

"""
Checks the update_pending_transaction function within db, checks whether a transaction is correctly marked pending.
"""
def test_shallow_transaction_stays_pending(add_transfer, fake_chain):
    add_transfer("0xa", block=100, block_hash="0xhashA")
    fake_chain.set(100, "0xhashA")

    seen, confirmed, orphaned = db.update_pending_transactions(103, 6, fake_chain.hash_at)

    assert (seen, confirmed, orphaned) == (1, 0, 0)
    assert status_of("0xa") == ("Yes", 3)


""" Work on this loophole - should be able to change status to pending after hash check is added """
def test_transaction_confirms_at_threshold(add_transfer, fake_chain):
    add_transfer("0xa", block=100, block_hash="0xhashA")
    fake_chain.set(100, "0xhashA")

    seen, confirmed, orphaned = db.update_pending_transactions(106, 6, fake_chain.hash_at)

    assert (seen, confirmed, orphaned) == (1, 1, 0)
    assert status_of("0xa") == ("No", 6)


"""
Checks the update_pending_transaction function within db, checks that a transaction whose block
was reorged out (stored hash no longer matches the chain) is marked orphaned, while a transaction
in an unaffected block still confirms normally.
"""
def test_reorged_block_marks_transaction_orphaned(add_transfer, fake_chain):
    add_transfer("0xsurvivor", block=100, block_hash="0xhashA")
    add_transfer("0xorphan", block=101, block_hash="0xhashB")

    fake_chain.set(100, "0xhashA")
    fake_chain.set(101, "0xREPLACEMENT")

    seen, confirmed, orphaned = db.update_pending_transactions(110, 6, fake_chain.hash_at)

    assert (seen, confirmed, orphaned) == (2, 1, 1)
    assert status_of("0xsurvivor") == ("No", 10)
    assert status_of("0xorphan")[0] == "Orphaned"


"""
Checks the update_pending_transaction function within db, shows the bug the hash check exists to
prevent: run without a chain lookup, the reorged transaction is wrongly confirmed by depth alone.
Once confirmed it is never re-examined, so a later pass with the hash check cannot undo it.
"""
def test_orphan_would_have_been_confirmed_without_hash_check(add_transfer, fake_chain):
    add_transfer("0xorphan", block=101, block_hash="0xhashB")
    fake_chain.set(101, "0xREPLACEMENT")

    db.update_pending_transactions(110, 6)
    assert status_of("0xorphan") == ("No", 9)

    db.update_pending_transactions(110, 6, fake_chain.hash_at)
    assert status_of("0xorphan") == ("No", 9)


"""
Checks the update_pending_transaction function within db, confirms that a transaction already past
the threshold is skipped entirely - not re-examined, and its block is never looked up on the chain.
"""
def test_confirmed_rows_are_never_reexamined(add_transfer, fake_chain):
    add_transfer("0xdeep", block=50, block_hash="0xhashC", confirmations=9, status="No")
    add_transfer("0xshallow", block=100, block_hash="0xhashA")
    fake_chain.set(100, "0xhashA")

    seen, _, _ = db.update_pending_transactions(104, 6, fake_chain.hash_at)

    assert seen == 1
    assert fake_chain.calls == [100]
    assert status_of("0xdeep") == ("No", 9)


"""
Checks the update_pending_transaction function within db, confirms that once a transaction is marked
orphaned it drops out of the pending set and is not looked up again on later passes.
"""
def test_orphaned_rows_are_never_reexamined(add_transfer, fake_chain):
    add_transfer("0xorphan", block=101, block_hash="0xhashB")
    fake_chain.set(101, "0xREPLACEMENT")

    db.update_pending_transactions(110, 6, fake_chain.hash_at)
    fake_chain.calls.clear()

    seen, _, _ = db.update_pending_transactions(200, 6, fake_chain.hash_at)

    assert seen == 0
    assert fake_chain.calls == []


"""
Checks the update_pending_transaction function within db, confirms that several pending transactions
in the same block trigger only one chain lookup for that block, not one lookup per transaction.
"""
def test_block_hash_fetched_once_per_distinct_block(add_transfer, fake_chain):
    add_transfer("0xa", block=100, block_hash="0xhashA", log_index=0)
    add_transfer("0xb", block=100, block_hash="0xhashA", log_index=1)
    add_transfer("0xc", block=100, block_hash="0xhashA", log_index=2)
    fake_chain.set(100, "0xhashA")

    db.update_pending_transactions(104, 6, fake_chain.hash_at)

    assert fake_chain.calls == [100]


"""
Checks the update_pending_transaction function within db, confirms that with no chain lookup passed
the function falls back to depth-only confirmation instead of erroring.
"""
def test_missing_chain_lookup_degrades_to_depth_only(add_transfer):
    add_transfer("0xa", block=100, block_hash="0xhashA")

    seen, confirmed, orphaned = db.update_pending_transactions(110, 6)

    assert (seen, confirmed, orphaned) == (1, 1, 0)
    assert status_of("0xa") == ("No", 10)


"""
Checks the update_pending_transaction function within db, confirms that if the chain lookup raises
(node down), no transaction is falsely orphaned - a failed lookup must not be read as a hash mismatch.
"""
def test_unreachable_node_does_not_orphan_rows(add_transfer):
    def broken(block):
        raise ConnectionError("node down")

    add_transfer("0xa", block=100, block_hash="0xhashA")

    seen, confirmed, orphaned = db.update_pending_transactions(110, 6, broken)

    assert orphaned == 0
    assert status_of("0xa") == ("No", 10)


"""
Checks the update_pending_transaction function within db, confirms that when nothing is pending the
function returns early and never touches the chain at all.
"""
def test_no_pending_rows_skips_chain_entirely(add_transfer, fake_chain):
    add_transfer("0xdeep", block=50, block_hash="0xhashC", confirmations=9, status="No")

    seen, confirmed, orphaned = db.update_pending_transactions(200, 6, fake_chain.hash_at)

    assert (seen, confirmed, orphaned) == (0, 0, 0)
    assert fake_chain.calls == []
