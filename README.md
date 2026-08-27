# Automated Trading Engine

A local, Dockerized trading engine for Interactive Brokers. Two strategies live here:

| Strategy | Status | What it does |
|---|---|---|
| **ORB + GEX** (`trading_engine`) | Primary | 30-minute opening range → clean-body 5-minute breakout → gamma-exposure confirmation → 0DTE option bracket order, human-confirmed. |
| **0DTE options scanner** (`trading_engine.strategies.options_0dte`) | Parked | Scans a watchlist for 0DTE options, filters on Greeks, ranks by a weighted score. Kept working, not actively developed. |

Everything runs against an IB **paper** account. Every order requires you to type
the ticker symbol to confirm. There is no configuration flag that turns that off.

---

## Architecture

Two containers on a `trading-network` bridge:

```
┌─────────────────────────────┐
│  ajj-ib-gateway             │   ghcr.io/gnzsnz/ib-gateway
│  IB Gateway + IBC + socat   │   handles login and the IB connection
│  VNC on :5900               │
└──────────────┬──────────────┘
               │  docker network
┌──────────────▼──────────────┐
│  ajj-options-trader         │   your Python code (ib_async)
│  trading_engine             │
└─────────────────────────────┘
```

### Ports — read this before changing them

The Gateway image binds IB Gateway to **container-localhost** on 4001 (live) /
4002 (paper). Those are unreachable from outside the container, so the image runs
**socat** relaying **4003 (live) / 4004 (paper)**. The right port depends on where
you connect *from*:

| From | Paper port |
|---|---|
| The trader container, over the docker network | **4004** |
| Your Mac (`127.0.0.1`) — compose maps host 4002 → container 4004 | **4002** |

The app runs inside the trader container, so its config says `4004`. Both numbers
are correct; they describe different vantage points.

---

## Setup

### 1. Credentials

```bash
make setup
```

Creates `.env.jf.dev` from `example.env` and opens it. Fill in `IB_USERNAME`,
`IB_PASSWORD`, and leave `TRADING_MODE=paper`.

`.env.jf.dev` is gitignored and is what `docker-compose` actually reads. Without
it, every `make` target fails.

### 2. Two environment variables that are easy to confuse

| Variable | Controls | Values |
|---|---|---|
| `TRADING_MODE` | Which **account** the Gateway logs into | `paper` / `live` |
| `DATA_MODE` | Where **bars** come from | `realtime` / `delayed` / `replay` |

They are deliberately separate. Conflating them is how a test run ends up
pointed at an account you did not intend.

### 3. Market data

`DATA_MODE` determines what you can actually do:

| Mode | Subscription | Can trade? | Use it for |
|---|---|---|---|
| `replay` | none | **No** | Verifying the strategy against a past session. The default. |
| `delayed` | none | No (bars are ~15 min late) | Watching the state machine against live-shaped data. |
| `realtime` | **required** | Yes | The only mode that can trade a live breakout. |

A 0DTE opening-range breakout cannot be traded on 15-minute-delayed bars — the
move is over by the time the bar arrives. Real-time mode needs an IB market-data
subscription (a US equities/index bundle plus OPRA options top-of-book). Check
current pricing in IB Account Management; paper accounts inherit the live
account's subscriptions.

---

## Running

```bash
make gateway-start
```

Wait ~60 seconds, then confirm it logged in:

```bash
make gateway-check
```

```bash
make gateway-vnc
```

That opens the Gateway UI at `localhost:5900` so you can watch the login.

### The ORB + GEX engine

```bash
make orb-replay
```

Replays a past session end to end. No subscription, no open market, no orders —
this is how you verify the strategy works.

```bash
make orb-delayed
```

```bash
make orb-live
```

Real-time mode. Requires a market-data subscription. Can place orders (paper
account, confirmation required).

Set the session to replay via `data.replay_date` in `config/orb-gamma-config.yaml`,
or `--replay-date 2026-08-26` on the command line.

### The parked options scanner

```bash
make trades-dev
```

Drops you into a shell in the trader container, then:

```bash
python -m trading_engine.strategies.options_0dte.scanner
```

### Tests

```bash
make test-local
```

---

## Configuration

| File | Purpose |
|---|---|
| `.env.jf.dev` | Credentials, `TRADING_MODE`, `DATA_MODE`. Gitignored. |
| `config/orb-gamma-config.yaml` | ORB + GEX engine: instrument, opening range, breakout, GEX, bracket levels. |
| `config/options-trader-config.yaml` | The parked options scanner: watchlist, Greeks thresholds. |

---

## Safety

- **Paper-account assertion.** `ib.managedAccounts()` must return only accounts
  prefixed `DU`/`DF`. Checked immediately after connecting *and* again immediately
  before every `placeOrder` — a reconnect can land somewhere unexpected in
  between. The port number is not a safety guarantee; this is.
- **Human confirmation.** Approving an order requires typing the ticker symbol,
  not `y`. The prompt shows the full bracket, the total debit, the max loss, and
  IB's `whatIfOrder` margin and commission estimate.
- **Replay cannot trade.** Enforced inside `OrderManager`, not just at the call
  site, so a future caller cannot route around it.
- **Journal.** Every proposal, decline, submission, and order-status change is
  appended to `data/journal/trades_YYYYMMDD.jsonl`.

---

## Useful commands

```bash
make help
```

| Command | Does |
|---|---|
| `make gateway-logs` | Follow Gateway logs |
| `make trader-shell` | Shell into the trading container |
| `make debug-gateway` | Container status, recent logs, port bindings |
| `make config-check` | Validate config files and report the resolved modes |
| `make test-connection` | Ping + port check from trader to gateway |
| `make backup-signals` | Copy signal CSVs into `backups/<date>/` |
| `make stop` / `make down` | Stop / remove containers |

---

## Documentation

- [`docs/ib_gateway_setup_guide.md`](docs/ib_gateway_setup_guide.md) — detailed Gateway bring-up
- [`docs/quick_reference_card.md`](docs/quick_reference_card.md) — port and command reference
- [`docs/ib_async_migration.md`](docs/ib_async_migration.md) — why `ib_async` over `ib_insync`
- [`makefile_usage_guide.md`](makefile_usage_guide.md) — Makefile walkthrough

---

## Disclaimer

Personal software, for educational use. Trading options involves substantial risk
of loss. Not financial advice. Use at your own risk.
