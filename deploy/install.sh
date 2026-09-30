#!/usr/bin/env bash
# UMSAE telemetry logger -- install script (OPS-01).
#
# Reproduces 03-RESEARCH.md Pattern 2's verified commands in order: install the
# unit with explicit permission bits, daemon-reload, then enable --now.
# daemon-reload MUST run before enable --now -- systemd caches unit definitions,
# so enabling before reloading can enable a stale, previously-cached definition
# of a unit file that was just changed on disk.
#
# Three additions beyond Pattern 2, each flagged below as an addition Pattern 2
# did not cover, each necessary for the unit to actually start on a bare Pi:
#   1. Idempotently create the service account the unit's User= names.
#   2. Verify /opt/telemetry looks like a real deployed checkout before
#      installing a unit that will try to run out of it.
#   3. Create the archive root and the heartbeat file's parent directory and
#      chown both to the service account, so the unprivileged process can
#      actually write to them on first boot.
#
# All three, plus the /opt/telemetry layout assumption itself, are confirmed
# during 03-07's single Pi bring-up verification -- not treated as proven here.
set -euo pipefail

UNIT_NAME="telemetry-logger.service"
SERVICE_USER="telemetry"
DEPLOY_ROOT="/opt/telemetry"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Addition 1 (beyond Pattern 2): idempotent service account creation -----
# The unit's User= names this exact account. It must exist before the unit is
# enabled, or the service fails at first start with no clearer diagnostic than
# "user does not exist". A system account, no home directory, no login shell --
# least privilege (ASVS V4), matching the unit's own non-root User=.
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  echo "Creating system account '${SERVICE_USER}'..."
  sudo useradd --system --no-create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
else
  echo "System account '${SERVICE_USER}' already exists -- not recreating."
fi

# --- Addition 2 (beyond Pattern 2): verify the deploy layout ---------------
# This script installs a service; it deliberately does NOT copy or clone the
# repository -- where the code comes from is a deployment decision this phase
# has not been asked to make. Fail with a clear message rather than installing
# a unit that will start and immediately fail an import.
if [ ! -d "${DEPLOY_ROOT}/src/telemetry" ] || [ ! -f "${DEPLOY_ROOT}/config/logger.json" ]; then
  echo "ERROR: ${DEPLOY_ROOT} does not look like a deployed telemetry checkout" >&2
  echo "  expected to find: ${DEPLOY_ROOT}/src/telemetry and ${DEPLOY_ROOT}/config/logger.json" >&2
  echo "  this script does not copy or clone the repository -- put a real checkout at" >&2
  echo "  ${DEPLOY_ROOT} first, then re-run this script." >&2
  exit 1
fi

# --- Addition 3 (beyond Pattern 2): archive root + heartbeat directory -----
# The logger runs unprivileged (User=telemetry in the unit). Without this,
# first boot fails on a permission error at the archive or heartbeat path
# that looks nothing like its actual cause. config/logger.json is the source
# of truth for both paths on the real deployment; this script does not parse
# JSON, so it creates the conventional locations documented in the runbook
# (03-07) and confirmed during the same Pi bring-up item as the account and
# layout assumptions above.
#
# THIS BLOCK MUST STAY ABOVE `systemctl enable --now`. It originally sat
# below it (CR-01, 03-REVIEW.md): the service was started before the
# directories it writes to existed or were owned by the service account, so
# every fresh install threw a permission failure into the journal before
# Restart=always papered over it ~2s later. That inverted this block's own
# stated purpose, and it is the first thing a new team member following the
# runbook would have seen. `tests/test_deploy_unit_file.py` now pins the
# ordering so it cannot silently regress.
ARCHIVE_ROOT="${DEPLOY_ROOT}/sessions"
HEARTBEAT_DIR="${DEPLOY_ROOT}/var"

sudo mkdir -p "${ARCHIVE_ROOT}"
sudo mkdir -p "${HEARTBEAT_DIR}"
sudo chown "${SERVICE_USER}:${SERVICE_USER}" "${ARCHIVE_ROOT}" "${HEARTBEAT_DIR}"

# --- Pattern 2, verified: install the unit, reload, enable -----------------
# install -m 644 sets permission bits explicitly instead of trusting whatever
# the source file carried through a copy -- this also avoids the spurious
# "marked executable" warning observed live this session when a unit file's
# permission bits carried an execute bit through a copy.
if [ -f "/etc/systemd/system/${UNIT_NAME}" ]; then
  echo "NOTE: /etc/systemd/system/${UNIT_NAME} already exists -- overwriting with" \
       "the version in this repository (install.sh never silently destroys" \
       "anything it did not just check for first)."
fi
sudo install -m 644 "${SCRIPT_DIR}/${UNIT_NAME}" "/etc/systemd/system/${UNIT_NAME}"
sudo systemctl daemon-reload
sudo systemctl enable --now "${UNIT_NAME}"

echo "Installed and started ${UNIT_NAME}. Check status with:"
echo "  systemctl status ${UNIT_NAME}"
echo "  journalctl -u ${UNIT_NAME} -f"
