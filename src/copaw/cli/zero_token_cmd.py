# -*- coding: utf-8 -*-
"""CLI commands for Zero-Token browser-based authentication."""
from __future__ import annotations

import asyncio

import click

from ..providers.web_registry import WEB_PROVIDERS, get_web_provider_meta
from ..providers.web_store import (
    delete_web_credential,
    get_web_credential,
    is_credential_valid,
    load_web_credentials,
    save_web_credential,
)


@click.group("zero-token")
def zero_token_group() -> None:
    """Zero-Token: browser-based credential capture for 9 AI platforms."""


@zero_token_group.command("chrome")
@click.option(
    "--port",
    default=9222,
    type=int,
    help="Chrome DevTools Protocol port",
)
def chrome_cmd(port: int) -> None:
    """Launch Chrome in CDP debug mode."""
    from ..providers.web_capture import launch_chrome_debug

    click.echo(f"Launching Chrome with CDP on port {port}...")
    proc = launch_chrome_debug(port=port)
    if proc is None:
        click.echo(click.style("Failed to launch Chrome.", fg="red"))
        raise SystemExit(1)
    click.echo(f"Chrome started (PID: {proc.pid})")
    click.echo(
        "Please log in to the desired platforms in the browser, "
        "then run 'copaw zero-token login'.",
    )


@zero_token_group.command("login")
@click.argument("provider_id", required=False, default=None)
@click.option("--all", "login_all", is_flag=True, help="Capture all platforms")
@click.option(
    "--port",
    default=9222,
    type=int,
    help="Chrome CDP port",
)
@click.option(
    "--timeout",
    default=300,
    type=int,
    help="Capture timeout in seconds",
)
def login_cmd(
    provider_id: str | None,
    login_all: bool,
    port: int,
    timeout: int,
) -> None:
    """Capture credentials from browser session."""
    if login_all:
        targets = list(WEB_PROVIDERS.keys())
    elif provider_id:
        if provider_id not in WEB_PROVIDERS:
            click.echo(
                click.style(
                    f"Unknown web provider: {provider_id}",
                    fg="red",
                ),
            )
            click.echo(
                "Available: "
                + ", ".join(WEB_PROVIDERS.keys()),
            )
            raise SystemExit(1)
        targets = [provider_id]
    else:
        # Interactive selection
        click.echo("Available web providers:")
        ids = list(WEB_PROVIDERS.keys())
        for i, pid in enumerate(ids, 1):
            defn = WEB_PROVIDERS[pid]
            cred = get_web_credential(pid)
            status = (
                "captured"
                if cred and is_credential_valid(cred)
                else "expired"
                if cred
                else "not configured"
            )
            click.echo(f"  {i}. {defn.name} [{status}]")
        choice = click.prompt(
            "Select provider number",
            type=int,
            default=1,
        )
        if choice < 1 or choice > len(ids):
            click.echo(click.style("Invalid selection.", fg="red"))
            raise SystemExit(1)
        targets = [ids[choice - 1]]

    asyncio.run(_capture_targets(targets, port, timeout))


async def _capture_targets(
    targets: list[str],
    port: int,
    timeout: int,
) -> None:
    """Capture credentials for the given provider IDs."""
    from ..providers.web_capture import capture_credentials, connect_cdp

    try:
        browser, context = await connect_cdp(port=port)
    except Exception as exc:
        click.echo(
            click.style(
                f"Failed to connect to Chrome CDP on port {port}: {exc}",
                fg="red",
            ),
        )
        click.echo("Please run 'copaw zero-token chrome' first.")
        raise SystemExit(1) from exc

    try:
        for pid in targets:
            defn = WEB_PROVIDERS[pid]
            click.echo(f"\nCapturing credentials for {defn.name}...")
            try:
                cred = await capture_credentials(
                    pid,
                    context,
                    timeout=timeout,
                )
                save_web_credential(pid, cred)
                click.echo(
                    click.style(f"  {defn.name}: captured", fg="green"),
                )
            except TimeoutError:
                click.echo(
                    click.style(
                        f"  {defn.name}: timeout (not logged in?)",
                        fg="yellow",
                    ),
                )
            except Exception as exc:
                click.echo(
                    click.style(
                        f"  {defn.name}: failed ({exc})",
                        fg="red",
                    ),
                )
    finally:
        await browser.close()


@zero_token_group.command("status")
def status_cmd() -> None:
    """Show credential status for all web providers."""
    creds = load_web_credentials()

    click.echo(f"\n{'Provider':<20s} {'Status':<14s} {'Captured At':<24s}")
    click.echo("=" * 58)

    for pid, defn in WEB_PROVIDERS.items():
        cred = creds.get(pid)
        if cred is None:
            status = click.style("not configured", fg="white")
            captured = "-"
        elif is_credential_valid(cred):
            status = click.style("active", fg="green")
            captured = cred.captured_at[:19] if cred.captured_at else "-"
        else:
            status = click.style("expired", fg="yellow")
            captured = cred.captured_at[:19] if cred.captured_at else "-"

        click.echo(f"  {defn.name:<18s} {status:<24s} {captured}")

    click.echo()


@zero_token_group.command("refresh")
@click.argument("provider_id", required=False, default=None)
@click.option(
    "--port",
    default=9222,
    type=int,
    help="Chrome CDP port",
)
def refresh_cmd(provider_id: str | None, port: int) -> None:
    """Refresh expired credentials."""
    creds = load_web_credentials()

    if provider_id:
        targets = [provider_id]
    else:
        # Refresh all expired
        targets = [
            pid
            for pid in WEB_PROVIDERS
            if pid in creds and not is_credential_valid(creds[pid])
        ]

    if not targets:
        click.echo("No expired credentials to refresh.")
        return

    asyncio.run(_capture_targets(targets, port, timeout=300))


@zero_token_group.command("remove")
@click.argument("provider_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def remove_cmd(provider_id: str, yes: bool) -> None:
    """Remove a stored credential."""
    if provider_id not in WEB_PROVIDERS:
        click.echo(
            click.style(f"Unknown web provider: {provider_id}", fg="red"),
        )
        raise SystemExit(1)

    cred = get_web_credential(provider_id)
    if cred is None:
        click.echo(f"No credential stored for '{provider_id}'.")
        return

    if not yes:
        defn = WEB_PROVIDERS[provider_id]
        if not click.confirm(
            f"Delete credential for {defn.name}?",
        ):
            return

    delete_web_credential(provider_id)
    click.echo(f"Credential for '{provider_id}' deleted.")
