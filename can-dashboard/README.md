# CAN Live Dashboard

A lightweight real-time CAN bus data viewer. Pipe your logger to a Node.js server and anyone on your network can watch signals update live in their browser — no app install needed.

## Quick start

```bash
npm install        # one-time setup (only needs 'ws')
node simulate.js | node server.js   # test with fake data
```

Open the URL printed in the terminal on any phone or laptop.

## Using with your real CAN logger

Your logger must output **one JSON object per line** to stdout:

```json
{"channel":"CAN0","id":"0x123","name":"EngineControl","signal":"RPM","value":2450,"unit":"rpm","timestamp":1700000000.123}
```

| Field | Required | Description |
|-------|----------|-------------|
| `channel` | yes | Bus channel name, e.g. `CAN0`, `HS-CAN` |
| `id` | yes | CAN message ID, e.g. `0x123` |
| `name` | no | Human-readable message name (falls back to id) |
| `signal` | yes | Signal name within the message |
| `value` | yes | Numeric or string value |
| `unit` | no | Unit string, e.g. `rpm`, `°C`, `%` |
| `timestamp` | no | Unix timestamp in seconds (defaults to now) |

Pipe your logger to the server:

```bash
your-can-logger | node server.js
# or
python3 your_logger.py | node server.js
```

## candump fallback

If your logger outputs raw `candump` lines like:

```
CAN0  123   [8]  DE AD BE EF 01 02 03 04
```

The server will parse these automatically, showing the raw big-endian integer value.
For decoded signals, output JSON instead.

## Network access

The server binds to `0.0.0.0` so anyone on the same Wi-Fi/LAN can connect.
The terminal will print the local IP, e.g.:

```
Network: http://192.168.1.42:3000
```

Share that URL. No port-forwarding or firewall rules needed on a typical local network.

## Change the port

```bash
PORT=8080 node server.js
```

## Dashboard features

- **Channel tabs** — switch between CAN0, CAN1, etc.
- **Per-message toggle** — hide an entire message group with one click
- **Per-signal toggle** — hide individual signals
- **Mini range bar** — shows where the current value sits in its observed min/max range
- **Search** — filter by message name, ID, or signal name
- **All on / All off** — global visibility control
- **Collapse all** — collapse all message groups for a compact view
- **Message rate counter** — live msg/s in the header
- **Auto-reconnect** — browsers reconnect automatically if the server restarts
- **Snapshot on connect** — new clients get the full current state instantly

## System requirements

- Node.js 14+ on the machine running the server
- Any modern browser on viewing devices (no install required)
- Same local network (Wi-Fi / LAN)
