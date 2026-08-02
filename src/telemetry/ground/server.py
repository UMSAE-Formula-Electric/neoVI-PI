"""
telemetry.ground.server — `SseHub` and `DashboardServer`, the browser-facing
half of the ground station (GND-02/04/05), serving Server-Sent Events over
the stdlib `http.server` per the locked decision (D-01): zero new runtime
dependencies.

**No in-repo analog for the SSE/`http.server` mechanics** — Phase 1 is
entirely batch/stream-to-file/stream-to-link, never stream-to-browser.
`02-RESEARCH.md`'s own verified probe (run live against a real
`ThreadingHTTPServer` this session) is the source for the handler shape
below, not documentation prose. The thread-lifecycle half (name the thread,
poll `stop_event`, drop-oldest-and-count) mirrors
`src/telemetry/archive/runner.py` and `src/telemetry/capture/fanout.py`.

**Cross-thread shutdown is this module's one surprising exception**
(02-RESEARCH.md Pattern 4 / Pitfall 3): `DashboardServer.serve_forever()`
runs on the main thread; `DashboardServer.shutdown()` must be called from a
*different* thread or it deadlocks (`socketserver.BaseServer.shutdown`'s own
docstring). `cli.py`'s link-receive/decode thread is the only caller that
may ever call it -- the SIGINT/SIGTERM handler must never call it directly
(same-thread deadlock, since Python delivers signal handlers on the main
thread, which is the thread blocked inside `serve_forever()`).

**SSE wire framing (Claude's-discretion decision, 02-RESEARCH.md Open
Question 1):** one generic `message` event (no `event:` line) whose `data:`
is a JSON object carrying `type` = `"snapshot"` or `"update"` -- the ported
`dashboard.html` already dispatches on `msg.type` inside a single handler.

**Never set `Content-Length` on `/events`** (Pitfall 5): the stream has no
known end. **Always send `200 text/event-stream` unconditionally, before
any work that could fail** (Pitfall 4): the browser's `EventSource` gives
up permanently on any non-200 response or wrong content type, unlike the
manual `setTimeout` retry loop it replaces.
"""

import http.server
import json
import logging
import queue
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional, Set

logger = logging.getLogger(__name__)

# Fixed literals, not config keys -- this phase adds no new config surface
# (Claude's Discretion in D-01's block leaves route layout and flags to the
# planner; CLI flags cover everything an operator needs to change).
SSE_CLIENT_QUEUE_MAXSIZE = 256
SSE_HEARTBEAT_S = 1.0

# The only route this plan serves. The ported `dashboard.html` static route
# is 02-02 scope.
EVENTS_ROUTE = "/events"

# Hosts this server logs no warning for -- everything else is treated as
# publishing unauthenticated live vehicle telemetry to a wider network
# (T-02-04).
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _json_default(value):
    """Mirrors `telemetry.ground.cli._json_default`: `cantools`
    choice-decoded signals come back as `NamedSignalValue`, which
    `json.dumps` cannot serialise natively -- stringify anything `json`
    does not already know how to handle, rather than letting a decoded enum
    crash a broadcast."""
    return str(value)


def _sse_frame(payload: dict) -> bytes:
    """One SSE `data:` frame terminated by a blank line -- the generic
    `message` event framing this module's docstring fixes. No `event:`
    line, per the interface contract."""
    data = json.dumps(payload, default=_json_default)
    return f"data: {data}\n\n".encode("utf-8")


@dataclass
class SseHubCounters:
    """Mutable, shared counters for `SseHub` (mirrors `FanOutCounters`'
    dataclass-with-embedded-lock shape). `clients_connected`/`clients_peak`
    are the one deliberate read-modify-write exception: they are written by
    every HTTP handler thread on `register()`/`unregister()`, concurrently
    with every other connected client's handler thread, so they are guarded
    by `_client_count_lock`. Every other field here is a simple per-event
    increment from within a single handler's own request lifecycle; a rare
    lost increment under heavy concurrent connections is an accepted
    diagnostic imprecision, matching this project's established counters
    (e.g. `FanOutCounters`'s non-high-water-mark fields)."""

    clients_connected: int = 0
    clients_peak: int = 0
    frames_dropped_oldest: int = 0
    client_write_failures: int = 0
    write_failure_log_suppressed_count: int = 0

    _client_count_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )


class SseHub:
    """Owns the set of connected clients' per-client queues and fans
    broadcasts out to all of them. `broadcast()` is called only from the
    link-receive/decode thread (via `cli.py`'s `on_record`);
    `register()`/`unregister()` are called from HTTP handler threads, one
    per connected browser, concurrently with each other and with
    `broadcast()`."""

    def __init__(self, counters: Optional[SseHubCounters] = None) -> None:
        self._clients_lock = threading.Lock()
        self._clients: Set["queue.Queue[bytes]"] = set()
        self.counters = counters if counters is not None else SseHubCounters()

    def register(self) -> "queue.Queue[bytes]":
        client_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=SSE_CLIENT_QUEUE_MAXSIZE)
        with self._clients_lock:
            self._clients.add(client_queue)
        with self.counters._client_count_lock:
            self.counters.clients_connected += 1
            self.counters.clients_peak = max(
                self.counters.clients_peak, self.counters.clients_connected
            )
        return client_queue

    def unregister(self, client_queue: "queue.Queue[bytes]") -> None:
        with self._clients_lock:
            self._clients.discard(client_queue)
        with self.counters._client_count_lock:
            self.counters.clients_connected = max(0, self.counters.clients_connected - 1)

    def client_count(self) -> int:
        with self._clients_lock:
            return len(self._clients)

    def broadcast(self, payload: dict) -> None:
        """Serialise `payload` once and push the same bytes object to every
        registered client queue. Never blocks and never raises to the
        caller -- a slow or full client queue must be structurally
        incapable of applying backpressure to the decode thread."""
        frame = _sse_frame(payload)
        with self._clients_lock:
            clients = list(self._clients)
        for client_queue in clients:
            try:
                client_queue.put_nowait(frame)
            except queue.Full:
                # The tracer's single path (Task 1): a full client queue
                # simply drops this frame. Task 2 replaces this with a
                # drop-oldest wrapper, matching `FanOut.submit`'s
                # established discipline.
                pass


def make_handler_class(
    *, hub: SseHub, snapshot_provider: Callable[[], dict]
) -> type:
    """Build a `BaseHTTPRequestHandler` subclass bound to `hub` and
    `snapshot_provider` via closure -- one handler class per
    `DashboardServer` instance, since `http.server` handler classes carry no
    per-instance constructor arguments of their own."""

    class DashboardRequestHandler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args) -> None:
            # Never the stdlib's uncontrolled direct stderr write -- route
            # through this module's own logger at debug level, per this
            # project's stderr-logging convention.
            logger.debug("%s - %s", self.address_string(), format % args)

        def do_GET(self) -> None:
            # Explicit route allowlist, never a filesystem path join (ASVS
            # V5, threat T-02-01) -- this plan serves exactly one route.
            if self.path != EVENTS_ROUTE:
                self.send_response(404)
                self.end_headers()
                return
            self._serve_events()

        def _serve_events(self) -> None:
            # Unconditional happy-path headers, sent before any work that
            # could fail (Pitfall 4): a non-200 or wrong-content-type
            # response here permanently stops the browser's EventSource
            # from ever retrying. Deliberately no Content-Length (Pitfall
            # 5) -- this stream has no known end.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            client_queue = hub.register()
            try:
                try:
                    snapshot = snapshot_provider()
                except Exception:
                    # Headers are already sent -- a snapshot failure is a
                    # stream-level failure (log and close), never an HTTP
                    # error status, which would permanently stop retry.
                    logger.exception(
                        "snapshot_provider failed for a newly connected SSE client"
                    )
                    return
                self.wfile.write(_sse_frame({"type": "snapshot", "state": snapshot}))

                while True:
                    try:
                        frame = client_queue.get(timeout=SSE_HEARTBEAT_S)
                    except queue.Empty:
                        # SSE comment line: a half-dead socket fails fast on
                        # the next write, rather than being detected only
                        # via TCP timeout.
                        self.wfile.write(b": heartbeat\n\n")
                        continue
                    self.wfile.write(frame)
            except (
                BrokenPipeError,
                ConnectionAbortedError,
                ConnectionResetError,
                OSError,
            ) as exc:
                logger.debug("SSE client disconnected: %s", exc)
            finally:
                hub.unregister(client_queue)

    return DashboardRequestHandler


class DashboardServer:
    """Wraps a `ThreadingHTTPServer` (daemon-threaded by default, so no
    handler thread can outlive the process) bound to `host`/`port`, exposing
    the ACTUAL bound port so a caller that asked for port 0 learns what it
    got."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        hub: SseHub,
        snapshot_provider: Callable[[], dict],
    ) -> None:
        handler_cls = make_handler_class(hub=hub, snapshot_provider=snapshot_provider)
        self._httpd = http.server.ThreadingHTTPServer((host, port), handler_cls)
        self.port: int = self._httpd.server_address[1]

        if host not in _LOOPBACK_HOSTS:
            logger.warning(
                "DashboardServer bound to non-loopback host %s:%d -- this "
                "server has no authentication of any kind; live vehicle "
                "telemetry is now reachable by anyone on that network "
                "(T-02-04)",
                host,
                self.port,
            )

    def serve_forever(self) -> None:
        self._httpd.serve_forever()

    def shutdown(self) -> None:
        """Blocks until `serve_forever()`'s loop has finished. MUST be
        called from a thread other than the one running `serve_forever()`
        -- see this module's docstring. The link-receive/decode thread is
        the only caller that may ever call this in production; the
        SIGINT/SIGTERM handler must never call it directly."""
        self._httpd.shutdown()

    def server_close(self) -> None:
        self._httpd.server_close()
