# Options Trading Microservice with Interactive Brokers

A dockerized Python microservice for analyzing and trading 0DTE options based on Greeks analysis and breakout signals.

## Features

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
- TWS (Trader Workstation) or IB Gateway installed and running
- Enable API connections in TWS/Gateway settings

### 2. Docker
- Docker Engine 20.10+
- Docker Compose 2.0+

## Quick Start

### 1. Clone and Setup

```bash
# Create project directory
mkdir options-trader
cd options-trader

# Create all necessary files (copy the artifacts provided)
# - main.py
# - config.yaml
# - requirements.txt
# - Dockerfile
# - docker-compose.yml
```

### 2. Configure Interactive Brokers

**In TWS/IB Gateway:**
1. Go to File → Global Configuration → API → Settings
2. Enable "Enable ActiveX and Socket Clients"
3. Add "127.0.0.1" to "Trusted IP Addresses"
4. Set Socket port to 7497 (paper) or 7496 (live)
5. Uncheck "Read-Only API"
6. Click OK and restart TWS/Gateway

### 3. Configure the Service

Edit `config.yaml`:

```yaml
# Set your watchlist
watchlist:
  - SPX
  - SPY
  - QQQ

# Adjust for paper vs live trading
ib_port: 7497  # 7497 = paper, 7496 = live
paper_trading: true  # Always start with paper trading!

# Tune your Greeks thresholds
min_gamma: 0.05
min_delta: 0.20
max_delta: 0.80
```

### 4. Build and Run

```bash
# Build the Docker image
docker-compose build

# Run the service
docker-compose up

# Or run in detached mode
docker-compose up -d

# View logs
docker-compose logs -f
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
docker-compose logs -f options-trader

# Check trade log file
cat logs/trading.log

# Access container shell
docker exec -it options-trading-service bash
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
- Ensure TWS/Gateway is running
- Check API settings are enabled
- Verify correct port (7497/7496)
- Check firewall settings

**Error: "Cannot connect to IB"**
```bash
# Test connection
telnet 127.0.0.1 7497
```

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
- [ib_insync Documentation](https://ib-insync.readthedocs.io/)

### Options Trading
- Greeks definitions and strategies
- 0DTE options risks and rewards
- Position sizing calculators

## License

This is a personal trading tool. Use at your own risk. Not financial advice.

## Disclaimer

This software is for educational purposes. Trading options involves substantial risk of loss. The developer is not responsible for any financial losses incurred from using this software. Always trade responsibly and within your risk tolerance.
