"""
Core trading loop: runs once per invocation.
"""
import logging
from datetime import datetime, timezone

from config import Config
from bot import schwab as sc
from bot.state import StateDB, Trade
from bot.strategy import Regime, evaluate
from bot.notifier import send_email

logger = logging.getLogger(__name__)


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
        _handle_risk_on(cfg, client, db, tqqq_shares, bil_shares, cash, result, now)
    else:
        _handle_risk_off(cfg, client, db, tqqq_shares, bil_shares, cash, result, now)

    logger.info("=== tqqq-bot run end ===")


def _handle_risk_on(cfg, client, db, tqqq_shares, bil_shares, cash, result, now):
    if tqqq_shares > 0:
        logger.info(
            "RISK_ON: holding %d %s (price $%.2f > SMA $%.2f) — no action.",
            tqqq_shares, cfg.TICKER, result.current_price, result.sma_200,
        )
        return

    if bil_shares > 0:
        logger.info("RISK_ON: selling %d %s to rotate into %s.", bil_shares, cfg.SAFE_TICKER, cfg.TICKER)
        sc.place_sell_market(client, cfg.SCHWAB_ACCOUNT_HASH, cfg.SAFE_TICKER, bil_shares, cfg.DRY_RUN)
        pos = db.get_position()
        db.record_trade(Trade(
            timestamp=now,
            action="SELL_BIL",
            shares=bil_shares,
            price=0.0,
            total_value=0.0,
            sma_200=result.sma_200,
            notes=f"rotating to {cfg.TICKER}; price unknown until fill",
        ))
        db.set_position(0, 0.0, pos.total_invested)
        _notify(
            cfg,
            f"SELL {bil_shares} {cfg.SAFE_TICKER} → rotating to {cfg.TICKER}",
            f"Sold {bil_shares} shares of {cfg.SAFE_TICKER} at market.\n"
            f"Cash will be available next run to buy {cfg.TICKER}.\n"
            f"{cfg.TICKER} price: ~${result.current_price:.2f}\n"
            f"200-day SMA: ${result.sma_200:.2f}\n"
            f"{'[DRY RUN]' if cfg.DRY_RUN else ''}",
        )
        return

    shares_to_buy = int(cash // result.current_price)
    if shares_to_buy < 1:
        logger.warning(
            "RISK_ON: cash $%.2f is less than one %s share (~$%.2f) — no action.",
            cash, cfg.TICKER, result.current_price,
        )
        return

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
    _notify(
        cfg,
        f"BUY {shares_to_buy} {cfg.TICKER}",
        f"Bought {shares_to_buy} shares of {cfg.TICKER} at ~${result.current_price:.2f}\n"
        f"Cost: ${cost:.2f}\n"
        f"200-day SMA: ${result.sma_200:.2f}\n"
        f"{'[DRY RUN]' if cfg.DRY_RUN else ''}",
    )


def _handle_risk_off(cfg, client, db, tqqq_shares, bil_shares, cash, result, now):
    if bil_shares > 0:
        logger.info(
            "RISK_OFF: holding %d %s (price $%.2f < SMA $%.2f) — no action.",
            bil_shares, cfg.SAFE_TICKER, result.current_price, result.sma_200,
        )
        return

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
        _notify(
            cfg,
            f"SELL {tqqq_shares} {cfg.TICKER} → rotating to {cfg.SAFE_TICKER}",
            f"Sold {tqqq_shares} shares of {cfg.TICKER} at ~${result.current_price:.2f}\n"
            f"Proceeds: ${proceeds:.2f}\n"
            f"Cost basis: ${tqqq_shares * pos.avg_cost:.2f}\n"
            f"P/L: ${proceeds - tqqq_shares * pos.avg_cost:.2f}\n"
            f"200-day SMA: ${result.sma_200:.2f}\n"
            f"Cash will be available next run to buy {cfg.SAFE_TICKER}.\n"
            f"{'[DRY RUN]' if cfg.DRY_RUN else ''}",
        )
        return

    # Have cash — buy BIL
    bil_candles = sc.get_price_history(client, cfg.SAFE_TICKER, num_days=5)
    bil_price = bil_candles[-1]["close"]
    shares_to_buy = int(cash // bil_price)
    if shares_to_buy < 1:
        logger.warning(
            "RISK_OFF: cash $%.2f is less than one %s share (~$%.2f) — no action.",
            cash, cfg.SAFE_TICKER, bil_price,
        )
        return

    logger.info("RISK_OFF: buying %d %s @ ~$%.2f (cash: $%.2f)", shares_to_buy, cfg.SAFE_TICKER, bil_price, cash)
    sc.place_buy_market(client, cfg.SCHWAB_ACCOUNT_HASH, cfg.SAFE_TICKER, shares_to_buy, cfg.DRY_RUN)

    cost = shares_to_buy * bil_price
    pos = db.get_position()
    db.set_position(0, 0.0, pos.total_invested)
    db.record_trade(Trade(
        timestamp=now,
        action="BUY_BIL",
        shares=shares_to_buy,
        price=bil_price,
        total_value=cost,
        sma_200=result.sma_200,
        notes=f"cash_used=${cost:.2f}",
    ))
    _notify(
        cfg,
        f"BUY {shares_to_buy} {cfg.SAFE_TICKER}",
        f"Bought {shares_to_buy} shares of {cfg.SAFE_TICKER} at ~${bil_price:.2f}\n"
        f"Cost: ${cost:.2f}\n"
        f"{cfg.TICKER} 200-day SMA: ${result.sma_200:.2f}\n"
        f"{'[DRY RUN]' if cfg.DRY_RUN else ''}",
    )


def _notify(cfg, subject, body):
    send_email(
        to_addr=cfg.NOTIFY_EMAIL,
        subject=subject,
        body=body,
        smtp_host=cfg.SMTP_HOST,
        smtp_port=cfg.SMTP_PORT,
        smtp_user=cfg.SMTP_USER,
        smtp_pass=cfg.SMTP_PASS,
    )
