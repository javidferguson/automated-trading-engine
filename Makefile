# Variables
COMPOSE_FILE := docker/docker-compose-options-trader.yml
# Must match the env_file: entries in the compose file.
ENV_FILE := env.dev

# include env file
#
# The leading '-' matters: a plain `include` is a FATAL error when the file is
# missing, which silently breaks EVERY target here. env.dev is gitignored, so a
# fresh clone has none until you run `make setup`.
#
# Include $(ENV_FILE) by name rather than a glob: the old `-include .env*`
# pattern cannot match env.dev (no leading dot), and compose only *warns* on
# unset interpolation -- so the Gateway would start with empty credentials and
# just fail to log in, with nothing pointing at the cause.
-include $(ENV_FILE)
export
# Makefile for Options Trading Microservice
# Two-container setup: IB Gateway + Trading Application

GATEWAY_SERVICE := ajj-ib-gateway
TRADER_SERVICE := ajj-options-trader
GATEWAY_WAIT_TIME := 60

# Color output
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[1;33m
NC := \033[0m # No Color

.PHONY: help
help: ## Show this help message
	@echo "$(GREEN)Options Trading Microservice - Available Commands$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(firstword $(MAKEFILE_LIST)) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""

# =============================================================================
# Development Commands
# =============================================================================

# =============================================================================
# Production/Daemon Commands
# =============================================================================

.PHONY: start
start: ## Start all services in background (production mode)
	@echo "$(GREEN)Starting all services...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) up -d
	@echo "$(GREEN)Services started. Use 'make logs' to view output$(NC)"

.PHONY: stop
stop: ## Stop all services
	@echo "$(YELLOW)Stopping all services...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) stop
	@echo "$(GREEN)Services stopped$(NC)"

.PHONY: down
down: ## Stop and remove all containers
	@echo "$(RED)Stopping and removing all containers...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) down
	@echo "$(GREEN)Cleanup complete$(NC)"

.PHONY: restart
restart: stop start ## Restart all services

# =============================================================================
# Gateway-Specific Commands
# =============================================================================

.PHONY: gateway-start
gateway-start: ## Start IB Gateway only
	@echo "$(GREEN)Starting IB Gateway...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) up -d $(GATEWAY_SERVICE)
	@echo "$(GREEN)Gateway starting. Wait $(GATEWAY_WAIT_TIME)s for initialization.$(NC)"

.PHONY: gateway-stop
gateway-stop: ## Stop IB Gateway
	@echo "$(YELLOW)Stopping IB Gateway...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) stop $(GATEWAY_SERVICE)

.PHONY: gateway-restart
gateway-restart: gateway-stop gateway-start ## Restart IB Gateway

.PHONY: gateway-logs
gateway-logs: ## Show Gateway logs (follow mode)
	@docker-compose -f $(COMPOSE_FILE) logs -f $(GATEWAY_SERVICE)

.PHONY: gateway-check
gateway-check: ## Check if Gateway is ready
	@echo "$(YELLOW)Checking Gateway status...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) ps $(GATEWAY_SERVICE) | grep "Up" > /dev/null && \
		echo "$(GREEN)✓ Gateway container is running$(NC)" || \
		(echo "$(RED)✗ Gateway container is not running$(NC)" && exit 1)
	@docker-compose -f $(COMPOSE_FILE) exec -T $(GATEWAY_SERVICE) \
		bash -c "echo > /dev/tcp/127.0.0.1/4002" 2>/dev/null && \
		echo "$(GREEN)✓ IB Gateway is logged in and listening (4002)$(NC)" || \
		(echo "$(YELLOW)⚠ Gateway is running but NOT logged in yet.$(NC)"; \
		 echo "  Login can take 60-90s. If it stays this way, look at the screen:"; \
		 echo "    make gateway-vnc      # opens vnc://localhost:5900"; \
		 echo "  A dialog waiting for input (2FA, warning, or config) will be visible there.")
	@docker-compose -f $(COMPOSE_FILE) exec -T $(GATEWAY_SERVICE) \
		bash -c "echo > /dev/tcp/127.0.0.1/4004" 2>/dev/null && \
		echo "$(GREEN)✓ socat relay is listening (4004)$(NC)" || \
		echo "$(RED)✗ socat relay is not listening on 4004$(NC)"

.PHONY: gateway-vnc
gateway-vnc: ## Open the Gateway screen in a VNC client
	@grep -qE "^VNC_PASSWORD=.+" $(ENV_FILE) 2>/dev/null || \
		(echo "$(RED)✗ VNC_PASSWORD is not set in $(ENV_FILE).$(NC)"; \
		 echo "  The container starts its VNC server only when that is set."; \
		 echo "  Set it, then: make gateway-restart"; exit 1)
	@docker-compose -f $(COMPOSE_FILE) exec -T $(GATEWAY_SERVICE) \
		bash -c "echo > /dev/tcp/127.0.0.1/5900" 2>/dev/null || \
		echo "$(YELLOW)⚠ VNC not listening yet -- give it ~15s after start.$(NC)"
	@echo "$(GREEN)Opening the Gateway screen...$(NC)"
	@echo "$(YELLOW)Password is VNC_PASSWORD from $(ENV_FILE).$(NC)"
	@open vnc://localhost:5900 2>/dev/null || \
		echo "$(YELLOW)Connect a VNC client to localhost:5900$(NC)"

# =============================================================================
# Trader-Specific Commands
# =============================================================================

.PHONY: trader-start
trader-start: ## Start trading app in background
	@echo "$(GREEN)Starting trading application...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) up -d $(TRADER_SERVICE)

.PHONY: trader-stop
trader-stop: ## Stop trading app
	@echo "$(YELLOW)Stopping trading application...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) stop $(TRADER_SERVICE)

.PHONY: trader-restart
trader-restart: trader-stop trader-start ## Restart trading app

.PHONY: trader-logs
trader-logs: ## Show trading app logs (follow mode)
	@docker-compose -f $(COMPOSE_FILE) logs -f $(TRADER_SERVICE)

.PHONY: trader-shell
trader-shell: ## Open shell in trading container
	@docker-compose -f $(COMPOSE_FILE) exec $(TRADER_SERVICE) bash

# =============================================================================
# Build Commands
# =============================================================================

.PHONY: build
build: ## Build both containers
	@echo "$(GREEN)Building all containers...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) build

.PHONY: build-gateway
build-gateway: ## Pull latest Gateway image
	@echo "$(GREEN)Pulling latest Gateway image...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) pull $(GATEWAY_SERVICE)

.PHONY: build-trader
build-trader: ## Build trading app container
	@echo "$(GREEN)Building trading application...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) build $(TRADER_SERVICE)

.PHONY: build-no-cache
build-no-cache: ## Force rebuild without cache
	@echo "$(GREEN)Force rebuilding all containers...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) build --no-cache

# =============================================================================
# Logging & Monitoring Commands
# =============================================================================

.PHONY: logs
logs: ## Show logs from all services (follow mode)
	@docker-compose -f $(COMPOSE_FILE) logs -f

.PHONY: logs-tail
logs-tail: ## Show last 50 lines of logs from all services
	@docker-compose -f $(COMPOSE_FILE) logs --tail=50

.PHONY: ps
ps: ## Show status of all containers
	@docker-compose -f $(COMPOSE_FILE) ps

.PHONY: status
status: ## Show detailed status of all services
	@echo "$(GREEN)Service Status:$(NC)"
	@docker-compose -f $(COMPOSE_FILE) ps
	@echo ""
	@echo "$(GREEN)Gateway Health:$(NC)"
	@$(MAKE) gateway-check 2>&1 || true
	@echo ""
	@echo "$(GREEN)Recent Logs (last 10 lines):$(NC)"
	@docker-compose -f $(COMPOSE_FILE) logs --tail=10

# =============================================================================
# ORB + GEX Engine
# =============================================================================

.PHONY: orb-replay
orb-replay: ## Replay a past session through the engine (no orders, no subscription)
	@echo "$(GREEN)Replaying a past session through the ORB+GEX engine...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) run --rm -e DATA_MODE=replay $(TRADER_SERVICE) \
		python -m trading_engine.main --data-mode replay

.PHONY: orb-delayed
orb-delayed: ## Run on live-but-delayed data (~15 min late; CAN place paper orders)
	@echo "$(YELLOW)Delayed data lags ~15 min, so the entry limit is stale.$(NC)"
	@echo "$(YELLOW)This CAN place a paper order -- you will be asked to confirm.$(NC)"
	@docker-compose -f $(COMPOSE_FILE) run --rm -e DATA_MODE=delayed $(TRADER_SERVICE) \
		python -m trading_engine.main --data-mode delayed

.PHONY: orb-live
orb-live: ## Run against real-time bars (REQUIRES a paid IB market data subscription)
	@echo "$(RED)Real-time mode: orders can be placed (paper account, confirmation required).$(NC)"
	@docker-compose -f $(COMPOSE_FILE) run --rm -e DATA_MODE=realtime $(TRADER_SERVICE) \
		python -m trading_engine.main --data-mode realtime

.PHONY: test
test: ## Run the test suite in the trader container
	@docker-compose -f $(COMPOSE_FILE) run --rm $(TRADER_SERVICE) \
		sh -c "pip install -q pytest pytest-asyncio pytest-mock && python -m pytest tests -q"

.PHONY: test-local
test-local: ## Run the test suite on the host (needs a local venv)
	@test -x .venv/bin/python || \
		(echo "$(RED)✗ No .venv here.$(NC)"; \
		 echo "  Create one:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"; \
		 echo "  Or run the suite in the container:  make test"; exit 1)
	@.venv/bin/python -m pytest tests -q

# =============================================================================
# Testing & Debug Commands
# =============================================================================

.PHONY: test-connection
test-connection: ## Test connection from trader to gateway
	@echo "$(YELLOW)Testing connection from trader to gateway...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) exec -T $(TRADER_SERVICE) ping -c 3 $(GATEWAY_SERVICE) && \
		echo "$(GREEN)✓ Network connectivity OK$(NC)" || \
		echo "$(RED)✗ Network connectivity failed$(NC)"
	@docker-compose -f $(COMPOSE_FILE) exec -T $(TRADER_SERVICE) nc -zv $(GATEWAY_SERVICE) 4004 && \
		echo "$(GREEN)✓ socat relay reachable on 4004$(NC)" || \
		echo "$(RED)✗ socat relay not reachable$(NC)"
	@echo "$(YELLOW)Note: reaching 4004 only proves socat is up. Use 'make gateway-check'$(NC)"
	@echo "$(YELLOW)to confirm IB Gateway itself has finished logging in.$(NC)"

.PHONY: debug-gateway
debug-gateway: ## Show detailed Gateway debug info
	@echo "$(GREEN)Gateway Debug Information:$(NC)"
	@echo ""
	@echo "$(YELLOW)Container Status:$(NC)"
	@docker-compose -f $(COMPOSE_FILE) ps $(GATEWAY_SERVICE)
	@echo ""
	@echo "$(YELLOW)Last 30 log lines:$(NC)"
	@docker-compose -f $(COMPOSE_FILE) logs --tail=30 $(GATEWAY_SERVICE)
	@echo ""
	@echo "$(YELLOW)Port Bindings:$(NC)"
	@docker inspect $$(docker-compose -f $(COMPOSE_FILE) ps -q $(GATEWAY_SERVICE)) | grep -A 10 "Ports" || true

.PHONY: debug-trader
debug-trader: ## Show detailed trader debug info
	@echo "$(GREEN)Trading App Debug Information:$(NC)"
	@echo ""
	@echo "$(YELLOW)Container Status:$(NC)"
	@docker-compose -f $(COMPOSE_FILE) ps $(TRADER_SERVICE)
	@echo ""
	@echo "$(YELLOW)Last 30 log lines:$(NC)"
	@docker-compose -f $(COMPOSE_FILE) logs --tail=30 $(TRADER_SERVICE)
	@echo ""
	@echo "$(YELLOW)Environment Variables:$(NC)"
	@docker-compose -f $(COMPOSE_FILE) exec -T $(TRADER_SERVICE) env | grep -E "IB_|PAPER" || true

# =============================================================================
# Data Management Commands
# =============================================================================

.PHONY: backup-logs
backup-logs: ## Backup log files
	@echo "$(GREEN)Backing up log files...$(NC)"
	@mkdir -p backups/$$(date +%Y%m%d)
	@cp -v logs/*.log backups/$$(date +%Y%m%d)/ 2>/dev/null || echo "$(YELLOW)No log files to backup$(NC)"
	@echo "$(GREEN)Backup complete: backups/$$(date +%Y%m%d)$(NC)"

.PHONY: backup-all
backup-all: backup-logs ## Backup all data files

.PHONY: clean-logs
clean-logs: ## Clean old log files (keeps last 7 days)
	@echo "$(YELLOW)Cleaning old log files...$(NC)"
	@find logs -name "*.log" -mtime +7 -delete 2>/dev/null || true
	@echo "$(GREEN)Log cleanup complete$(NC)"

# =============================================================================
# Cleanup Commands
# =============================================================================

.PHONY: clean
clean: ## Remove all containers and volumes (WARNING: deletes data)
	@echo "$(RED)⚠ WARNING: This will remove all containers and volumes!$(NC)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker-compose -f $(COMPOSE_FILE) down -v; \
		echo "$(GREEN)Cleanup complete$(NC)"; \
	else \
		echo "$(YELLOW)Cleanup cancelled$(NC)"; \
	fi

.PHONY: clean-images
clean-images: ## Remove unused Docker images
	@echo "$(YELLOW)Removing unused Docker images...$(NC)"
	@docker image prune -f
	@echo "$(GREEN)Image cleanup complete$(NC)"

.PHONY: clean-all
clean-all: clean clean-images ## Full cleanup (containers, volumes, images)

# =============================================================================
# Configuration Commands
# =============================================================================

.PHONY: config-check
config-check: ## Validate configuration files
	@echo "$(GREEN)Checking configuration...$(NC)"
	@test -f $(ENV_FILE) && echo "$(GREEN)✓ $(ENV_FILE) exists$(NC)" || echo "$(RED)✗ $(ENV_FILE) missing (run: make setup)$(NC)"
	@test -f config/orb-gamma-config.yaml && echo "$(GREEN)✓ orb-gamma-config.yaml exists$(NC)" || echo "$(RED)✗ orb-gamma-config.yaml missing$(NC)"
	@grep -q "^IB_USERNAME=" $(ENV_FILE) 2>/dev/null && echo "$(GREEN)✓ IB_USERNAME set$(NC)" || echo "$(RED)✗ IB_USERNAME not set$(NC)"
	@grep -q "^IB_PASSWORD=" $(ENV_FILE) 2>/dev/null && echo "$(GREEN)✓ IB_PASSWORD set$(NC)" || echo "$(RED)✗ IB_PASSWORD not set$(NC)"
	@grep -qE "^IB_USERNAME=your_username|^IB_PASSWORD=your_password" $(ENV_FILE) 2>/dev/null && echo "$(YELLOW)⚠ $(ENV_FILE) still has template placeholders -- edit it$(NC)" || true
	@echo "$(YELLOW)DATA_MODE:$(NC) $${DATA_MODE:-replay}  $(YELLOW)TRADING_MODE:$(NC) $${TRADING_MODE:-paper}"

.PHONY: config-edit
config-edit: ## Open config file in editor
	@$${EDITOR:-nano} config/orb-gamma-config.yaml

.PHONY: env-edit
env-edit: ## Open the env file in editor
	@$${EDITOR:-nano} $(ENV_FILE)

# =============================================================================
# Quick Workflow Commands
# =============================================================================

.PHONY: morning
morning: ## Morning routine: start everything and check status
	@echo "$(GREEN)☀️  Starting morning routine...$(NC)"
	@$(MAKE) start
	@sleep $(GATEWAY_WAIT_TIME)
	@$(MAKE) status
	@echo "$(GREEN)✓ Morning routine complete. Ready to trade!$(NC)"

.PHONY: evening
evening: ## Evening routine: backup data and stop services
	@echo "$(YELLOW)🌙 Starting evening routine...$(NC)"
	@$(MAKE) backup-all
	@$(MAKE) stop
	@echo "$(GREEN)✓ Evening routine complete. Good night!$(NC)"

.PHONY: quick-restart
quick-restart: ## Quick restart of trading app only (keeps Gateway running)
	@echo "$(YELLOW)Quick restart of trading application...$(NC)"
	@$(MAKE) trader-restart
	@echo "$(GREEN)✓ Trading app restarted$(NC)"

# =============================================================================
# Setup Commands (First Time)
# =============================================================================

.PHONY: setup
setup: ## First-time setup wizard
	@echo "$(GREEN)🚀 Options Trading Microservice Setup$(NC)"
	 @echo ""
	 @test -f $(ENV_FILE) || (echo "$(YELLOW)Creating $(ENV_FILE) from template...$(NC)" && cp example.env $(ENV_FILE))
	 @echo "$(YELLOW)Please edit $(ENV_FILE) with your IB credentials:$(NC)"
	 @echo "  - IB_USERNAME"
	 @echo "  - IB_PASSWORD"
	 @echo "  - TRADING_MODE (paper/live)  -- which ACCOUNT the Gateway logs into"
	 @echo "  - DATA_MODE (realtime/delayed/replay)  -- where BARS come from"
	 @read -p "Press Enter to open $(ENV_FILE) in editor..." && $${EDITOR:-nano} $(ENV_FILE)
	 @echo ""
	@echo "$(GREEN)Pulling IB Gateway image...$(NC)"
	@$(MAKE) build-gateway
	@echo ""
	@echo "$(GREEN)Building trading application...$(NC)"
	@$(MAKE) build-trader
	@echo ""
	@echo "$(GREEN)✓ Setup complete.$(NC)"
	@echo "$(YELLOW)Next: make gateway-start && make gateway-vnc, then make orb-replay$(NC)"

# =============================================================================
# Default target
# =============================================================================

.DEFAULT_GOAL := help

