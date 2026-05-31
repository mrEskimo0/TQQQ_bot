#!/usr/bin/env python3
"""
tqqq-bot — entry point.

Usage:
  python main.py run          # check regime & trade (called by cron)
  python main.py init-auth    # one-time OAuth setup (run locally w/ browser)
  python main.py status       # live position from Schwab + regime
  python main.py history      # recent trade history
"""
import argparse

from config import config
from bot.logger import setup_logger
from bot.state import StateDB

logger = setup_logger("tqqq_bot", config.LOG_PATH, config.LOG_LEVEL)


def cmd_run(_args):
    from bot.trader import run
    from bot.notifier import send_run_result
    db = StateDB(config.DB_PATH)
    try:
        run(config, db)
        send_run_result(success=True, cfg=config)
    except Exception as exc:
        logger.exception("Unhandled error during run")
        send_run_result(success=False, cfg=config, exc=exc)
        raise


def cmd_init_auth(_args):
    from bot.auth import init_auth
    init_auth(
        token_path=config.SCHWAB_TOKEN_PATH,
        app_key=config.SCHWAB_APP_KEY,
        app_secret=config.SCHWAB_APP_SECRET,
        callback_url=config.SCHWAB_CALLBACK_URL,
    )


def cmd_status(_args):
    from bot import schwab as sc
    from bot.strategy import evaluate

    client = sc.get_client(config.SCHWAB_TOKEN_PATH, config.SCHWAB_APP_KEY, config.SCHWAB_APP_SECRET)
    account = sc.get_account_state(client, config.SCHWAB_ACCOUNT_HASH)
    tqqq_shares = account["positions"].get(config.TICKER, 0)
    bil_shares = account["positions"].get(config.SAFE_TICKER, 0)
    tqqq_avg = account["avg_costs"].get(config.TICKER, 0.0)
    cash = account["cash"]

    candles = sc.get_price_history(client, config.TICKER, num_days=config.SMA_PERIOD + 5)
    result = evaluate(candles, sma_period=config.SMA_PERIOD)

    db = StateDB(config.DB_PATH)
    pos = db.get_position()

    print(f"\n{'─'*50}")
    print(f"  TQQQ Bot Status")
    print(f"{'─'*50}")
    print(f"  Regime            : {result.regime.value}")
    print(f"  {config.TICKER} price        : ${result.current_price:.2f}")
    print(f"  200-day SMA       : ${result.sma_200:.2f}")
    print(f"{'─'*50}")
    print(f"  {config.TICKER} shares     : {tqqq_shares}")
    if tqqq_shares > 0:
        print(f"  Avg cost / share  : ${tqqq_avg:.2f}")
        print(f"  Cost basis        : ${tqqq_shares * tqqq_avg:.2f}")
        print(f"  Market value      : ${tqqq_shares * result.current_price:.2f}")
    print(f"  {config.SAFE_TICKER} shares      : {bil_shares}")
    print(f"  Cash available    : ${cash:.2f}")
    if pos.last_updated:
        print(f"  Last DB update    : {pos.last_updated}")
    print(f"{'─'*50}\n")


def cmd_history(_args):
    db = StateDB(config.DB_PATH)
    trades = db.get_trades(limit=20)
    if not trades:
        print("No trades recorded yet.")
        return
    print(f"\n{'─'*84}")
    print(f"  {'Timestamp':<26}  {'Action':<9}  {'Shares':>6}  {'Price':>8}  {'Value':>10}  {'SMA200':>8}")
    print(f"{'─'*84}")
    for t in trades:
        print(
            f"  {t['timestamp']:<26}  {t['action']:<9}  {t['shares']:>6}  "
            f"${t['price']:>7.2f}  ${t['total_value']:>9.2f}  ${t['sma_200']:>7.2f}"
        )
    print(f"{'─'*84}\n")


def main():
    parser = argparse.ArgumentParser(description="TQQQ 200-day SMA trading bot")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="Run the trading check (called by cron)")
    sub.add_parser("init-auth", help="One-time OAuth setup (run locally with a browser)")
    sub.add_parser("status", help="Show current position and available cash")
    sub.add_parser("history", help="Show recent trade history")

    args = parser.parse_args()
    {
        "run":       cmd_run,
        "init-auth": cmd_init_auth,
        "status":    cmd_status,
        "history":   cmd_history,
    }[args.command](args)


if __name__ == "__main__":
    main()
