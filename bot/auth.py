"""
One-time OAuth authentication helper.
Run this locally (with a browser) to generate the token file,
then copy the token file to your server.
"""
import logging
from pathlib import Path

import schwab

logger = logging.getLogger(__name__)


def init_auth(token_path: str, app_key: str, app_secret: str, callback_url: str):
    """
    Opens a browser for the Schwab OAuth flow and saves the token.
    Must be run in an environment with a browser (not on the headless server).
    """
    Path(token_path).parent.mkdir(parents=True, exist_ok=True)
    logger.info("Starting OAuth flow. A browser window will open.")
    logger.info("After authorizing, you will be redirected to: %s", callback_url)

    client = schwab.auth.easy_client(
        api_key=app_key,
        app_secret=app_secret,
        callback_url=callback_url,
        token_path=token_path,
    )
    logger.info("Token saved to %s", token_path)

    resp = client.get_account_numbers()
    resp.raise_for_status()
    accounts = resp.json()
    print("\nAccount hash(es) — add one to your .env as SCHWAB_ACCOUNT_HASH:")
    for acct in accounts:
        print(f"  account: {acct.get('accountNumber')}  hash: {acct.get('hashValue')}")

    logger.info(
        "Copy the token file to your server:\n"
        "  scp %s root@YOUR_DROPLET_IP:%s",
        token_path,
        token_path,
    )
