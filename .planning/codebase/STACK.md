# Technology Stack

**Analysis Date:** 2026-07-30

## Languages

**Primary:**
- Python 3.x - Backend CAN logger and utility scripts (`src/`)
- JavaScript - Dashboard server and frontend display (`can-dashboard/`)

**Markup:**
- HTML/CSS - Dashboard UI (`can-dashboard/dashboard.html`)

## Runtime

**Environment:**
- Python 3.x - For CAN bus logging and data processing scripts
- Node.js 14+ - For real-time dashboard server and WebSocket communication

**Package Manager:**
- pip (Python)
- npm (Node.js) - For WebSocket dependency
- Lockfile: Not present (minimal, single external npm dependency)

## Frameworks

**Core:**
- vspyx - Intrepid Control Systems neoVI SDK for Vehicle Spy X integration
- python-ics - Alternative python-ics library for neoVI Pi hardware interface

**Data Processing:**
- cantools - DBC file parsing and CAN message decoding (`src/neoVI_logger.py`, `src/new_logger.py`)
- python-can - Python CAN bus interface library

**Logging:**
- csv module (stdlib) - CSV logging format for data export
- json module (stdlib) - JSON interchange between Python logger and Node.js server

**Web Server:**
- Node.js http module (stdlib) - HTTP server for dashboard
- ws package - WebSocket server for real-time dashboard updates

**CLI/Arguments:**
- argparse (stdlib) - Command-line argument parsing for logger scripts

## Key Dependencies

**Critical:**
- vspyx - Required for Vehicle Spy X integration and neoVI hardware communication. Used in `src/neoVI_logger.py` and `src/references.py`
- ics (python-ics) - Alternative/complementary library for neoVI Pi. Used in `src/new_logger.py`
- cantools - Essential for decoding CAN messages from DBC file (`epbr2026_DBC_v1.0.dbc`). Used across all logging scripts
- ws (WebSocket) - Required for dashboard real-time updates. Installed via `npm install` per `can-dashboard/README.md`

**Infrastructure:**
- python-can - Provides unified CAN bus interface across platforms

## Configuration

**Environment:**
- Node.js PORT - Configurable via env var (defaults to 3000), specified in `can-dashboard/server.js` line 20
- Python debugging - Configured via `.vscode/launch.json` with debugpy

**Build:**
- No build pipeline - Scripts run directly (Python) or via Node.js

**Runtime Arguments:**
- Python loggers accept `--channels` and `--hardware_sn` CLI args for hardware selection
- Node.js server reads CAN data from stdin (piped from Python logger)

## Platform Requirements

**Development:**
- Python 3.x interpreter
- Node.js 14+ runtime
- neoVI Pi hardware or VSB buffer file for testing
- VS Code with Python extension (for debugging)

**Production:**
- Raspberry Pi (neoVI Pi target) or Linux/Windows with neoVI hardware
- Python 3.x
- Node.js 14+
- CAN bus hardware (neoVI Pi or compatible Intrepid device)

---

*Stack analysis: 2026-07-30*
