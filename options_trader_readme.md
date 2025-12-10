## Features# Options Trading Microservice with Interactive Brokers

A dockerized Python microservice for analyzing and trading 0DTE options based on Greeks analysis and breakout signals. Uses the modern `ib_async` library (successor to `ib_insync`).

## Architecture

### Two-Container System

```
┌─────────────────────────┐
│   IB Gateway Container  │  ← Handles IB connection
│   Port: 4001/4002       │     and authentication
└───────────┬─────────────┘
            │
            │ Docker Network
            │
┌───────────▼─────────────┐
│  Trading App Container  │  ← Your Python code
│  ajj-options-trader     │     with ib_async
└─────────────────────────┘
```

The system uses two separate containers:
- **IB Gateway**: Manages connection to Interactive Brokers
- **Trading Application**: Your Python code that analyzes and trades options

This separation provides:
- ✅ Update trading code without restarting Gateway
- ✅ Better debugging and monitoring
- ✅ Gateway can be shared by multiple strategies
- ✅ Easier maintenance and troubleshooting

- ✅ Real-time options data from Interactive Brokers
- ✅ Greeks calculation (Gamma, Delta, Vega, Theta, IV)
- ✅ Breakout signal detection based on configurable thresholds
- ✅ Paper trading and live trading modes
- ✅ Interactive CLI for position sizing and trade confirmation
- ✅ Comprehensive logging and trade tracking
- ✅ Risk management (max trades/day, confirmation required)
- ✅ 0DTE options focus with configurable watchlist

## Prerequisites

### 1. Interactive Brokers Account
- Active IB account with API access enabled
- Paper trading account recommended for testing
- Market data subscriptions (if needed)

### 2. Docker
- Docker Engine 20.10+
- Docker Compose 2.0+

### 3. System Requirements
- 4GB RAM minimum
- 2GB disk space
- Stable internet connection

## Quick Start

### 1. Clone and Setup

```bash
# Create project directory
mkdir options-trader
cd options-trader

# Create all necessary files (copy the artifacts provided)
# - main.py
# - config/options-trader-config.yaml
# - requirements.txt
# - Dockerfile
# - docker-compose.yml
# - .env (from .env.example)
```

### 2. Configure Credentials

```bash
# Copy environment template
cp .env.example .env

# Edit with your IB credentials
nano .env
```

**Required in .env:**
```bash
IB_USERNAME=your_username
IB_PASSWORD=your_password
TRADING_MODE=paper
IB_PORT=4002
```

### 3. Configure Trading Parameters

Edit `config/options-trader-config.yaml`:

```yaml
# Connection (already configured for Docker)
ib_host: 'ib-gateway'  # Docker service name
ib_port: 4002          # Gateway paper trading port

# Set your watchlist
watchlist:
  - SPX
  - SPY
  - QQQ

# Adjust for paper vs live trading
paper_trading: true  # Always start with paper trading!

# Tune your Greeks thresholds
min_gamma: 0.05
min_delta: 0.20
max_delta: 0.80
```

### 4. Build and Run

```bash
# Start IB Gateway first
docker-compose up -d ib-gateway

# Wait 60 seconds for Gateway to initialize and login
sleep 60

# Check Gateway is ready
docker-compose logs ib-gateway | grep "ready"

# Start trading service
docker-compose up -d ajj-options-trader

# View logs
docker-compose logs -f ajj-options-trader
```

## Usage

### Running a Scan

When you start the service, it will:
1. Connect to Interactive Brokers
2. Scan each symbol in your watchlist for 0DTE options
3. Calculate Greeks for all options
4. Analyze for breakout opportunities
5. Present top opportunities for your review

### Trade Confirmation Flow

When a potential trade is detected:

```
==============================================================
TRADE OPPORTUNITY DETECTED
==============================================================
Symbol: SPX
Type: C (Call/Put)
Strike: $4500.00
Expiration: 20241209
Price: $12.50

Greeks:
  Delta: 0.4532
  Gamma: 0.0823
  Vega: 0.2341
  Theta: -0.3210
  IV: 18.45%

Breakout Score: 87.32
==============================================================

Execute this trade? (yes/no): yes
Enter number of contracts: 2
```

### Monitoring

```bash
# View real-time logs
docker-compose logs -f ajj-options-trader

# View Gateway logs
docker-compose logs -f ib-gateway

# Check trade log file
cat logs/trading.log

# Access Gateway UI via browser (VNC)
open http://localhost:6080

# Access container shell
docker exec -it ajj-options-trader bash
```

## Configuration Reference

### Greeks Thresholds

| Parameter | Description | Default | Recommendation |
|-----------|-------------|---------|----------------|
| `min_gamma` | Minimum gamma for sensitivity | 0.05 | Higher = more volatile |
| `min_delta` | Minimum directional exposure | 0.20 | For OTM options |
| `max_delta` | Maximum directional exposure | 0.80 | Avoid deep ITM |
| `min_vega` | Minimum vol sensitivity | 0.10 | Benefits from vol expansion |
| `min_theta` | Maximum time decay | -0.50 | Less decay = longer hold |

### IV Percentile Strategy

- **30-70 range**: Balanced approach, avoid extremes
- **20-40 range**: Low IV, expect expansion
- **60-80 range**: High IV, mean reversion risk

### Risk Management

```yaml
max_trades_per_day: 5      # Limit daily trades
require_confirmation: true  # Manual approval required
```

## Advanced Features

### Custom Watchlist

```yaml
watchlist:
  - SPX    # S&P 500 Index
  - SPY    # S&P 500 ETF
  - QQQ    # Nasdaq ETF
  - AAPL   # Individual stocks
  - TSLA
  - NVDA
```

### Scheduling Scans

Use cron inside container:

```dockerfile
# Add to Dockerfile
RUN apt-get install -y cron

# Create cron job
CMD cron && python main.py
```

Or use external scheduler:

```bash
# Run every hour
0 * * * * cd /path/to/options-trader && docker-compose up
```

### Environment Variables

Override config via environment:

```bash
# .env file
IB_HOST=192.168.1.100
IB_PORT=7496
PAPER_TRADING=false
```

## Extending the Service

### Adding New Strategies

1. **Spreads**: Modify `execute_trade()` to handle multi-leg orders
2. **Stop Loss**: Add `stop_loss_monitor()` async task
3. **Profit Taking**: Implement target price exits

### Additional Analysis

```python
# Add to BreakoutAnalyzer class
def calculate_expected_move(self, df: pd.DataFrame) -> float:
    """Calculate expected move from straddle prices"""
    atm_call = df[df['right'] == 'C'].iloc[0]
    atm_put = df[df['right'] == 'P'].iloc[0]
    return (atm_call['mid_price'] + atm_put['mid_price']) * 0.85
```

### Database Integration

Add PostgreSQL for trade history:

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: trading
      POSTGRES_USER: trader
      POSTGRES_PASSWORD: secure_password
```

## Troubleshooting

### Connection Issues

**Error: "Connection refused"**
- Ensure IB Gateway container is running: `docker-compose ps ib-gateway`
- Wait 60-90 seconds after starting Gateway
- Check Gateway logs: `docker-compose logs ib-gateway`
- Verify credentials in `.env` file

**Error: "Cannot connect to IB"**
```bash
# Test connection from trading container
docker exec ajj-options-trader ping ib-gateway
docker exec ajj-options-trader nc -zv ib-gateway 4002
```

**Wrong port:**
- IB Gateway Paper: 4002
- IB Gateway Live: 4001
- TWS Paper: 7497
- TWS Live: 7496

### Data Issues

**No options found**
- Symbol may not have 0DTE options
- Check if options are available for that expiration
- Verify market hours

**Greeks not calculating**
- Increase sleep time in `get_option_data()`
- Check if market data subscription is active

### Performance

**Slow scanning**
- Reduce number of strikes analyzed
- Increase asyncio sleep times
- Use `asyncio.gather()` for parallel requests

## Safety Reminders

⚠️ **ALWAYS START WITH PAPER TRADING** ⚠️

1. Test thoroughly in paper trading mode
2. Verify all calculations are correct
3. Ensure order execution works as expected
4. Start with small position sizes
5. Monitor first trades manually
6. Set appropriate stop losses

## Support and Resources

### Interactive Brokers API
- [IB API Documentation](https://interactivebrokers.github.io/tws-api/)
- [ib_async Documentation](https://ib-api-reloaded.github.io/ib_async/)
- [ib_async GitHub](https://github.com/ib-api-reloaded/ib_async)

### Options Trading
- Greeks definitions and strategies
- 0DTE options risks and rewards
- Position sizing calculators

## License

This is a personal trading tool. Use at your own risk. Not financial advice.

## Disclaimer

This software is for educational purposes. Trading options involves substantial risk of loss. The developer is not responsible for any financial losses incurred from using this software. Always trade responsibly and within your risk tolerance.
