/**
 * CAN Bus Live Dashboard — Server
 *
 * Pipe your CAN logger output to stdin in newline-delimited JSON:
 *   node server.js < can_log.jsonl
 *   your-can-logger | node server.js
 *
 * Expected JSON format (one object per line):
 *   { "channel": "CAN0", "id": "0x123", "name": "EngineRPM", "signal": "RPM", "value": 2500, "unit": "rpm", "timestamp": 1700000000.123 }
 *
 * Open http://<your-ip>:3000 on any device on the same network.
 */

const http = require("http");
const fs = require("fs");
const path = require("path");
const { WebSocketServer } = require("ws");
const readline = require("readline");

const PORT = process.env.PORT || 3000;

// --- State store: latest value per signal ---
// Structure: state[channel][messageId] = { name, signals: { signalName: { value, unit, ts } } }
const state = {};

// --- HTTP server — serves the dashboard HTML ---
const server = http.createServer((req, res) => {
  if (req.url === "/" || req.url === "/index.html") {
    const file = path.join(__dirname, "dashboard.html");
    fs.readFile(file, (err, data) => {
      if (err) {
        res.writeHead(404);
        res.end("dashboard.html not found");
        return;
      }
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(data);
    });
  } else if (req.url === "/state") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(state));
  } else {
    res.writeHead(404);
    res.end("Not found");
  }
});

// --- WebSocket server ---
const wss = new WebSocketServer({ server });

function broadcast(msg) {
  const data = JSON.stringify(msg);
  wss.clients.forEach((client) => {
    if (client.readyState === 1) client.send(data);
  });
}

wss.on("connection", (ws) => {
  // Send full current state on connect so new clients catch up instantly
  ws.send(JSON.stringify({ type: "snapshot", state }));
});

// --- Parse stdin — your CAN logger pipes data here ---
const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });

rl.on("line", (line) => {
  line = line.trim();
  if (!line) return;

  let msg;
  try {
    msg = JSON.parse(line);
  } catch {
    // Try to parse common candump / log formats as a fallback
    msg = parseFallback(line);
    if (!msg) return;
  }

  const { channel = "CAN0", id, name, signal, value, unit = "", timestamp } = msg;
  const ts = timestamp || Date.now() / 1000;
  const msgId = id || "0x000";
  const msgName = name || msgId;
  const sigName = signal || "value";

  if (!state[channel]) state[channel] = {};
  if (!state[channel][msgId]) state[channel][msgId] = { name: msgName, signals: {} };

  state[channel][msgId].signals[sigName] = { value, unit, ts };

  broadcast({
    type: "update",
    channel,
    id: msgId,
    name: msgName,
    signal: sigName,
    value,
    unit,
    ts,
  });
});

// --- Fallback: parse candump-style lines like "CAN0  123   [8]  DE AD BE EF 01 02 03 04" ---
function parseFallback(line) {
  const m = line.match(/^(\S+)\s+([0-9A-Fa-f]+)\s+\[\d+\]\s+([\dA-Fa-f ]+)/);
  if (!m) return null;
  const rawBytes = m[3].trim().split(/\s+/).map((b) => parseInt(b, 16));
  const value = rawBytes.reduce((acc, b) => acc * 256 + b, 0);
  return { channel: m[1], id: "0x" + m[2].toUpperCase(), name: "0x" + m[2].toUpperCase(), signal: "raw", value, unit: "" };
}

server.listen(PORT, "0.0.0.0", () => {
  const { networkInterfaces } = require("os");
  const nets = networkInterfaces();
  const ips = [];
  for (const iface of Object.values(nets)) {
    for (const net of iface) {
      if (net.family === "IPv4" && !net.internal) ips.push(net.address);
    }
  }
  console.log(`\n🚗  CAN Dashboard running`);
  console.log(`   Local:   http://localhost:${PORT}`);
  ips.forEach((ip) => console.log(`   Network: http://${ip}:${PORT}`));
  console.log(`\n   Pipe your CAN logger to stdin:`);
  console.log(`   your-logger | node server.js\n`);
});
