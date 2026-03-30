#!/usr/bin/env bash
# Deepfreeze Installer
# Installs deepfreeze packages, builds the web frontend, scaffolds config,
# and optionally sets up the systemd service.
#
# Usage:
#   ./install.sh                  # Interactive install
#   ./install.sh --cli-only       # Install CLI + core only (no server)
#   ./install.sh --dev            # Development mode (editable installs)
#   ./install.sh --uninstall      # Remove deepfreeze packages

set -euo pipefail

# -- Colors --
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}==>${NC} ${BOLD}$*${NC}"; }
ok()    { echo -e "${GREEN}  ✓${NC} $*"; }
warn()  { echo -e "${YELLOW}  !${NC} $*"; }
err()   { echo -e "${RED}  ✗${NC} $*"; }
ask()   { echo -en "${BLUE}  ?${NC} $* "; }

# -- Defaults --
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_ONLY=false
DEV_MODE=false
UNINSTALL=false
YES_MODE=false
CONFIG_DIR="${HOME}/.deepfreeze"
CONFIG_FILE="${CONFIG_DIR}/config.yml"

# -- Parse args --
while [[ $# -gt 0 ]]; do
  case $1 in
    --cli-only)  CLI_ONLY=true; shift ;;
    --dev)       DEV_MODE=true; shift ;;
    --uninstall) UNINSTALL=true; shift ;;
    -y|--yes)    YES_MODE=true; shift ;;
    -h|--help)
      echo "Usage: ./install.sh [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --cli-only    Install CLI + core only (no server/web UI)"
      echo "  --dev         Development mode (pip install -e)"
      echo "  --uninstall   Remove deepfreeze packages"
      echo "  -y, --yes     Answer yes to all prompts (restart service, etc.)"
      echo "  -h, --help    Show this help"
      exit 0
      ;;
    *) err "Unknown option: $1"; exit 1 ;;
  esac
done

# -- Uninstall --
if $UNINSTALL; then
  info "Uninstalling deepfreeze packages..."
  pip uninstall -y deepfreeze-server deepfreeze-cli deepfreeze-core 2>/dev/null || true
  ok "Packages removed"
  echo ""
  warn "Config file at ${CONFIG_FILE} was NOT removed."
  warn "systemd units (if installed) were NOT removed."
  echo "  To remove manually:"
  echo "    rm -rf ${CONFIG_DIR}"
  echo "    sudo rm /etc/systemd/system/deepfreeze-server.service"
  echo "    sudo systemctl daemon-reload"
  exit 0
fi

# -- Pre-flight checks --
info "Checking prerequisites..."

# Python
if ! command -v python3 &>/dev/null; then
  err "Python 3 is required but not found."
  exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 10 ]]; then
  if $CLI_ONLY && [[ "$PYTHON_MINOR" -ge 8 ]]; then
    ok "Python ${PYTHON_VERSION} (sufficient for CLI)"
  else
    err "Python 3.10+ is required for the server (found ${PYTHON_VERSION})."
    err "Use --cli-only to install just the CLI (requires Python 3.8+)."
    exit 1
  fi
else
  ok "Python ${PYTHON_VERSION}"
fi

# pip
if ! command -v pip &>/dev/null && ! python3 -m pip --version &>/dev/null 2>&1; then
  err "pip is required but not found."
  exit 1
fi
ok "pip"

# Node.js (only for server)
if ! $CLI_ONLY; then
  if ! command -v node &>/dev/null; then
    err "Node.js is required to build the web frontend."
    err "Install Node.js 18+ or use --cli-only to skip the server."
    exit 1
  fi
  NODE_VERSION=$(node -v | sed 's/v//')
  ok "Node.js ${NODE_VERSION}"

  if ! command -v npm &>/dev/null; then
    err "npm is required to build the web frontend."
    exit 1
  fi
  ok "npm"
fi

echo ""

# -- Build frontend (before pip install so assets get packaged) --
STATIC_DIR="${SCRIPT_DIR}/packages/deepfreeze-server/deepfreeze_server/static"
if ! $CLI_ONLY; then
  FRONTEND_DIR="${SCRIPT_DIR}/packages/deepfreeze-server/frontend"
  if [[ -f "${FRONTEND_DIR}/package.json" ]]; then
    info "Building web frontend..."
    (cd "$FRONTEND_DIR" && npm install --silent 2>&1 | tail -1)
    ok "npm dependencies installed"
    (cd "$FRONTEND_DIR" && npm run build --silent 2>&1 | tail -1)
    ok "Frontend built"

    # Copy built assets into the Python package so pip install includes them
    rm -rf "$STATIC_DIR"
    cp -r "${FRONTEND_DIR}/dist" "$STATIC_DIR"
    ok "Frontend assets copied to package"
  fi
  echo ""
fi

# -- Install Python packages --
info "Installing Python packages..."

PIP_FLAGS=""
if $DEV_MODE; then
  PIP_FLAGS="-e"
  warn "Development mode: using editable installs"
fi

pip install $PIP_FLAGS "${SCRIPT_DIR}/packages/deepfreeze-core" 2>&1 | tail -1
ok "deepfreeze-core"

pip install $PIP_FLAGS "${SCRIPT_DIR}/packages/deepfreeze-cli" 2>&1 | tail -1
ok "deepfreeze-cli"

if ! $CLI_ONLY; then
  pip install $PIP_FLAGS "${SCRIPT_DIR}/packages/deepfreeze-server" 2>&1 | tail -1
  ok "deepfreeze-server"
fi

echo ""

# -- Scaffold config --
if [[ ! -f "$CONFIG_FILE" ]]; then
  info "Creating configuration file..."
  mkdir -p "$CONFIG_DIR"

  ask "Elasticsearch host [https://localhost:9200]:"
  read -r ES_HOST
  ES_HOST="${ES_HOST:-https://localhost:9200}"

  ask "Elasticsearch username [elastic]:"
  read -r ES_USER
  ES_USER="${ES_USER:-elastic}"

  ask "Elasticsearch password:"
  read -rs ES_PASS
  echo ""

  if ! $CLI_ONLY; then
    ask "Server port [8000]:"
    read -r SERVER_PORT
    SERVER_PORT="${SERVER_PORT:-8000}"
  fi

  cat > "$CONFIG_FILE" << YAML
# Deepfreeze Configuration
# Generated by install.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")

elasticsearch:
  hosts:
    - ${ES_HOST}
  username: ${ES_USER}
  password: ${ES_PASS}
  # verify_certs: true
  # ca_certs: /path/to/ca.crt

logging:
  loglevel: INFO
  # logfile: /var/log/deepfreeze.log
YAML

  if ! $CLI_ONLY; then
    cat >> "$CONFIG_FILE" << YAML

server:
  host: 0.0.0.0
  port: ${SERVER_PORT}
  # refresh_interval: 30.0
  # auth:
  #   tokens:
  #     - name: admin
  #       token: changeme
  #       roles: [admin]
  # tls:
  #   cert: /path/to/cert.pem
  #   key: /path/to/key.pem
YAML
  fi

  chmod 600 "$CONFIG_FILE"
  ok "Config written to ${CONFIG_FILE} (mode 600)"
else
  ok "Config file already exists: ${CONFIG_FILE}"
fi

echo ""

# -- systemd setup --
if ! $CLI_ONLY && [[ -d /etc/systemd/system ]]; then
  UNIT_FILE="/etc/systemd/system/deepfreeze-server.service"

  if systemctl is-active --quiet deepfreeze-server 2>/dev/null; then
    # Service is already running — offer to restart it
    ok "deepfreeze-server service is running"
    if $YES_MODE; then
      RESTART_SERVICE="y"
    else
      ask "Restart deepfreeze-server to pick up changes? [y/N]:"
      read -r RESTART_SERVICE
    fi
    if [[ "${RESTART_SERVICE,,}" == "y" ]]; then
      sudo systemctl restart deepfreeze-server
      ok "deepfreeze-server restarted"
      echo ""
      echo "  View logs:    journalctl -u deepfreeze-server -f"
    fi
  else
    ask "Install systemd service for deepfreeze-server? [y/N]:"
    read -r INSTALL_SYSTEMD
    if [[ "${INSTALL_SYSTEMD,,}" == "y" ]]; then
      DEEPFREEZE_SERVER_BIN=$(command -v deepfreeze-server 2>/dev/null || echo "$(python3 -c 'import sysconfig; print(sysconfig.get_path("scripts"))')/deepfreeze-server")
      CURRENT_USER=$(whoami)

      sudo tee "$UNIT_FILE" > /dev/null << EOF
[Unit]
Description=Deepfreeze Server
After=network.target elasticsearch.service

[Service]
Type=simple
User=${CURRENT_USER}
ExecStart=${DEEPFREEZE_SERVER_BIN} --config ${CONFIG_FILE}
WorkingDirectory=${HOME}
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

# Security hardening
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
ReadWritePaths=${CONFIG_DIR}

[Install]
WantedBy=multi-user.target
EOF

      sudo systemctl daemon-reload
      ok "systemd unit installed: ${UNIT_FILE}"

      ask "Enable and start deepfreeze-server now? [y/N]:"
      read -r START_NOW
      if [[ "${START_NOW,,}" == "y" ]]; then
        sudo systemctl enable deepfreeze-server
        sudo systemctl start deepfreeze-server
        ok "deepfreeze-server is running"
        echo ""
        echo "  View logs:    journalctl -u deepfreeze-server -f"
        echo "  Stop:         sudo systemctl stop deepfreeze-server"
        echo "  Restart:      sudo systemctl restart deepfreeze-server"
      fi
    fi
  fi
fi

echo ""

# -- Summary --
info "Installation complete!"
echo ""
echo "  Installed:"
ok "deepfreeze-core"
ok "deepfreeze-cli"
if ! $CLI_ONLY; then
  ok "deepfreeze-server"
  ok "Web UI frontend"
fi
echo ""
echo "  Configuration: ${CONFIG_FILE}"
echo ""
echo "  Quick start:"
echo "    deepfreeze --config ${CONFIG_FILE} status"
if ! $CLI_ONLY; then
  echo "    deepfreeze-server --config ${CONFIG_FILE}"
  echo ""
  echo "  Web UI: http://localhost:${SERVER_PORT:-8000}"
fi
echo ""
echo "  First-time setup:"
echo "    deepfreeze --config ${CONFIG_FILE} setup"
echo ""
echo "  For more information:"
echo "    deepfreeze --help"
echo "    ${SCRIPT_DIR}/README.md"
