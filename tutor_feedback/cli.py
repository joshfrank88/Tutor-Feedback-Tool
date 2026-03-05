"""Typer CLI for the tutor-feedback pipeline."""

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Dict, List, Optional

import typer
from rich.console import Console
from rich.table import Table

from tutor_feedback import __version__
from tutor_feedback.config import get_settings
from tutor_feedback.utils import setup_logging, open_in_finder, require_key

app = typer.Typer(
    name="tutor-feedback",
    help="Turn tutoring session recordings into platform-specific feedback.",
    add_completion=False,
)
console = Console()


@app.command()
def run(
    file: Annotated[
        Path,
        typer.Argument(help="Path to the audio/video recording file."),
    ],
    student: Annotated[
        str,
        typer.Option("--student", "-s", help="Student's first name."),
    ],
    platform: Annotated[
        List[str],
        typer.Option("--platform", "-p", help="Platform style(s) to render. Repeat for multiple."),
    ],
    transcript: Annotated[
        Optional[Path],
        typer.Option("--transcript", "-t", help="Existing transcript.json to skip re-transcribing."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Create folder structure without calling Whisper/Claude."),
    ] = False,
    open_folder: Annotated[
        bool,
        typer.Option("--open", help="Open session folder in Finder when done."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable debug logging."),
    ] = False,
) -> None:
    """Run the full feedback pipeline on a recording."""
    log = setup_logging(verbose)
    settings = get_settings()
    timings: Dict[str, float] = {}

    # ── Pre-flight checks ──────────────────────────────────────────
    from tutor_feedback.ffmpeg_utils import check_ffmpeg, validate_input_file

    check_ffmpeg()
    input_path = validate_input_file(file)

    if not dry_run:
        require_key(settings.anthropic_api_key)

    # Validate platforms
    from tutor_feedback.styles import list_styles, load_style

    available = list_styles(settings.styles_dir)
    for p in platform:
        if p not in available:
            console.print(
                f"[bold red]Error:[/] Unknown platform '{p}'. "
                f"Available: {', '.join(available)}"
            )
            raise typer.Exit(1)

    # ── Create session folder ──────────────────────────────────────
    from tutor_feedback.storage import create_session_folder, save_meta, save_to_db
    from tutor_feedback.models import SessionMeta

    now = datetime.now()
    session_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    session_dir = create_session_folder(settings.data_dir, student, now)

    meta = SessionMeta(
        session_id=session_id,
        student_name=student,
        input_file=str(input_path),
        session_folder=str(session_dir),
        whisper_model=settings.whisper_model,
        claude_model=settings.claude_model,
        platforms=platform,
        dry_run=dry_run,
    )

    if dry_run:
        console.print("[bold yellow]DRY RUN[/] – skipping transcription and Claude calls.")
        save_meta(session_dir, meta)
        console.print(f"Session folder created: [bold]{session_dir}[/]")
        if open_folder:
            open_in_finder(session_dir)
        raise typer.Exit(0)

    # ── Step 1: Convert audio ──────────────────────────────────────
    from tutor_feedback.ffmpeg_utils import convert_to_wav, get_audio_duration

    wav_path = session_dir / "audio.wav"
    t0 = time.time()
    convert_to_wav(input_path, wav_path)
    timings["convert"] = round(time.time() - t0, 2)

    duration_minutes = get_audio_duration(wav_path) / 60.0

    # ── Step 2: Transcribe ─────────────────────────────────────────
    from tutor_feedback.transcribe import (
        transcribe,
        save_transcript,
        load_transcript_json,
    )

    if transcript and transcript.is_file():
        log.info("Using existing transcript: %s", transcript)
        segments = load_transcript_json(transcript)
        plain_lines = []
        for seg in segments:
            m, s = divmod(int(seg.get("start", 0)), 60)
            plain_lines.append(f"[{m}:{s:02d}] {seg.get('text', '')}")
        plain_text = "\n".join(plain_lines)
        save_transcript(session_dir, plain_text, segments)
        timings["transcribe"] = 0.0
    else:
        t0 = time.time()
        plain_text, segments = transcribe(wav_path, settings.whisper_model)
        timings["transcribe"] = round(time.time() - t0, 2)
        save_transcript(session_dir, plain_text, segments)

    # ── Step 3: Claude Stage A – Extract ───────────────────────────
    from tutor_feedback.claude_extract import extract_session

    t0 = time.time()
    extracted, extract_elapsed = extract_session(
        transcript_json=segments,
        student_name=student,
        session_datetime=now.isoformat(),
        duration_minutes=duration_minutes,
        api_key=settings.anthropic_api_key,
        model=settings.claude_model,
    )
    timings["extract"] = round(time.time() - t0, 2)

    extracted_path = session_dir / "extracted.json"
    extracted_path.write_text(
        json.dumps(extracted.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Saved extracted.json")

    # ── Step 4: Claude Stage B – Render per platform ───────────────
    from tutor_feedback.claude_render import render_feedback, render_homework

    for p in platform:
        style = load_style(p, settings.styles_dir)
        t0 = time.time()
        feedback_text, render_elapsed = render_feedback(
            extracted,
            style,
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
        )
        timings[f"render_{p}"] = round(time.time() - t0, 2)

        fb_path = session_dir / f"feedback_{p}.txt"
        fb_path.write_text(feedback_text, encoding="utf-8")
        log.info("Saved feedback_%s.txt (%d words)", p, len(feedback_text.split()))

    # ── Homework summary ───────────────────────────────────────────
    hw_text = render_homework(extracted)
    (session_dir / "homework.txt").write_text(hw_text, encoding="utf-8")

    # ── Save metadata ──────────────────────────────────────────────
    meta.timings = timings
    save_meta(session_dir, meta)
    save_to_db(settings.data_dir, meta)

    # ── Summary ────────────────────────────────────────────────────
    console.print()
    console.print("[bold green]Pipeline complete![/]")
    console.print(f"  Session folder: [bold]{session_dir}[/]")
    console.print(f"  Transcript:     {len(segments)} segments")
    console.print(f"  Platforms:      {', '.join(platform)}")
    for k, v in timings.items():
        console.print(f"  {k:16s} {v:.1f}s")

    if open_folder:
        open_in_finder(session_dir)


@app.command(name="list-styles")
def list_styles_cmd(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show style card details."),
    ] = False,
) -> None:
    """List available platform style cards."""
    setup_logging(verbose)
    settings = get_settings()

    from tutor_feedback.styles import list_styles, load_style, get_example_count

    styles = list_styles(settings.styles_dir)
    if not styles:
        console.print(f"[yellow]No style cards found in {settings.styles_dir}[/]")
        raise typer.Exit(1)

    table = Table(title="Available Style Cards")
    table.add_column("Name", style="bold")
    table.add_column("Format")
    table.add_column("Word Limit", justify="right")
    table.add_column("Examples", justify="right")
    table.add_column("Sections")

    for name in styles:
        style = load_style(name, settings.styles_dir)
        n_examples = get_example_count(name, settings.styles_dir)
        ex_display = str(n_examples) if n_examples else "[dim]0[/dim]"
        table.add_row(
            style.name,
            style.format,
            str(style.word_limit),
            ex_display,
            ", ".join(style.required_sections) if style.required_sections else "[dim]—[/dim]",
        )

    console.print(table)
    if any(get_example_count(n, settings.styles_dir) == 0 for n in styles):
        console.print(
            "\n[dim]Tip: Add example feedback to[/] styles/<platform>/examples/*.txt "
            "[dim]for better voice matching.[/]"
        )


@app.command(name="add-example")
def add_example_cmd(
    platform_name: Annotated[
        str,
        typer.Argument(help="Platform name (e.g. intergreat, simpletext)."),
    ],
    file: Annotated[
        Optional[Path],
        typer.Argument(help="Text file to add. If omitted, reads from stdin."),
    ] = None,
) -> None:
    """Add a feedback example for voice matching."""
    import sys as _sys

    setup_logging(False)
    settings = get_settings()

    from tutor_feedback.styles import list_styles

    available = list_styles(settings.styles_dir)
    if platform_name not in available:
        console.print(
            f"[bold red]Error:[/] Unknown platform '{platform_name}'. "
            f"Available: {', '.join(available)}"
        )
        raise typer.Exit(1)

    examples_dir = settings.styles_dir / platform_name / "examples"
    examples_dir.mkdir(parents=True, exist_ok=True)

    if file and file.is_file():
        content = file.read_text(encoding="utf-8").strip()
    else:
        if file:
            console.print(f"[bold red]Error:[/] File not found: {file}")
            raise typer.Exit(1)
        console.print("[dim]Paste your example feedback, then press Ctrl+D when done:[/]")
        content = _sys.stdin.read().strip()

    if not content:
        console.print("[bold red]Error:[/] Empty example, nothing saved.")
        raise typer.Exit(1)

    existing = list(examples_dir.glob("*.txt"))
    # Skip README.txt when counting
    existing = [f for f in existing if f.name.lower() != "readme.txt"]
    next_num = len(existing) + 1
    out_path = examples_dir / f"{next_num:02d}.txt"
    out_path.write_text(content + "\n", encoding="utf-8")

    console.print(f"[bold green]Saved[/] example {next_num} for [bold]{platform_name}[/] → {out_path}")
    console.print(f"  Total examples: {next_num}")


@app.command()
def validate(
    session_folder: Annotated[
        Path,
        typer.Argument(help="Path to a session output folder to validate."),
    ],
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable debug logging."),
    ] = False,
) -> None:
    """Validate outputs in a session folder."""
    setup_logging(verbose)
    settings = get_settings()

    from tutor_feedback.validate import validate_session_folder

    folder = Path(session_folder).resolve()
    if not folder.is_dir():
        console.print(f"[bold red]Error:[/] Not a directory: {folder}")
        raise typer.Exit(1)

    results = validate_session_folder(folder, settings.styles_dir)

    all_ok = True
    for filename, errors in results.items():
        if errors:
            all_ok = False
            console.print(f"[bold red]✗[/] {filename}")
            for e in errors:
                console.print(f"    {e}")
        else:
            console.print(f"[bold green]✓[/] {filename}")

    if all_ok:
        console.print("\n[bold green]All outputs valid![/]")
    else:
        console.print("\n[bold red]Validation issues found.[/]")
        raise typer.Exit(1)


@app.command()
def serve(
    port: Annotated[
        int,
        typer.Option("--port", help="Port to run the web UI on."),
    ] = 8000,
    host: Annotated[
        str,
        typer.Option("--host", help="Host to bind to."),
    ] = "127.0.0.1",
    open_browser: Annotated[
        bool,
        typer.Option("--open/--no-open", help="Open browser automatically."),
    ] = True,
) -> None:
    """Launch the web UI."""
    import uvicorn

    setup_logging(False)
    console.print(f"Starting web UI at [bold]http://{host}:{port}[/]")

    if open_browser:
        import threading
        import webbrowser
        threading.Timer(1.2, lambda: webbrowser.open(f"http://{host}:{port}")).start()

    uvicorn.run("tutor_feedback.web:app", host=host, port=port, log_level="warning")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", help="Show version and exit."),
    ] = False,
) -> None:
    """Tutor Feedback Pipeline – turn lesson recordings into platform-specific feedback."""
    if version:
        console.print(f"tutor-feedback {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
