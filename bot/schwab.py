"""
Thin wrapper around schwab-py for the operations this bot needs.
"""
import json
import logging
import time
from pathlib import Path
from typing import Optional

import schwab
from schwab import orders as schwab_orders
from schwab.client import Client

logger = logging.getLogger(__name__)


def get_client(token_path: str, app_key: str, app_secret: str) -> Client:
    """
    Load client from a cached token file. Token must already exist.

    Uses client_from_access_functions so we can hook into the token write and
    log each refresh. The access token expires every 30 minutes and is refreshed
    automatically, but the refresh token hard-expires 7 days after init-auth —
    refreshing does not extend it, so init-auth must be re-run weekly.
    """
    path = Path(token_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Token file not found at {token_path}. "
            "Run `python main.py init-auth` locally to authenticate first, "
            "then copy the token file to the server."
        )

    with open(path) as f:
        token = json.load(f)

    def token_write_func(new_token: dict, **kwargs):
        with open(path, "w") as f:
            json.dump(new_token, f)
        logger.info("OAuth token refreshed and saved to %s", path)

    return schwab.auth.client_from_access_functions(
        api_key=app_key,
        app_secret=app_secret,
        token_read_func=lambda: token,
        token_write_func=token_write_func,
    )


def get_token_age_days(token_path: str) -> Optional[float]:
    """Days since init-auth created the token file, or None if it can't be read."""
    try:
        with open(token_path) as f:
            created = json.load(f)["creation_timestamp"]
    except (OSError, KeyError, ValueError):
        return None
    return (time.time() - created) / 86400


def get_price_history(client: Client, ticker: str, num_days: int = 250) -> list[dict]:
    """
    Return a list of daily OHLCV candles, oldest-first.
    Each candle: {open, high, low, close, volume, datetime}
    """
    resp = client.get_price_history(
        symbol=ticker,
        period_type=Client.PriceHistory.PeriodType.YEAR,
        period=Client.PriceHistory.Period.ONE_YEAR,
        frequency_type=Client.PriceHistory.FrequencyType.DAILY,
        frequency=Client.PriceHistory.Frequency.DAILY,
        need_extended_hours_data=False,
    )
    resp.raise_for_status()
    data = resp.json()
    candles = data.get("candles", [])
    if len(candles) < num_days:
        logger.warning(
            "Only %d candles returned; expected at least %d", len(candles), num_days
        )
    return candles


def place_buy_market(
    client: Client, account_hash: str, ticker: str, quantity: int, dry_run: bool = False
) -> Optional[str]:
    """Place a market buy order. Returns order ID string or None if dry_run."""
    if dry_run:
        logger.info("[DRY RUN] Would BUY %d shares of %s at market", quantity, ticker)
        return None
    order = schwab_orders.equities.equity_buy_market(ticker, quantity).build()
    resp = client.place_order(account_hash, order)
    resp.raise_for_status()
    location = resp.headers.get("Location", "")
    order_id = location.rstrip("/").split("/")[-1]
    logger.info("BUY order placed: %d shares of %s  order_id=%s", quantity, ticker, order_id)
    return order_id


def place_sell_market(
    client: Client, account_hash: str, ticker: str, quantity: int, dry_run: bool = False
) -> Optional[str]:
    """Place a market sell order. Returns order ID string or None if dry_run."""
    if dry_run:
        logger.info("[DRY RUN] Would SELL %d shares of %s at market", quantity, ticker)
        return None
    order = schwab_orders.equities.equity_sell_market(ticker, quantity).build()
    resp = client.place_order(account_hash, order)
    resp.raise_for_status()
    location = resp.headers.get("Location", "")
    order_id = location.rstrip("/").split("/")[-1]
    logger.info("SELL order placed: %d shares of %s  order_id=%s", quantity, ticker, order_id)
    return order_id


def get_account_state(client: Client, account_hash: str) -> dict:
    """
    Fetch live account positions and cash from Schwab.

    Returns:
        {
          "positions": {"TQQQ": 150, "BIL": 200},  # ticker → integer shares
          "avg_costs": {"TQQQ": 45.23},             # ticker → avg cost per share
          "cash": 1234.56                            # cash available for trading
        }
    """
    resp = client.get_account(account_hash, fields=[Client.Account.Fields.POSITIONS])
    resp.raise_for_status()
    data = resp.json()
    acct = data.get("securitiesAccount", {})

    positions: dict[str, int] = {}
    avg_costs: dict[str, float] = {}
    for pos in acct.get("positions", []):
        symbol = pos.get("instrument", {}).get("symbol", "")
        qty = int(pos.get("longQuantity", 0))
        avg = float(pos.get("averagePrice", 0.0))
        if symbol and qty > 0:
            positions[symbol] = qty
            avg_costs[symbol] = avg

    cash = float(acct.get("currentBalances", {}).get("cashAvailableForTrading", 0.0))
    logger.info("Account state: positions=%s  cash=$%.2f", positions, cash)
    return {"positions": positions, "avg_costs": avg_costs, "cash": cash}
