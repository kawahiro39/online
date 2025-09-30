import asyncio
import json
import os
import threading
import time
from threading import Lock

from flask import Flask, Response, request
from werkzeug.exceptions import HTTPException

app = Flask(__name__)

_online_count = 0
_lock = Lock()
_cors_origin = os.getenv("CORS_ALLOW_ORIGIN", "*")


def _now() -> int:
    return int(time.time())


def _change_online(delta: int) -> None:
    global _online_count
    with _lock:
        _online_count = max(0, _online_count + delta)


def _get_online() -> int:
    with _lock:
        return _online_count

@app.get("/readyz")
def readyz():
    return {"ok": True}, 200

@app.after_request
def add_cors_headers(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = _cors_origin
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Max-Age"] = "600"
    return resp

@app.errorhandler(Exception)
def handle_exceptions(exc: Exception):
    if isinstance(exc, HTTPException):
        response = exc.get_response()
        response.data = json.dumps({"error": exc.description})
        response.content_type = "application/json"
        return response

    app.logger.exception("Unhandled exception during request", exc_info=exc)
    return Response(
        json.dumps({"error": "Internal Server Error"}),
        status=500,
        mimetype="application/json",
    )


@app.get("/healthz")
def healthz():
    return {"ok": True}, 200


@app.get("/readyz")
def readyz():
    return {"ok": True}, 200


@app.route("/sse/online", methods=["GET", "OPTIONS"])
def sse_online():
    if request.method == "OPTIONS":
        return "", 204

    role = request.args.get("role", "client")
    counted = role == "client"

    if counted:
        _change_online(1)

    async def event_stream():
        try:
            while True:
                payload = {"ts": _now(), "online_total": _get_online()}
                yield f"data: {json.dumps(payload)}\n\n"
                await asyncio.sleep(2)
        finally:
            if counted:
                _change_online(-1)

    response = Response(event_stream(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["X-Accel-Buffering"] = "no"
    return response

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
