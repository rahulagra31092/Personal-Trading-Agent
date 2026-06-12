#!/bin/bash
# Warren B Trading System Deployment Script
# Deploy to DigitalOcean droplet: 204.48.17.22

set -e

DROPLET_IP="204.48.17.22"
DROPLET_USER="root"
APP_DIR="/opt/trading-analyst"
REPO_URL="https://github.com/yourusername/trading-analyst.git"  # Update this

echo "=========================================="
echo "Warren B Trading System - DigitalOcean Deploy"
echo "=========================================="
echo "Droplet: $DROPLET_IP"
echo "App Dir: $APP_DIR"
echo ""

# Step 1: SSH into droplet and prepare environment
echo "[1/6] Preparing DigitalOcean environment..."
ssh $DROPLET_USER@$DROPLET_IP << 'REMOTE_COMMANDS'
set -e

# Create app directory
mkdir -p /opt/trading-analyst
cd /opt/trading-analyst

# Update system packages
apt-get update
apt-get install -y python3.12 python3.12-venv python3.12-dev git curl

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install --upgrade pip setuptools wheel
pip install fastapi uvicorn yfinance pandas numpy scipy scikit-learn requests

echo "Environment ready"
REMOTE_COMMANDS

# Step 2: Copy codebase to droplet
echo "[2/6] Uploading codebase to droplet..."
rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='.pytest_cache' --exclude='venv' \
  $(pwd)/ $DROPLET_USER@$DROPLET_IP:$APP_DIR/

# Step 3: Create .env file on droplet
echo "[3/6] Creating environment configuration..."
ssh $DROPLET_USER@$DROPLET_IP << 'REMOTE_ENV'
cat > /opt/trading-analyst/.env << 'EOF'
# FastAPI Configuration
FASTAPI_HOST=0.0.0.0
FASTAPI_PORT=8000
FASTAPI_ENV=production

# Slack Webhooks (update with real values)
SLACK_WEBHOOK_CRITICAL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
SLACK_WEBHOOK_DATA_QUALITY=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

# Database
DATABASE_PATH=/opt/trading-analyst/data/paper_portfolio.db
BACKUP_DIR=/opt/trading-analyst/data/backups

# API Keys (if needed)
NEWSAPI_KEY=your_key_here
EOF

chmod 600 /opt/trading-analyst/.env
echo ".env created (update with real Slack webhooks)"
REMOTE_ENV

# Step 4: Create systemd service file
echo "[4/6] Installing systemd service..."
ssh $DROPLET_USER@$DROPLET_IP << 'REMOTE_SERVICE'
cat > /etc/systemd/system/trading-analyst.service << 'EOF'
[Unit]
Description=Warren B Trading System
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/trading-analyst
Environment="PATH=/opt/trading-analyst/venv/bin"
EnvironmentFile=/opt/trading-analyst/.env
ExecStart=/opt/trading-analyst/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
echo "Service file installed"
REMOTE_SERVICE

# Step 5: Start the service
echo "[5/6] Starting trading-analyst service..."
ssh $DROPLET_USER@$DROPLET_IP << 'REMOTE_START'
systemctl start trading-analyst
systemctl enable trading-analyst

# Wait for service to start
sleep 3

# Check status
systemctl status trading-analyst --no-pager

# Test health endpoint
echo ""
echo "Testing health endpoint..."
curl -s http://127.0.0.1:8000/health || echo "Health check pending (service starting...)"
REMOTE_START

# Step 6: Verify external connectivity
echo ""
echo "[6/6] Verifying external connectivity..."
echo "Testing: curl http://$DROPLET_IP:8000/health"
sleep 2

if curl -s http://$DROPLET_IP:8000/health | grep -q "ok"; then
    echo "✅ SUCCESS - FastAPI is accessible on $DROPLET_IP:8000"
else
    echo "⚠️  Waiting for service to fully start..."
    sleep 5
    curl -s http://$DROPLET_IP:8000/health
fi

echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Update .env with real Slack webhook URLs:"
echo "   ssh root@$DROPLET_IP"
echo "   nano /opt/trading-analyst/.env"
echo ""
echo "2. Import n8n workflows from deploy/ directory"
echo ""
echo "3. Test daily briefing:"
echo "   curl -X POST http://$DROPLET_IP:8000/run-briefing/daily"
echo ""
echo "4. View logs:"
echo "   ssh root@$DROPLET_IP"
echo "   journalctl -u trading-analyst -f"
echo ""
echo "Service is running at: http://$DROPLET_IP:8000"
