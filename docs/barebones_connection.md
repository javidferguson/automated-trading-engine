# Barebones: just get connected

Strip away Docker, IBC, socat and the strategy. One question at a time.

The Docker image exists to **automate the login** — IBC types the username,
clicks the button, dismisses dialogs. That automation is what struggles with
2FA. Running the app yourself sidesteps all of it: you log in with your own
hands, answer 2FA like a human, and the API port opens.

Your engine does not care which one it talks to. It connects to a TCP port
speaking the IB API. Native app or container is irrelevant to it.

---

## Step 1 — Run IB Gateway natively

Download **IB Gateway** (smaller and lighter than TWS; either works) from
Interactive Brokers, install, and launch it.

At the login screen:
- Select **Paper Trading**
- Enter your **paper** username and password
  (Client Portal → Settings → Account Settings → Paper Trading Account —
  these are *not* your live credentials)
- Complete 2FA when prompted

If this fails with "Invalid username or password", the credentials are wrong.
Fix that here, in the app, before touching any code. Nothing downstream can
work until this screen does.

## Step 2 — Enable the API

**Configure → Settings → API → Settings**

- ✅ Enable ActiveX and Socket Clients
- ❌ Read-Only API  (must be unticked to place orders)
- Trusted IPs: add `127.0.0.1`
- Note the **Socket port**: `4002` for Gateway paper, `7497` for TWS paper

Apply, then leave it running.

## Step 3 — Prove the connection

```bash
python scripts/check_ib_connection.py --port 4002
```

Use `--port 7497` for TWS. The script checks, in order: something is listening,
the API handshake completes, the account is a paper account (`DU`/`DF`), the
server clock responds, and delayed bars arrive.

It places no orders and needs no market-data subscription.

## Step 4 — Run the engine against it

```bash
python -m trading_engine.main --data-mode replay
```

with `connection.host: 127.0.0.1` and `connection.port: 4002` in
`config/orb-gamma-config.yaml`.

---

## Only then, go back to Docker

The container is a convenience for unattended running, not a requirement. Once
the native path works you have a known-good reference, and any container
failure is a container problem rather than an unknown.

Two things to carry over:

- **`TIME_ZONE`** must match the exchange. The image defaults to `Etc/UTC`, and
  the opening-range filter then rejects every bar.
- **`AUTO_RESTART_TIME`** lets the Gateway restart daily without re-doing 2FA.
  Authenticate once, then it keeps itself alive.

## Ports

| Application | Paper | Live |
|---|---|---|
| Native IB Gateway | 4002 | 4001 |
| Native TWS | 7497 | 7496 |
| Docker container (socat relay) | 4004 | 4003 |
| Docker container, from your Mac | 4002 | — |

## Troubleshooting

**Nothing listening** — the app is not running, is not logged in, or the API is
not enabled. Look at the app window.

**Port open, handshake fails** — API not enabled, `127.0.0.1` not trusted, or
the clientId is already in use. Each client needs a distinct clientId; a clash
fails silently.

**Non-paper account** — you logged into the live account. Check the title bar.
