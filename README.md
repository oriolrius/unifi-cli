# unifi-cli

CLI tool for managing UniFi UDM Pro networks. Built on [aiounifi](https://github.com/Kane610/aiounifi) with custom SSO + TOTP MFA authentication.

## Features

- List clients with online/offline status, IP, MAC, network, vendor info
- List network devices (APs, switches, gateways) with firmware and client counts
- List wireless networks (WLANs)
- Filter by status (online/offline), network name, and sort by any field
- Output as rich table, JSON, or CSV
- Auth token caching (avoids repeated TOTP prompts)
- Raw API endpoint access for advanced queries

## Quick Start

```bash
# Run directly with uvx (no installation needed)
uvx --from "git+https://github.com/oriolrius/unifi-cli.git" unifi-cli configure
uvx --from "git+https://github.com/oriolrius/unifi-cli.git" unifi-cli clients

# Or install as a tool
uv tool install "git+https://github.com/oriolrius/unifi-cli.git"
unifi-cli configure
unifi-cli clients
```

## Setup

```bash
# Interactive configuration
unifi-cli configure

# Or set environment variables
export UNIFI_HOST=192.168.1.1
export UNIFI_PORT=443
export UNIFI_SITE=default
export UNIFI_USERNAME=admin
export UNIFI_PASSWORD=secret
export UNIFI_TOTP_SECRET=BASE32SECRET
```

Config is stored in `~/.config/unifi-cli/config.json` (mode 600).

## Usage

```bash
# List all clients (online + offline)
unifi-cli clients

# Online clients only
unifi-cli clients --status online

# Filter by network and sort by hostname
unifi-cli clients --network IoT --sort hostname

# JSON output
unifi-cli --format json clients --status online

# CSV output
unifi-cli --format csv clients

# List network devices
unifi-cli devices

# List WLANs
unifi-cli networks

# Raw API query
unifi-cli raw stat/health
unifi-cli raw stat/device
```

## Authentication

This tool handles the UDM Pro's Ubiquiti SSO + TOTP MFA authentication automatically:

1. Sends credentials to get an MFA challenge
2. Generates a TOTP code from your secret
3. Completes authentication with the MFA cookie
4. Caches the session token for ~23 hours

If the cached token expires, it automatically re-authenticates.

> **Note**: aiounifi v90 has built-in SSO MFA support, but has a [cookie-handling bug](https://github.com/Kane610/aiounifi/issues) where the MFA cookie is set without URL context, causing aiohttp to never send it. This tool includes a workaround.

## Requirements

- Python >= 3.13
- UniFi OS controller (UDM, UDM Pro, UDM SE, Cloud Key Gen2+)
- Ubiquiti account with TOTP MFA enabled

## Acknowledgments

This tool is built on [aiounifi](https://github.com/Kane610/aiounifi) by Kane610. The library's async architecture and typed data models made it a pleasure to work with. Special thanks to the aiounifi team for maintaining this project and to the Home Assistant community for the extensive documentation of the UniFi API quirks.

## License

MIT
