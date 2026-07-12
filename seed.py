import argparse
import time
from functools import lru_cache

from web3 import Web3

from config import (ALCHEMY_URL, CONFIRMATION_THRESHOLD, ERC20_ABI,
                    PRICE_WINDOW_SECONDS, TOKENS)
from db import (init_db, query_transactions, record_price_moves,
                save_transaction)
from prices import price_change_pct, unit_price_usd

w3 = Web3(Web3.HTTPProvider(ALCHEMY_URL))

CHUNK_SIZE = 10
MAX_LOOKBACK = 5_000


@lru_cache(maxsize=4096)
def block_timestamp_at(block_number):
    return w3.eth.get_block(block_number)["timestamp"]


def fetch_logs(contract, from_block, to_block):
    try:
        return contract.events.Transfer.get_logs(from_block=from_block, to_block=to_block)
    except Exception:
        if from_block >= to_block:
            raise
        mid = (from_block + to_block) // 2
        return (fetch_logs(contract, from_block, mid)
                + fetch_logs(contract, mid + 1, to_block))


def whale_transfers_in_range(symbol, token, from_block, to_block):
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(token["address"]), abi=ERC20_ABI
    )

    found = []
    for log in fetch_logs(contract, from_block, to_block):
        amount = log["args"]["value"] / 10 ** token["decimals"]
        if amount >= token["whale_threshold"]:
            found.append({
                "token_symbol": symbol,
                "from_addr": log["args"]["from"],
                "to_addr": log["args"]["to"],
                "amount": amount,
                "block_confirmed": log["blockNumber"],
                "transaction_hash": log["transactionHash"].hex(),
                "log_index": log["logIndex"],
                "block_hash": log["blockHash"].hex(),
            })
    return found


def collect(target_rows, head):
    collected = []
    to_block = head
    scanned = 0

    while len(collected) < target_rows and scanned < MAX_LOOKBACK and to_block > 0:
        from_block = max(to_block - CHUNK_SIZE + 1, 0)

        for symbol, token in TOKENS.items():
            try:
                collected.extend(whale_transfers_in_range(symbol, token, from_block, to_block))
            except Exception as e:
                print(f"[{symbol}] blocks {from_block}-{to_block} failed: {e}")

        scanned += to_block - from_block + 1
        print(f"blocks {from_block}-{to_block}: {len(collected)} whale transfers so far")
        to_block = from_block - 1

    collected.sort(key=lambda t: (t["block_confirmed"], t["log_index"]), reverse=True)
    return collected[:target_rows], scanned


def run(target_rows, end_block=None):
    if not w3.is_connected():
        raise RuntimeError("could not connect to node")

    init_db()
    head = w3.eth.block_number
    start_from = end_block if end_block is not None else head
    print(f"seeding {target_rows} most recent whale transfers from block {start_from}")

    transfers, scanned = collect(target_rows, start_from)

    inserted = 0
    for t in transfers:
        num_confirmations = head - t["block_confirmed"]
        pending = "Yes" if num_confirmations < CONFIRMATION_THRESHOLD else "No"
        timestamp = block_timestamp_at(t["block_confirmed"])

        if save_transaction(
            t["token_symbol"], t["from_addr"], t["to_addr"], t["amount"],
            t["block_confirmed"], num_confirmations, pending, t["transaction_hash"],
            t["log_index"], t["block_hash"], timestamp,
            unit_price_usd(t["token_symbol"], timestamp),
        ):
            inserted += 1

    skipped = len(transfers) - inserted
    print(f"scanned {scanned} blocks, inserted {inserted}, skipped {skipped} already present")

    # Backfilled transfers are old enough that their price window has already elapsed, so record
    # the observed move now instead of waiting for the watcher.
    recorded = record_price_moves(
        int(time.time()), PRICE_WINDOW_SECONDS,
        lambda sym, ts: price_change_pct(sym, ts, PRICE_WINDOW_SECONDS),
    )
    print(f"recorded price move for {recorded} volatile transfer(s)")
    print(f"table now holds {query_transactions()['total']} transactions")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=20)
    parser.add_argument("--end-block", type=int, default=None,
                        help="Start scanning backwards from this block instead of the chain head. "
                             "Use an older block to backfill transfers whose price window has elapsed.")
    args = parser.parse_args()
    run(args.rows, args.end_block)
