"""UniFi controller wrapper combining custom SSO auth with aiounifi.

aiounifi's built-in SSO MFA has a bug where the MFA cookie is set on the
CookieJar without a URL, so aiohttp never sends it. We work around this by
performing the SSO+MFA login ourselves, then injecting the TOKEN cookie and
CSRF token into aiounifi's headers dict (which is how aiounifi propagates
auth to every request).

Auth tokens are cached to disk (~23h TTL) to avoid TOTP code reuse issues
when running commands in quick succession.
"""

import asyncio
import ssl
from contextlib import asynccontextmanager

import aiohttp
import aiounifi
from aiounifi.errors import LoginRequired
from aiounifi.models.configuration import Configuration

from .auth import login_udm_pro
from .config import (
    clear_cached_token,
    load_cached_token,
    load_config,
    save_cached_token,
)


async def _authenticate(cfg: dict) -> tuple[str, str | None]:
    """Get auth token, using cache when available."""
    cached = load_cached_token()
    if cached:
        return cached["token"], cached.get("csrf")

    token, csrf = await login_udm_pro(
        host=cfg["host"],
        port=cfg["port"],
        username=cfg["username"],
        password=cfg["password"],
        totp_secret=cfg["totp_secret"],
        verify_ssl=cfg.get("verify_ssl", False),
    )
    save_cached_token(token, csrf)
    return token, csrf


@asynccontextmanager
async def get_controller(config: dict | None = None):
    """Connect and authenticate to the UniFi controller.

    Yields an aiounifi Controller with active session.
    """
    cfg = config or load_config()

    ssl_context: ssl.SSLContext | bool = False
    if cfg.get("verify_ssl"):
        ssl_context = ssl.create_default_context()

    token_cookie, csrf_token = await _authenticate(cfg)

    session = aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(unsafe=True),
        connector=aiohttp.TCPConnector(ssl=ssl_context),
    )

    try:
        configuration = Configuration(
            session,
            host=cfg["host"],
            username=cfg["username"],
            password=cfg["password"],
            port=cfg["port"],
            site=cfg["site"],
            ssl_context=ssl_context,
        )

        controller = aiounifi.Controller(configuration)

        # Detect UniFi OS without logging in
        await controller.connectivity.check_unifi_os()

        # Inject auth headers the same way aiounifi.login() would
        controller.connectivity.headers["Cookie"] = f"TOKEN={token_cookie}"
        if csrf_token:
            controller.connectivity.headers["x-csrf-token"] = csrf_token
        controller.connectivity.can_retry_login = True

        yield controller
    except LoginRequired:
        # Cached token expired - clear cache and re-auth
        clear_cached_token()
        await session.close()
        async with get_controller(cfg) as ctrl:
            yield ctrl
        return
    finally:
        await session.close()


async def fetch_clients(controller: aiounifi.Controller) -> tuple[dict, dict]:
    """Fetch active and all-known clients.

    Returns (active_clients_by_mac, all_clients_by_mac).
    """
    await asyncio.gather(
        controller.clients.update(),
        controller.clients_all.update(),
    )
    return dict(controller.clients.items()), dict(controller.clients_all.items())


async def fetch_devices(controller: aiounifi.Controller) -> dict:
    """Fetch network devices (APs, switches, gateways)."""
    await controller.devices.update()
    return dict(controller.devices.items())


async def fetch_networks(controller: aiounifi.Controller) -> dict:
    """Fetch network configurations."""
    await controller.wlans.update()
    return dict(controller.wlans.items())
