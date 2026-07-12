# WhaleWatch

Tracks large ERC-20 transfers on Ethereum mainnet, stores them in SQLite, and serves them
through a filterable REST API and dashboard.

A transfer counts as a whale transaction when it exceeds a per-token threshold
(100,000 USDC/USDT, 50 WETH). Transfers start as pending and become confirmed once the chain
head is at least 6 blocks past the block that included them — unless that block is reorged out
of the canonical chain first, in which case they are marked orphaned.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # then add your Alchemy URL
```

## Running

```bash
python seed.py       # one time: backfill the 20 most recent whale transfers
python watcher.py    # poll for new transfers, reconcile pending ones
python app.py        # dashboard at http://localhost:5001
```

The watcher and the API are separate processes that share the SQLite file: the watcher owns
all writes, the API only reads. Port 5001 rather than 5000, since macOS binds 5000 to AirPlay.

`seed.py` is idempotent — rerunning it inserts nothing new.

## Confirmations and reorgs

A block number identifies a *position* in the chain, not a specific block. If the block
containing a transfer is orphaned by a reorg, a different block takes over that height, and
counting `head - block_number` would eventually mark a reverted transfer as confirmed.

To avoid that false positive, each row also stores the `block_hash` it was seen in. On every
reconcile pass, `update_pending_transactions` re-fetches the canonical block at that height and
compares hashes. A mismatch means the transfer was reverted, and the row becomes `Orphaned`
rather than drifting toward `Confirmed`.

Only pending rows are checked — once a transfer passes 6 confirmations it is treated as final,
which is what the threshold is for. Rows are fetched once per distinct block, not once per row.
If the node is unreachable, reconciliation degrades to depth-only rather than falsely orphaning
rows.

## Schema notes

The unique key is `(transaction_hash, log_index)`, not `transaction_hash`. A single transaction
routinely emits several `Transfer` events — swaps, routers, and flash loans can move the same
tokens through multiple hops — so a hash alone does not identify a transfer.

Amounts are stored and returned in token units, already divided by the token's decimals.

## API

`GET /api/transactions` accepts any combination of `token_symbol`, `address`, `from_address`,
`to_address`, `min_amount`, `max_amount`, `min_confirmations`, `max_confirmations`,
`block_confirmed`, `status`, `transaction_hash`, `sort_by`, `order`, `limit`, `offset`.

`status` is one of `pending`, `confirmed`, `orphaned`.

| Endpoint | Returns |
| --- | --- |
| `GET /api/transactions/token/<symbol>` | transfers of one token |
| `GET /api/transactions/address/<address>` | transfers where the address is sender or receiver |
| `GET /api/transactions/block/<block_number>` | transfers included in one block |
| `GET /api/transactions/amount?min=&max=` | transfers within an amount range |
| `GET /api/transactions/confirmations?min=&max=` | transfers within a confirmation range |
| `GET /api/transactions/pending/<status>` | transfers by status |
| `GET /api/transactions/<transaction_hash>` | every transfer in one transaction |
| `GET /api/tokens` | watched tokens and their thresholds |

## Tests

```bash
pytest tests/ -q
```

Reconciliation is tested by injecting a fake chain into `update_pending_transactions`, so reorg
handling is verified without waiting for a real reorg to occur.

## Limitations

- A `Transfer` event is not a trade. Exchange rebalances, bridge deposits, and internal custodial
  moves all appear here and are not distinguished from economically meaningful flows.
- The watcher only sees transfers emitted while it is running. `seed.py` backfills, but there is
  no continuous gap-filling.
- `eth_newFilter` subscriptions expire on idle nodes. The watcher recreates an expired filter,
  but transfers emitted during the gap are lost.
- Reorgs deeper than 6 blocks are not detected, by design.
