"""Configuration management for unifi-cli."""

import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("UNIFI_CLI_CONFIG_DIR", Path.home() / ".config" / "unifi-cli"))
CONFIG_FILE = CONFIG_DIR / "config.json"
TOKEN_CACHE_FILE = CONFIG_DIR / ".token_cache"

DEFAULT_CONFIG = {
    "host": "192.168.1.1",
    "port": 443,
    "site": "default",
    "username": "",
    "password": "",
    "totp_secret": "",
    "verify_ssl": False,
}


def load_config() -> dict:
    """Load config from file, env vars, or defaults."""
    config = dict(DEFAULT_CONFIG)

    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            config.update(json.load(f))

    # Env vars override file config
    env_map = {
        "UNIFI_HOST": "host",
        "UNIFI_PORT": ("port", int),
        "UNIFI_SITE": "site",
        "UNIFI_USERNAME": "username",
        "UNIFI_PASSWORD": "password",
        "UNIFI_TOTP_SECRET": "totp_secret",
        "UNIFI_VERIFY_SSL": ("verify_ssl", lambda v: v.lower() in ("1", "true", "yes")),
    }
    for env_key, mapping in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            if isinstance(mapping, tuple):
                config[mapping[0]] = mapping[1](val)
            else:
                config[mapping] = val

    return config


def save_config(config: dict) -> None:
    """Save config to file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    CONFIG_FILE.chmod(0o600)


def load_cached_token() -> dict | None:
    """Load cached auth token if still valid."""
    if not TOKEN_CACHE_FILE.exists():
        return None
    try:
        with open(TOKEN_CACHE_FILE) as f:
            data = json.load(f)
        # Check expiry (tokens last ~30 days, but we use a 23h cache)
        import time
        if data.get("timestamp", 0) + 82800 > time.time():
            return data
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def save_cached_token(token: str, csrf: str | None) -> None:
    """Cache auth token to disk."""
    import time
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_CACHE_FILE, "w") as f:
        json.dump({"token": token, "csrf": csrf, "timestamp": time.time()}, f)
    TOKEN_CACHE_FILE.chmod(0o600)


def clear_cached_token() -> None:
    """Remove cached token."""
    TOKEN_CACHE_FILE.unlink(missing_ok=True)
