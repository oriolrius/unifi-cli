"""CLI entry point for unifi-cli."""

import asyncio
import sys
from datetime import datetime, timezone

import click

from .config import load_config, save_config
from .controller import fetch_clients, fetch_devices, fetch_networks, get_controller
from .output import console, print_csv, print_json, print_table


def run(coro):
    """Run an async coroutine in a new event loop."""
    return asyncio.run(coro)


@click.group()
@click.option("--host", envvar="UNIFI_HOST", help="Controller host/IP")
@click.option("--port", envvar="UNIFI_PORT", type=int, help="Controller port")
@click.option("--site", envvar="UNIFI_SITE", help="Site name")
@click.option("--format", "fmt", type=click.Choice(["table", "json", "csv"]), default="table")
@click.pass_context
def cli(ctx, host, port, site, fmt):
    """UniFi UDM Pro CLI - manage your network from the terminal."""
    ctx.ensure_object(dict)
    config = load_config()
    if host:
        config["host"] = host
    if port:
        config["port"] = port
    if site:
        config["site"] = site
    ctx.obj["config"] = config
    ctx.obj["fmt"] = fmt


# --- configure ---

@cli.command()
@click.option("--host", prompt="Controller host/IP", default="192.168.1.1")
@click.option("--port", prompt="Controller port", default=443, type=int)
@click.option("--site", prompt="Site name", default="default")
@click.option("--username", prompt="Username")
@click.option("--password", prompt="Password", hide_input=True)
@click.option("--totp-secret", prompt="TOTP secret (base32)", hide_input=True)
def configure(host, port, site, username, password, totp_secret):
    """Save controller credentials to ~/.config/unifi-cli/config.json."""
    config = {
        "host": host,
        "port": port,
        "site": site,
        "username": username,
        "password": password,
        "totp_secret": totp_secret,
        "verify_ssl": False,
    }
    save_config(config)
    console.print(f"[green]Config saved to {load_config.__module__}[/green]")


# --- clients ---

@cli.command()
@click.option("--status", type=click.Choice(["online", "offline", "all"]), default="all",
              help="Filter by connection status")
@click.option("--network", help="Filter by network name")
@click.option("--sort", "sort_by", default="ip", help="Sort by field (ip, hostname, mac, network)")
@click.pass_context
def clients(ctx, status, network, sort_by):
    """List network clients with online/offline status."""
    run(_clients(ctx.obj["config"], ctx.obj["fmt"], status, network, sort_by))


async def _clients(config, fmt, status, network, sort_by):
    async with get_controller(config) as ctrl:
        active, all_known = await fetch_clients(ctrl)

        rows = []
        # Active clients
        for mac, client in active.items():
            raw = client.raw
            row = {
                "status": "online",
                "hostname": raw.get("hostname") or raw.get("name") or "?",
                "ip": raw.get("ip", "N/A"),
                "mac": mac,
                "network": raw.get("network", raw.get("essid", "wired" if raw.get("is_wired") else "wireless")),
                "uptime": _fmt_duration(raw.get("uptime", 0)),
                "wired": "wired" if raw.get("is_wired") else "wifi",
                "oui": raw.get("oui", ""),
            }
            rows.append(row)

        # Offline clients (in all_known but not active)
        for mac, client in all_known.items():
            if mac not in active:
                raw = client.raw
                last_seen = raw.get("last_seen", 0)
                row = {
                    "status": "offline",
                    "hostname": raw.get("hostname") or raw.get("name") or "?",
                    "ip": raw.get("last_ip", "N/A"),
                    "mac": mac,
                    "network": raw.get("last_connection_network_name", "?"),
                    "uptime": _fmt_last_seen(last_seen) if last_seen else "?",
                    "wired": "",
                    "oui": raw.get("oui", ""),
                }
                rows.append(row)

        # Filters
        if status != "all":
            rows = [r for r in rows if r["status"] == status]
        if network:
            rows = [r for r in rows if network.lower() in r["network"].lower()]

        # Sort
        rows.sort(key=lambda r: _sort_key(r, sort_by))

        columns = [
            ("status", "Status"),
            ("hostname", "Hostname"),
            ("ip", "IP"),
            ("mac", "MAC"),
            ("network", "Network"),
            ("wired", "Type"),
            ("uptime", "Uptime/Last Seen"),
            ("oui", "Vendor"),
        ]

        online_count = sum(1 for r in rows if r["status"] == "online")
        offline_count = sum(1 for r in rows if r["status"] == "offline")
        title = f"Clients ({online_count} online, {offline_count} offline)"

        if fmt == "json":
            print_json(rows)
        elif fmt == "csv":
            print_csv(columns, rows)
        else:
            print_table(columns, rows, title=title)


# --- devices ---

@cli.command()
@click.pass_context
def devices(ctx):
    """List network devices (APs, switches, gateways)."""
    run(_devices(ctx.obj["config"], ctx.obj["fmt"]))


async def _devices(config, fmt):
    async with get_controller(config) as ctrl:
        devs = await fetch_devices(ctrl)

        rows = []
        for mac, device in devs.items():
            raw = device.raw
            row = {
                "name": raw.get("name", "?"),
                "model": raw.get("model", "?"),
                "type": raw.get("type", "?"),
                "ip": raw.get("ip", "N/A"),
                "mac": mac,
                "version": raw.get("version", "?"),
                "status": "online" if raw.get("state", 0) == 1 else "offline",
                "uptime": _fmt_duration(raw.get("uptime", 0)),
                "clients": raw.get("num_sta", 0),
            }
            rows.append(row)

        rows.sort(key=lambda r: r["name"])
        columns = [
            ("status", "Status"),
            ("name", "Name"),
            ("model", "Model"),
            ("type", "Type"),
            ("ip", "IP"),
            ("mac", "MAC"),
            ("version", "Firmware"),
            ("uptime", "Uptime"),
            ("clients", "Clients"),
        ]

        if fmt == "json":
            print_json(rows)
        elif fmt == "csv":
            print_csv(columns, rows)
        else:
            print_table(columns, rows, title="Network Devices")


# --- networks ---

@cli.command()
@click.pass_context
def networks(ctx):
    """List wireless networks (WLANs)."""
    run(_networks(ctx.obj["config"], ctx.obj["fmt"]))


async def _networks(config, fmt):
    async with get_controller(config) as ctrl:
        wlans = await fetch_networks(ctrl)

        rows = []
        for wlan_id, wlan in wlans.items():
            raw = wlan.raw
            row = {
                "name": raw.get("name", "?"),
                "enabled": "yes" if raw.get("enabled") else "no",
                "security": raw.get("security", "?"),
                "vlan": raw.get("networkconf_id", "?"),
                "is_guest": "yes" if raw.get("is_guest") else "no",
            }
            rows.append(row)

        rows.sort(key=lambda r: r["name"])
        columns = [
            ("name", "Name"),
            ("enabled", "Enabled"),
            ("security", "Security"),
            ("is_guest", "Guest"),
        ]

        if fmt == "json":
            print_json(rows)
        elif fmt == "csv":
            print_csv(columns, rows)
        else:
            print_table(columns, rows, title="Wireless Networks")


# --- raw ---

@cli.command()
@click.argument("endpoint")
@click.pass_context
def raw(ctx, endpoint):
    """Make a raw API request (e.g. 'stat/sta', 'rest/user')."""
    run(_raw(ctx.obj["config"], endpoint))


async def _raw(config, endpoint):
    async with get_controller(config) as ctrl:
        from aiounifi.models.api import ApiRequest

        site = config.get("site", "default")
        url = f"/api/s/{site}/{endpoint}"
        request = ApiRequest("get", url, None)
        response = await ctrl.request(request)
        print_json(response.get("data", response))


# --- helpers ---

def _fmt_duration(seconds: int) -> str:
    if seconds <= 0:
        return "-"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def _fmt_last_seen(ts: int) -> str:
    if ts <= 0:
        return "?"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    delta = now - dt
    days = delta.days
    if days > 30:
        return f"{days // 30}mo ago"
    if days > 0:
        return f"{days}d ago"
    hours = delta.seconds // 3600
    if hours > 0:
        return f"{hours}h ago"
    return f"{delta.seconds // 60}m ago"


def _sort_key(row: dict, field: str):
    val = row.get(field, "")
    if field == "ip":
        # Sort IPs numerically
        try:
            parts = val.split(".")
            return tuple(int(p) for p in parts)
        except (ValueError, AttributeError):
            return (999, 999, 999, 999)
    if field == "status":
        return 0 if val == "online" else 1
    return str(val).lower()


def main():
    cli()
