# External Integrations

**Analysis Date:** 2026-07-30

## APIs & External Services

**Automotive Hardware:**
- neoVI Pi (Intrepid Control Systems) - CAN bus data capture and transmission
  - SDK: vspyx (Vehicle Spy X API)
  - Alternative library: python-ics (python-ics library)
  - Configuration: Serial/USB connection to neoVI Pi hardware

**neoVI Hardware Channels:**
Multiple CAN bus channels supported via hardware:
- HSCAN (High-Speed CAN)
- MSCAN (Middle-Speed CAN)
- SWCAN (Single-Wire CAN)
- HSCAN2, HSCAN3 (Additional high-speed CAN buses)
- DW CAN 01, DW CAN 02 (Data warehouse CAN buses)

Channel mapping defined in `src/new_logger.py` lines 41-50:
```python
CHANNEL_MAP: dict[str, int] = {
    "HSCAN":     ics.NETID_HSCAN,
    "MSCAN":     ics.NETID_MSCAN,
    "SWCAN":     ics.NETID_SWCAN,
    "HSCAN2":    ics.NETID_HSCAN2,
    "HSCAN3":    ics.NETID_HSCAN3,
    "DW CAN 01": ics.NETID_HSCAN,
    "DW CAN 02": ics.NETID_HSCAN2,
    "neoVI":     ics.NETID_HSCAN,
}
```

## Data Storage

**Databases:**
- None - No traditional database system

**File Storage:**
- Local filesystem logs directory
  - CSV format: `src/new_logger.py` outputs timestamped CSV with columns: timestamp_s, arb_id_hex, network_id, dlc, data_hex, decoded
  - neoVI native format (.vsb): `src/neoVI_logger.py` outputs Vehicle Spy binary format
  - Log location: `logs/` directory (relative to project root)

**Caching:**
- In-memory state in Node.js dashboard (`can-dashboard/server.js` lines 22-24)
- Per-signal min/max tracking in browser for range visualization

## Data Format Integration

**CAN Message Decoding:**
- DBC File: `epbr2026_DBC_v1.0.dbc` - Contains complete vehicle message and signal definitions
- Parser: cantools library decodes CAN messages using DBC definitions
- Output: Decoded signal names, values, and units

**Inter-Process Communication:**
- Python logger → Node.js server: Newline-delimited JSON format
- Example message structure (from `can-dashboard/server.js` line 79):
```json
{
  "channel": "CAN0",
  "id": "0x123",
  "name": "EngineRPM",
  "signal": "RPM",
  "value": 2500,
  "unit": "rpm",
  "timestamp": 1700000000.123
}
```

## Authentication & Identity

**Auth Provider:**
- None - No authentication system
- All services are local/LAN network only

## Monitoring & Observability

**Error Tracking:**
- None - No external error tracking service

**Logs:**
- Console output: Python scripts print to stdout for piping to Node.js server
- CSV file output: `src/new_logger.py` writes decoded CAN data to CSV files in `logs/` directory
- VSB binary format: `src/neoVI_logger.py` writes Vehicle Spy binary format logs

**Message Rate Monitoring:**
- Dashboard displays real-time message rate (msg/s) in header (`can-dashboard/dashboard.html` lines 709-716)
- Calculated per 2-second interval browser-side

## CI/CD & Deployment

**Hosting:**
- Local network deployment - Node.js server binds to 0.0.0.0 for LAN accessibility
- Raspberry Pi (neoVI Pi target environment)
- Can run on Windows/Linux with compatible neoVI hardware

**CI Pipeline:**
- None - No automated CI/CD configured

**Launch Configuration:**
- Python debugging via VS Code (``.vscode/launch.json``)
- Node.js server starts with `npm install` then `node server.js`

## Environment Configuration

**Required env vars:**
- `PORT` - Controls Node.js dashboard server port (default: 3000)
  - Set via `PORT=8080 node server.js` (documented in `can-dashboard/README.md` line 64)

**Python Runtime Configuration:**
- Hardware serial number: `--hardware_sn` CLI arg (default: 'icsneo **1' for first device)
- CAN channel selection: `--channels` CLI arg (default: 'HSCAN')
- Output directory: Defaults to `logs/` relative to script location

## Webhooks & Callbacks

**Incoming:**
- None configured

**Outgoing:**
- None - Dashboard is pull-based (stdin piping, WebSocket push from server)

## Testing & Simulation

**Simulator:**
- `can-dashboard/simulate.js` - Generates synthetic CAN data for testing dashboard without hardware
- Usage: `node simulate.js | node server.js`
- Outputs same JSON format as real logger for seamless testing

**Testing Mode:**
- `src/neoVI_logger.py` supports TESTING_MODE flag to use VSB buffer files instead of hardware (line 12)
- References.py supports analysis mode without live hardware via buffer files

---

*Integration audit: 2026-07-30*
