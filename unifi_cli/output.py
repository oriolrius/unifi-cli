"""Output formatting helpers for the CLI."""

import csv
import io
import json
import sys

from rich.console import Console
from rich.table import Table

console = Console()


def print_table(columns: list[tuple[str, str]], rows: list[dict], title: str = ""):
    """Print a rich table. columns = [(key, header_label), ...]."""
    table = Table(title=title, show_lines=False, expand=False)
    for _, header in columns:
        table.add_column(header, no_wrap=True, overflow="ellipsis", max_width=30)
    for row in rows:
        table.add_row(*(str(row.get(k, "")) for k, _ in columns))
    console.print(table)


def print_json(rows: list[dict]):
    """Print rows as JSON."""
    json.dump(rows, sys.stdout, indent=2, default=str)
    print()


def print_csv(columns: list[tuple[str, str]], rows: list[dict]):
    """Print rows as CSV."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[k for k, _ in columns], extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    print(buf.getvalue(), end="")
