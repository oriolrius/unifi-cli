"""Authentication for UniFi UDM Pro with SSO + TOTP MFA.

The UDM Pro uses Ubiquiti SSO authentication. When MFA is enabled, the login
flow is:

1. POST /api/auth/login with {username, password}
   -> Returns HTTP 499 with MFA challenge containing mfaCookie in JSON body
2. Set the mfaCookie as a Cookie header
3. POST /api/auth/login again with {username, password, token, rememberMe}
   -> Returns HTTP 200 with TOKEN cookie and x-csrf-token header

The TOKEN cookie is then used for all subsequent API requests, including
aiounifi's /proxy/network/... endpoints.

Note: aiounifi v90 has built-in SSO MFA support, but its cookie handling
has a bug (sets MFA cookie without URL context, so aiohttp never sends it).
This module works around that by doing the auth flow with requests-style
headers instead of relying on the cookie jar.
"""

import asyncio
import ssl
import time

import aiohttp
import pyotp


async def login_udm_pro(
    host: str,
    port: int,
    username: str,
    password: str,
    totp_secret: str,
    verify_ssl: bool = False,
) -> tuple[str, str | None]:
    """Authenticate to UDM Pro with SSO + TOTP MFA.

    Returns (token_cookie_value, csrf_token).
    """
    ssl_context: ssl.SSLContext | bool = False
    if verify_ssl:
        ssl_context = ssl.create_default_context()

    login_url = f"https://{host}/api/auth/login"

    async with aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(unsafe=True),
        connector=aiohttp.TCPConnector(ssl=ssl_context),
    ) as session:
        # Step 1: Initial login to get MFA challenge
        async with session.post(
            login_url,
            json={"username": username, "password": password},
        ) as resp:
            if resp.status == 200:
                return _extract_auth(session, resp)

            if resp.status != 499:
                text = await resp.text()
                raise AuthError(f"Login failed with HTTP {resp.status}: {text[:200]}")

            data = await resp.json()
            if data.get("code") != "MFA_AUTH_REQUIRED":
                raise AuthError(f"Unexpected response: {data.get('message', 'unknown')}")

            mfa_cookie = data["data"]["mfaCookie"]

        # Step 2: Re-login with TOTP token and MFA cookie as header
        # Wait for a fresh TOTP interval to avoid code-reuse rejection
        totp = pyotp.TOTP(totp_secret)
        elapsed = time.time() % 30
        if elapsed > 25:
            await asyncio.sleep(30 - elapsed + 1)
        token = totp.now()

        async with session.post(
            login_url,
            json={
                "username": username,
                "password": password,
                "token": token,
                "rememberMe": True,
            },
            headers={"Cookie": mfa_cookie},
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise AuthError(f"MFA verification failed: {resp.status}: {text[:200]}")

            return _extract_auth(session, resp)


def _extract_auth(
    session: aiohttp.ClientSession,
    response: aiohttp.ClientResponse,
) -> tuple[str, str | None]:
    """Extract TOKEN cookie and CSRF token from login response."""
    # Get TOKEN from cookie jar
    token = None
    for cookie in session.cookie_jar:
        if cookie.key == "TOKEN":
            token = cookie.value
            break

    # Also check Set-Cookie header directly
    if not token:
        set_cookie = response.headers.get("Set-Cookie", "")
        if "TOKEN=" in set_cookie:
            for part in set_cookie.split(";"):
                part = part.strip()
                if part.startswith("TOKEN="):
                    token = part[6:]
                    break

    if not token:
        raise AuthError("No TOKEN cookie received after login")

    csrf = response.headers.get("x-csrf-token")
    return token, csrf


class AuthError(Exception):
    """Authentication failure."""
