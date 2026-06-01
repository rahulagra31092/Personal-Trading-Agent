#!/usr/bin/env bash
# =============================================================================
# deploy_to_droplet.sh  —  Deploy Trading Analyst to DigitalOcean droplet
# Run from Git Bash on Windows: bash scripts/deploy_to_droplet.sh
# =============================================================================
set -euo pipefail

DROPLET_IP="204.48.17.22"
REMOTE_DIR="/opt/trading-analyst"
# If GITHUB_TOKEN is set, embed it in the URL (avoids interactive prompt on server)
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  GITHUB_REPO="https://${GITHUB_TOKEN}@github.com/rahulagra31092/Personal-Trading-Agent.git"
else
  GITHUB_REPO="https://github.com/rahulagra31092/Personal-Trading-Agent.git"
fi
GITHUB_BRANCH="plan-1-foundation"
LOCAL_ENV="$(dirname "$0")/../.env"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[deploy]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}  $*"; }
die()  { echo -e "${RED}[error]${NC} $*"; exit 1; }

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
command -v ssh  >/dev/null 2>&1 || die "ssh not found. Install OpenSSH."
command -v scp  >/dev/null 2>&1 || die "scp not found."
command -v git  >/dev/null 2>&1 || die "git not found."

[[ -f "$LOCAL_ENV" ]] || die ".env not found at $LOCAL_ENV"

log "Testing SSH connection to $DROPLET_IP …"
ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new root@"$DROPLET_IP" "echo 'SSH OK'" \
  || die "Cannot connect to $DROPLET_IP. Check your SSH key or droplet firewall."

# ---------------------------------------------------------------------------
# Step 1 — Make sure latest code is on GitHub
# ---------------------------------------------------------------------------
log "Checking git status …"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"
if git -C . rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  UNCOMMITTED=$(git status --porcelain | wc -l)
  if [[ "$UNCOMMITTED" -gt 0 ]]; then
    warn "$UNCOMMITTED uncommitted changes detected."
    read -rp "Commit and push now? [y/N] " choice
    if [[ "$choice" =~ ^[Yy]$ ]]; then
      git add -A
      git commit -m "chore: pre-deploy commit $(date +%Y-%m-%d)"
      git push origin "$GITHUB_BRANCH"
    else
      warn "Deploying without pushing — droplet will get last pushed version."
    fi
  else
    log "Pushing latest commits …"
    git push origin "$GITHUB_BRANCH" 2>/dev/null || warn "Nothing to push."
  fi
else
  warn "Not inside a git repo — skipping push. Droplet will use existing clone."
fi

# ---------------------------------------------------------------------------
# Step 2 — Install system packages + Python 3.12 on droplet
# ---------------------------------------------------------------------------
log "Installing system packages on droplet …"
ssh root@"$DROPLET_IP" bash <<'REMOTE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y -qq \
  python3.12 python3.12-venv python3.12-dev \
  git curl build-essential libssl-dev libffi-dev

# Verify Python 3.12
python3.12 --version
echo "System packages OK"
REMOTE

# ---------------------------------------------------------------------------
# Step 3 — Clone or update the repo on the droplet
# ---------------------------------------------------------------------------
log "Deploying code to $REMOTE_DIR …"
ssh root@"$DROPLET_IP" bash <<REMOTE
set -euo pipefail
GITHUB_REPO="$GITHUB_REPO"
GITHUB_BRANCH="$GITHUB_BRANCH"
REMOTE_DIR="$REMOTE_DIR"

if [ -d "\$REMOTE_DIR/.git" ]; then
  echo "Repo exists — pulling latest …"
  cd "\$REMOTE_DIR"
  git fetch origin
  git checkout "\$GITHUB_BRANCH"
  git reset --hard "origin/\$GITHUB_BRANCH"
else
  echo "Cloning repo …"
  git clone -b "\$GITHUB_BRANCH" "\$GITHUB_REPO" "\$REMOTE_DIR"
fi
echo "Code OK — \$(git -C \$REMOTE_DIR log -1 --oneline)"
REMOTE

# ---------------------------------------------------------------------------
# Step 4 — Copy .env to droplet
# ---------------------------------------------------------------------------
log "Copying .env to droplet …"
scp "$LOCAL_ENV" root@"$DROPLET_IP":"$REMOTE_DIR/.env"
log ".env copied"

# ---------------------------------------------------------------------------
# Step 5 — Create virtualenv and install dependencies
# ---------------------------------------------------------------------------
log "Installing Python dependencies on droplet …"
ssh root@"$DROPLET_IP" bash <<REMOTE
set -euo pipefail
cd "$REMOTE_DIR"

if [ ! -d ".venv" ]; then
  python3.12 -m venv .venv
  echo "venv created"
fi

.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt --quiet
echo "Dependencies installed"
REMOTE

# ---------------------------------------------------------------------------
# Step 6 — Run a smoke test
# ---------------------------------------------------------------------------
log "Running smoke test (health check) …"
ssh root@"$DROPLET_IP" bash <<REMOTE
set -euo pipefail
cd "$REMOTE_DIR"
source .env
.venv/bin/python -c "
from data.cache import init_db
init_db()
from api.main import app
print('Import OK — FastAPI app loads cleanly')
"
REMOTE

# ---------------------------------------------------------------------------
# Step 7 — Install and start systemd service
# ---------------------------------------------------------------------------
log "Installing systemd service …"
scp "$REPO_ROOT/deploy/trading-analyst.service" \
    root@"$DROPLET_IP":/etc/systemd/system/trading-analyst.service

ssh root@"$DROPLET_IP" bash <<'REMOTE'
set -euo pipefail
systemctl daemon-reload
systemctl enable trading-analyst
systemctl restart trading-analyst
sleep 3
systemctl is-active trading-analyst && echo "Service is RUNNING" || echo "Service FAILED — check: journalctl -u trading-analyst -n 50"
REMOTE

# ---------------------------------------------------------------------------
# Step 8 — Verify the API is up
# ---------------------------------------------------------------------------
log "Verifying /health endpoint …"
sleep 3
ssh root@"$DROPLET_IP" bash <<'REMOTE'
set -euo pipefail
RESPONSE=$(curl -sf http://127.0.0.1:8000/health || echo "FAILED")
echo "Health response: $RESPONSE"
[[ "$RESPONSE" == *"ok"* ]] && echo "API is UP" || echo "API not responding yet — wait 10s and retry"
REMOTE

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
log "=== Deployment complete ==="
echo ""
echo "  Service:   systemctl status trading-analyst"
echo "  Logs:      journalctl -u trading-analyst -f"
echo "  Test API:  ssh root@$DROPLET_IP curl http://127.0.0.1:8000/health"
echo ""
echo "  Next step: Import n8n workflows from deploy/"
echo "    deploy/n8n_daily_workflow.json   — Mon-Fri 8am ET"
echo "    deploy/n8n_monthly_workflow.json — 1st of month 8am ET"
echo ""
echo "  n8n → New Workflow → ⋮ menu → Import from JSON → paste file contents"
