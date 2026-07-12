# WhaleWatch

WhaleWatch tracks large ERC-20 whale transfers (USDC, USDT, WETH, WBTC) on Ethereum in real time.
It lets you filter transfers, star wallet addresses, and get price-movement alerts. Since stablecoin
flows often precede volatile price swings, it flags wallets active in both. It is a reorg-aware
early-signal tool for on-chain whale watching.

A transfer counts as a "whale" when it clears a per-token threshold (100,000 USDC/USDT, 50 WETH,
5 WBTC). The watcher records these as they happen, tracks each one until it's confirmed, or reverted
by a chain reorg, and serves them through a filterable dashboard and REST API.

## Why stablecoins

A stablecoin like USDC or USDT is pegged to the US dollar, so its own price barely moves, unlike ETH
or BTC. That's exactly why traders park capital in stablecoins to hedge, and why a sudden, large
stablecoin transfer is often a whale getting into position before buying. A lot of that buying
happens on centralized exchanges, off-chain, so there's no matching on-chain trade to see — but the
price feed still reflects it. So WhaleWatch looks for wallets that move both stablecoins and volatile
assets, and shows the price move around their volatile transfers. It's an observational signal, not a
prediction — but it's the kind of pattern worth watching.

## Features

- Real-time tracking of whale-sized ERC-20 transfers across USDC, USDT, WETH, and WBTC.
- A filterable dashboard and REST API — by token, sender/receiver address, amount, confirmations,
  block, and status.
- Star wallets to build a watchlist (saved in your browser) and get desktop or in-page alerts when
  they move, with the price change attached for volatile transfers.
- Automatic cross-asset flagging — wallets that appear in both a stablecoin and a volatile transfer
  are marked, since those are the ones the stablecoin-flow idea is about.
- Price context from a free, keyless feed: the ETH/BTC price move around a transfer.
- Reorg-aware confirmations — a transfer reverted by a chain reorganization is caught and marked,
  not silently counted as confirmed.
- Etherscan links on every address, transaction, and block.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # then put your Alchemy URL in .env
```

You need a free Alchemy endpoint (or any Ethereum JSON-RPC URL) set as `ALCHEMY_URL`.

## Running

There are three processes, each with a `make` target. The watcher and dashboard run in separate
terminals.

```bash
make seed      # one-time: backfill the most recent whale transfers so the dashboard isn't empty
make watch     # poll for new transfers and reconcile the pending ones
make serve     # dashboard at http://localhost:5001
```

It's port 5001, not 5000 — macOS binds 5000 to AirPlay. If your default `python3` is missing the
dependencies, point `make` at the right interpreter: `make serve PYTHON=/path/to/python`.

`seed.py` is idempotent, so re-running it is harmless. Run `make watch` alongside `make serve` to get
live updates and alerts; the dashboard polls every 10 seconds.

## How it works

### Confirmations and reorgs

Ethereum blocks aren't final the moment they appear — occasionally the chain reorganizes and a block
is discarded, reverting every transfer inside it. A block *number* always exists, though, so counting
`current_block − block_number` to decide when a transfer is confirmed would eventually mark a reverted
transfer as final. That's a false positive I didn't want.

So each transfer also stores the **hash** of the block it was seen in. On every pass, the watcher
re-checks the canonical block at that height: if the hash still matches, it counts confirmations
normally; if it changed, the transfer was reverted and the row is marked `Orphaned` instead of
drifting toward confirmed. A transfer is treated as final once it's 6 blocks deep. This is covered by
tests that inject a fake chain to simulate a reorg without waiting for a real one.

### Cross-asset flagging

The interesting wallets are the ones that move *both* asset classes — stablecoins to hedge, volatile
assets to trade. `cross_asset_addresses` finds every address that appears (as sender or receiver) in
both a stablecoin and a volatile transfer, and the dashboard marks those with a badge. You don't tag
them by hand; they're computed from the data.

### Price context

For a volatile transfer, WhaleWatch shows the token's own price just before and just after the
transfer, from Coinbase's free, keyless candle feed. (I originally reached for Binance, but its API is
geo-blocked in the US — Coinbase works without a key and covers both ETH-USD and BTC-USD, the proxies
for WETH and WBTC.) Resolution is one minute, the finest the free feed gives.

### One more schema note

A single transaction routinely emits several `Transfer` events — a swap or a router moves the same
tokens through multiple hops — so a transaction hash alone doesn't identify a transfer. The unique key
is `(transaction_hash, log_index)`, which keeps every distinct transfer instead of silently dropping
the extras.

## API

`GET /api/transactions` takes any combination of: `token_symbol`, `address`, `from_address`,
`to_address`, `min_amount`, `max_amount`, `min_confirmations`, `max_confirmations`, `block_confirmed`,
`status`, `transaction_hash`, `sort_by`, `order`, `limit`, `offset`. `status` is one of `pending`,
`confirmed`, `orphaned`. Amounts are returned in token units, already divided by decimals.

| Endpoint | Returns |
| --- | --- |
| `GET /api/transactions/token/<symbol>` | transfers of one token |
| `GET /api/transactions/address/<address>` | transfers where the address is sender or receiver |
| `GET /api/transactions/block/<block>` | transfers included in one block |
| `GET /api/transactions/amount?min=&max=` | transfers within an amount range |
| `GET /api/transactions/confirmations?min=&max=` | transfers within a confirmation range |
| `GET /api/transactions/pending/<status>` | transfers by status (pending / confirmed / orphaned) |
| `GET /api/transactions/<tx_hash>` | every transfer in one transaction |
| `GET /api/cross-asset` | addresses active in both stablecoin and volatile transfers |
| `GET /api/cross-asset/price-moves` | price move around each cross-asset wallet's volatile transfers |
| `GET /api/price-impact/<tx_hash>` | price before/after a transfer |
| `GET /api/tokens` | tracked tokens and their thresholds |

## Tests

```bash
make test
```

The suite covers the query/filter layer and the reconciliation logic. Reorg handling is tested by
injecting a fake chain into the reconciler, so orphan detection is verified without waiting for a real
reorg — including a regression test for the false-positive the hash check exists to prevent.

## Built with

Python, Flask, web3.py, SQLAlchemy + SQLite, and the Coinbase public price API. No frontend framework —
the dashboard is a single self-contained page.
