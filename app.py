import os, time, json, asyncio
from threading import Lock
from flask import Flask, request, Response

app = Flask(__name__)

# === 同時接続カウンタ（role=client のみ） ===
_ONLINE = 0
_LOCK = Lock()

def _inc():
    global _ONLINE
    with _LOCK:
        _ONLINE += 1

def _dec():
    global _ONLINE
    with _LOCK:
        if _ONLINE > 0:
            _ONLINE -= 1

def _get():
    with _LOCK:
        return _ONLINE

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
    counted = (role == "client")

    if counted:
        _inc()

    async def gen():
        try:
            while True:
                data = {"ts": _now(), "online_total": _get()}
                yield f"data: {json.dumps(data)}\n\n"
                await asyncio.sleep(2)
        finally:
            if counted:
                _dec()

    return Response(gen(), mimetype="text/event-stream")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
