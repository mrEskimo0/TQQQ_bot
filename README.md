# tqqq-bot

Automated trading bot that rotates between TQQQ and BIL based on the TQQQ 200-day simple moving average (SMA). Runs once daily after market close via cron.

---

## Strategy

- **RISK_ON** (price >= 200-day SMA): hold TQQQ
- **RISK_OFF** (price < 200-day SMA): hold BIL

Rotations are two-step because market sell orders settle before the cash is available to redeploy:
1. Run 1: sell the outgoing position (TQQQ or BIL)
2. Run 2 (next day): buy the incoming position with the settled cash

---

## Architecture

```
main.py          Entry point, CLI commands, wires config → modules
config.py        All settings via pydantic-settings (reads from .env)
bot/
  auth.py        One-time OAuth flow for Schwab API access
  schwab.py      Thin wrapper around schwab-py (price history, orders, account state)
  strategy.py    Computes 200-day SMA and returns RISK_ON / RISK_OFF regime
  trader.py      Core trading loop — reads account, evaluates regime, places orders
  state.py       SQLite-backed persistence (position and trade history)
  logger.py      Configures console + file logging
  notifier.py    Optional Discord webhook notifications
```

---

## Configuration

All settings are read from a `.env` file in the project root.

| Variable | Required | Default | Description |
|---|---|---|---|
| `SCHWAB_APP_KEY` | Yes | — | Schwab developer app key |
| `SCHWAB_APP_SECRET` | Yes | — | Schwab developer app secret |
| `SCHWAB_ACCOUNT_HASH` | Yes | — | Schwab account hash |
| `SCHWAB_TOKEN_PATH` | No | `/var/lib/tqqq-bot/schwab_token.json` | OAuth token file path |
| `SCHWAB_CALLBACK_URL` | No | `https://127.0.0.1` | OAuth redirect URL |
| `DB_PATH` | No | `/var/lib/tqqq-bot/tqqq.db` | SQLite database path |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `LOG_PATH` | No | `/var/log/tqqq-bot/bot.log` | Log file path |
| `DRY_RUN` | No | `False` | Log intended orders without placing them |
| `SMA_PERIOD` | No | `200` | SMA lookback period in trading days |
| `TICKER` | No | `TQQQ` | Risk-on ticker |
| `SAFE_TICKER` | No | `BIL` | Risk-off ticker |
| `DISCORD_WEBHOOK_URL` | No | — | Discord webhook for trade and heartbeat notifications |

Every run posts exactly one Discord message: a trade confirmation (BUY/SELL), or a heartbeat explaining why nothing was traded (fully invested, no cash, below SMA). Failed runs post the traceback. Messages also show the token age and warn once it reaches 6 days. Notifications are skipped if `DISCORD_WEBHOOK_URL` is unset.

---

## CLI Commands

```bash
python main.py run          # check regime and trade (called by cron)
python main.py init-auth    # one-time OAuth setup (requires a browser)
python main.py status       # live position, cash, and current regime
python main.py history      # last 20 trades from the database
```

---

## OAuth Token

The Schwab API uses OAuth 2.0. The access token expires every 30 minutes and is automatically refreshed by schwab-py on each API call. The refresh token **hard-expires 7 days after `init-auth`** — refreshing does not extend it. Re-run `init-auth` and copy the new token to the server at least once a week; the Discord notifications warn when the token is 6+ days old.

The token is stored as a JSON file at `SCHWAB_TOKEN_PATH`. It must be generated once locally (on a machine with a browser) via `python main.py init-auth`, then copied to the server.

---

## State / Database

SQLite database at `DB_PATH` with two tables:

- **position** — single-row table tracking current shares, average cost, and total capital invested
- **trades** — append-only log of every buy/sell with timestamp, price, shares, and SMA value at time of trade

The database and its parent directory are created automatically on first run.

---

## Git

`.gitignore` excludes all `*.json` files to prevent the OAuth token from being committed. If you need to add a `.json` file to the repo, force-add it explicitly:

```bash
git add -f filename.json
```

---

## Deployment

Schedule with cron to run Monday–Friday at 4:45 PM ET (20:45 UTC, or 21:45 UTC Nov–Mar for EST):

sudo mkdir -p /var/lib/tqqq-bot /var/log/tqqq-bot
sudo chown $USER:$USER /var/lib/tqqq-bot /var/log/tqqq-bot

```bash
35 9 * * 1-5 /root/tqqq_bot/venv/bin/python3 /root/tqqq_bot/main.py run >> /var/log/tqqq-bot/bot.log 2>&1
```

Expected server layout:
```
/opt/tqqq-bot/          project root
/opt/tqqq-bot/venv/     Python virtual environment
/var/lib/tqqq-bot/      token file and SQLite database
/var/log/tqqq-bot/      log file
```
