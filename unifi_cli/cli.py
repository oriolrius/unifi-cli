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


# --- wan ---

@cli.command()
@click.option("--uplink", is_flag=True, help="Show uplink details")
@click.option("--ports", is_flag=True, help="Show all ethernet ports")
@click.option("--dns", is_flag=True, help="Show DNS configuration")
@click.option("--traffic", is_flag=True, help="Show traffic counters")
@click.option("--speedtest", is_flag=True, help="Show speedtest status")
@click.pass_context
def wan(ctx, uplink, ports, dns, traffic, speedtest):
    """Show WAN status and details.

    By default shows a summary. Use flags to drill down into specific sections.
    """
    run(_wan(ctx.obj["config"], ctx.obj["fmt"], uplink, ports, dns, traffic, speedtest))


async def _wan(config, fmt, uplink, ports, dns, traffic, speedtest):
    async with get_controller(config) as ctrl:
        await ctrl.devices.update()

        # Find the UDM Pro device
        udmp = None
        for mac, device in ctrl.devices.items():
            raw = device.raw
            if raw.get("type") == "udm" or raw.get("name") == "UDMPRO":
                udmp = raw
                break

        if not udmp:
            console.print("[red]UDM Pro device not found[/red]")
            return

        # If no flags, show everything grouped
        if not any([uplink, ports, dns, traffic, speedtest]):
            # Summary view
            rows = []
            wan_status = udmp.get("last_wan_status", {})
            wan_ips = udmp.get("last_wan_interfaces", {})
            for wan_name, info in wan_ips.items():
                ip = info.get("ip", "N/A")
                alive = info.get("alive", False)
                rows.append({
                    "wan": wan_name,
                    "ip": ip,
                    "status": "online" if alive else "offline",
                    "latency": f"{udmp.get('wan1', {}).get('latency', '?')}ms" if wan_name == "WAN" else "-",
                    "speed": _fmt_speed(udmp.get("wan1", {}).get("speed", 0)) if wan_name == "WAN" else "-",
                    "uptime": _fmt_duration(udmp.get("uplink", {}).get("uptime", 0)) if wan_name == "WAN" else "-",
                })
            columns = [
                ("wan", "WAN"),
                ("ip", "IP"),
                ("status", "Status"),
                ("latency", "Latency"),
                ("speed", "Speed"),
                ("uptime", "Uptime"),
            ]
            if fmt == "json":
                print_json(rows)
            elif fmt == "csv":
                print_csv(columns, rows)
            else:
                print_table(columns, rows, title="WAN Summary")

            console.print()
            # Quick counters
            uplink_data = udmp.get("uplink", {})
            console.print(f"[bold]WAN Traffic (Total):[/bold]")
            console.print(f"  RX: {_fmt_bytes(uplink_data.get('rx_bytes', 0))}")
            console.print(f"  TX: {_fmt_bytes(uplink_data.get('tx_bytes', 0))}")
            rx_mbps = uplink_data.get('rx_bytes-r', 0) * 8 / 1_000_000
            tx_mbps = uplink_data.get('tx_bytes-r', 0) * 8 / 1_000_000
            console.print(f"  Current: {_fmt_speed(rx_mbps)} ↓ / {_fmt_speed(tx_mbps)} ↑")
            console.print()
            console.print(f"[bold]DNS Shield:[/bold] {udmp.get('dns_shield_server_list_hash', '?')[:16]}... ({udmp.get('ids_ips_signature', {}).get('rule_count', 0)} rules)")

        # Uplink detail
        if uplink:
            ul = udmp.get("uplink", {})
            wan1 = udmp.get("wan1", {})
            wan2 = udmp.get("wan2", {})

            rows = [
                {
                    "interface": "WAN",
                    "up": "yes" if ul.get("up") else "no",
                    "ip": ul.get("ip", "?"),
                    "netmask": ul.get("netmask", "?"),
                    "gateway": "?" if ul.get("ip") == "172.19.0.3" else "?",
                    "dns": ", ".join(ul.get("nameservers_dynamic", [])),
                    "latency_ms": ul.get("latency", "?"),
                    "speed": _fmt_speed(wan1.get("speed", 0)),
                    "duplex": "full" if wan1.get("full_duplex") else "half",
                    "type": ul.get("type", "?"),
                },
                {
                    "interface": "WAN2",
                    "up": "yes" if wan2.get("up") else "no",
                    "ip": wan2.get("ip", "?"),
                    "netmask": "?" if not wan2.get("ip") else "255.255.255.0",
                    "gateway": "?",
                    "dns": "-",
                    "latency_ms": "-",
                    "speed": _fmt_speed(wan2.get("speed", 0)),
                    "duplex": "full" if wan2.get("full_duplex") else "half",
                    "type": wan2.get("type", "?"),
                },
            ]
            columns = [
                ("interface", "Interface"),
                ("up", "Up"),
                ("ip", "IP"),
                ("netmask", "Netmask"),
                ("gateway", "Gateway"),
                ("dns", "DNS"),
                ("latency_ms", "Latency"),
                ("speed", "Speed"),
                ("duplex", "Duplex"),
                ("type", "Type"),
            ]
            if fmt == "json":
                print_json(rows)
            elif fmt == "csv":
                print_csv(columns, rows)
            else:
                print_table(columns, rows, title="WAN Uplinks")

        # Ports
        if ports:
            rows = []
            for p in udmp.get("port_table", []):
                rows.append({
                    "port": p.get("ifname", "?"),
                    "name": p.get("name", "?"),
                    "network": p.get("network_name", "?"),
                    "up": "yes" if p.get("up") else "no",
                    "speed": _fmt_speed(p.get("speed", 0)),
                    "duplex": "full" if p.get("full_duplex") else "half" if p.get("speed", 0) > 0 else "-",
                    "rx_bytes": _fmt_bytes(p.get("rx_bytes", 0)),
                    "tx_bytes": _fmt_bytes(p.get("tx_bytes", 0)),
                    "current_rx": _fmt_speed(p.get("rx_rate", 0) / 1_000_000),
                    "current_tx": _fmt_speed(p.get("tx_rate", 0) / 1_000_000),
                    "mac": p.get("mac", "?"),
                })
            columns = [
                ("port", "Port"),
                ("name", "Name"),
                ("network", "Network"),
                ("up", "Up"),
                ("speed", "Speed"),
                ("duplex", "Duplex"),
                ("rx_bytes", "RX Total"),
                ("tx_bytes", "TX Total"),
                ("current_rx", "RX/s"),
                ("current_tx", "TX/s"),
                ("mac", "MAC"),
            ]
            if fmt == "json":
                print_json(rows)
            elif fmt == "csv":
                print_csv(columns, rows)
            else:
                print_table(columns, rows, title="Ethernet Ports")

        # DNS
        if dns:
            ul = udmp.get("uplink", {})
            sp = udmp.get("speedtest-status", {})
            ids = udmp.get("ids_ips_signature", {})
            rows = [
                {
                    "service": "Primary DNS",
                    "server": ul.get("nameservers_dynamic", ["?"])[0] if ul.get("nameservers_dynamic") else "?",
                },
                {
                    "service": "Secondary DNS",
                    "server": ul.get("nameservers_dynamic", ["?", "?"])[1] if len(ul.get("nameservers_dynamic", [])) > 1 else "?",
                },
                {
                    "service": "DNS Shield",
                    "server": "Enabled" if udmp.get("dns_shield_server_list_hash") else "Disabled",
                },
                {
                    "service": "IDS/IPS Signature",
                    "server": f"{ids.get('rule_count', 0)} rules (ET {ids.get('signature_type', '')})",
                },
                {
                    "service": "Speedtest Server",
                    "server": sp.get("server", {}).get("provider", "?") or "?",
                },
            ]
            columns = [("service", "Service"), ("server", "Server / Info")]
            if fmt == "json":
                print_json(rows)
            elif fmt == "csv":
                print_csv(columns, rows)
            else:
                print_table(columns, rows, title="DNS & Security")

        # Traffic
        if traffic:
            ul = udmp.get("uplink", {})
            rows = [
                {
                    "counter": "Total RX",
                    "bytes": _fmt_bytes(ul.get("rx_bytes", 0)),
                    "packets": f"{ul.get('rx_packets', 0):,}",
                    "dropped": f"{ul.get('rx_dropped', 0):,}",
                    "errors": f"{ul.get('rx_errors', 0):,}",
                    "current": f"{_fmt_speed(ul.get('rx_bytes-r', 0) * 8)}/s",
                },
                {
                    "counter": "Total TX",
                    "bytes": _fmt_bytes(ul.get("tx_bytes", 0)),
                    "packets": f"{ul.get('tx_packets', 0):,}",
                    "dropped": f"{ul.get('tx_dropped', 0):,}",
                    "errors": f"{ul.get('tx_errors', 0):,}",
                    "current": f"{_fmt_speed(ul.get('tx_bytes-r', 0) * 8)}/s",
                },
            ]
            columns = [("counter", "Counter"), ("bytes", "Bytes"), ("packets", "Packets"), ("dropped", "Dropped"), ("errors", "Errors"), ("current", "Current Rate")]
            if fmt == "json":
                print_json(rows)
            elif fmt == "csv":
                print_csv(columns, rows)
            else:
                print_table(columns, rows, title="WAN Traffic Counters")

        # Speedtest
        if speedtest:
            sp = udmp.get("speedtest-status", {})
            rows = [{
                "status": sp.get("status_summary", "?"),
                "latency_ms": sp.get("latency", "?"),
                "download": f"{sp.get('xput_download', 0):.1f} Mbps" if sp.get("xput_download") else "not run",
                "upload": f"{sp.get('xput_upload', 0):.1f} Mbps" if sp.get("xput_upload") else "not run",
                "server": f"{sp.get('server', {}).get('city', '')}, {sp.get('server', {}).get('country', '')}" or "?",
                "provider": sp.get("server", {}).get("provider", "?"),
                "last_run": sp.get("runtime", "never"),
            }]
            columns = [
                ("status", "Status"),
                ("latency_ms", "Latency"),
                ("download", "Download"),
                ("upload", "Upload"),
                ("server", "Server"),
                ("provider", "Provider"),
                ("last_run", "Last Run"),
            ]
            if fmt == "json":
                print_json(rows)
            elif fmt == "csv":
                print_csv(columns, rows)
            else:
                print_table(columns, rows, title="Speedtest")


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

def _fmt_speed(mbps: int | float) -> str:
    """Format megabits per second as human-readable."""
    if mbps <= 0:
        return "-"
    for unit in ["Mbps", "Gbps"]:
        if mbps < 1000:
            return f"{mbps:.0f} {unit}"
        mbps /= 1000
    return f"{mbps:.1f} Tbps"


def _fmt_bytes(num: int) -> str:
    """Format bytes as human-readable."""
    if num <= 0:
        return "-"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} PB"


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
