# Makefile Usage Guide

## Overview

The updated Makefile handles the two-container setup automatically, managing both IB Gateway and the trading application.

## Quick Start

```bash
# First time setup
make setup

# Development workflow (replaces your old trades-dev)
make trades-dev

# View all available commands
make help
```

## Key Differences from Old Command

### Old Command (Single Container)
```makefile
trades-dev:
    docker-compose -f docker/docker-compose-options-trader.yml build && \
    docker-compose -f docker/docker-compose-options-trader.yml run --service-ports --rm ajj-options-trader
```

**Problem:** Doesn't handle Gateway startup/wait time

### New Command (Two Containers)
```makefile
trades-dev:
    - Starts Gateway first
    - Waits 60 seconds for initialization
    - Checks Gateway health
    - Builds trading app
    - Runs trading app interactively
```

**Benefits:** Handles entire workflow automatically!

## Common Commands

### Development (Most Used)

```bash
# Complete dev workflow (recommended)
make trades-dev
# → Starts Gateway, waits, checks health, builds & runs trader

# Quick run (Gateway already running)
make trades-dev-quick
# → Skip Gateway startup, just run trader

# Force rebuild trader app
make trades-dev-rebuild
# → Rebuild from scratch, then run
```

### Daily Workflow

```bash
# Morning routine
make morning
# → Start everything, check status

# Monitor logs
make logs
# → View all logs in follow mode

# Check status
make status
# → Show service status and health

# Evening routine
make evening
# → Backup data, stop services
```

### Gateway Management

```bash
# Start Gateway only
make gateway-start

# Check if Gateway is ready
make gateway-check

# View Gateway logs
make gateway-logs

# View Gateway UI in browser
make gateway-vnc

# Restart Gateway
make gateway-restart
```

### Trader Management

```bash
# Start trader in background
make trader-start

# View trader logs
make trader-logs

# Restart trader (keeps Gateway running)
make trader-restart

# Open shell in trader container
make trader-shell
```

### Debugging

```bash
# Test connection between containers
make test-connection

# Detailed Gateway debug info
make debug-gateway

# Detailed trader debug info
make debug-trader

# Check configuration
make config-check
```

## Recommended Workflows

### First Time Setup

```bash
# 1. Run setup wizard
make setup
# → Creates .env, prompts for credentials, builds images

# 2. Test in development mode
make trades-dev
# → Runs everything interactively
```

### Daily Trading

```bash
# Morning
make morning              # Start everything
make trader-logs          # Monitor trading

# During day
make quick-restart        # Restart trader if needed
make status               # Check health

# Evening
make evening              # Backup and stop
```

### Development/Testing

```bash
# Keep Gateway running, iterate on code
make gateway-start
sleep 60

# Make code changes, then:
make trades-dev-quick     # Test without rebuilding Gateway

# Or with rebuild:
make trades-dev-rebuild   # Force clean rebuild
```

### Production/Background Mode

```bash
# Start all services in background
make start

# Monitor
make logs

# Stop
make stop
```

## Environment Variables

The Makefile uses these variables (can be overridden):

```makefile
COMPOSE_FILE := docker/docker-compose-options-trader.yml
GATEWAY_SERVICE := ib-gateway
TRADER_SERVICE := ajj-options-trader
GATEWAY_WAIT_TIME := 60
```

### Override Example

```bash
# Use different compose file
make trades-dev COMPOSE_FILE=docker-compose.yml

# Adjust wait time
make trades-dev GATEWAY_WAIT_TIME=90

# Different service name
make trader-logs TRADER_SERVICE=my-trader
```

## Comparison: Old vs New

| Task | Old Way | New Way |
|------|---------|---------|
| **Start for dev** | `make trades-dev` | `make trades-dev` |
| | (Only trader, Gateway manual) | (Both, automated) |
| **Check Gateway** | Manual | `make gateway-check` |
| **View logs** | docker-compose logs | `make logs` or `make trader-logs` |
| **Restart** | Stop and rerun | `make quick-restart` |
| **Debug** | docker inspect | `make debug-trader` |

## Full Command Reference

### Development
- `make trades-dev` - Full dev workflow (Gateway + Trader)
- `make trades-dev-quick` - Run trader only (no Gateway startup)
- `make trades-dev-rebuild` - Force rebuild trader

### Production
- `make start` - Start all services (background)
- `make stop` - Stop all services
- `make down` - Stop and remove containers
- `make restart` - Restart all services

### Gateway
- `make gateway-start` - Start Gateway
- `make gateway-stop` - Stop Gateway
- `make gateway-restart` - Restart Gateway
- `make gateway-logs` - View Gateway logs
- `make gateway-check` - Check Gateway health
- `make gateway-vnc` - Open Gateway UI

### Trader
- `make trader-start` - Start trader (background)
- `make trader-stop` - Stop trader
- `make trader-restart` - Restart trader
- `make trader-logs` - View trader logs
- `make trader-shell` - Open shell in trader

### Build
- `make build` - Build all containers
- `make build-gateway` - Pull Gateway image
- `make build-trader` - Build trader image
- `make build-no-cache` - Force rebuild without cache

### Monitoring
- `make logs` - All logs (follow mode)
- `make logs-tail` - Last 50 lines
- `make ps` - Container status
- `make status` - Detailed status

### Testing
- `make test-connection` - Test trader→gateway connection
- `make debug-gateway` - Gateway debug info
- `make debug-trader` - Trader debug info

### Data
- `make backup-signals` - Backup CSV files
- `make backup-logs` - Backup log files
- `make backup-all` - Backup everything
- `make clean-logs` - Remove logs >7 days
- `make clean-signals` - Remove signals >30 days

### Cleanup
- `make clean` - Remove containers & volumes
- `make clean-images` - Remove unused images
- `make clean-all` - Full cleanup

### Config
- `make config-check` - Validate config files
- `make config-edit` - Edit config.yaml
- `make env-edit` - Edit .env

### Workflows
- `make morning` - Morning startup routine
- `make evening` - Evening shutdown routine
- `make quick-restart` - Restart trader only

### Setup
- `make setup` - First-time setup wizard
- `make help` - Show all commands

## Tips & Tricks

### 1. Keep Gateway Running During Development

```bash
# Start Gateway once
make gateway-start
sleep 60

# Then iterate on code
make trades-dev-quick
# Make changes
make trades-dev-quick
# Repeat...
```

### 2. Monitor Multiple Terminals

```bash
# Terminal 1: Gateway logs
make gateway-logs

# Terminal 2: Trader logs
make trader-logs

# Terminal 3: Run commands
make status
```

### 3. Quick Health Check

```bash
# One command to check everything
make status
```

### 4. Automated Daily Routines

```bash
# Add to crontab
0 9 * * 1-5 cd /path/to/project && make morning
0 17 * * 1-5 cd /path/to/project && make evening
```

### 5. Debug Connection Issues

```bash
# Full diagnostic sequence
make gateway-check
make test-connection
make debug-gateway
make debug-trader
```

## Color Output

The Makefile uses colors for better readability:
- 🟢 **Green** - Success messages
- 🟡 **Yellow** - Warnings and info
- 🔴 **Red** - Errors and destructive operations

## Error Handling

If `make trades-dev` fails:

1. **Check Gateway first:**
   ```bash
   make gateway-check
   ```

2. **View Gateway logs:**
   ```bash
   make gateway-logs
   ```

3. **Test connection:**
   ```bash
   make test-connection
   ```

4. **Debug trader:**
   ```bash
   make debug-trader
   ```

## Customization

### Change Wait Time

```makefile
# In Makefile, change:
GATEWAY_WAIT_TIME := 60
# To:
GATEWAY_WAIT_TIME := 90
```

### Add Custom Commands

```makefile
.PHONY: my-workflow
my-workflow: ## My custom workflow
	@echo "Running custom workflow..."
	@$(MAKE) gateway-start
	@sleep 30
	@$(MAKE) trader-start
```

## Migration from Old Makefile

If you had:
```makefile
trades-dev:
    docker-compose -f docker/docker-compose-options-trader.yml build && \
    docker-compose -f docker/docker-compose-options-trader.yml run --service-ports --rm ajj-options-trader
```

Simply replace with the new Makefile and your existing command `make trades-dev` will work better than before!

**Bonus:** You also get 40+ additional commands for free!

## Quick Reference Card

```bash
# Most Used Commands
make help              # Show all commands
make trades-dev        # Dev mode (interactive)
make trades-dev-quick  # Dev mode (skip Gateway start)
make start             # Background mode
make stop              # Stop everything
make logs              # View logs
make status            # Check health
make morning           # Morning startup
make evening           # Evening shutdown
make gateway-vnc       # View Gateway UI
```

---

**Pro Tip:** Run `make help` anytime to see all available commands with descriptions!
