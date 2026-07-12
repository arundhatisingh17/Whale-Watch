import pytest

import db

"""
Checks the query_transactions functions within db.py, checks for the count data member within response.
"""
def test_same_tx_hash_different_log_index_both_stored(add_transfer):
    assert add_transfer("0xsame", block=100, block_hash="0xh", log_index=386)
    assert add_transfer("0xsame", block=100, block_hash="0xh", log_index=388)

    assert db.query_transactions(transaction_hash="0xsame")["count"] == 2


"""
Checks the query_transactions functions within db.py, the same transaction hash cannot be appended twice to the test db.
"""
def test_identical_log_is_rejected(add_transfer):
    assert add_transfer("0xsame", block=100, block_hash="0xh", log_index=1)
    assert not add_transfer("0xsame", block=100, block_hash="0xh", log_index=1)

    assert db.query_transactions(transaction_hash="0xsame")["count"] == 1


"""
Checks the query_transactions functions within db.py:

query_transactions dynamically executes queries based on whether or not the user passes in a parameter
on the client-facing dashboard. Tests whether the right transaction count is returned based on different 
address, from_address, and to_address parameter values.
"""
def test_address_filter_matches_sender_or_receiver(add_transfer):
    add_transfer("0xa", 100, "0xh", from_addr="0xWHALE", to_addr="0xother", log_index=0)
    add_transfer("0xb", 100, "0xh", from_addr="0xother", to_addr="0xWHALE", log_index=1)
    add_transfer("0xc", 100, "0xh", from_addr="0xother", to_addr="0xelse", log_index=2)

    assert db.query_transactions(address="0xwhale")["count"] == 2
    assert db.query_transactions(from_address="0xwhale")["count"] == 1
    assert db.query_transactions(to_address="0xwhale")["count"] == 1
    

"""
Checks the query_transactions functions within db.py: the min/max amount and min/max
confirmation filters return only the transactions that fall inside the given range.
"""
def test_amount_and_confirmation_ranges(add_transfer):
    add_transfer("0xa", 100, "0xh", amount=50_000.0, confirmations=1, log_index=0)
    add_transfer("0xb", 100, "0xh", amount=500_000.0, confirmations=10, log_index=1)

    assert db.query_transactions(min_amount=100_000)["count"] == 1
    assert db.query_transactions(max_amount=100_000)["count"] == 1
    assert db.query_transactions(min_amount=1_000_000)["count"] == 0
    assert db.query_transactions(min_confirmations=6)["count"] == 1
    assert db.query_transactions(max_confirmations=6)["count"] == 1


"""
Checks the query_transactions functions within db.py: the status filter maps each of the
three states - pending, confirmed, orphaned - to the right transactions.
"""
def test_status_filter_covers_three_states(add_transfer):
    add_transfer("0xa", 100, "0xh", status="Yes", log_index=0)
    add_transfer("0xb", 100, "0xh", status="No", log_index=1)
    add_transfer("0xc", 100, "0xh", status="Orphaned", log_index=2)

    assert db.query_transactions(status="pending")["count"] == 1
    assert db.query_transactions(status="confirmed")["count"] == 1
    assert db.query_transactions(status="orphaned")["count"] == 1


"""
Checks the query_transactions functions within db.py: an unrecognised status value is
rejected with a ValueError rather than silently returning nothing.
"""
def test_unknown_status_rejected(add_transfer):
    with pytest.raises(ValueError):
        db.query_transactions(status="maybe")


"""
Checks the query_transactions functions within db.py: sort_by only accepts a known column
name, so a SQL injection attempt passed as sort_by is ignored and the table is left intact.
"""
def test_sort_by_injection_is_ignored(add_transfer):
    add_transfer("0xa", 100, "0xh")

    result = db.query_transactions(sort_by="amount; DROP TABLE transactions")

    assert result["count"] == 1
    assert db.query_transactions()["count"] == 1


"""
Checks the query_transactions functions within db.py: passing several filters at once
combines them, returning only the transactions that match all of them together.
"""
def test_filters_compose(add_transfer):
    add_transfer("0xa", 100, "0xh", token="USDC", amount=200_000.0, status="Yes", log_index=0)
    add_transfer("0xb", 100, "0xh", token="USDC", amount=200_000.0, status="No", log_index=1)
    add_transfer("0xc", 101, "0xh2", token="WETH", amount=200_000.0, status="Yes", log_index=0)

    result = db.query_transactions(token_symbol="USDC", min_amount=100_000, status="pending")

    assert result["count"] == 1
    assert result["results"][0]["transaction_hash"] == "0xa"


"""
Checks the query_transactions functions within db.py: total counts every matching
transaction while count reflects only the current page, so limit caps count but not total.
"""
def test_total_reflects_filter_not_page_size(add_transfer):
    for i in range(5):
        add_transfer("0xa", 100, "0xh", log_index=i)

    result = db.query_transactions(limit=2)

    assert result["total"] == 5
    assert result["count"] == 2


"""
Checks the cross_asset_addresses function within db.py: only addresses that appear in both a
stablecoin transfer and a volatile-asset transfer are returned, whether as sender or receiver.
"""
def test_cross_asset_matches_only_addresses_in_both_classes(add_transfer):
    # 0xboth: receives USDC and sends WETH -> qualifies
    add_transfer("0xt1", 100, "0xh", token="USDC", from_addr="0xother", to_addr="0xboth", log_index=0)
    add_transfer("0xt2", 100, "0xh", token="WETH", from_addr="0xboth", to_addr="0xother", log_index=1)
    # 0xstableonly: only stablecoin transfers -> excluded
    add_transfer("0xt3", 100, "0xh", token="USDT", from_addr="0xstableonly", to_addr="0xother", log_index=2)

    result = db.cross_asset_addresses()
    matched = {r["addr"]: r for r in result["results"]}

    assert "0xboth" in matched
    assert "0xstableonly" not in matched
    assert matched["0xboth"]["stablecoin_transfers"] == 1
    assert matched["0xboth"]["volatile_transfers"] == 1
