import json
import os
import time
from threading import Lock
from typing import Dict, List

from flask import Flask, Response, request, stream_with_context
from gevent import sleep

app = Flask(__name__)

_SSE_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

_CORS_ALLOW_ORIGIN = os.getenv(
    "CORS_ALLOW_ORIGIN", "https://solar-system-82998.bubbleapps.io"
)

_STALE_THRESHOLD_SECONDS = 30

_online_users: Dict[str, int] = {}
_lock = Lock()


def _now() -> int:
    return int(time.time())


def _record_user(uid: str, timestamp: int) -> None:
    with _lock:
        _online_users[uid] = timestamp


def _prune_and_snapshot(current_ts: int) -> List[str]:
    threshold = current_ts - _STALE_THRESHOLD_SECONDS
    with _lock:
        stale = [uid for uid, last_seen in _online_users.items() if last_seen < threshold]
        for uid in stale:
            _online_users.pop(uid, None)
        active = [uid for uid, last_seen in _online_users.items() if last_seen >= threshold]
    active.sort()
    return active


def _sse_response(iterable, status: int = 200) -> Response:
    response = Response(iterable, status=status)
    for key, value in _SSE_HEADERS.items():
        response.headers[key] = value
    return response


@app.after_request
def add_cors_headers(resp: Response) -> Response:
    request_origin = request.headers.get("Origin")
    allowed_origin = request_origin or _CORS_ALLOW_ORIGIN
    resp.headers["Access-Control-Allow-Origin"] = allowed_origin
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Vary"] = "Origin"
    return resp


@app.route("/v1/hit", methods=["POST", "OPTIONS"])
def hit():
    if request.method == "OPTIONS":
        return Response("", status=204)

    payload = request.get_json(silent=True) or {}
    uid = payload.get("uid")

    if not uid:
        return {"ok": False, "error": "no uid"}, 400

    timestamp = _now()
    _record_user(str(uid), timestamp)
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
        return Response("", status=204)

    def event_stream():
        while True:
            try:
                now_ts = _now()
                active_uids = _prune_and_snapshot(now_ts)
                payload = {
                    "ts": now_ts,
                    "online_total": len(active_uids),
                    "uids": active_uids,
                }
                yield f"data: {json.dumps(payload)}\n\n"
                sleep(2)
            except Exception as exc:  # pragma: no cover - defensive guard
                app.logger.exception("SSE streaming error", exc_info=exc)
                now_ts = _now()
                active_uids = _prune_and_snapshot(now_ts)
                error_payload = {
                    "ts": now_ts,
                    "online_total": len(active_uids),
                    "uids": active_uids,
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
