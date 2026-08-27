# TradingAgents: architecture and design decisions

Design for a multi-agent LLM research desk, modeled on the TradingAgents paper
(arXiv 2412.20138), intended to live in **a separate repository** from this
ORB+GEX options engine.

This document exists so the reasoning survives the gap between projects. Most of
it is *why*, not *what* — the what is recoverable, the why is not.

**Status:** designed, not built.

---

## Scope

- **Equities and ETFs first.** Daily bars, BUY/SELL/HOLD on shares. The options
  strategy in this repo stays separate.
- **Local models by default**, hosted API for the one or two nodes where
  reasoning quality actually moves the outcome.
- **Every order requires human confirmation.** Paper account only.
- Driven by a stated **portfolio intent** rather than a watchlist.

---

## 0. The decision everything else follows from

**Split into two processes that communicate through a file, never a shared
event loop.**

```
[ decide ]  agents + LLM + free data  →  proposal.json  →  [ execute ]  human gate + ib_async
 no IB connection, no ib_async import                       no LLM, no network beyond IB
```

This solves five problems at once:

1. **Avoids the event-loop tangle.** `ib_async` installs its own loop policy and
   already needs `nest_asyncio`. Mixing that with a dozen concurrent LLM HTTP
   calls is a debugging tarpit. Separate processes, separate loops.
2. **The confirmation gate becomes a file you read**, not an `input()` racing a
   socket keepalive.
3. **Local model slowness stops mattering.** `decide` runs after the close;
   `execute` runs when you are at the keyboard.
4. **Replay is free.** `decide` in replay mode emits the same artifact type.
5. **IB can be down** while you research.

Everything below assumes this split.

---

## 1. Framework: an explicit pipeline, not LangGraph

Use a plain `async def run_decision(...)`. Not LangGraph, and not a home-rolled
graph engine either — that is the trap where you spend a week building a worse
LangGraph.

The graph is **static**: four parallel nodes, two counter-bounded loops, six
sequential nodes. That is `asyncio.gather` plus two `for` loops, roughly 200
lines.

| Constraint | LangGraph | Explicit pipeline |
|---|---|---|
| Weak local tool-calling | Its main value-add (`ToolNode`, ReAct loops) is exactly what must not be used | No tool-calling at all (§2) |
| Per-node model routing | A dict inside node functions anyway | Same dict, no framework |
| Inspect/replay state | Checkpointer blobs keyed by thread_id; replay means "resume a graph", not "re-run 2024-03-15 with a different model" | Own `DecisionState` JSONL is a better substrate for the thing actually wanted |
| Explainability | Wants LangSmith to be pleasant | Reports are typed objects in your own schema |

It also drags ~40 transitive dependencies into a container that would otherwise
have a handful.

**The hedge:** give every node the LangGraph-compatible signature

```python
async def node(state: DecisionState, ctx: NodeContext) -> dict[str, Any]:  # partial-state patch
```

Adopting LangGraph later is then a wrapper per node, not a rewrite. Free
insurance.

---

## 2. The rule that makes weak local models usable

**No tool-calling, ever.**

The paper's "~20 tool calls" are not agentic decisions — they are
`get_price_history`, `get_news`, `get_financials`. There is no judgment in
choosing them.

So: **deterministic prefetch, then constrained summarization.**

1. `build_market_snapshot(symbol, as_of)` fetches everything from Python, with
   retries and caching. No LLM involved.
2. Every LLM node receives rendered pre-computed facts and returns **JSON
   constrained by a Pydantic schema** — Ollama's `format=<json_schema>`,
   Anthropic's tool-schema forcing.
3. **All arithmetic happens in `indicators.py`.** RSI, ATR, drawdown, YoY
   growth, position sizing — never in a prompt.

An 8B model will confidently produce a wrong RSI. It is genuinely good at "RSI
is 71 and price is at the upper Bollinger band — that's stretched." This single
rule is the difference between local models being usable and useless here.

---

## 3. Nodes

▪ = no LLM, ● = LLM

```
▪ 0  prefetch            build_market_snapshot()
▪ 1  memory_recall       past reflections for (symbol, regime)
● 2  market_analyst      ─┐
● 3  news_analyst         ├─ asyncio.gather, 4-way parallel
● 4  social_analyst       │
● 5  fundamentals_analyst─┘
   ── research debate, rounds 1..N ──
● 6  bull_researcher
● 7  bear_researcher
● 8  research_facilitator   (also emits should_continue)
● 9  trader                 -> TraderProposal (BUY/SELL/HOLD + conviction)
   ── risk debate, rounds 1..M ──
● 10 risky_debater
● 11 neutral_debater
● 12 safe_debater
● 13 fund_manager           -> FinalDecision (approve / adjust / veto)
▪ 14 compliance             deterministic veto vs PortfolioIntent
▪ 15 persist                write DecisionState + proposal.json
```

14 LLM calls at N=M=1. Matches the paper's ~11–14.

---

## 4. State schema

`models/state.py`, Pydantic v2. Abbreviated:

```python
class Evidence(BaseModel):
    source: str; url: str | None; as_of: datetime; excerpt: str  # <=300 chars

class AnalystReport(BaseModel):
    kind: Literal["market","news","social","fundamentals"]
    stance: Literal["bullish","bearish","neutral"]
    confidence: float = Field(ge=0, le=1)
    summary: str                      # <=200 words
    key_points: list[str]             # 3-6
    evidence: list[Evidence]
    data_gaps: list[str]              # what it could NOT see -- feeds calibration
    parse_failed: bool = False

class DebateTurn(BaseModel):
    round: int; speaker: str; claim: str
    supporting_report_kinds: list[str]
    rebuts: str | None
    new_information: bool             # facilitator-verified; drives the novelty stop

class DebateTranscript(BaseModel):
    turns: list[DebateTurn] = []
    rounds_completed: int = 0
    stop_reason: Literal["max_rounds","converged","no_novelty","budget","error"] | None = None

class ResearchVerdict(BaseModel):
    winner: Literal["bull","bear","tie"]
    thesis: str
    strongest_counterargument: str    # dissent is REQUIRED, never dropped
    confidence: float

class TraderProposal(BaseModel):
    action: Literal["BUY","SELL","HOLD"]
    conviction: float = Field(ge=0, le=1)
    target_weight_pct: float          # desired % of equity, not share count
    horizon_days: int
    rationale: str
    invalidation: str                 # "what would prove this wrong"
    intent_alignment: str             # which theme/gap this closes

class FinalDecision(BaseModel):
    schema_version: int = 1
    action: Literal["BUY","SELL","HOLD"]
    symbol: str
    conviction: float
    target_weight_pct: float
    order_type: Literal["LMT","MKT"] = "LMT"
    limit_offset_bps: int = 10
    stop_loss_pct: float | None
    take_profit_pct: float | None
    horizon_days: int
    rationale: str
    dissent: str                      # preserved bear/safe case
    invalidation: str
    expires_at: datetime              # a stale proposal cannot be executed
    fund_manager_adjustment: str | None

class DecisionState(BaseModel):
    schema_version: int = 1
    run_id: str; symbol: str
    as_of: date                       # decision date -- the replay anchor
    created_at: datetime
    mode: Literal["live","replay","replay_llm"]
    config_hash: str; prompt_pack_version: str
    intent: PortfolioIntent
    portfolio: PortfolioSnapshot
    snapshot: MarketSnapshot
    memory_hits: list[MemoryHit] = []
    analyst_reports: dict[str, AnalystReport] = {}
    research_debate: DebateTranscript = DebateTranscript()
    research_verdict: ResearchVerdict | None = None
    trader_proposal: TraderProposal | None = None
    risk_debate: DebateTranscript = DebateTranscript()
    final_decision: FinalDecision | None = None
    violations: list[Violation] = []
    llm_calls: list[LLMCallRecord] = []   # prompt hash, model+digest, RAW response, tokens, ms, $
    errors: list[NodeError] = []
```

Two details that pay for themselves:

- **`LLMCallRecord` stores the raw response**, enabling `mode="replay_llm"`:
  re-run the pipeline against recorded outputs to test downstream changes at
  zero cost and zero latency. Use this constantly during development.
- **`dissent` and `invalidation` are required fields** on `FinalDecision`. This
  is where the paper's explainability claim actually cashes out — both surface
  in the confirmation prompt.

---

## 5. Debate termination

Four conditions. **Budget always wins.**

1. `rounds_completed >= cfg.max_rounds` (default **1**, not 2 — start cheap)
2. Facilitator returns `converged=True` with a reason
3. **Novelty guard**: every turn this round has `new_information=False`, or a
   speaker's claim has >0.85 Jaccard overlap with its previous round. Local
   models loop and restate; this is not optional.
4. `budget.exhausted()`

Conditions 1 and 4 are hard caps enforced in Python. Never let the model alone
decide when to stop.

**Failure direction is always HOLD.** Any node error, budget exhaustion, or
schema-parse failure after one repair turn →
`FinalDecision(action="HOLD", rationale="degraded: <reason>")`. Never fail
toward a trade.

---

## 6. Model routing

`config/models.yaml`:

```yaml
providers:
  ollama:    {base_url: "${OLLAMA_BASE_URL}", timeout_s: 300}
  anthropic: {api_key_env: ANTHROPIC_API_KEY}
profiles:
  quick:       {provider: ollama,    model: "qwen3:8b",   temperature: 0.3, num_ctx: 8192}
  deep_local:  {provider: ollama,    model: "qwen3:14b",  temperature: 0.5, num_ctx: 16384}
  deep_hosted: {provider: anthropic, model: "<model-id>", temperature: 0.5, max_tokens: 2000}
nodes:
  market_analyst: quick
  news_analyst: quick
  social_analyst: quick
  fundamentals_analyst: quick
  bull_researcher: quick
  bear_researcher: quick
  research_facilitator: deep_local
  trader: deep_local
  risky_debater: quick
  neutral_debater: quick
  safe_debater: quick
  fund_manager: deep_hosted      # the one node worth paying for
  reflection: deep_local
presets:
  all_local:  {"*": quick}
  all_hosted: {"*": deep_hosted}   # for eval / strategy development
```

`structured()` handles: schema-constrained decode → validate → on failure, one
repair turn with the validation error appended → on second failure, return
`schema.degraded()` with `parse_failed=True`. A degraded analyst report beats a
crashed 8-minute run.

---

## 7. Data sources

No paid market-data subscription assumed. `indicators.py` computes everything
numeric; providers only fetch.

| Analyst | Source | Key | Notes |
|---|---|---|---|
| Market | **yfinance** daily OHLCV; **IB `reqHistoricalData`** fallback | none | yfinance is an unofficial scrape and *will* break — keep it behind a `Provider` protocol and record which source was used |
| News | **Finnhub** `/company-news` | free, 60/min | Date-rangeable, which is what replay needs. Yahoo RSS as no-key fallback |
| Social | **Reddit / PRAW** | free script app | **Ship disabled by default** — see below |
| Fundamentals | **SEC EDGAR** XBRL `companyfacts` + **Finnhub** `/stock/metric` | EDGAR needs no key but **requires a `User-Agent: Name email` header** | EDGAR is the best free source and genuinely point-in-time |
| Macro (shared) | **FRED**: VIXCLS, DGS10, DGS2, T10Y2Y, CPIAUCSL | free | Regime context, and the regime tag for memory retrieval |

Computed in Python: SMA 20/50/200, EMA 12/26, RSI-14, MACD, ATR-14, Bollinger
%B, realized vol, volume z-score, 52-week percentile, max drawdown, beta vs SPY.

**Point-in-time discipline.** Every provider method takes `as_of`. Cache key =
`sha256(provider, method, sorted(kwargs), as_of)`. **In `mode="replay"` the
cache is the only permitted source** — HTTP is hard-disabled and any provider
with `supports_point_in_time=False` raises. Look-ahead bias is the number one
way agentic backtests produce fictional Sharpe ratios.

**Why the social analyst ships off:** retail social sentiment is the noisiest and
most deliberately manipulated input in the stack, and the one most likely to
make a small model enthusiastic about the wrong thing. Turn it on only if the
ablation shows lift.

---

## 8. Portfolio intent

`config/portfolio-intent.yaml` — objective (horizon, benchmark, prose), `risk:`
(per_trade_risk_pct, default_stop_pct, max_position_pct, max_sector_pct,
min_cash_pct, max_gross_exposure_pct, max_positions, min_trade_usd,
max_order_shares), `universe:` (include/exclude/allow_shorts), `themes:` (name,
target_weight_pct, conviction, thesis, exemplars), optional `targets:` with
bands, free-text `constraints:`, and `cadence:` (max_decisions_per_day,
proposal_ttl_hours).

**Consumed through four distinct channels, deliberately not one:**

1. **Deterministic pre-filter (no LLM).** Universe minus exclusions minus
   earnings blackout minus at-max-positions → today's candidates, computed
   before any model runs. Saves money and removes a class of hallucination.
2. **Drift table (no LLM).** `intent_engine.compute_gaps()` → per symbol and
   theme: current weight, target, band, gap in % and USD. The Trader node gets
   this as a table. **Its job is choosing which gap to close, not inventing
   allocations.** This is the biggest reliability win — it converts an
   open-ended "how much should we buy" into a bounded "close this gap or don't",
   which small models handle far better.
3. **Prompt context (LLM).** Objective description, theme theses and free-text
   constraints go into the **Trader and Fund Manager system prompts only**.
4. **Hard veto (no LLM).** Everything under `risk:` is enforced by
   `compliance.py` *after* sizing.

**Analysts are intentionally intent-blind.** Do not tell the fundamentals
analyst "we are bullish on AI infrastructure" before it reads the 10-K. The
entire value of a bear researcher evaporates if every upstream report was primed
with your thesis. Intent enters at the Trader node and no earlier. This deserves
a code comment so nobody "helpfully" fixes it later.

---

## 9. Decision → broker

Three layers, so the first two run with no broker at all:

```
FinalDecision (broker-agnostic) → OrderPlan (sizing + compliance) → ib_async Contract/Order
```

**Sizing** — deterministic, minimum of four caps:

```
conviction_w    = target_weight_pct * conviction
cap_position    = intent.risk.max_position_pct
cap_risk        = intent.risk.per_trade_risk_pct / stop_dist
target_w        = min(conviction_w, cap_position, cap_risk)
delta_notional  = equity * target_w/100 - pf.position_value(symbol)
```

Then reject dust (`< min_trade_usd`), clamp to `max_order_shares` and 90% of
buying power.

**Compliance** — post-trade-state checks against max_position_pct,
max_sector_pct, min_cash_pct, max_gross_exposure, max_positions, universe
membership, earnings blackout, max_decisions_per_day, ADV participation.
**Any violation blocks the order regardless of what the fund manager decided.**
Two-key system: LLM proposes, Python vetoes. This is where trust comes from.

**Execution** — three rules carried from the options engine:

- **`assert_paper_account()` after connect *and* again immediately before every
  `placeOrder`.** The port is not a safety guarantee; a socat or env-var mistake
  can point a "paper" port at live. `managedAccounts()` is the real gate.
- **`ib.whatIfOrder()` before the human sees the prompt** — free, places
  nothing, returns margin impact and commission. Put those numbers *in* the
  confirmation.
- **Marketable `LimitOrder`, never `MarketOrder`.** With delayed data you are
  looking at a 15-minute-old price.

**Confirmation** requires typing the **ticker symbol**, not `y`. A yes/no prompt
is answered by muscle memory. Show the dissent, the invalidation condition, and
the whatIf numbers. There is deliberately no config flag to disable the gate.

---

## 10. Ollama on macOS: run it natively

**Do not containerize Ollama on macOS.** Docker Desktop runs a Linux VM with no
Metal passthrough, so a containerized Ollama is CPU-only inside a VM with a
fraction of your RAM — roughly **5–15× slower** than native with Metal. A
14-call pipeline that takes 4 minutes natively takes 40+ containerized. That is
the difference between a tool you use and one you abandon.

The app container reaches host Ollama via
`OLLAMA_BASE_URL=http://host.docker.internal:11434` plus
`extra_hosts: ["host.docker.internal:host-gateway"]` for Linux portability.

**The gotcha that costs an hour:** Ollama binds `127.0.0.1:11434` by default,
which a container cannot reach. Set `OLLAMA_HOST=0.0.0.0:11434` on the host
daemon. Add a check target that curls `/api/tags` **from inside the container**
so this is diagnosed in seconds rather than via stack traces.

Still ship a containerized Ollama behind a **compose profile** so the same file
works on a Linux/NVIDIA box and in CI. Set `OLLAMA_KEEP_ALIVE=30m` (otherwise
the model unloads between nodes and you pay a multi-second reload per call) and
`OLLAMA_NUM_PARALLEL=4` (otherwise the four-analyst `asyncio.gather` silently
serializes).

---

## 11. Evaluation: the go/no-go

The purpose is **not** to prove alpha — on three months you cannot. It is to
detect disqualifying badness, check calibration, and answer one question:
**does the multi-agent structure beat a single LLM call?**

| # | Baseline | Why |
|---|---|---|
| B0 | Buy-and-hold SPY | The bar you must clear to justify existing |
| B1 | Always HOLD | Isolates whether trading at all helps |
| B2 | Random, turnover-matched, **200 seeds** | Gives a null *distribution*, not a point. Without this you cannot tell skill from noise |
| B3 | Deterministic rule (50/200 SMA + RSI) | The cheapest thing that could work |
| **B4** | **Single LLM call**, same snapshot, one prompt | **The one that matters** |
| A | Full 14-node pipeline | |

**If A does not beat B4 by a margin outside B2's noise band, the multi-agent
layer is not earning its 14× cost — ship B4.** Build the harness so this
comparison is a one-line config change, and be genuinely willing to act on the
answer. Most multi-agent systems fail this test.

Scoring: forward returns at 1/5/20 days; hit rate; **information coefficient**
(Spearman of stated conviction vs forward return — if conviction does not
correlate with outcomes, the model's confidence is decorative); turnover; equity
curve using the real sizing and compliance code, not idealized fills. **Report
residual return vs SPY**, not raw, or you will conclude the agents are geniuses
in an up market. Block bootstrap (5-day blocks) for confidence intervals. A
**calibration plot** (realized hit rate bucketed by stated confidence) is cheap
and usually the most damning diagnostic.

**Shadow mode is the primary tool**: run `decide` daily on live data with
`execute` never called, journal everything, accumulate 60–90 sessions.
Out-of-sample and leakage-free — worth more than any replay.

Ablations, one flag each: `social.enabled=false`, `research_rounds=0`,
`risk_rounds=0`, `memory.enabled=false`, `trader→deep_hosted`, `all_local` vs
`all_hosted`.

---

## 12. Cost and latency

| Config | Per symbol per decision |
|---|---|
| Native Ollama, 8B q4, parallel=4 | **~3–8 min**, $0 |
| Containerized Ollama on macOS | 20–60+ min — not viable |
| Hybrid (fund_manager hosted only) | ~3–8 min + **~$0.03** (~$40/yr at 5 symbols daily) |
| All 14 calls hosted | seconds + **~$0.40** (~$500/yr daily; a 90-day × 5-symbol replay ≈ $180) |

*Order-of-magnitude. Re-derive against current per-Mtok rates. Prompt caching on
the repeated system prompts cuts input cost materially — wire it on day one.*

Mitigations by leverage: **run after the close** (latency stops mattering, and
it is free); cache `AnalystReport` per `(symbol, as_of, prompt_version,
model_digest)`; use `mode="replay_llm"` for downstream development; enforce
`RunBudget(max_llm_calls=20, max_wall_s=900, max_usd=0.50)`; default both debate
rounds to 1; run symbols sequentially overnight (parallel symbols thrash
Ollama's model cache).

---

## 13. Build order

| Stage | Deliverable | Gate |
|---|---|---|
| 0 | pyproject/uv, `src/` layout | imports clean |
| 1 | `llm/` router + Ollama structured output + `models.yaml` | smoke test returns a valid Pydantic object |
| 2 | providers + cache + limiter + `indicators.py` + `snapshot.py` | `snapshot SYMBOL=SPY` prints a full `MarketSnapshot`, no LLM |
| **3** | **Vertical slice: market_analyst → trader → `FinalDecision` → proposal.json** | **A sane, schema-valid decision end to end. Highest-value de-risking step** |
| 4 | 3 remaining analysts + bull/bear/facilitator + termination | Debate stops for the right reason every time |
| 5 | Risk trio + fund_manager + `deep_hosted` routing | Full 14-node run under budget |
| 6 | `PortfolioIntent` + intent_engine + sizing + compliance + journal | `OrderPlan` produced, zero IB contact |
| 7 | `execution/` — safety, whatIf, limit orders, confirmation gate | One paper trade, human-confirmed, `DU`-asserted |
| 8 | `eval/` — replay, B0–B4, scoring, calibration | **The B4 comparison. Go/no-go** |
| 9 | `memory.py` + `reflect.py` | Reflections retrieved and measurably change decisions |

Stage 3 first, always. If market-analyst → trader → proposal does not produce
something sane, more agents will not fix it.

---

## 14. Carried forward from the ORB+GEX engine

Worth lifting rather than rewriting — each cost real debugging:

| Module | Why |
|---|---|
| `execution/safety.py` | `assert_paper_account` — the DU/DF gate, called twice |
| `execution/confirmation.py` | Type-the-ticker gate, whatIf numbers in the prompt |
| `execution/journal.py` | Append-only JSONL that never raises |
| `logging_setup.py` | Benign-IB-code filter — otherwise 10091 fires once per contract at ERROR and buries real failures |

**IB connection lessons, all learned the hard way:**

- **`endDateTime` must be timezone-aware.** A naive value is resolved by IB in a
  zone of its own choosing — measured: naive `10:00` returned the 10:30–10:59
  bars, aware `10:00 ET` returned 09:30–09:59.
- **`TIME_ZONE` on the Gateway container must match the exchange.** The image
  defaults to `Etc/UTC` and IB then stamps bars in UTC.
- **Option chains: select by `tradingClass`, not exchange.**
  `reqSecDefOptParams` returns one entry per exchange × tradingClass; for SPY
  that is ~20 entries and all but one are a 3-strike mini class.
- **`reqMarketDataType(3)`** gives delayed greeks with no subscription. Error
  10091 is a substitution notice, not a failure.
- **Paper accounts need their own credentials**, and the paper account must be
  *created* in Client Portal → Account Configuration first. Client Portal will
  accept live credentials while the Gateway rejects them.

---

## 15. Risks and things that are bad ideas

1. **Look-ahead bias will silently invalidate the backtest.** Providers that
   cannot do point-in-time must **raise** in replay, not degrade quietly.
2. **Multi-agent debate manufactures confident consensus.** Three agents
   agreeing is not three pieces of evidence — they read the same reports. B4 is
   the only defense.
3. **Never let an LLM do arithmetic.**
4. **Do not build a generic graph engine.** A fixed 14-node pipeline is a
   function.
5. **Do not vendor a vector DB.** SQLite + numpy dot product over a few thousand
   reflection rows is exact, instant, and one fewer container.
6. **Do not schedule `execute`.** `decide` on a cron is fine; `execute` must be
   human-initiated, always.
7. **Scope risk.** 14 nodes × prompts × 6 providers is a lot of surface. Build
   the Stage 3 vertical slice before anything else.
8. **GEX cannot be backtested from IB** — expired contracts are removed from the
   chain, so historical option greeks and open interest are unavailable. If
   options ever enter the agent path, the evaluation harness needs a different
   data source.
9. Personal software on a paper account. Keep the human gate even after Stage 8
   gives reason to trust it.
