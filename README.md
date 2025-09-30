# Cloud Run Real-time Presence Service

Flask application that exposes an SSE endpoint for real-time online counts without any external data store.

## Endpoints

- `GET /sse/online` — streams the current number of connected browsers every two seconds via Server-Sent Events. Responses disable proxy buffering so the first event is delivered immediately.
- `GET /healthz` — always returns `{ "ok": true }`.
- `GET /readyz` — always returns `{ "ok": true }`.

## Environment Variables

- `CORS_ALLOW_ORIGIN` — optional fallback value for `Access-Control-Allow-Origin` when requests omit the `Origin` header (default: `*`).
- `PORT` (default: `8080`)

## Development

Install dependencies and run the Flask app:

```bash
pip install -r requirements.txt
gunicorn -b 0.0.0.0:8080 app:app
```

-No external services are required to run the server.

## Container Image

To build and run the service in a container (e.g. for Cloud Run), use the provided
`Dockerfile`:

```bash
docker build -t presence-service .
docker run --rm -p 8080:8080 presence-service
```

The container entrypoint uses Gunicorn with the threaded worker class so
Server-Sent Event streams flush promptly while still supporting concurrent
requests.

## Cloud Run Deployment Notes

- Configure the Cloud Run service with `max-instances=1` so a single instance maintains the in-memory connection count.
- Adjust `--concurrency` to the expected number of simultaneous SSE clients (for example `--concurrency 50`).
