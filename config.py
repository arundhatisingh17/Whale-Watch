import os

from dotenv import load_dotenv

load_dotenv()

ALCHEMY_URL = os.environ.get("ALCHEMY_URL")
if not ALCHEMY_URL:
    raise RuntimeError("ALCHEMY_URL is not set. Copy .env.example to .env and fill it in.")

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///transactions")

CONFIRMATION_THRESHOLD = 6
POLL_INTERVAL_SECONDS = 5

TOKENS = {
    "USDC": {
        "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "decimals": 6,
        "whale_threshold": 100_000,
    },
    "USDT": {
        "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "decimals": 6,
        "whale_threshold": 100_000,
    },
    "WETH": {
        "address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "decimals": 18,
        "whale_threshold": 50,
    },
    "WBTC": {
        "address": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
        "decimals": 8,
        "whale_threshold": 5,
    },
}

# Which tokens are stablecoins vs volatile assets, used for cross-asset analysis.
STABLECOINS = {"USDC", "USDT"}
VOLATILE = {"WETH", "WBTC"}

ERC20_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "from", "type": "address"},
            {"indexed": True, "name": "to", "type": "address"},
            {"indexed": False, "name": "value", "type": "uint256"},
        ],
        "name": "Transfer",
        "type": "event",
    }
]
