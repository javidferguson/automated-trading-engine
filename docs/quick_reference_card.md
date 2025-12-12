# Quick Reference Card

## Port Reference

| Application | Paper Trading | Live Trading |
|-------------|---------------|--------------|
| **IB Gateway** | 4002 | 4001 |
| **TWS** | 7497 | 7496 |
| **VNC** | 5900 | 5900 |
| **noVNC (Browser)** | 6080 | 6080 |

## Essential Commands

### Starting the System

```bash
# Start everything
docker-compose up -d

# Start just Gateway
docker-compose up -d ib-gateway

# Start just trading app
docker-compose up -d ajj-options-trader

# Start and view logs
docker-compose up
```

### Monitoring

```bash
# View all logs
docker-compose logs -f

# Gateway logs only
docker-compose logs -f ib-gateway

# Trading app logs only
docker-compose logs -f ajj-options-trader

# Last 50 lines
docker-compose logs --tail=50 ajj-options-trader

# Check status
docker-compose ps
```

### Stopping

```bash
# Stop all services
docker-compose down

# Stop but keep containers
docker-compose stop

# Stop specific service
docker-compose stop ajj-options-trader
```

### Restarting

```bash
# Restart everything
docker-compose restart

# Restart specific service
docker-compose restart ib-gateway
docker-compose restart ajj-options-trader

# Rebuild and restart (after code changes)
docker-compose up -d --build ajj-options-trader
```

## Configuration Files

### .env (Your Credentials)

```bash
# Paper Trading
IB_USERNAME=your_username
IB_PASSWORD=your_password
TRADING_MODE=paper
PAPER_TRADING=true
IB_PORT=4002
VNC_PASSWORD=vncpass

# Live Trading
TRADING_MODE=live
PAPER_TRADING=false
IB_PORT=4001
```

### config/options-trader-config.yaml

```yaml
# Connection
ib_host: 'ib-gateway'  # Docker service name
ib_port: 4002          # 4002=paper, 4001=live

# Watchlist
watchlist:
  - SPX
  - SPY

# Trading
paper_trading: true    # true or false
max_trades_per_day: 5
require_confirmation: true

# Greeks Thresholds
min_gamma: 0.05
min_delta: 0.20
max_delta: 0.80
```

## Troubleshooting Quick Fixes

### Gateway Won't Start

```bash
# Check logs
docker-compose logs ib-gateway | grep -i error

# Verify credentials
cat .env | grep IB_

# Restart
docker-compose restart ib-gateway
```

### App Can't Connect

```bash
# Check Gateway is running
docker-compose ps ib-gateway

# Should show "Up (healthy)"

# Test connection
docker exec ajj-options-trader ping ib-gateway
docker exec ajj-options-trader nc -zv ib-gateway 4002

# Check port matches
grep ib_port config/options-trader-config.yaml
grep IB_PORT .env
```

### See Gateway UI

```bash
# Browser (easiest)
open http://localhost:6080

# Or VNC client to localhost:5900
# Password: from VNC_PASSWORD in .env
```

### Check Logs for Errors

```bash
# Today's errors only
docker-compose logs --since 1h | grep -i error

# Connection issues
docker-compose logs | grep -i "connect\|refused\|timeout"

# Trade issues
docker-compose logs ajj-options-trader | grep -i "trade\|order"
```

## File Locations

```
Config:   config/options-trader-config.yaml
Logs:     logs/trading.log
Signals:  data/daily_signals_*.csv
Env:      .env (your credentials)
Compose:  docker-compose.yml
```

## Health Checks

```bash
# Is Gateway healthy?
docker inspect ib-gateway | grep -A 3 '"Health"'

# Manual health check
docker exec ib-gateway nc -zv localhost 4002

# Check if API is responding
curl -v telnet://localhost:4002
```

## VNC Access

```bash
# Browser-based (noVNC)
http://localhost:6080

# VNC Client
Host: localhost:5900
Password: <VNC_PASSWORD from .env>

# Check VNC is running
docker-compose ps | grep 5900
```

## Common Issues

| Symptom | Likely Cause | Quick Fix |
|---------|-------------|-----------|
| "Connection refused" | Gateway not ready | Wait 60s, check logs |
| "Timeout" | Wrong port | Check .env and config.yaml match |
| "Authentication failed" | Wrong credentials | Verify .env IB_USERNAME/PASSWORD |
| "API version mismatch" | Old ib_async | `pip install --upgrade ib_async` |
| Container keeps restarting | Bad credentials or 2FA | Check logs, disable 2FA temporarily |
| No options found | Wrong symbol or time | Check market hours, symbol has 0DTE |
| Gateway disconnects daily | Normal IB maintenance | Automatic, will reconnect |

## Paper vs Live Trading

### Switch to Paper

```bash
# Edit .env
TRADING_MODE=paper
PAPER_TRADING=true
IB_PORT=4002

# Edit config/options-trader-config.yaml
paper_trading: true
ib_port: 4002

# Restart
docker-compose restart
```

### Switch to Live (⚠️ Be Careful!)

```bash
# Edit .env
TRADING_MODE=live
PAPER_TRADING=false
IB_PORT=4001

# Edit config/options-trader-config.yaml
paper_trading: false
ib_port: 4001

# Restart
docker-compose restart

# VERIFY in logs
docker-compose logs ajj-options-trader | grep "Trading Mode"
# Should show: "Trading Mode: LIVE"
```

## Daily Workflow

### Morning

```bash
# 1. Start system
docker-compose up -d

# 2. Check Gateway connected
docker-compose logs ib-gateway | tail -20

# 3. Check trading app connected
docker-compose logs ajj-options-trader | grep Connected

# 4. Monitor
docker-compose logs -f ajj-options-trader
```

### During Day

```bash
# Watch for signals
tail -f logs/trading.log

# Check positions (in IB account)

# View signal data
ls -lh data/daily_signals_*.csv
```

### Evening

```bash
# Stop system
docker-compose down

# Backup signal data
cp data/*.csv backups/$(date +%Y%m%d)/

# Review logs
less logs/trading.log
```

## Environment Variables Override

```bash
# Override without editing files
IB_PORT=4002 docker-compose up -d

# Multiple overrides
IB_HOST=localhost IB_PORT=4002 docker-compose up -d
```

## Docker Shortcuts

```bash
# Enter container shell
docker exec -it ajj-options-trader bash
docker exec -it ib-gateway bash

# Copy files from container
docker cp ajj-options-trader:/app/logs/trading.log ./

# View container resource usage
docker stats

# Clean up everything
docker-compose down -v
docker system prune -a
```

## Getting Help

```bash
# View full logs
docker-compose logs --no-trunc

# Export logs to file
docker-compose logs > debug.log 2>&1

# Check container details
docker inspect ajj-options-trader

# Network info
docker network inspect ajj-trading-network
```

## Important URLs

- **noVNC (Browser Gateway UI)**: http://localhost:6080
- **IB Status Page**: https://status.interactivebrokers.com
- **IB Account Management**: https://www.interactivebrokers.com/sso
- **Docker Hub Gateway Image**: https://github.com/gnzsnz/ib-gateway-docker

## Emergency Commands

```bash
# Stop everything immediately
docker-compose down --remove-orphans

# Kill all containers
docker kill $(docker ps -q)

# Remove all volumes (⚠️ deletes data)
docker-compose down -v

# Full cleanup and restart
docker-compose down
docker system prune -f
docker-compose up -d
```

---

## Quick Start Sequence

```bash
# 1. Setup credentials
cp .env.example .env
nano .env  # Add IB_USERNAME, IB_PASSWORD

# 2. Start Gateway
docker-compose up -d ib-gateway

# 3. Wait for Gateway (60 seconds)
sleep 60

# 4. Check Gateway
docker-compose logs ib-gateway | grep "ready"

# 5. Start trading app
docker-compose up -d ajj-options-trader

# 6. Monitor
docker-compose logs -f ajj-options-trader
```

---

**Print this page for quick reference while trading!**
