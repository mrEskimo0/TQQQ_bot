"""
Core trading loop: runs once per invocation.

Every run sends exactly one Discord message: a trade confirmation, or a
heartbeat explaining why nothing was traded.
"""
import logging
from datetime import datetime, timezone

from config import Config
from bot import schwab as sc
from bot.state import StateDB, Trade
from bot.strategy import Regime, StrategyResult, evaluate
from bot.notifier import GREEN, GREY, ORANGE, RED, send_discord

logger = logging.getLogger(__name__)

# Schwab refresh tokens hard-expire 7 days after init-auth
TOKEN_WARN_DAYS = 6


def run(cfg: Config, db: StateDB):
    logger.info("=== tqqq-bot run start ===")

    # ── 1. Connect ────────────────────────────────────────────────────────────
    client = sc.get_client(cfg.SCHWAB_TOKEN_PATH, cfg.SCHWAB_APP_KEY, cfg.SCHWAB_APP_SECRET)

    # ── 2. Read actual account state from Schwab ──────────────────────────────
    account = sc.get_account_state(client, cfg.SCHWAB_ACCOUNT_HASH)
    tqqq_shares = account["positions"].get(cfg.TICKER, 0)
    bil_shares = account["positions"].get(cfg.SAFE_TICKER, 0)
    cash = account["cash"]

    # ── 3. Evaluate regime ────────────────────────────────────────────────────
    candles = sc.get_price_history(client, cfg.TICKER, num_days=cfg.SMA_PERIOD + 5)
    result = evaluate(candles, sma_period=cfg.SMA_PERIOD)

    now = datetime.now(timezone.utc).isoformat()

    # ── 4. Act ────────────────────────────────────────────────────────────────
    if result.regime == Regime.RISK_ON:
        title, body, color = _handle_risk_on(cfg, client, db, tqqq_shares, bil_shares, cash, result, now)
    else:
        title, body, color = _handle_risk_off(cfg, client, db, tqqq_shares, bil_shares, cash, result, now)

    # ── 5. Notify ─────────────────────────────────────────────────────────────
    token_age = sc.get_token_age_days(cfg.SCHWAB_TOKEN_PATH)
    if token_age is not None and token_age >= TOKEN_WARN_DAYS:
        title += " — token expiring"
        color = ORANGE
        body += (
            f"\n\n**Schwab token is {token_age:.1f} days old** and expires at 7 days. "
            "Run `python main.py init-auth` and copy the token to the server."
        )

    summary = (
        f"Regime: **{result.regime.value}**\n"
        f"{cfg.TICKER}: ${result.current_price:.2f}  |  SMA({cfg.SMA_PERIOD}): ${result.sma_200:.2f}\n"
        f"Holdings: {tqqq_shares} {cfg.TICKER}, {bil_shares} {cfg.SAFE_TICKER}, ${cash:.2f} cash\n"
    )
    if token_age is not None:
        summary += f"Token age: {token_age:.1f} days\n"
    if cfg.DRY_RUN:
        summary += "**[DRY RUN]**\n"

    send_discord(cfg.DISCORD_WEBHOOK_URL, title, f"{body}\n\n{summary}", color)
    logger.info("=== tqqq-bot run end ===")


def _handle_risk_on(cfg, client, db, tqqq_shares, bil_shares, cash, result: StrategyResult, now):
    """Returns (title, body, color) for the run notification."""
    if bil_shares > 0:
        logger.info("RISK_ON: selling %d %s to rotate into %s.", bil_shares, cfg.SAFE_TICKER, cfg.TICKER)
        sc.place_sell_market(client, cfg.SCHWAB_ACCOUNT_HASH, cfg.SAFE_TICKER, bil_shares, cfg.DRY_RUN)
        db.record_trade(Trade(
            timestamp=now,
            action="SELL_BIL",
            shares=bil_shares,
            price=0.0,
            total_value=0.0,
            sma_200=result.sma_200,
            notes=f"rotating to {cfg.TICKER}; price unknown until fill",
        ))
        return (
            f"SELL {bil_shares} {cfg.SAFE_TICKER}",
            f"{cfg.TICKER} is above its SMA — sold {bil_shares} {cfg.SAFE_TICKER} at market.\n"
            f"Cash will be used to buy {cfg.TICKER} on the next run.",
            RED,
        )

    # Buy with whatever cash is available, including topping up an existing position
    shares_to_buy = int(cash // result.current_price)
    if shares_to_buy < 1:
        logger.info(
            "RISK_ON: holding %d %s; cash $%.2f is less than one share (~$%.2f) — no action.",
            tqqq_shares, cfg.TICKER, cash, result.current_price,
        )
        return (
            "No trade — fully invested" if tqqq_shares > 0 else "No trade — no cash",
            f"{cfg.TICKER} is above its SMA. Holding {tqqq_shares} {cfg.TICKER}; "
            f"${cash:.2f} cash is not enough for another share (~${result.current_price:.2f}).",
            GREY,
        )

    logger.info("RISK_ON: buying %d %s @ ~$%.2f (cash: $%.2f)", shares_to_buy, cfg.TICKER, result.current_price, cash)
    sc.place_buy_market(client, cfg.SCHWAB_ACCOUNT_HASH, cfg.TICKER, shares_to_buy, cfg.DRY_RUN)

    cost = shares_to_buy * result.current_price
    pos = db.get_position()
    new_avg = (pos.shares * pos.avg_cost + cost) / (pos.shares + shares_to_buy)
    db.set_position(pos.shares + shares_to_buy, new_avg, pos.total_invested)
    db.record_trade(Trade(
        timestamp=now,
        action="BUY_TQQQ",
        shares=shares_to_buy,
        price=result.current_price,
        total_value=cost,
        sma_200=result.sma_200,
        notes=f"cash_used=${cost:.2f}",
    ))
    return (
        f"BUY {shares_to_buy} {cfg.TICKER}",
        f"{cfg.TICKER} is above its SMA — bought {shares_to_buy} {cfg.TICKER} at market "
        f"(~${result.current_price:.2f}, ~${cost:.2f} total).",
        GREEN,
    )


def _handle_risk_off(cfg, client, db, tqqq_shares, bil_shares, cash, result: StrategyResult, now):
    """Returns (title, body, color) for the run notification."""
    if tqqq_shares > 0:
        logger.info("RISK_OFF: selling %d %s to rotate into %s.", tqqq_shares, cfg.TICKER, cfg.SAFE_TICKER)
        proceeds = tqqq_shares * result.current_price
        pos = db.get_position()
        sc.place_sell_market(client, cfg.SCHWAB_ACCOUNT_HASH, cfg.TICKER, tqqq_shares, cfg.DRY_RUN)
        db.record_trade(Trade(
            timestamp=now,
            action="SELL_TQQQ",
            shares=tqqq_shares,
            price=result.current_price,
            total_value=proceeds,
            sma_200=result.sma_200,
            notes=f"proceeds=${proceeds:.2f}  cost_basis=${tqqq_shares * pos.avg_cost:.2f}  rotating to {cfg.SAFE_TICKER}",
        ))
        db.set_position(0, 0.0, pos.total_invested)
        return (
            f"SELL {tqqq_shares} {cfg.TICKER}",
            f"{cfg.TICKER} is below its SMA — sold {tqqq_shares} {cfg.TICKER} at market "
            f"(~${result.current_price:.2f}, ~${proceeds:.2f} proceeds, "
            f"P/L ~${proceeds - tqqq_shares * pos.avg_cost:.2f}).\n"
            f"Cash will be used to buy {cfg.SAFE_TICKER} on the next run.",
            RED,
        )

    # Park any available cash in BIL, including topping up an existing position
    bil_candles = sc.get_price_history(client, cfg.SAFE_TICKER, num_days=5)
    bil_price = bil_candles[-1]["close"]
    shares_to_buy = int(cash // bil_price)
    if shares_to_buy < 1:
        logger.info(
            "RISK_OFF: holding %d %s; cash $%.2f is less than one share (~$%.2f) — no action.",
            bil_shares, cfg.SAFE_TICKER, cash, bil_price,
        )
        return (
            "No trade — below SMA",
            f"{cfg.TICKER} is below its SMA. Holding {bil_shares} {cfg.SAFE_TICKER}; "
            f"${cash:.2f} cash is not enough for another {cfg.SAFE_TICKER} share (~${bil_price:.2f}).",
            GREY,
        )

    logger.info("RISK_OFF: buying %d %s @ ~$%.2f (cash: $%.2f)", shares_to_buy, cfg.SAFE_TICKER, bil_price, cash)
    sc.place_buy_market(client, cfg.SCHWAB_ACCOUNT_HASH, cfg.SAFE_TICKER, shares_to_buy, cfg.DRY_RUN)

    cost = shares_to_buy * bil_price
    db.record_trade(Trade(
        timestamp=now,
        action="BUY_BIL",
        shares=shares_to_buy,
        price=bil_price,
        total_value=cost,
        sma_200=result.sma_200,
        notes=f"cash_used=${cost:.2f}",
    ))
    return (
        f"BUY {shares_to_buy} {cfg.SAFE_TICKER}",
        f"{cfg.TICKER} is below its SMA — bought {shares_to_buy} {cfg.SAFE_TICKER} at market "
        f"(~${bil_price:.2f}, ~${cost:.2f} total).",
        GREEN,
    )
