import os

from flask import Flask, abort, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from config import STABLECOINS, TOKENS, VOLATILE
from db import STATUS_VALUES, cross_asset_addresses, init_db, query_transactions
from prices import PRODUCT_FOR, price_move

app = Flask(__name__)


@app.errorhandler(HTTPException)
def json_errors(e):
    return jsonify({"error": e.description}), e.code


def arg_float(name):
    value = request.args.get(name)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        abort(400, f"{name} must be a number")


def arg_int(name):
    value = request.args.get(name)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        abort(400, f"{name} must be an integer")


def arg_str(name):
    value = request.args.get(name)
    return value or None


def arg_pending(name):
    value = request.args.get(name)
    if value in (None, "", "all"):
        return None
    return value.lower() in ("yes", "true", "1", "pending")


def arg_status(name):
    value = request.args.get(name)
    if value in (None, "", "all"):
        return None
    if value.lower() not in STATUS_VALUES:
        abort(400, f"{name} must be one of {sorted(STATUS_VALUES)}")
    return value.lower()


@app.route("/")
def dashboard():
    return render_template("index.html", tokens=sorted(TOKENS))


@app.route("/api/tokens")
def tokens():
    return jsonify([
        {"symbol": symbol, "decimals": t["decimals"], "whale_threshold": t["whale_threshold"]}
        for symbol, t in sorted(TOKENS.items())
    ])


@app.route("/api/transactions")
def transactions():
    return jsonify(query_transactions(
        token_symbol=arg_str("token_symbol"),
        address=arg_str("address"),
        from_address=arg_str("from_address"),
        to_address=arg_str("to_address"),
        min_amount=arg_float("min_amount"),
        max_amount=arg_float("max_amount"),
        min_confirmations=arg_int("min_confirmations"),
        max_confirmations=arg_int("max_confirmations"),
        block_confirmed=arg_int("block_confirmed"),
        pending=arg_pending("pending"),
        status=arg_status("status"),
        transaction_hash=arg_str("transaction_hash"),
        sort_by=request.args.get("sort_by", "id"),
        order=request.args.get("order", "desc"),
        limit=arg_int("limit") or 100,
        offset=arg_int("offset") or 0,
    ))


@app.route("/api/transactions/token/<symbol>")
def by_token(symbol):
    return jsonify(query_transactions(token_symbol=symbol, limit=arg_int("limit") or 100))


@app.route("/api/transactions/address/<address>")
def by_address(address):
    return jsonify(query_transactions(address=address, limit=arg_int("limit") or 100))


@app.route("/api/transactions/block/<int:block_number>")
def by_block(block_number):
    return jsonify(query_transactions(block_confirmed=block_number, limit=arg_int("limit") or 100))


@app.route("/api/transactions/amount")
def by_amount():
    return jsonify(query_transactions(
        min_amount=arg_float("min"),
        max_amount=arg_float("max"),
        token_symbol=arg_str("token_symbol"),
        limit=arg_int("limit") or 100,
    ))


@app.route("/api/transactions/confirmations")
def by_confirmations():
    return jsonify(query_transactions(
        min_confirmations=arg_int("min"),
        max_confirmations=arg_int("max"),
        limit=arg_int("limit") or 100,
    ))


@app.route("/api/transactions/pending/<state>")
def by_pending(state):
    if state not in STATUS_VALUES:
        abort(400, f"state must be one of {sorted(STATUS_VALUES)}")
    return jsonify(query_transactions(status=state, limit=arg_int("limit") or 100))


@app.route("/api/cross-asset")
def cross_asset():
    return jsonify(cross_asset_addresses(limit=arg_int("limit") or 100))


@app.route("/api/cross-asset/price-moves")
def cross_asset_price_moves():
    """For each cross-asset whale (an address seen in both a stablecoin and a volatile transfer),
    show the price run-up of the volatile asset over the window ending at each of its volatile
    transfers. Price resolution is one minute - the finest the keyless Coinbase feed offers.
    """
    window = arg_int("window") or 60
    limit = arg_int("limit") or 20

    results = []
    for row in cross_asset_addresses(limit=limit)["results"]:
        addr = row["addr"]
        moves = []
        for tx in query_transactions(address=addr, limit=500)["results"]:
            if tx["token_symbol"] not in VOLATILE:
                continue
            product = PRODUCT_FOR[tx["token_symbol"]]
            try:
                move = price_move(product, tx["block_timestamp"], window)
            except Exception as e:
                move = {"product": product, "error": str(e)}
            if move:
                move.update({
                    "token_symbol": tx["token_symbol"],
                    "transaction_hash": tx["transaction_hash"],
                    "block_timestamp": tx["block_timestamp"],
                })
                moves.append(move)
        if moves:
            results.append({"addr": addr, "volatile_transfers": moves})

    return jsonify({"window_seconds": window, "count": len(results), "results": results})


@app.route("/api/price-impact/<transaction_hash>")
def price_impact_route(transaction_hash):
    result = query_transactions(transaction_hash=transaction_hash, limit=1)
    if not result["results"]:
        abort(404, "not found")

    tx = result["results"][0]
    window = arg_int("window") or 60
    symbol = tx["token_symbol"]

    # A stablecoin move is the signal, so show the reaction in both volatile proxies; a volatile
    # token shows its own price feed.
    if symbol in STABLECOINS:
        products = ["ETH-USD", "BTC-USD"]
    else:
        products = [PRODUCT_FOR[symbol]] if symbol in PRODUCT_FOR else []

    moves = []
    for product in products:
        try:
            move = price_move(product, tx["block_timestamp"], window)
        except Exception as e:
            move = {"product": product, "error": str(e)}
        if move:
            moves.append(move)

    return jsonify({
        "transaction_hash": transaction_hash,
        "token_symbol": symbol,
        "block_timestamp": tx["block_timestamp"],
        "window_seconds": window,
        "price_impact": moves,
    })


@app.route("/api/transactions/<transaction_hash>")
def by_hash(transaction_hash):
    result = query_transactions(transaction_hash=transaction_hash, limit=100)
    if not result["results"]:
        abort(404, "not found")
    return jsonify(result)


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=int(os.environ.get("PORT", 5001)))
