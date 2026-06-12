# Deploy Trading Analyst to DigitalOcean droplet
# Run from PowerShell: .\scripts\deploy_to_droplet.ps1

param(
    [string]$DROPLET_IP = "204.48.17.22",
    [string]$REMOTE_DIR = "/opt/trading-analyst",
    [string]$GITHUB_BRANCH = "plan-1-foundation"
)

$REPO_ROOT = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$LOCAL_ENV = "$REPO_ROOT\.env"
$GITHUB_REPO = "https://github.com/rahulagra31092/Personal-Trading-Agent.git"

function Log($msg) { Write-Host "[deploy] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "[warn] $msg" -ForegroundColor Yellow }
function Die($msg) { Write-Host "[error] $msg" -ForegroundColor Red; exit 1 }

# Pre-flight checks
Log "Checking prerequisites..."
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) { Die "ssh not found" }
if (-not (Get-Command scp -ErrorAction SilentlyContinue)) { Die "scp not found" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Die "git not found" }
if (-not (Test-Path $LOCAL_ENV)) { Die ".env not found at $LOCAL_ENV" }

Log "Testing SSH connection to $DROPLET_IP..."
ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new root@$DROPLET_IP "echo 'SSH OK'" | Out-Null
if ($LASTEXITCODE -ne 0) { Die "Cannot connect to $DROPLET_IP" }

# Step 1: Git status and push
Log "Checking git status..."
cd $REPO_ROOT
$status = git status --porcelain | Measure-Object -Line
if ($status.Lines -gt 0) {
    Warn "$($status.Lines) uncommitted changes detected"
    $choice = Read-Host "Commit and push now? [y/N]"
    if ($choice -eq 'y' -or $choice -eq 'Y') {
        git add -A
        git commit -m "chore: pre-deploy commit $(Get-Date -Format yyyy-MM-dd)"
        git push origin $GITHUB_BRANCH
    }
    else {
        Warn "Deploying without pushing — droplet will get last pushed version"
    }
}
else {
    Log "Pushing latest commits..."
    git push origin $GITHUB_BRANCH 2>&1 | Out-Null
}

# Step 2: Install system packages on droplet
Log "Installing system packages on droplet..."
$install_script = @'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y -qq \
  python3.12 python3.12-venv python3.12-dev \
  git curl build-essential libssl-dev libffi-dev

python3.12 --version
echo "System packages OK"
'@

ssh root@$DROPLET_IP $install_script

# Step 3: Clone or update repo
Log "Deploying code to $REMOTE_DIR..."
$clone_script = @"
set -euo pipefail
GITHUB_REPO="$GITHUB_REPO"
GITHUB_BRANCH="$GITHUB_BRANCH"
REMOTE_DIR="$REMOTE_DIR"

if [ -d "\$REMOTE_DIR/.git" ]; then
  echo "Repo exists — pulling latest..."
  cd "\$REMOTE_DIR"
  git fetch origin
  git checkout "\$GITHUB_BRANCH"
  git reset --hard "origin/\$GITHUB_BRANCH"
else
  echo "Cloning repo..."
  git clone -b "\$GITHUB_BRANCH" "\$GITHUB_REPO" "\$REMOTE_DIR"
fi
echo "Code OK — \$(git -C \$REMOTE_DIR log -1 --oneline)"
"@

ssh root@$DROPLET_IP $clone_script

# Step 4: Copy .env
Log "Copying .env to droplet..."
scp $LOCAL_ENV "root@${DROPLET_IP}:${REMOTE_DIR}/.env" | Out-Null
Log ".env copied"

# Step 5: Install dependencies
Log "Installing Python dependencies on droplet..."
$deps_script = @"
set -euo pipefail
cd "$REMOTE_DIR"

if [ ! -d ".venv" ]; then
  python3.12 -m venv .venv
  echo "venv created"
fi

.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt --quiet
echo "Dependencies installed"
"@

ssh root@$DROPLET_IP $deps_script

# Step 6: Smoke test
Log "Running smoke test (health check)..."
$smoke_script = @"
set -euo pipefail
cd "$REMOTE_DIR"
source .env
.venv/bin/python -c "
from data.cache import init_db
init_db()
from api.main import app
print('Import OK — FastAPI app loads cleanly')
"
"@

ssh root@$DROPLET_IP $smoke_script

# Step 7: Install systemd service
Log "Installing systemd service..."
scp "$REPO_ROOT\deploy\trading-analyst.service" "root@${DROPLET_IP}:/etc/systemd/system/trading-analyst.service" | Out-Null

$service_script = @'
set -euo pipefail
systemctl daemon-reload
systemctl enable trading-analyst
systemctl restart trading-analyst
sleep 3
systemctl is-active trading-analyst && echo "Service is RUNNING" || echo "Service FAILED — check: journalctl -u trading-analyst -n 50"
'@

ssh root@$DROPLET_IP $service_script

# Step 8: Verify API
Log "Verifying /health endpoint..."
Start-Sleep -Seconds 3
$health_script = @'
set -euo pipefail
RESPONSE=$(curl -sf http://127.0.0.1:8000/health || echo "FAILED")
echo "Health response: $RESPONSE"
[[ "$RESPONSE" == *"ok"* ]] && echo "API is UP" || echo "API not responding yet — wait 10s and retry"
'@

ssh root@$DROPLET_IP $health_script

# Done
Write-Host ""
Log "=== Deployment complete ==="
Write-Host ""
Write-Host "  Service:   systemctl status trading-analyst"
Write-Host "  Logs:      journalctl -u trading-analyst -f"
Write-Host "  Test API:  ssh root@$DROPLET_IP curl http://127.0.0.1:8000/health"
Write-Host ""
Write-Host "  Next step: Import n8n workflows from deploy/"
Write-Host "    deploy/n8n_daily_workflow.json   — Mon-Fri 8am ET"
Write-Host "    deploy/n8n_monthly_workflow.json — 1st of month 8am ET"
Write-Host ""
