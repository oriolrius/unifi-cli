# UniFi CLI

CLI tool for managing UniFi UDM Pro networks via the aiounifi library.

## Project Structure

```
unifi_cli/
  __init__.py
  cli.py          # Click CLI entry point (commands: clients, devices, networks, raw, configure)
  auth.py         # SSO + TOTP MFA authentication (custom, works around aiounifi bug)
  controller.py   # aiounifi controller wrapper with token caching
  config.py       # Config file + token cache management
  output.py       # Rich table / JSON / CSV output formatters
```

## Authentication Flow

The UDM Pro uses Ubiquiti SSO with TOTP MFA. The login is a two-step process:

1. `POST /api/auth/login` with `{username, password}` → HTTP 499 with `mfaCookie` in JSON body
2. `POST /api/auth/login` again with `{username, password, token, rememberMe}` + `Cookie: <mfaCookie>` header → HTTP 200 with TOKEN cookie

**aiounifi v90 bug**: `_login_sso_2fa()` sets the MFA cookie via `session.cookie_jar.update_cookies({name: value})` without a URL, so aiohttp's CookieJar never sends it. We work around this by:
- Performing auth ourselves in `auth.py`
- Injecting `TOKEN` cookie and `x-csrf-token` into `controller.connectivity.headers`

**Token caching**: Auth tokens are cached to `~/.config/unifi-cli/.token_cache` (23h TTL) to avoid TOTP code reuse issues when running commands in quick succession. If a cached token expires, the cache is cleared and a fresh login is performed automatically.

**TOTP timing**: When generating a TOTP code, if we're within the last 5 seconds of a 30-second interval, we wait for the next interval to avoid code-reuse rejection.

## API Endpoints (UDM Pro)

All endpoints prefixed with `/proxy/network` on UniFi OS devices:

| Endpoint | Description |
|---|---|
| `/api/s/{site}/stat/sta` | Active (online) clients |
| `/api/s/{site}/rest/user` | All known clients (online + offline) |
| `/api/s/{site}/stat/device` | Network devices (APs, switches, gateway) |

## Running

```bash
# Install and run with uvx (no install needed)
uvx unifi-cli-tool clients

# Or install locally
uv sync
uv run unifi-cli configure
uv run unifi-cli clients
```

## Dependencies

- `aiounifi>=90` - Async UniFi controller client (used for data models and API request routing)
- `aiohttp>=3.9` - Async HTTP client
- `click>=8.1` - CLI framework
- `pyotp>=2.9` - TOTP code generation for MFA
- `rich>=13.0` - Terminal table formatting
