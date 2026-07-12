
import time
from functools import lru_cache

from web3 import Web3

from config import (ALCHEMY_URL, CONFIRMATION_THRESHOLD, ERC20_ABI,
                    POLL_INTERVAL_SECONDS, PRICE_WINDOW_SECONDS, TOKENS)
from db import (init_db, record_price_moves, save_transaction,
                update_pending_transactions)
from prices import price_change_pct, unit_price_usd

w3 = Web3(Web3.HTTPProvider(ALCHEMY_URL))


def make_filter(token):
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(token["address"]), abi=ERC20_ABI
    )
    return contract.events.Transfer.create_filter(from_block="latest")


def block_hash_at(block_number):
    return w3.eth.get_block(block_number)["hash"].hex()


@lru_cache(maxsize=2048)
def block_timestamp_at(block_number):
    return w3.eth.get_block(block_number)["timestamp"]


def drain(symbol, token, event_filter):
    try:
        return event_filter.get_new_entries(), event_filter
    except ValueError as e:
        print(f"[{symbol}] filter expired ({e}), recreating")
        return [], make_filter(token)


def run():
    if not w3.is_connected():
        raise RuntimeError("could not connect to node")

    init_db()

    filters = {symbol: make_filter(token) for symbol, token in TOKENS.items()}
    print(f"watching {', '.join(filters)} from block {w3.eth.block_number}")

    while True:
        latest_block = w3.eth.block_number

        for symbol, token in TOKENS.items():
            events, filters[symbol] = drain(symbol, token, filters[symbol])

            for event in events:
                value = event["args"]["value"] / 10 ** token["decimals"]
                if value < token["whale_threshold"]:
                    continue

                block_number = event["blockNumber"]
                num_confirmations = latest_block - block_number
                pending = "Yes" if num_confirmations < CONFIRMATION_THRESHOLD else "No"
                timestamp = block_timestamp_at(block_number)

                saved = save_transaction(
                    symbol,
                    event["args"]["from"],
                    event["args"]["to"],
                    value,
                    block_number,
                    num_confirmations,
                    pending,
                    event["transactionHash"].hex(),
                    event["logIndex"],
                    event["blockHash"].hex(),
                    timestamp,
                    unit_price_usd(symbol, timestamp),
                )
                if saved:
                    print(f"[{symbol}] {value:,.2f} in block {block_number}")

        seen, confirmed, orphaned = update_pending_transactions(
            latest_block, CONFIRMATION_THRESHOLD, block_hash_at
        )
        if confirmed or orphaned:
            print(f"{seen} pending: {confirmed} confirmed, {orphaned} orphaned by reorg")

        recorded = record_price_moves(
            int(time.time()), PRICE_WINDOW_SECONDS,
            lambda sym, ts: price_change_pct(sym, ts, PRICE_WINDOW_SECONDS),
        )
        if recorded:
            print(f"recorded price move for {recorded} transfer(s)")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
