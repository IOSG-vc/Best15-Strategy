"""Crypto Valuation Dashboard — Flask backend."""
import json
import os
import sys
import threading
import traceback
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

AGENTS = {
    "jup": {
        "name": "Jupiter",
        "symbol": "JUP",
        "chain": "Solana",
        "module": "agents.jup",
        "available": True,
    },
    "ethfi": {
        "name": "ether.fi",
        "symbol": "ETHFI",
        "chain": "Ethereum",
        "module": "agents.ethfi",
        "available": True,
    },
    "uni": {
        "name": "Uniswap",
        "symbol": "UNI",
        "chain": "Ethereum",
        "module": "agents.uni",
        "available": True,
    },
    "hype": {
        "name": "Hyperliquid",
        "symbol": "HYPE",
        "chain": "HyperEVM",
        "module": "agents.hype",
        "available": True,
    },
    "lighter": {
        "name": "Lighter",
        "symbol": "LIT",
        "chain": "Ethereum",
        "module": "agents.lighter",
        "available": True,
    },
    "sky": {
        "name": "Sky",
        "symbol": "SKY",
        "chain": "Ethereum",
        "module": None,
        "available": False,
        "unavailable_reason": "Requires sky_research_extra.json data file with money-market TVL returns (not included in bundle)",
    },
    "cards": {
        "name": "Collector Crypt",
        "symbol": "CARDS",
        "chain": "Solana",
        "module": "agents.cards",
        "available": True,
    },
}

_state_lock = threading.Lock()
_state = {
    token: {"status": "idle", "result": None, "error": None, "last_run": None}
    for token in AGENTS
}


def _load_cached(token: str):
    path = os.path.join(RESULTS_DIR, f"{token}_result.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def _run_agent(token: str):
    import importlib

    module_name = AGENTS[token]["module"]
    with _state_lock:
        _state[token]["status"] = "running"
        _state[token]["error"] = None

    try:
        if module_name not in sys.modules:
            mod = importlib.import_module(module_name)
        else:
            mod = importlib.reload(sys.modules[module_name])
        result = mod.run()
        with _state_lock:
            _state[token]["status"] = "done"
            _state[token]["result"] = result
            _state[token]["last_run"] = datetime.now(timezone.utc).isoformat()
    except Exception:
        err = traceback.format_exc()
        with _state_lock:
            _state[token]["status"] = "error"
            _state[token]["error"] = err
            _state[token]["last_run"] = datetime.now(timezone.utc).isoformat()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    with _state_lock:
        out = {}
        for token, cfg in AGENTS.items():
            s = _state[token]
            result = s["result"] or _load_cached(token)
            out[token] = {
                "name": cfg["name"],
                "symbol": cfg["symbol"],
                "chain": cfg["chain"],
                "available": cfg["available"],
                "unavailable_reason": cfg.get("unavailable_reason"),
                "status": s["status"],
                "last_run": s["last_run"],
                "has_result": result is not None,
                "error": s["error"],
            }
    return jsonify(out)


@app.route("/api/run/<token>", methods=["POST"])
def api_run(token):
    if token not in AGENTS:
        return jsonify({"error": "Unknown token"}), 404
    if not AGENTS[token]["available"]:
        return jsonify({"error": AGENTS[token].get("unavailable_reason", "Unavailable")}), 400
    with _state_lock:
        if _state[token]["status"] == "running":
            return jsonify({"error": "Already running"}), 409
    t = threading.Thread(target=_run_agent, args=(token,), daemon=True)
    t.start()
    return jsonify({"status": "started"})


@app.route("/api/result/<token>")
def api_result(token):
    if token not in AGENTS:
        return jsonify({"error": "Unknown token"}), 404
    with _state_lock:
        s = _state[token]
        result = s["result"]
        error = s["error"]
        status = s["status"]
    if result is None:
        result = _load_cached(token)
    return jsonify({"status": status, "result": result, "error": error})


if __name__ == "__main__":
    app.run(debug=True, port=5050, use_reloader=False)
