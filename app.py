import asyncio
import json
import os
import threading
import time
from dataclasses import dataclass
from threading import Lock
from typing import Dict, Iterator, List, Tuple

from flask import Flask, Response, request, stream_with_context
from gevent import sleep

app = Flask(__name__)

@dataclass
class Presence:
    last_seen: int
    last_activity: int


_SSE_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

_CORS_ALLOW_ORIGIN = os.getenv(
    "CORS_ALLOW_ORIGIN", "https://solar-system-82998.bubbleapps.io"
)

_LAST_SEEN_TTL_SECONDS = 60
_ACTIVE_THRESHOLD_SECONDS = 300
_SSE_BROADCAST_INTERVAL_SECONDS = 2

_presence: Dict[str, Presence] = {}
_lock = Lock()


def _now() -> int:
    return int(time.time())


def _update_presence(uid: str, last_activity: int, timestamp: int) -> None:
    with _lock:
        _presence[uid] = Presence(last_seen=timestamp, last_activity=last_activity)


def _prune_and_snapshot(current_ts: int) -> Tuple[List[str], List[str]]:
    last_seen_cutoff = current_ts - _LAST_SEEN_TTL_SECONDS
    active_cutoff = current_ts - _ACTIVE_THRESHOLD_SECONDS
    with _lock:
        stale: List[str] = []
        active: List[str] = []
        idle: List[str] = []

        for uid, data in list(_presence.items()):
            if data.last_seen < last_seen_cutoff:
                stale.append(uid)
                continue

            if data.last_activity >= active_cutoff:
                active.append(uid)
            else:
                idle.append(uid)

        for uid in stale:
            _presence.pop(uid, None)

    active.sort()
    idle.sort()
    return active, idle


def _sse_response(iterable, status: int = 200) -> Response:
    response = Response(iterable, status=status)
    for key, value in _SSE_HEADERS.items():
        response.headers[key] = value
    return response

def _sse_response(iterable, status: int = 200) -> Response:
    response = Response(iterable, status=status)
    for key, value in _SSE_HEADERS.items():
        response.headers[key] = value
    return response

@app.after_request
def add_cors_headers(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = _CORS_ALLOW_ORIGIN
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Vary"] = "Origin"
    return resp


@app.route("/v1/hit", methods=["POST", "OPTIONS"])
def hit():
    if request.method == "OPTIONS":
        resp = Response("", status=204)
        resp.headers["Access-Control-Allow-Origin"] = _CORS_ALLOW_ORIGIN
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Vary"] = "Origin"
        return resp

    payload = request.get_json(force=True, silent=True) or {}
    uid = payload.get("uid")
    last_activity = payload.get("last_activity")

    if not uid:
        return {"ok": False, "error": "no uid"}, 400

    if last_activity is None:
        return {"ok": False, "error": "no last_activity"}, 400

    try:
        last_activity_int = int(last_activity)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid last_activity"}, 400

    timestamp = _now()
    _update_presence(str(uid), last_activity_int, timestamp)
    return {"ok": True}


@app.get("/healthz")
def healthz():
    return {"ok": True}, 200

@app.get("/readyz")
def readyz():
    return {"ok": True}, 200


@app.route("/sse/online", methods=["GET", "OPTIONS"])
def sse_online():
    if request.method == "OPTIONS":
        resp = Response("", status=204)
        resp.headers["Access-Control-Allow-Origin"] = _CORS_ALLOW_ORIGIN
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Vary"] = "Origin"
        return resp

    def event_stream() -> Iterator[str]:
        while True:
            try:
                now_ts = _now()
                active_uids, idle_uids = _prune_and_snapshot(now_ts)
                payload = {
                    "ts": now_ts,
                    "online_total": len(active_uids) + len(idle_uids),
                    "active_total": len(active_uids),
                    "idle_total": len(idle_uids),
                    "active_uids": active_uids,
                    "idle_uids": idle_uids,
                }
                yield f"data: {json.dumps(payload)}\n\n"
                sleep(_SSE_BROADCAST_INTERVAL_SECONDS)
            except Exception as exc:  # pragma: no cover - defensive guard
                app.logger.exception("SSE streaming error", exc_info=exc)
                now_ts = _now()
                active_uids, idle_uids = _prune_and_snapshot(now_ts)
                error_payload = {
                    "ts": now_ts,
                    "online_total": len(active_uids) + len(idle_uids),
                    "active_total": len(active_uids),
                    "idle_total": len(idle_uids),
                    "active_uids": active_uids,
                    "idle_uids": idle_uids,
                    "error": "internal_error",
                }
                yield f"data: {json.dumps(error_payload)}\n\n"
                return
                  
    try:
        return _sse_response(stream_with_context(event_stream()))
    except Exception as exc:  # pragma: no cover - defensive route guard
        app.logger.exception("Unhandled SSE request error", exc_info=exc)

        def error_stream():
            now_ts = _now()
            active_uids, idle_uids = _prune_and_snapshot(now_ts)
            payload = {
                "ts": now_ts,
                "online_total": len(active_uids) + len(idle_uids),
                "active_total": len(active_uids),
                "idle_total": len(idle_uids),
                "active_uids": active_uids,
                "idle_uids": idle_uids,
                "error": "internal_error",
            }
            yield f"data: {json.dumps(payload)}\n\n"

        return _sse_response(error_stream())

    try:
        return _sse_response(stream_with_context(event_stream()))
    except Exception as exc:  # pragma: no cover - defensive route guard
        app.logger.exception("Unhandled SSE request error", exc_info=exc)

        def error_stream():
            now_ts = _now()
            active_uids = _prune_and_snapshot(now_ts)
            payload = {
                "ts": now_ts,
                "online_total": len(active_uids),
                "uids": active_uids,
                "error": "internal_error",
            }
            yield f"data: {json.dumps(payload)}\n\n"

        return _sse_response(error_stream())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
