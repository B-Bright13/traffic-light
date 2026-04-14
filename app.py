import json
import logging
import os
import queue
import signal
import sys
import threading
from datetime import datetime, timezone

from flask import Flask, Response, jsonify, render_template, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
CORS(app)

COLORS = {
    "red": {
        "label": "Red",
        "meaning": "Stop",
        "hex": "#ef4444",
        "tailwind": "red-500",
    },
    "yellow": {
        "label": "Yellow",
        "meaning": "Caution",
        "hex": "#eab308",
        "tailwind": "yellow-500",
    },
    "green": {
        "label": "Green",
        "meaning": "Go",
        "hex": "#22c55e",
        "tailwind": "green-500",
    },
}

_state = {
    "active": "red",
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
_state_lock = threading.Lock()

_subscribers: list[queue.Queue] = []
_subscribers_lock = threading.Lock()


def _get_state() -> dict:
    with _state_lock:
        return dict(_state)


def _set_color(color: str) -> dict:
    with _state_lock:
        _state["active"] = color
        _state["updated_at"] = datetime.now(timezone.utc).isoformat()
        snapshot = dict(_state)
    _broadcast(snapshot)
    return snapshot


def _broadcast(data: dict) -> None:
    with _subscribers_lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(data)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _subscribers.remove(q)


def _sse_generator():
    q: queue.Queue = queue.Queue(maxsize=10)
    with _subscribers_lock:
        _subscribers.append(q)
    try:
        yield f"data: {json.dumps(_get_state())}\n\n"
        while True:
            try:
                data = q.get(timeout=25)
                yield f"data: {json.dumps(data)}\n\n"
            except queue.Empty:
                yield ": heartbeat\n\n"
    finally:
        with _subscribers_lock:
            if q in _subscribers:
                _subscribers.remove(q)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "healthy", "service": "traffic-light", "version": "1.0.0"}), 200


@app.route("/api/status", methods=["GET"])
def api_status():
    """Return the currently active traffic light color."""
    state = _get_state()
    return jsonify({
        "active": state["active"],
        "updated_at": state["updated_at"],
        "color_info": COLORS[state["active"]],
    })


@app.route("/api/colors", methods=["GET"])
def api_colors():
    """Return all valid colors that can be set."""
    return jsonify({
        "colors": list(COLORS.keys()),
        "details": COLORS,
    })


@app.route("/api/set", methods=["POST"])
def api_set():
    """Set the active traffic light color."""
    body = request.get_json(silent=True) or {}
    color = body.get("color", "").lower().strip()

    if not color:
        return jsonify({"error": "Missing required field: color"}), 400
    if color not in COLORS:
        return jsonify({
            "error": f"Invalid color '{color}'. Must be one of: {', '.join(COLORS.keys())}",
            "valid_colors": list(COLORS.keys()),
        }), 400

    state = _set_color(color)
    logger.info("Color set to '%s'", color)
    return jsonify({
        "success": True,
        "active": state["active"],
        "updated_at": state["updated_at"],
        "color_info": COLORS[state["active"]],
    })


@app.route("/api/stream")
def api_stream():
    """Server-Sent Events stream for real-time light state updates."""
    return Response(
        _sse_generator(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Graceful shutdown ─────────────────────────────────────────────────────────

def _signal_handler(sig, frame):
    logger.info("Received shutdown signal (%s), shutting down gracefully.", sig)
    sys.exit(0)


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info("Starting traffic-light app on port %d", port)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
