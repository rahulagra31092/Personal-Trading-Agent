# Warren B Trading System - DigitalOcean Deployment Guide

## Droplet Details
- **IP:** 204.48.17.22
- **User:** root
- **App Directory:** /opt/trading-analyst
- **Service Name:** trading-analyst

---

## Prerequisites

You'll need SSH access. On Windows, use:
- **Option 1:** Windows Terminal + OpenSSH (built-in)
- **Option 2:** PuTTY or MobaXterm
- **Option 3:** WSL 2 with ssh command

Test connection:
```bash
ssh root@204.48.17.22
```

---

## Step 1: Prepare the Droplet Environment

SSH into the droplet and run:

```bash
ssh root@204.48.17.22
```

Then run these commands on the droplet:

```bash
# Update system packages
apt-get update
apt-get install -y python3.12 python3.12-venv python3.12-dev git curl

# Create app directory
mkdir -p /opt/trading-analyst
cd /opt/trading-analyst

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install --upgrade pip
pip install \
    fastapi==0.104.1 \
    uvicorn==0.24.0 \
    yfinance==0.2.32 \
    pandas==2.1.3 \
    numpy==1.26.2 \
    scipy==1.11.4 \
    scikit-learn==1.3.2 \
    requests==2.31.0 \
    python-dotenv==1.0.0

echo "✅ Environment ready"
```

---

## Step 2: Upload the Codebase

On your **local machine** (Windows), copy the Trading Analyst repo to the droplet.

**Option A: Using SCP (if you have OpenSSH on Windows)**

```bash
# From C:\Claude\Trading Analyst directory
scp -r . root@204.48.17.22:/opt/trading-analyst/

# This copies everything. Wait for completion.
```

**Option B: Manual Upload (if SCP doesn't work)**

1. Download WinSCP: https://winscp.net/
2. Connect to 204.48.17.22 (SFTP, user: root)
3. Create folder: `/opt/trading-analyst`
4. Drag & drop the entire `C:\Claude\Trading Analyst` folder contents into `/opt/trading-analyst`
5. Exclude these folders to save time:
   - `.git`
   - `__pycache__`
   - `.pytest_cache`
   - `venv`

---

## Step 3: Create Environment Configuration

SSH back into the droplet:

```bash
ssh root@204.48.17.22
```

Create the `.env` file:

```bash
cat > /opt/trading-analyst/.env << 'EOF'
# FastAPI Configuration
FASTAPI_HOST=0.0.0.0
FASTAPI_PORT=8000
FASTAPI_ENV=production

# Slack Webhooks - UPDATE WITH YOUR ACTUAL URLS
SLACK_WEBHOOK_CRITICAL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
SLACK_WEBHOOK_DATA_QUALITY=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

# Database
DATABASE_PATH=/opt/trading-analyst/data/paper_portfolio.db
BACKUP_DIR=/opt/trading-analyst/data/backups

# API Keys (if needed)
NEWSAPI_KEY=your_key_here
EOF

chmod 600 /opt/trading-analyst/.env
echo "✅ .env created"
```

**Important:** Update the Slack webhook URLs with your actual values:

```bash
nano /opt/trading-analyst/.env
# Edit and save (Ctrl+X, Y, Enter in nano)
```

---

## Step 4: Create Systemd Service

On the droplet, create the service file:

```bash
cat > /etc/systemd/system/trading-analyst.service << 'EOF'
[Unit]
Description=Warren B Trading System - FastAPI
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/trading-analyst
Environment="PATH=/opt/trading-analyst/venv/bin"
EnvironmentFile=/opt/trading-analyst/.env
ExecStart=/opt/trading-analyst/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000 --access-log
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
echo "✅ Service file created"
```

---

## Step 5: Start the Service

On the droplet:

```bash
# Enable and start the service
systemctl enable trading-analyst
systemctl start trading-analyst

# Check status
systemctl status trading-analyst

# View logs (Ctrl+C to exit)
journalctl -u trading-analyst -f
```

Expected output:
```
● trading-analyst.service - Warren B Trading System - FastAPI
     Loaded: loaded (/etc/systemd/system/trading-analyst.service; enabled)
     Active: active (running) since ...
```

---

## Step 6: Verify External Connectivity

From your **local machine**, test the API:

```bash
# Test health endpoint
curl http://204.48.17.22:8000/health

# Expected response:
# {"status":"ok"}
```

If this works, you're done! 🎉

If it fails, check:
1. Service is running: `systemctl status trading-analyst`
2. Port 8000 is listening: `netstat -tulpn | grep 8000`
3. Logs for errors: `journalctl -u trading-analyst -f`

---

## Step 7: Test the Daily Briefing

From your local machine, manually trigger the briefing:

```bash
curl -X POST http://204.48.17.22:8000/run-briefing/daily
```

Check the database was updated:

```bash
ssh root@204.48.17.22
sqlite3 /opt/trading-analyst/data/paper_portfolio.db "SELECT COUNT(*) FROM score_history WHERE DATE(score_date) = DATE('now');"
```

Should return > 0 if briefing ran.

---

## Step 8: Configure n8n Workflows

Log into n8n at http://204.48.17.22:5678

Import workflows:
1. `deploy/n8n_daily_workflow.json` (trigger: 8:05 AM EDT)
2. `deploy/n8n_monthly_workflow.json` (trigger: 1st @ 1:00 PM EDT)

Both workflows already have the correct URL: `http://172.17.0.1:8000/run-briefing/daily` ✅

---

## Troubleshooting

### Service won't start
```bash
systemctl status trading-analyst
journalctl -u trading-analyst -n 50
# Check for missing dependencies or Python errors
```

### Port 8000 already in use
```bash
# Find what's using port 8000
netstat -tulpn | grep 8000

# Or change port in .env and service file to 8001
```

### Database permission error
```bash
# Ensure data directory exists and is writable
mkdir -p /opt/trading-analyst/data
chmod 755 /opt/trading-analyst/data
```

### n8n can't reach FastAPI
```bash
# From inside n8n container, test:
curl http://172.17.0.1:8000/health

# From droplet, test external:
curl http://204.48.17.22:8000/health
```

---

## Monitoring

View live logs:
```bash
ssh root@204.48.17.22
journalctl -u trading-analyst -f --lines=100
```

Check system resources:
```bash
ssh root@204.48.17.22
top
# or
ps aux | grep uvicorn
```

Restart service:
```bash
ssh root@204.48.17.22
systemctl restart trading-analyst
```

---

## Daily Operations

### View Yesterday's Briefing Results
```bash
ssh root@204.48.17.22
sqlite3 /opt/trading-analyst/data/paper_portfolio.db << 'SQL'
SELECT ticker, score_date, composite_score 
FROM score_history 
WHERE DATE(score_date) = DATE('now', '-1 day')
ORDER BY composite_score DESC;
SQL
```

### Check Backup Status
```bash
ssh root@204.48.17.22
ls -lah /opt/trading-analyst/data/backups/
```

### Manual Briefing Trigger (if scheduled one fails)
```bash
curl -X POST http://204.48.17.22:8000/run-briefing/daily
```

---

## Rollback (if needed)

If something breaks, restore from backup:

```bash
ssh root@204.48.17.22
systemctl stop trading-analyst

# Restore database
cp /opt/trading-analyst/data/backups/paper_portfolio_YYYY-MM-DD_HH-MM-SS.db \
   /opt/trading-analyst/data/paper_portfolio.db

systemctl start trading-analyst
```

---

## Success Checklist

- [ ] Droplet SSH access confirmed
- [ ] Python 3.12 and venv installed
- [ ] Codebase uploaded to `/opt/trading-analyst`
- [ ] `.env` created with Slack webhook URLs
- [ ] Service file created and enabled
- [ ] Service is running: `systemctl status trading-analyst`
- [ ] Health endpoint responds: `curl http://204.48.17.22:8000/health`
- [ ] n8n workflows imported and active
- [ ] First briefing runs at 8:05 AM EDT tomorrow

---

## Next Steps

1. Follow steps 1-7 above to get the service running
2. Verify health endpoint works from your local machine
3. Import n8n workflows (they'll auto-trigger at scheduled times)
4. Monitor June 10 briefing at 8:05 AM EDT
5. Check `/run-briefing/daily` results in database
6. Monitor logs: `journalctl -u trading-analyst -f`

Once deployed, the system will:
- ✅ Generate daily briefings at 8:05 AM EDT
- ✅ Send Slack notifications with BUY/AVOID picks
- ✅ Track paper portfolio P&L
- ✅ Monitor circuit breaker status
- ✅ Back up databases nightly at 2 AM EDT
