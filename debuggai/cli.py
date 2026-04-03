"""DebuggAI CLI — the main command-line interface."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from rich.console import Console

from debuggai import __version__
from debuggai.config import generate_default_config, load_config

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="debuggai")
def main():
    """DebuggAI — The universal verification layer for AI-generated software."""
    pass


@main.command()
@click.argument("directory", default=".")
def init(directory: str):
    """Initialize DebuggAI for a project."""
    project_dir = str(Path(directory).resolve())
    config_path = Path(project_dir) / ".debuggai.yaml"

    if config_path.exists():
        console.print("[yellow]Config already exists:[/yellow] .debuggai.yaml")
        if not click.confirm("Overwrite?"):
            return

    config_content = generate_default_config(project_dir)
    config_path.write_text(config_content)

    console.print(f"[green]Initialized DebuggAI[/green] in {project_dir}")
    console.print(f"Config written to: {config_path}")
    console.print("\nDetected languages:", end=" ")

    from debuggai.config import auto_detect_languages

    langs = auto_detect_languages(project_dir)
    console.print(", ".join(langs) if langs else "[dim]none[/dim]")
    console.print("\nRun [bold]debuggai scan[/bold] to analyze your code.")


@main.command()
@click.option("--file", "-f", "target", help="File or directory to scan")
@click.option("--diff", "-d", "diff_ref", help="Git ref to diff against (e.g., HEAD~1)")
@click.option("--staged", "-s", is_flag=True, help="Scan staged changes only")
@click.option("--intent", "-i", help="Intent to verify against")
@click.option("--spec", "spec_file", help="Path to intent spec file")
@click.option("--no-llm", is_flag=True, help="Skip LLM-powered analysis (faster, less thorough)")
@click.option("--format", "-o", "output_format", type=click.Choice(["terminal", "markdown", "json"]), default="terminal")
@click.option("--config", "config_path", help="Path to config file")
@click.option("--strict", is_flag=True, help="Use high strictness (report all severities)")
def scan(
    target: str | None,
    diff_ref: str | None,
    staged: bool,
    intent: str | None,
    spec_file: str | None,
    no_llm: bool,
    output_format: str,
    config_path: str | None,
    strict: bool,
):
    """Scan code for AI-generated bugs, security issues, and intent mismatches."""
    from debuggai.orchestrator import run_scan
    from debuggai.reports.generator import format_json, format_markdown, format_terminal

    # Override strictness if --strict flag
    if strict:
        os.environ["DEBUGGAI_STRICTNESS"] = "high"

    with console.status("[bold blue]Scanning...[/bold blue]"):
        report = run_scan(
            target=target,
            diff_ref=diff_ref,
            staged=staged,
            intent=intent,
            spec_file=spec_file,
            use_llm=not no_llm,
            config_path=config_path,
        )

    # Format output
    if output_format == "json":
        click.echo(format_json(report))
    elif output_format == "markdown":
        click.echo(format_markdown(report))
    else:
        console.print(format_terminal(report))

    # Exit code based on findings
    if report.summary.critical > 0:
        sys.exit(2)
    elif report.summary.major > 0:
        sys.exit(1)
    sys.exit(0)


@main.command()
@click.option("--intent", "-i", required=True, help="Intent to verify")
@click.option("--file", "-f", "target", help="File or directory to verify against")
@click.option("--diff", "-d", "diff_ref", help="Git ref to verify against")
@click.option("--format", "-o", "output_format", type=click.Choice(["terminal", "markdown", "json"]), default="terminal")
@click.option("--config", "config_path", help="Path to config file")
def verify(
    intent: str,
    target: str | None,
    diff_ref: str | None,
    output_format: str,
    config_path: str | None,
):
    """Verify code against a natural language intent. Computes Prompt Fidelity Score."""
    from debuggai.orchestrator import run_scan
    from debuggai.reports.generator import format_json, format_markdown, format_terminal

    with console.status("[bold blue]Verifying intent...[/bold blue]"):
        report = run_scan(
            target=target,
            diff_ref=diff_ref,
            intent=intent,
            use_llm=True,
            config_path=config_path,
        )

    if output_format == "json":
        click.echo(format_json(report))
    elif output_format == "markdown":
        click.echo(format_markdown(report))
    else:
        console.print(format_terminal(report))

    # Exit based on fidelity score
    if report.intent and report.intent.fidelity_score < 50:
        sys.exit(2)
    elif report.intent and report.intent.fidelity_score < 80:
        sys.exit(1)
    sys.exit(0)


@main.command()
def config():
    """Show current DebuggAI configuration."""
    cfg = load_config()
    console.print("[bold]DebuggAI Configuration[/bold]")
    console.print()
    console.print(f"  Project: {cfg.project_name or '[dim]not set[/dim]'}")
    console.print(f"  Type: {cfg.project_type}")
    console.print(f"  Languages: {', '.join(cfg.code.languages) or '[dim]auto-detect[/dim]'}")
    console.print(f"  Strictness: {cfg.code.strictness}")
    console.print(f"  LLM: {'[green]configured[/green]' if cfg.anthropic_api_key else '[yellow]no API key[/yellow]'}")
    console.print()
    console.print("  Rules:")
    for rule, enabled in cfg.code.rules.items():
        status = "[green]on[/green]" if enabled else "[red]off[/red]"
        console.print(f"    {rule}: {status}")


if __name__ == "__main__":
    main()
