# Architecture

What this engine is, what drives it, and what it can and cannot do.

---

## What it does

An **opening-range breakout on an underlying, confirmed by gamma exposure,
expressed as a 0DTE option bracket**.

It is both a 0DTE options strategy *and* a GEX strategy — those operate at
different stages, which is the thing most easily confused:

| Stage | State | What happens | Role |
|---|---|---|---|
| 1 | `GETTING_OPENING_RANGE` | First 30 minutes of the session → HIGH / LOW levels | Establishes the levels |
| 2 | `MONITORING_BREAKOUT` | A 5-minute candle whose **whole body** clears a level | **The signal** |
| 3 | `ANALYZING_GEX` | Gamma exposure per strike → the peak-|GEX| strike | **The filter** |
| 4 | `PENDING_TRADE_EXECUTION` | Buys a 0DTE call or put as a confirmed bracket | The trade |
| 5 | `MONITORING_POSITION` | Stays attached until the bracket resolves | Exit management |

**The breakout generates the signal. GEX only confirms or vetoes it.**

### The rules, precisely

**Breakout** (`strategy/breakout.py`) — a clean-body break, not a wick:

```
Bullish : close > open  AND  low  > HIGH_LEVEL
Bearish : close < open  AND  high < LOW_LEVEL
```

**GEX** (`strategy/gex.py`):

```
GEX_strike = (gamma_call × OI_call − gamma_put × OI_put) × multiplier
```

Puts enter with the opposite sign because dealers are short calls and long puts
against customer flow. The peak strike is the largest `|GEX|`.

**Decision** (`execution/order_manager.py::decide_trade`) — trade only when the
break heads *toward* the gamma peak:

| Signal | Peak vs spot | Action |
|---|---|---|
| BUY | above | long call |
| SELL | below | long put |
| anything else | — | **no trade** |

A break running *away* from the peak is where dealer hedging is most likely to
fade the move, so it is vetoed.

---

## Configuration

**`config/orb-gamma-config.yaml` is the only config the engine reads.**
Resolution order: `--config` → `ORB_CONFIG_FILE` → the default path.

The asset comes from `instrument.ticker`. **One instrument, not a watchlist** —
the strategy establishes one opening range and monitors one price series.
Running several symbols means several engine instances, each with its own
`connection.client_id` (a clash silently fails to connect).

Switching to an index requires three fields together — `sec_type: "IND"`,
`exchange: "CBOE"` — because the engine builds an `Index` rather than a `Stock`
based on `sec_type`. Strike spacing is *not* one of them: `snap_to_strike` reads
the real chain, so SPY's $1 grid and SPX's $5 both work.

`.env.jf.dev` supplies credentials and the two mode variables. It is gitignored;
`example.env` is the template.

---

## The two mode variables

Deliberately separate. Conflating them is how a test run ends up pointed at an
account you did not intend.

| Variable | Controls | Values |
|---|---|---|
| `TRADING_MODE` | Which **account** the Gateway logs into | `paper` / `live` |
| `DATA_MODE` | Where **bars** come from | `realtime` / `delayed` / `replay` |

`TRADING_MODE` is consumed by the Gateway container, not by this code.

### DATA_MODE

| Mode | Subscription | Can trade | Use |
|---|---|---|---|
| `replay` | none | **No — blocked in `OrderManager`** | Verifying the strategy against a past session |
| `delayed` | none | No in practice — bars are ~15 min late | Watching the state machine against live-shaped data |
| `realtime` | **required** | Yes | The only mode that can trade a live breakout |

`reqRealTimeBars` has no delayed equivalent, which is why `realtime` needs a
paid subscription. Selection happens in `bars/base.py::make_bar_source`; the
state machine consumes an async bar stream and does not know the source.

---

## Safety

- **Paper-account assertion** — `execution/safety.py::assert_paper_account`
  requires every managed account to start with `DU`/`DF`. Called immediately
  after connect **and again immediately before every `placeOrder`**, because a
  reconnect can land somewhere unexpected in between. The port number is not a
  safety guarantee; this is.
- **Human confirmation** — approving requires typing the **ticker symbol**, not
  `y`. The prompt shows the full bracket, total debit, max loss, and IB's
  `whatIfOrder` margin and commission estimate. `require_confirmation: false` is
  rejected at config load; there is no path to an unattended order.
- **Replay cannot trade** — enforced inside `OrderManager`, not only at the call
  site, so a future caller cannot route around it.
- **Marketable limit orders, never market orders.** With delayed data the last
  price may be 15 minutes stale.
- **Journal** — every proposal, decline, submission and status change appends to
  `data/journal/trades_YYYYMMDD.jsonl`.

---

## Known limitations

**Replayed GEX is only point-in-time when `replay.date` is today.** IB removes
expired contracts from the option chain, so a past session's own expiration
cannot be requested and its greeks and open interest are unavailable. For any
earlier date the engine warns loudly, falls forward to the nearest live
expiration, and sets `GEXResult.point_in_time = False`. Stages 1 and 2 stay
faithful either way — it is only the option positioning that reflects today.

Practical consequence: **GEX cannot be backtested from IB.** Setting
`replay.date` to today is the closest thing to a full rehearsal without placing
an order — real bars, real breakout, real current positioning.

**A 0DTE breakout cannot be traded on delayed data.** By the time a 15-minute-old
bar arrives the move is over.

---

## Layout

```
src/trading_engine/
  main.py            CLI entry point
  engine.py          the state machine
  config.py          YAML + env → validated models
  models.py          Bar, Signal, GEXResult, TradeDecision, DataMode
  logging_setup.py   log config + the benign-IB-code filter
  bars/              base (protocol + factory), realtime, delayed, replay
  strategy/          opening_range, breakout, gex
  execution/         safety, confirmation, order_manager, journal
```

`bars/base.py::bar_from_ib` is the single conversion point from IB's `BarData`
(`.date`) / `RealTimeBar` (`.time`, `.open_`) to our `Bar` (`.timestamp`).
Everything entering the strategies goes through it.

---

## Gotchas worth knowing before changing anything

- **`endDateTime` must be timezone-aware.** IB resolves a naive value in a zone
  of its own choosing — measured: naive `10:00` returned the 10:30–10:59 bars,
  aware `10:00 ET` returned 09:30–09:59.
- **`TIME_ZONE` on the Gateway container must match the exchange.** The image
  defaults to `Etc/UTC`, and the opening-range filter then rejects every bar.
- **Option chains: select by `tradingClass`, not exchange.**
  `reqSecDefOptParams` returns one entry per exchange × tradingClass; for SPY
  that is ~20 entries and all but one is a 3-strike mini class.
- **Gateway ports**: 4004 from inside the Docker network (the socat relay), 4002
  from the host. Both are correct — different vantage points.
- **IB error 10091** is a delayed-data substitution notice, not a failure. It is
  demoted to DEBUG in `logging_setup.py`; left at ERROR it fires once per
  contract and buries real errors.
- **The VNC image ships x11vnc only** — there is no noVNC, so `localhost:6080`
  will never work. Use `vnc://localhost:5900`.

---

## Running it

```bash
make gateway-start && make gateway-vnc     # start Gateway, watch it log in
make orb-replay                            # the correctness gate
make orb-delayed                           # live-but-lagged, observation only
make orb-live                              # needs a market data subscription
make test                                  # suite, in the container
```

See `README.md` for setup. `docs/tradingagents-architecture.md` covers the
separate LLM research-desk project.
