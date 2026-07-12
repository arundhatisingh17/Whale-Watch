from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from config import DATABASE_URL, STABLECOINS, VOLATILE

engine = create_engine(DATABASE_URL)


def init_db():
    """Create the transactions table if it doesn't exist.

    The unique key is (transaction_hash, log_index) rather than the hash alone: one
    transaction routinely emits several Transfer events, so a hash does not identify
    a single transfer. WAL mode lets the API keep reading while the watcher writes.
    """
    with engine.begin() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_symbol TEXT NOT NULL,
                from_address TEXT NOT NULL,
                to_address TEXT NOT NULL,
                amount REAL NOT NULL,
                block_confirmed INTEGER NOT NULL,
                num_confirmations INTEGER NOT NULL,
                transaction_pending TEXT NOT NULL,
                transaction_hash TEXT NOT NULL,
                log_index INTEGER NOT NULL,
                block_hash TEXT NOT NULL,
                block_timestamp INTEGER NOT NULL,
                UNIQUE (transaction_hash, log_index)
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_pending ON transactions(transaction_pending)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_block ON transactions(block_confirmed)"
        ))


def save_transaction(token_symbol, from_addr, to_addr, amount, block_confirmed,
                     num_confirmations, transaction_pending, transaction_hash, log_index,
                     block_hash, block_timestamp):
    """Insert one transfer, returning False if it is already stored.

    A duplicate (same hash and log index) raises IntegrityError, which we treat as a
    no-op so the watcher and the backfill can re-see the same transfer harmlessly.
    """
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO transactions
                (token_symbol, from_address, to_address, amount, block_confirmed,
                 num_confirmations, transaction_pending, transaction_hash, log_index,
                 block_hash, block_timestamp)
                VALUES
                (:token_symbol, :from_addr, :to_addr, :amount, :block_confirmed,
                 :num_confirmations, :pending, :tx_hash, :log_index, :block_hash, :block_timestamp)
            """), {
                "token_symbol": token_symbol,
                "from_addr": from_addr,
                "to_addr": to_addr,
                "amount": amount,
                "block_confirmed": block_confirmed,
                "num_confirmations": num_confirmations,
                "pending": transaction_pending,
                "tx_hash": transaction_hash,
                "log_index": log_index,
                "block_hash": block_hash,
                "block_timestamp": block_timestamp,
            })
        return True
    except IntegrityError:
        return False
    except SQLAlchemyError as e:
        print(f"Failed to save transaction {transaction_hash}: {e}")
        return False


def update_pending_transactions(latest_block, confirmation_threshold, block_hash_at=None):
    with engine.connect() as conn:
        pending = conn.execute(text("""
            SELECT id, transaction_hash, block_confirmed, block_hash
            FROM transactions
            WHERE transaction_pending = 'Yes'
        """)).fetchall()

    if not pending:
        return 0, 0, 0

    canonical = {}
    if block_hash_at is not None:
        for block_number in {row.block_confirmed for row in pending}:
            try:
                canonical[block_number] = block_hash_at(block_number)
            except Exception as e:
                print(f"could not fetch block {block_number}: {e}")

    confirmed = 0
    orphaned = 0
    updates = []

    for row in pending:
        canonical_hash = canonical.get(row.block_confirmed)

        if canonical_hash is not None and canonical_hash != row.block_hash:
            status = "Orphaned"
            num_confirmations = 0
            orphaned += 1
        else:
            num_confirmations = latest_block - row.block_confirmed
            status = "Yes" if num_confirmations < confirmation_threshold else "No"
            if status == "No":
                confirmed += 1

        updates.append({
            "num_confirmations": num_confirmations,
            "pending": status,
            "id": row.id,
        })

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE transactions
            SET num_confirmations = :num_confirmations,
                transaction_pending = :pending
            WHERE id = :id
        """), updates)

    return len(pending), confirmed, orphaned


SORT_COLUMNS = {"id", "amount", "block_confirmed", "num_confirmations"}

STATUS_VALUES = {"pending": "Yes", "confirmed": "No", "orphaned": "Orphaned"}


def query_transactions(token_symbol=None, address=None, from_address=None, to_address=None,
                       min_amount=None, max_amount=None, min_confirmations=None,
                       max_confirmations=None, block_confirmed=None, pending=None,
                       status=None, transaction_hash=None, sort_by="id", order="desc",
                       limit=100, offset=0):
    clauses = []
    params = {}

    if token_symbol:
        clauses.append("token_symbol = :token_symbol")
        params["token_symbol"] = token_symbol.upper()

    if address:
        clauses.append("(lower(from_address) = :address OR lower(to_address) = :address)")
        params["address"] = address.lower()

    if from_address:
        clauses.append("lower(from_address) = :from_address")
        params["from_address"] = from_address.lower()

    if to_address:
        clauses.append("lower(to_address) = :to_address")
        params["to_address"] = to_address.lower()

    if min_amount is not None:
        clauses.append("amount >= :min_amount")
        params["min_amount"] = min_amount

    if max_amount is not None:
        clauses.append("amount <= :max_amount")
        params["max_amount"] = max_amount

    if min_confirmations is not None:
        clauses.append("num_confirmations >= :min_confirmations")
        params["min_confirmations"] = min_confirmations

    if max_confirmations is not None:
        clauses.append("num_confirmations <= :max_confirmations")
        params["max_confirmations"] = max_confirmations

    if block_confirmed is not None:
        clauses.append("block_confirmed = :block_confirmed")
        params["block_confirmed"] = block_confirmed

    if status is not None:
        if status not in STATUS_VALUES:
            raise ValueError(f"status must be one of {sorted(STATUS_VALUES)}")
        clauses.append("transaction_pending = :status")
        params["status"] = STATUS_VALUES[status]
    elif pending is not None:
        clauses.append("transaction_pending = :pending")
        params["pending"] = "Yes" if pending else "No"

    if transaction_hash:
        clauses.append("transaction_hash = :transaction_hash")
        params["transaction_hash"] = transaction_hash

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    if sort_by not in SORT_COLUMNS:
        sort_by = "id"
    direction = "ASC" if str(order).lower() == "asc" else "DESC"

    params["limit"] = min(int(limit), 500)
    params["offset"] = int(offset)

    with engine.connect() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM transactions {where}"), params
        ).scalar()

        rows = conn.execute(text(f"""
            SELECT id, token_symbol, from_address, to_address, amount,
                   block_confirmed, num_confirmations, transaction_pending,
                   transaction_hash, log_index, block_hash, block_timestamp
            FROM transactions
            {where}
            ORDER BY {sort_by} {direction}
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()

    return {"total": total, "count": len(rows), "results": [dict(r) for r in rows]}


def cross_asset_addresses(limit=100):
    """Addresses that appear (as sender or receiver) in both a stablecoin and a volatile-asset
    transfer. STABLECOINS and VOLATILE are trusted config constants, so they are inlined directly.
    """
    stable = ", ".join(f"'{s}'" for s in STABLECOINS)
    volatile = ", ".join(f"'{s}'" for s in VOLATILE)

    sql = f"""
        SELECT addr,
               SUM(token_symbol IN ({stable})) AS stablecoin_transfers,
               SUM(token_symbol IN ({volatile})) AS volatile_transfers
        FROM (
            SELECT lower(from_address) AS addr, token_symbol FROM transactions
            UNION ALL
            SELECT lower(to_address) AS addr, token_symbol FROM transactions
        )
        GROUP BY addr
        HAVING stablecoin_transfers > 0 AND volatile_transfers > 0
        ORDER BY stablecoin_transfers + volatile_transfers DESC
        LIMIT :limit
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"limit": min(int(limit), 500)}).mappings().all()

    return {"count": len(rows), "results": [dict(r) for r in rows]}
