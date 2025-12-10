# Makefile for Options Trading Microservice
# Two-container setup: IB Gateway + Trading Application

# Variables
COMPOSE_FILE := docker/docker-compose-options-trader.yml
GATEWAY_SERVICE := ib-gateway
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
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""

# =============================================================================
# Development Commands
# =============================================================================

.PHONY: trades-dev
trades-dev: ## Build and run trading app in development mode (interactive)
	@echo "$(GREEN)Starting development environment...$(NC)"
	@$(MAKE) gateway-start
	@echo "$(YELLOW)Waiting $(GATEWAY_WAIT_TIME)s for Gateway to initialize...$(NC)"
	@sleep $(GATEWAY_WAIT_TIME)
	@$(MAKE) gateway-check
	@echo "$(GREEN)Building and starting trading application...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) build $(TRADER_SERVICE)
	@docker-compose -f $(COMPOSE_FILE) run --service-ports --rm $(TRADER_SERVICE)

.PHONY: trades-dev-quick
trades-dev-quick: ## Run trading app without rebuilding (assumes Gateway running)
	@echo "$(GREEN)Starting trading application (no rebuild)...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) run --service-ports --rm $(TRADER_SERVICE)

.PHONY: trades-dev-rebuild
trades-dev-rebuild: ## Force rebuild and run trading app
	@echo "$(GREEN)Force rebuilding trading application...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) build --no-cache $(TRADER_SERVICE)
	@docker-compose -f $(COMPOSE_FILE) run --service-ports --rm $(TRADER_SERVICE)

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
	@docker-compose -f $(COMPOSE_FILE) exec -T $(GATEWAY_SERVICE) nc -zv localhost 4002 2>&1 | grep succeeded > /dev/null && \
		echo "$(GREEN)✓ Gateway API is responding on port 4002$(NC)" || \
		echo "$(YELLOW)⚠ Gateway API not ready yet (may need more time)$(NC)"

.PHONY: gateway-vnc
gateway-vnc: ## Open Gateway UI in browser (noVNC)
	@echo "$(GREEN)Opening Gateway UI in browser...$(NC)"
	@echo "$(YELLOW)If browser doesn't open, visit: http://localhost:6080$(NC)"
	@open http://localhost:6080 2>/dev/null || xdg-open http://localhost:6080 2>/dev/null || \
		echo "$(YELLOW)Please manually open: http://localhost:6080$(NC)"

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
# Testing & Debug Commands
# =============================================================================

.PHONY: test-connection
test-connection: ## Test connection from trader to gateway
	@echo "$(YELLOW)Testing connection from trader to gateway...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) exec -T $(TRADER_SERVICE) ping -c 3 $(GATEWAY_SERVICE) && \
		echo "$(GREEN)✓ Network connectivity OK$(NC)" || \
		echo "$(RED)✗ Network connectivity failed$(NC)"
	@docker-compose -f $(COMPOSE_FILE) exec -T $(TRADER_SERVICE) nc -zv $(GATEWAY_SERVICE) 4002 && \
		echo "$(GREEN)✓ Gateway API reachable on port 4002$(NC)" || \
		echo "$(RED)✗ Gateway API not reachable$(NC)"

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

.PHONY: backup-signals
backup-signals: ## Backup signal CSV files
	@echo "$(GREEN)Backing up signal files...$(NC)"
	@mkdir -p backups/$$(date +%Y%m%d)
	@cp -v data/daily_signals_*.csv backups/$$(date +%Y%m%d)/ 2>/dev/null || echo "$(YELLOW)No signal files to backup$(NC)"
	@echo "$(GREEN)Backup complete: backups/$$(date +%Y%m%d)$(NC)"

.PHONY: backup-logs
backup-logs: ## Backup log files
	@echo "$(GREEN)Backing up log files...$(NC)"
	@mkdir -p backups/$$(date +%Y%m%d)
	@cp -v logs/*.log backups/$$(date +%Y%m%d)/ 2>/dev/null || echo "$(YELLOW)No log files to backup$(NC)"
	@echo "$(GREEN)Backup complete: backups/$$(date +%Y%m%d)$(NC)"

.PHONY: backup-all
backup-all: backup-signals backup-logs ## Backup all data files

.PHONY: clean-logs
clean-logs: ## Clean old log files (keeps last 7 days)
	@echo "$(YELLOW)Cleaning old log files...$(NC)"
	@find logs -name "*.log" -mtime +7 -delete 2>/dev/null || true
	@echo "$(GREEN)Log cleanup complete$(NC)"

.PHONY: clean-signals
clean-signals: ## Clean old signal files (keeps last 30 days)
	@echo "$(YELLOW)Cleaning old signal files...$(NC)"
	@find data -name "daily_signals_*.csv" -mtime +30 -delete 2>/dev/null || true
	@echo "$(GREEN)Signal cleanup complete$(NC)"

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
	@test -f .env && echo "$(GREEN)✓ .env file exists$(NC)" || echo "$(RED)✗ .env file missing$(NC)"
	@test -f config/options-trader-config.yaml && echo "$(GREEN)✓ config.yaml exists$(NC)" || echo "$(RED)✗ config.yaml missing$(NC)"
	@grep -q "IB_USERNAME" .env && echo "$(GREEN)✓ IB_USERNAME set$(NC)" || echo "$(RED)✗ IB_USERNAME not set$(NC)"
	@grep -q "IB_PASSWORD" .env && echo "$(GREEN)✓ IB_PASSWORD set$(NC)" || echo "$(RED)✗ IB_PASSWORD not set$(NC)"

.PHONY: config-edit
config-edit: ## Open config file in editor
	@$${EDITOR:-nano} config/options-trader-config.yaml

.PHONY: env-edit
env-edit: ## Open .env file in editor
	@$${EDITOR:-nano} .env

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
	@test -f .env || (echo "$(YELLOW)Creating .env file from template...$(NC)" && cp .env.example .env)
	@echo "$(YELLOW)Please edit .env with your IB credentials:$(NC)"
	@echo "  - IB_USERNAME"
	@echo "  - IB_PASSWORD"
	@echo "  - TRADING_MODE (paper/live)"
	@read -p "Press Enter to open .env in editor..." && $${EDITOR:-nano} .env
	@echo ""
	@echo "$(GREEN)Pulling IB Gateway image...$(NC)"
	@$(MAKE) build-gateway
	@echo ""
	@echo "$(GREEN)Building trading application...$(NC)"
	@$(MAKE) build-trader
	@echo ""
	@echo "$(GREEN)✓ Setup complete! Use 'make trades-dev' to start trading.$(NC)"

# =============================================================================
# Default target
# =============================================================================

.DEFAULT_GOAL := help


# Makes a local environment
# trades-dev:
# 	docker-compose -f docker/docker-compose-options-trader.yml build && \
# 	docker-compose -f docker/docker-compose-options-trader.yml run --service-ports --rm ajj-options-trader