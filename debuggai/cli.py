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


@main.command()
@click.option("--claude-code", is_flag=True, default=True, help="Install for Claude Code (default)")
@click.option("--cursor", is_flag=True, help="Install for Cursor")
def setup(claude_code: bool, cursor: bool):
    """Auto-install DebuggAI as an MCP server. One command, then use /scan, /verify, /init."""
    import json as json_mod
    import shutil

    # Find the debuggai-mcp entry point
    debuggai_mcp_path = shutil.which("debuggai-mcp")
    if not debuggai_mcp_path:
        # Fallback: use python -m
        python_path = sys.executable
        mcp_command = python_path
        mcp_args = ["-m", "debuggai.mcp_server"]
    else:
        mcp_command = debuggai_mcp_path
        mcp_args = []

    # Determine config paths
    home = Path.home()
    configs_to_update: list[tuple[str, Path]] = []

    if claude_code or (not cursor):
        claude_config = home / ".claude" / "settings.json"
        configs_to_update.append(("Claude Code", claude_config))

    if cursor:
        cursor_config = home / ".cursor" / "mcp.json"
        configs_to_update.append(("Cursor", cursor_config))

    mcp_entry = {
        "command": mcp_command,
        "args": mcp_args,
    }

    for name, config_path in configs_to_update:
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing config
        existing = {}
        if config_path.exists():
            try:
                existing = json_mod.loads(config_path.read_text())
            except json_mod.JSONDecodeError:
                existing = {}

        # Add/update DebuggAI MCP server
        if "mcpServers" not in existing:
            existing["mcpServers"] = {}

        existing["mcpServers"]["debuggai"] = mcp_entry

        config_path.write_text(json_mod.dumps(existing, indent=2) + "\n")
        console.print(f"[green]Installed for {name}[/green] -> {config_path}")

    console.print()
    console.print("[bold]Setup complete![/bold]")
    console.print()
    console.print("Restart Claude Code / Cursor, then use these slash commands:")
    console.print("  [bold]/scan[/bold]     — Scan code for AI-generated bugs")
    console.print("  [bold]/verify[/bold]   — Verify code matches intent")
    console.print("  [bold]/init[/bold]     — Initialize DebuggAI config")
    console.print()
    console.print("[dim]Or use the tools directly: scan_code, verify_intent, init_project[/dim]")


@main.command()
@click.option("--file", "-f", "target", help="File or directory to generate fixes for")
@click.option("--diff", "-d", "diff_ref", help="Git ref to diff against")
@click.option("--apply", is_flag=True, help="Apply all high-confidence fixes automatically")
@click.option("--min-confidence", default=0.7, help="Minimum confidence for fixes (0.0-1.0)")
def fix(target: str | None, diff_ref: str | None, apply: bool, min_confidence: float):
    """Generate and optionally apply fixes for detected issues."""
    from debuggai.orchestrator import run_scan
    from debuggai.engines.fix import generate_fixes_for_issues, apply_fix

    cfg = load_config()
    if not cfg.anthropic_api_key:
        console.print("[red]Auto-fix requires an Anthropic API key.[/red]")
        console.print("Set ANTHROPIC_API_KEY environment variable.")
        sys.exit(1)

    with console.status("[bold blue]Scanning for issues...[/bold blue]"):
        report = run_scan(target=target, diff_ref=diff_ref, use_llm=False)

    if not report.issues:
        console.print("[green]No issues found — nothing to fix![/green]")
        return

    console.print(f"Found {len(report.issues)} issues. Generating fixes...")

    project_dir = str(Path(target).resolve()) if target and Path(target).is_dir() else str(Path.cwd())

    with console.status("[bold blue]Generating fixes...[/bold blue]"):
        fixes = generate_fixes_for_issues(
            report.issues, project_dir,
            api_key=cfg.anthropic_api_key,
            min_confidence=min_confidence,
        )

    if not fixes:
        console.print("[yellow]Could not generate fixes for any issues.[/yellow]")
        return

    for i, f in enumerate(fixes):
        conf_color = "green" if f["confidence"] >= 0.8 else "yellow" if f["confidence"] >= 0.5 else "red"
        console.print(f"\n[bold]Fix {i+1}[/bold] [{conf_color}]confidence: {f['confidence']:.0%}[/{conf_color}]")
        console.print(f"  [{f['severity'].upper()}] {f['issue_title']}")
        console.print(f"  [dim]{f['file']}:{f['line']}[/dim]")
        console.print(f"  {f['explanation']}")
        if f.get("old_code") and f.get("new_code"):
            console.print(f"  [red]- {f['old_code'][:100]}...[/red]" if len(f['old_code']) > 100 else f"  [red]- {f['old_code']}[/red]")
            console.print(f"  [green]+ {f['new_code'][:100]}...[/green]" if len(f['new_code']) > 100 else f"  [green]+ {f['new_code']}[/green]")

    if apply:
        console.print(f"\n[bold]Applying {len(fixes)} fixes...[/bold]")
        applied = 0
        for f in fixes:
            if apply_fix(f, project_dir):
                applied += 1
                console.print(f"  [green]Applied:[/green] {f['file']}:{f['line']}")
            else:
                console.print(f"  [red]Failed:[/red] {f['file']}:{f['line']}")
        console.print(f"\n[bold]{applied}/{len(fixes)} fixes applied.[/bold]")
    else:
        console.print(f"\n[dim]Run with --apply to apply these fixes.[/dim]")


@main.command()
@click.option("--since", default="30d", help="Time range (e.g., 7d, 30d, 90d)")
@click.option("--format", "-o", "output_format", type=click.Choice(["terminal", "json"]), default="terminal")
def history(since: str, output_format: str):
    """Show scan history and quality trends for the current project."""
    import json as json_mod
    from debuggai.storage import get_db, get_scan_history, get_quality_delta

    db = get_db()
    scans = get_scan_history(db, limit=20)
    delta = get_quality_delta(db, project=scans[0]["project"] if scans else "")
    db.close()

    if not scans:
        console.print("[dim]No scan history yet. Run debuggai scan first.[/dim]")
        return

    if output_format == "json":
        click.echo(json_mod.dumps({"scans": scans, "delta": delta}, indent=2, default=str))
        return

    console.print("[bold]DebuggAI Scan History[/bold]\n")

    if delta:
        d = delta
        delta_str = []
        if d["delta_total"] > 0:
            delta_str.append(f"[red]+{d['delta_total']} issues[/red]")
        elif d["delta_total"] < 0:
            delta_str.append(f"[green]{d['delta_total']} issues[/green]")
        else:
            delta_str.append("[dim]no change[/dim]")
        if d["new_issues"]:
            delta_str.append(f"[red]+{d['new_issues']} new[/red]")
        if d["fixed_issues"]:
            delta_str.append(f"[green]-{d['fixed_issues']} fixed[/green]")
        console.print(f"  Since last scan: {', '.join(delta_str)}\n")

    console.print(f"  {'Timestamp':<22} {'Issues':>6} {'Crit':>5} {'Major':>6} {'Duration':>8}")
    console.print(f"  {'─'*22} {'─'*6} {'─'*5} {'─'*6} {'─'*8}")
    for s in scans[:15]:
        ts = s["timestamp"][:19] if s["timestamp"] else "?"
        dur = f"{s['duration_ms']}ms" if s.get("duration_ms") else "?"
        console.print(f"  {ts:<22} {s['total_issues']:>6} {s['critical']:>5} {s['major']:>6} {dur:>8}")


@main.command()
@click.argument("rule_id")
@click.option("--file-pattern", "-f", help="Only dismiss for files matching this pattern")
@click.option("--reason", "-r", default="", help="Reason for dismissal")
def dismiss(rule_id: str, file_pattern: str | None, reason: str):
    """Dismiss an issue rule. After 3 dismissals, it auto-suppresses."""
    from debuggai.storage import get_db, dismiss_issue, get_dismissals

    db = get_db()
    dismiss_issue(db, rule_id, file_pattern, reason)
    dismissals = get_dismissals(db)
    db.close()

    # Find the dismissal we just updated
    for d in dismissals:
        if d["rule_id"] == rule_id:
            if d["auto_suppress"]:
                console.print(f"[yellow]Rule '{rule_id}' auto-suppressed[/yellow] (dismissed {d['count']}x)")
            else:
                remaining = 3 - d["count"]
                console.print(f"[dim]Rule '{rule_id}' dismissed ({d['count']}x). {remaining} more to auto-suppress.[/dim]")
            break


@main.command()
@click.argument("directory", default=".")
@click.option("--focus", "-f", type=click.Choice(["all", "security", "performance", "deployment"]), default="all")
@click.option("--no-llm", is_flag=True, help="Skip LLM holistic review (faster, cheaper)")
@click.option("--format", "-o", "output_format", type=click.Choice(["terminal", "markdown", "json"]), default="terminal")
def deep(directory: str, focus: str, no_llm: bool, output_format: str):
    """Deep architectural analysis — finds system-level bugs that pattern matching misses."""
    from debuggai.engines.deep.engine import run_deep_analysis
    from debuggai.reports.generator import format_json, format_markdown, format_terminal

    project_dir = str(Path(directory).resolve())
    console.print(f"[bold blue]Deep Analysis[/bold blue] — {Path(project_dir).name}")
    console.print(f"[dim]Focus: {focus} | LLM: {'on' if not no_llm else 'off'}[/dim]\n")

    with console.status("[bold blue]Indexing project...[/bold blue]"):
        report = run_deep_analysis(
            project_dir=project_dir,
            focus=focus,
            use_llm=not no_llm,
        )

    # Show architecture summary
    if report.architecture_summary:
        console.print("[bold]Architecture[/bold]")
        console.print(f"[dim]{report.architecture_summary[:500]}[/dim]\n")

    if report.project_context:
        ctx = report.project_context
        console.print(f"  Deployment: {ctx.get('deployment', '?')} | "
                      f"Frameworks: {', '.join(ctx.get('frameworks', [])) or 'none'} | "
                      f"Files: {ctx.get('total_files', '?')} | "
                      f"Lines: {ctx.get('total_lines', '?')}")
        console.print()

    if output_format == "json":
        click.echo(format_json(report))
    elif output_format == "markdown":
        click.echo(format_markdown(report))
    else:
        console.print(format_terminal(report))

    if report.summary.critical > 0:
        sys.exit(2)
    elif report.summary.major > 0:
        sys.exit(1)
    sys.exit(0)


@main.command()
@click.argument("directory", default=".")
@click.option("--discover", is_flag=True, help="Only discover personas, don't analyze")
@click.option("--persona", "-p", "persona_name", help="Test for a specific persona")
@click.option("--format", "-o", "output_format", type=click.Choice(["terminal", "markdown", "json"]), default="terminal")
def persona(directory: str, discover: bool, persona_name: str | None, output_format: str):
    """Test your software from the customer's perspective. Discovers ICPs and finds UX issues."""
    from debuggai.engines.persona.engine import run_persona_analysis
    from debuggai.reports.generator import format_json, format_markdown, format_terminal

    project_dir = str(Path(directory).resolve())

    with console.status("[bold blue]Discovering personas...[/bold blue]"):
        profile, report = run_persona_analysis(
            project_dir=project_dir,
            persona_name=persona_name,
            discover_only=discover,
        )

    # Show discovered personas
    console.print(f"\n[bold]Personas Discovered[/bold] — {profile.project_name} ({profile.app_type})\n")
    for i, p in enumerate(profile.personas, 1):
        role_color = {"primary": "green", "secondary": "yellow", "tertiary": "dim"}.get(p.role, "dim")
        console.print(f"  {i}. [bold]{p.name}[/bold] [{role_color}]{p.role}[/{role_color}] ({p.tech_level})")
        console.print(f"     {p.description}")
        if p.goals:
            console.print(f"     Goals: {', '.join(p.goals[:3])}")
        if p.pain_points:
            console.print(f"     Pain points: {', '.join(p.pain_points[:3])}")
        if p.key_flows:
            console.print(f"     Key flows: {', '.join(p.key_flows[:4])}")
        console.print()

    if discover or report is None:
        return

    # Show analysis results
    if output_format == "json":
        click.echo(format_json(report))
    elif output_format == "markdown":
        click.echo(format_markdown(report))
    else:
        console.print(format_terminal(report))

    if report.summary.critical > 0:
        sys.exit(2)
    elif report.summary.major > 0:
        sys.exit(1)


@main.command()
def serve():
    """Start the DebuggAI MCP server (used internally by Claude Code / Cursor)."""
    from debuggai.mcp_server import main as mcp_main

    mcp_main()


if __name__ == "__main__":
    main()
