# IB Gateway Docker Setup Guide

## Overview

This guide will help you set up the complete two-container system:
1. **IB Gateway Container** - Handles connection to Interactive Brokers
2. **Trading Application Container** - Your Python options trading service

## Architecture

```
┌─────────────────────────────────┐
│     IB Gateway Container        │
│  • Connects to IB servers       │
│  • Handles authentication       │
│  • Provides API on port 4001/2  │
│  • VNC access (optional)        │
└────────────┬────────────────────┘
             │
             │ Docker Network
             │ (ajj-trading-network)
             │
┌────────────▼────────────────────┐
│  ajj-options-trader Container   │
│  • Your Python trading code     │
│  • Connects to ib-gateway:4002  │
│  • ib_async client              │
│  • Greeks analysis & trading    │
└─────────────────────────────────┘
```

## Prerequisites

### 1. IB Account Setup
- [ ] Interactive Brokers account created
- [ ] Paper trading account credentials
- [ ] Market data subscriptions (if needed)

### 2. System Requirements
- [ ] Docker installed (20.10+)
- [ ] Docker Compose installed (2.0+)
- [ ] 4GB RAM minimum
- [ ] Stable internet connection

## Step-by-Step Setup

### Step 1: Prepare Your Credentials

Create a `.env` file from the template:

```bash
cp .env.example .env
```

Edit `.env` with your IB credentials:

```bash
# Required: Your IB username and password
IB_USERNAME=your_username_here
IB_PASSWORD=your_password_here

# Trading mode (start with paper!)
TRADING_MODE=paper
PAPER_TRADING=true
IB_PORT=4002

# VNC password (for viewing Gateway UI)
VNC_PASSWORD=your_vnc_password
```

**Important:** Never commit `.env` to version control!

### Step 2: Review Configuration

Check `config/options-trader-config.yaml`:

```yaml
# Should already be set correctly for Docker
ib_host: 'ib-gateway'  # Docker service name
ib_port: 4002          # Gateway paper trading port
ib_client_id: 1        # Unique client ID

# Watchlist - add your symbols
watchlist:
  - SPX
  # - SPY
  # - QQQ

# Trading mode
paper_trading: true
```

### Step 3: Start IB Gateway

Start just the Gateway first:

```bash
# Pull the latest Gateway image
docker-compose pull ib-gateway

# Start Gateway container
docker-compose up -d ib-gateway

# Watch the logs
docker-compose logs -f ib-gateway
```

**What to look for:**

```
ib-gateway | Gateway ready for connect requests
ib-gateway | API server listening on port 4002
```

This usually takes **60-90 seconds** after starting.

### Step 4: Verify Gateway is Running

Check the Gateway status:

```bash
# Check if container is running
docker-compose ps

# Should show:
# NAME         STATUS        PORTS
# ib-gateway   Up (healthy)  4001-4002, 5900, 6080

# Check logs for errors
docker-compose logs ib-gateway | grep -i error
```

### Step 5: (Optional) Access Gateway UI via VNC

If you want to see the Gateway interface:

#### Option A: Browser-Based (Easiest)

Open your browser to: `http://localhost:6080`

#### Option B: VNC Client

1. Install a VNC client (RealVNC, TightVNC, etc.)
2. Connect to: `localhost:5900`
3. Enter password: (what you set as VNC_PASSWORD)

You should see the IB Gateway window showing:
- Login status
- Connection status
- "Ready for connection" message

### Step 6: Start Trading Application

Once Gateway is ready:

```bash
# Build and start trading service
docker-compose up -d ajj-options-trader

# Follow the logs
docker-compose logs -f ajj-options-trader
```

**Expected output:**

```
ajj-options-trader | Attempting to connect to IB Gateway at ib-gateway:4002
ajj-options-trader | ✓ Connected to IB Gateway at ib-gateway:4002
ajj-options-trader | Trading Mode: PAPER
ajj-options-trader | Starting options scan...
```

### Step 7: Verify Complete System

Check both containers:

```bash
# View all services
docker-compose ps

# Both should show "Up (healthy)"
```

Test the connection:

```bash
# Check trading app logs
docker-compose logs ajj-options-trader | grep "Connected"

# Should see: "✓ Connected to IB Gateway at ib-gateway:4002"
```

## Common Operations

### View Logs

```bash
# All services
docker-compose logs -f

# Just Gateway
docker-compose logs -f ib-gateway

# Just Trading App
docker-compose logs -f ajj-options-trader
```

### Restart Services

```bash
# Restart everything
docker-compose restart

# Restart just Gateway (if connection issues)
docker-compose restart ib-gateway

# Restart just trading app (after code changes)
docker-compose restart ajj-options-trader
```

### Stop Services

```bash
# Stop all services
docker-compose down

# Stop but keep data
docker-compose stop
```

### Update Gateway Image

```bash
# Pull latest Gateway version
docker-compose pull ib-gateway

# Restart with new image
docker-compose up -d ib-gateway
```

## Switching Between Paper and Live Trading

### To Switch to Live Trading:

**⚠️ WARNING: Only do this after extensive paper trading testing!**

1. Edit `.env`:
```bash
TRADING_MODE=live
PAPER_TRADING=false
IB_PORT=4001  # Live trading port
```

2. Edit `config/options-trader-config.yaml`:
```yaml
paper_trading: false
ib_port: 4001
```

3. Restart services:
```bash
docker-compose restart
```

### To Switch Back to Paper:

1. Edit `.env`:
```bash
TRADING_MODE=paper
PAPER_TRADING=true
IB_PORT=4002
```

2. Edit `config/options-trader-config.yaml`:
```yaml
paper_trading: true
ib_port: 4002
```

3. Restart services:
```bash
docker-compose restart
```

## Troubleshooting

### Gateway Won't Start

**Error:** `Container keeps restarting`

**Solutions:**
1. Check credentials in `.env`:
   ```bash
   docker-compose logs ib-gateway | grep -i "login\|auth\|error"
   ```

2. Verify IB account is active and credentials are correct

3. Check if IB servers are up (visit status.interactivebrokers.com)

### Trading App Can't Connect

**Error:** `Connection refused` or `Timeout`

**Solutions:**

1. **Verify Gateway is running and healthy:**
   ```bash
   docker-compose ps
   # ib-gateway should show "Up (healthy)"
   ```

2. **Check Gateway logs:**
   ```bash
   docker-compose logs ib-gateway | tail -20
   # Should see "API server listening on port 4002"
   ```

3. **Test network connectivity:**
   ```bash
   # From within trading container
   docker exec -it ajj-options-trader ping ib-gateway
   docker exec -it ajj-options-trader nc -zv ib-gateway 4002
   ```

4. **Verify port in config matches .env:**
   - Paper: 4002
   - Live: 4001

### Gateway Disconnects Daily

**This is normal!** IB Gateway automatically restarts once per day (around 11:45 PM ET) for maintenance.

The container will automatically:
1. Detect the restart
2. Re-login
3. Resume API connections

Your trading app will reconnect automatically.

### Wrong Trading Mode

**Symptom:** Orders going to wrong account (paper vs live)

**Check:**
```bash
# View current configuration
docker-compose logs ajj-options-trader | grep "Trading Mode"

# Should show: "Trading Mode: PAPER" or "Trading Mode: LIVE"
```

**Fix:** Ensure `.env` and `config.yaml` match:
- Both should have same mode (paper or live)
- Port should match (4002 for paper, 4001 for live)

### VNC Won't Connect

**Solutions:**

1. **Check if VNC port is exposed:**
   ```bash
   docker-compose ps
   # Should show 0.0.0.0:5900->5900/tcp
   ```

2. **Try browser-based noVNC:**
   Open: `http://localhost:6080`

3. **Check VNC password:**
   - Should be set in `.env` as VNC_PASSWORD
   - Default is 'vncpassword'

### API Version Mismatch

**Error:** `API version mismatch`

**Solution:** Update ib_async:
```bash
# In your Dockerfile or locally:
pip install --upgrade ib_async
```

## Health Checks

The Gateway container includes health checks:

```bash
# Check Gateway health
docker inspect ib-gateway | grep -A 5 Health

# Manual health check
docker exec ib-gateway nc -zv localhost 4002
```

## Daily Operations Checklist

### Morning Startup (Before Market Open)

- [ ] Start containers: `docker-compose up -d`
- [ ] Check Gateway status: `docker-compose logs ib-gateway | tail`
- [ ] Verify trading app connected: `docker-compose logs ajj-options-trader | grep Connected`
- [ ] (Optional) Check Gateway UI via VNC
- [ ] Review yesterday's logs for errors

### During Trading

- [ ] Monitor logs: `docker-compose logs -f ajj-options-trader`
- [ ] Check open positions in IB account
- [ ] Review signal CSV files as generated
- [ ] Watch for connection errors

### End of Day

- [ ] Review all trades executed
- [ ] Check log files for errors
- [ ] Backup signal CSV files: `cp data/*.csv backups/`
- [ ] Stop containers if desired: `docker-compose stop`

## File Locations

```
project/
├── .env                              # Your credentials (never commit!)
├── docker-compose.yml                # Service definitions
├── Dockerfile                        # Trading app container
├── config/
│   └── options-trader-config.yaml   # Trading parameters
├── logs/
│   └── trading.log                  # Application logs
├── data/
│   └── daily_signals_*.csv          # Signal data exports
└── README.md                        # Documentation
```

## Security Best Practices

1. **Never commit `.env` file**
   ```bash
   echo ".env" >> .gitignore
   ```

2. **Use strong passwords**
   - IB password should be complex
   - VNC password should be unique

3. **Restrict port access**
   - Ports bind to 127.0.0.1 (localhost only)
   - Don't expose to public internet

4. **Regular password rotation**
   - Change IB password periodically
   - Update `.env` after changes

5. **Monitor logs for unauthorized access**
   ```bash
   docker-compose logs | grep -i "unauthorized\|failed\|denied"
   ```

## Advanced Configuration

### Running Multiple Trading Strategies

You can run multiple trading containers against one Gateway:

```yaml
services:
  ib-gateway:
    # ... (same as before)
  
  ajj-options-trader:
    # ... (existing config)
  
  ajj-futures-trader:
    build: ./futures-strategy
    depends_on:
      - ib-gateway
    environment:
      - IB_HOST=ib-gateway
      - IB_PORT=4002
      - IB_CLIENT_ID=2  # Different client ID!
```

### Custom Gateway Configuration

Create `gateway-config/jts.ini` for advanced Gateway settings:

```ini
[IBGateway]
ApiOnly=true
WriteDebug=true
TrustedIPs=172.18.0.0/16
```

Mount in docker-compose:
```yaml
ib-gateway:
  volumes:
    - ./gateway-config:/root/ibc
```

## Performance Tuning

### For High-Frequency Trading

```yaml
ib-gateway:
  environment:
    # Reduce logging for performance
    LOG_LEVEL: ERROR
  deploy:
    resources:
      limits:
        cpus: '2.0'
        memory: 2G
      reservations:
        cpus: '1.0'
        memory: 1G
```

### For Stability

```yaml
ib-gateway:
  restart: always  # Always restart on failure
  
  healthcheck:
    interval: 10s    # More frequent health checks
    retries: 5
```

## Next Steps

Once you have the system running:

1. **Test in paper mode for 1-2 weeks**
2. **Monitor and tune Greeks thresholds**
3. **Expand watchlist gradually**
4. **Review and analyze all trades**
5. **Only then consider live trading**

## Getting Help

**Container Issues:**
```bash
# View detailed logs
docker-compose logs --tail=100 ib-gateway
docker-compose logs --tail=100 ajj-options-trader

# Check container stats
docker stats

# Inspect container
docker inspect ib-gateway
```

**IB Gateway Issues:**
- Check VNC to see actual Gateway UI
- Review IB system status page
- Verify credentials in IB Account Management

**Trading App Issues:**
- Check `logs/trading.log` for detailed errors
- Verify configuration in `config/options-trader-config.yaml`
- Test connection manually with sample script

---

**Remember:** Always start with paper trading and test thoroughly before going live!
