import os
import threading
import time
import json
import asyncio
from threading import Lock
from typing import Dict, Tuple
from flask import Flask, request, Response

app = Flask(__name__)

# === 同時接続カウンタ（role=client のみ） ===
_ONLINE = 0
_USER_COUNTS: Dict[str, int] = {}
_LOCK = Lock()


def _inc(uid: str) -> None:
    """Increment counters for the given user ID."""
    global _ONLINE
    with _LOCK:
        _ONLINE += 1
        _USER_COUNTS[uid] = _USER_COUNTS.get(uid, 0) + 1


def _dec(uid: str) -> None:
    """Decrement counters for the given user ID."""
    global _ONLINE
    with _LOCK:
        if _ONLINE > 0:
            _ONLINE -= 1
        current = _USER_COUNTS.get(uid)
        if current is None:
            return
        if current <= 1:
            _USER_COUNTS.pop(uid, None)
        else:
            _USER_COUNTS[uid] = current - 1


def _snapshot() -> Tuple[int, Dict[str, int]]:
    with _LOCK:
        return _ONLINE, dict(_USER_COUNTS)

def _now():
    return int(time.time())

@app.after_request
def cors(resp):
    # 管理・訪問ともブラウザから直接叩くのでCORSを許可
    origin = request.headers.get("Origin") or "*"
    resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Max-Age"] = "600"
    return resp

@app.get("/healthz")
def healthz():
    return {"ok": True}, 200

@app.route("/sse/online", methods=["GET", "OPTIONS"])
def sse_online():
    if request.method == "OPTIONS":
        return ("", 204)

    role = request.args.get("role", "client")
    uid = request.args.get("uid")
    if role == "client" and not uid:
        return {"error": "uid is required for role=client"}, 400

    counted = role == "client"

    if counted:
        _inc(uid)
    async def gen():
        try:
            while True:
                total, by_user = _snapshot()
                data = {
                    "ts": _now(),
                    "online_total": total,
                    "online_by_user": by_user,
                }
                yield f"data: {json.dumps(data)}\n\n"
                await asyncio.sleep(2)
        finally:
            if counted:
                _dec(uid)

    return Response(gen(), mimetype="text/event-stream")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
