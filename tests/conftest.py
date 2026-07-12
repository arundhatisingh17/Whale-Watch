import os
import tempfile
from pathlib import Path

# Use a temporary database for tests, not the real one.
# db.py connects as soon as it is imported, so this has to be set first.

os.environ.setdefault("ALCHEMY_URL", "http://node.invalid")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.mkdtemp()) / 'test.db'}"

import pytest
from sqlalchemy import text

import db


# clear out the database before populating it with data
@pytest.fixture(autouse=True)
def clean_db():
    db.init_db()
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM transactions"))
    yield

# saves transaction metadata in the test database
@pytest.fixture
def add_transfer():
    def _add(tx_hash, block, block_hash, confirmations=0, status="Yes",
             token="USDC", amount=1_000_000.0, log_index=0,
             from_addr="0xfrom", to_addr="0xto", block_timestamp=0, unit_price=1.0):
        return db.save_transaction(
            token, from_addr, to_addr, amount, block,
            confirmations, status, tx_hash, log_index, block_hash, block_timestamp, unit_price,
        )
    return _add

# explicitly provides methods for looking up a block's hash for reorganization - stores the block and its corresponding hash and the order in which lookup was requested for
@pytest.fixture
def fake_chain():
    class FakeChain:
        def __init__(self):
            self.blocks = {}
            self.calls = []

        def set(self, block, block_hash):
            self.blocks[block] = block_hash

        def hash_at(self, block):
            self.calls.append(block)
            return self.blocks[block]

    return FakeChain()
