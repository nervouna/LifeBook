"""Command-line entry point."""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import click

from .config import load_config, POINTER_FILE, resolve_config_path, KnowledgeConfig


@click.group()
@click.option("--config", "config_path", type=click.Path(), default=None, help="Path to config.yaml")
@click.pass_context
def main(ctx: click.Context, config_path: str | None) -> None:
    """LifeBook command-line interface."""
    cfg = load_config(config_path)
    logging.basicConfig(
        level=getattr(logging, cfg.logging.level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    ctx.ensure_object(dict)
    ctx.obj["config"] = cfg


@main.command()
@click.option("--root", "root_path", type=click.Path(), default=None,
              help="Knowledge base root directory (default: ~/Documents/Knowledge).")
@click.pass_context
def init(ctx: click.Context, root_path: str | None) -> None:
    """Initialize LifeBook: create pointer file and directory structure."""
    import shutil

    default_root = Path.home() / "Documents" / "Knowledge"
    root = Path(root_path) if root_path else default_root
    root = root.expanduser().resolve()

    # Use KnowledgeConfig defaults to determine directory names
    cfg = KnowledgeConfig(root=root)
    kb_dirs = [
        cfg.sources_path,
        cfg.topics_path,
        cfg.trajectories_path,
        cfg.publish_path,
        cfg.state_path,
    ]
    root.mkdir(parents=True, exist_ok=True)
    for d in kb_dirs:
        d.mkdir(exist_ok=True)

    ptr = POINTER_FILE
    ptr.parent.mkdir(parents=True, exist_ok=True)
    ptr.write_text(str(root), encoding="utf-8")
    click.echo(f"Pointer file written: {ptr}")

    cfg_target = root / ".lifebook" / "config.yaml"
    if not cfg_target.exists():
        example = Path(__file__).parent / "config.example.yaml"
        if example.exists():
            shutil.copy2(example, cfg_target)
            click.echo(f"Config copied: {cfg_target}")
        else:
            cfg_target.write_text("# LifeBook config\nknowledge:\n  root: {}\n".format(root),
                                 encoding="utf-8")
            click.echo(f"Config created: {cfg_target}")
    else:
        click.echo(f"Config already exists: {cfg_target}")

    click.echo(f"\nKnowledge base root: {root}")
    click.echo("Run 'lifebook doctor' to verify.")


@main.command()
@click.option("--file", "file_path", type=click.Path(exists=True), default=None,
              help="Process a single file instead of scanning inbox.")
@click.option("--watch", is_flag=True, default=False,
              help="Poll inbox directory and process new files automatically.")
@click.option("--interval", type=int, default=30,
              help="Polling interval in seconds for --watch mode (default: 30).")
@click.pass_context
def process(ctx: click.Context, file_path: str | None, watch: bool, interval: int) -> None:
    """Process inbox: classify, tag, link, and create topic notes."""
    from .executor import Executor
    cfg = ctx.obj["config"]
    executor = Executor(cfg)

    if file_path:
        result = executor.process_file(Path(file_path))
        _print_result(result)
        sys.exit(0 if result.ok else 1)

    def _run_once() -> int:
        results = executor.process_inbox()
        ok = sum(1 for r in results if r.ok)
        skipped = sum(1 for r in results if r.skipped_reason)
        failed = sum(1 for r in results if not r.ok and not r.skipped_reason)
        click.echo(f"\nSummary: {len(results)} total | {ok} ok | {skipped} skipped | {failed} failed")
        for r in results:
            _print_result(r)
        return len(results)

    if watch:
        click.echo(f"Watching inbox every {interval}s. Press Ctrl+C to stop.")
        _run_once()
        try:
            while True:
                time.sleep(interval)
                _run_once()
        except KeyboardInterrupt:
            click.echo("\nStopped.")
        return

    _run_once()


def _print_result(r) -> None:
    name = r.source_path.name
    if r.ok and r.topic_path:
        click.echo(f"  ✓ {name}  →  {r.topic_path.name}")
    elif r.skipped_reason:
        click.echo(f"  ⊘ {name}  [{r.skipped_reason}]")
    else:
        click.echo(f"  ✗ {name}  ERROR: {r.error}")


@main.command()
@click.argument("url_or_text")
@click.option("--type", "source_type",
              type=click.Choice(["webclip", "chat_link", "chat_note", "manual"]),
              default="manual")
@click.option("--title", default=None)
@click.pass_context
def ingest(ctx: click.Context, url_or_text: str, source_type: str, title: str | None) -> None:
    """Add a URL or text snippet to the inbox (for quick manual testing)."""
    from .ingest import ingest_url, ingest_text
    cfg = ctx.obj["config"]
    is_url = url_or_text.startswith("http://") or url_or_text.startswith("https://")
    if is_url:
        p = ingest_url(cfg.knowledge, url_or_text, source_type=source_type, title_hint=title)  # type: ignore[arg-type]
    else:
        p = ingest_text(cfg.knowledge, url_or_text, source_type=source_type, title_hint=title)  # type: ignore[arg-type]
    click.echo(f"Ingested: {p}")


@main.command()
@click.pass_context
def digest(ctx: click.Context) -> None:
    """Generate and push today's digest to Feishu."""
    click.echo("[stub] digest — Day 5 implementation pending")


@main.command()
@click.pass_context
def serve(ctx: click.Context) -> None:
    """Start Feishu bot long-connection client."""
    from .feishu import FeishuBot
    cfg = ctx.obj["config"]
    bot = FeishuBot(cfg)
    bot.start()  # blocks


@main.command()
@click.option("--timeout", "timeout_minutes", type=int, default=10,
              help="Rollback files stuck in processing for more than N minutes (default: 10).")
@click.option("--dry-run", is_flag=True, default=False,
              help="Only show what would be rolled back, don't modify files.")
@click.pass_context
def recover(ctx: click.Context, timeout_minutes: int, dry_run: bool) -> None:
    """Roll back files stuck in status:processing back to inbox."""
    from .executor import Executor
    cfg = ctx.obj["config"]
    executor = Executor(cfg)
    stale = executor.recover_stale(timeout_minutes=timeout_minutes, dry_run=dry_run)
    if not stale:
        click.echo(f"No files stuck in processing longer than {timeout_minutes} min.")
        return
    verb = "Would recover" if dry_run else "Recovered"
    click.echo(f"{verb} {len(stale)} file(s):")
    for p, info in stale:
        click.echo(f"  - {p.name}  [{info}]")


@main.command()
@click.option("--full", is_flag=True, help="Perform full rebuild instead of incremental update.")
@click.option("--interval", type=int, default=None, help="Set polling interval in seconds (for background mode).")
@click.pass_context
def index(ctx: click.Context, full: bool, interval: int | None) -> None:
    """Manage vector index: update, rebuild, or start background service."""
    from .indexer import Indexer
    cfg = ctx.obj["config"]
    
    if interval is not None:
        # Start background service with custom interval
        indexer = Indexer(cfg, interval=interval)
        click.echo(f"Starting indexer background service with {interval}s polling interval...")
        indexer.start()
        click.echo("Indexer started. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            click.echo("\nStopping indexer...")
            indexer.stop()
        return
    
    indexer = Indexer(cfg)
    
    if full:
        click.echo("Performing full rebuild...")
        stats = indexer.full_rebuild()
    else:
        click.echo("Performing incremental update...")
        stats = indexer.incremental_update()
    
    upserted = stats.get("upserted", 0)
    deleted = stats.get("deleted", 0)
    unchanged = stats.get("unchanged", 0)
    errors = stats.get("errors", 0)

    click.echo(f"\nIndex update complete:")
    click.echo(f"  Upserted: {upserted}")
    click.echo(f"  Deleted:  {deleted}")
    click.echo(f"  Unchanged: {unchanged}")
    if errors:
        click.echo(f"  Errors: {errors}")


@main.command()
@click.argument("query")
@click.option("--limit", type=int, default=10, help="Maximum number of results (default: 10).")
@click.pass_context
def search(ctx: click.Context, query: str, limit: int) -> None:
    """Search knowledge base using vector similarity."""
    from .vector import VectorIndex
    cfg = ctx.obj["config"]

    persist_dir = cfg.knowledge.vector_store_path
    vector = VectorIndex(persist_dir)
    results = vector.search(query, n_results=limit)

    if not results:
        click.echo(f"No results found for '{query}'")
        return

    click.echo(f"Found {len(results)} results for '{query}':\n")

    for i, r in enumerate(results, 1):
        title = r.metadata.get("title", r.doc_id)
        similarity = max(0, 1.0 - r.distance) * 100
        preview = r.text[:80] + "..." if len(r.text) > 80 else r.text

        click.echo(f"{i}. {title}")
        click.echo(f"   Similarity: {similarity:.1f}%")
        click.echo(f"   Path: {r.doc_id}")
        click.echo(f"   Preview: {preview}")
        click.echo()


def _mask(value: str, visible: int = 4) -> str:
    """Mask a secret, showing only the last few characters."""
    if not value:
        return "(empty)"
    if len(value) <= visible:
        return "*" * len(value)
    return "*" * (len(value) - visible) + value[-visible:]


@main.command()
@click.pass_context
def doctor(ctx: click.Context) -> None:
    """Check configuration and environment."""
    cfg = ctx.obj["config"]
    checks: list[tuple[str, bool, str]] = []

    config_source = resolve_config_path()
    click.echo(f"  Config:  {config_source}\n")

    for name, path in [
        ("Knowledge root", cfg.knowledge.root),
        ("Sources dir", cfg.knowledge.sources_path),
        ("Topics dir", cfg.knowledge.topics_path),
        ("Trajectories dir", cfg.knowledge.trajectories_path),
        ("State dir", cfg.knowledge.state_path),
    ]:
        checks.append((name, path.exists(), str(path)))

    checks.append(("LLM API key", bool(cfg.llm.api_key), _mask(cfg.llm.api_key)))
    checks.append(("LLM model", True, f"{cfg.llm.model} (digest: {cfg.llm.digest_model})"))
    checks.append(("Tavily API key", bool(cfg.tavily.api_key), _mask(cfg.tavily.api_key)))
    checks.append(("Feishu app_id", bool(cfg.feishu.app_id), cfg.feishu.app_id or "(empty)"))
    checks.append(("Feishu digest chat_id", bool(cfg.feishu.digest_chat_id),
                   cfg.feishu.digest_chat_id or "(empty)"))
    checks.append(("TTS API key", bool(cfg.tts.api_key), _mask(cfg.tts.api_key)))
    checks.append(("TTS model", True, f"{cfg.tts.model} ({cfg.tts.voice_id})"))

    for name, ok, detail in checks:
        mark = "✓" if ok else "✗"
        click.echo(f"  {mark}  {name:<28} {detail}")


@main.command("publish")
@click.option("--force", is_flag=True, default=False, help="Force publish even if checklist has items.")
@click.pass_context
def publish_cmd(ctx: click.Context, force: bool) -> None:
    """Publish the current draft to the knowledge base."""
    from .writer import Writer
    from .llm import LLMClient
    cfg = ctx.obj["config"]
    w = Writer(cfg, LLMClient(cfg.llm))
    result = w.publish(force=force)
    click.echo(result)


@main.command("writer-status")
@click.pass_context
def writer_status_cmd(ctx: click.Context) -> None:
    """Show writer session status."""
    from .writer import Writer
    from .llm import LLMClient
    cfg = ctx.obj["config"]
    w = Writer(cfg, LLMClient(cfg.llm))
    if w.active:
        click.echo(f"写作模式：进行中（阶段：{w.stage}）")
    else:
        click.echo("写作模式：未启动")


@main.command("restore")
@click.pass_context
def restore_cmd(ctx: click.Context) -> None:
    """Restore draft from backup."""
    from .writer import Writer
    from .llm import LLMClient
    cfg = ctx.obj["config"]
    w = Writer(cfg, LLMClient(cfg.llm))
    result = w.restore_draft()
    click.echo(result)


def _send_to_feishu(cfg, gen, audio_bytes: bytes, output: str, chat_id: str | None) -> None:
    """Convert audio to opus and send to Feishu."""
    from .feishu_transport import FeishuTransport

    feishu_cfg = cfg.feishu_podcast or cfg.feishu
    if not chat_id:
        chat_id = feishu_cfg.podcast_chat_id or cfg.feishu.digest_chat_id
    if not chat_id:
        click.echo("Error: no chat_id. Use --chat-id or set podcast_chat_id/digest_chat_id in config.")
        sys.exit(1)
    transport = FeishuTransport(feishu_cfg)
    click.echo("Converting to opus for Feishu...")
    opus_bytes = gen.convert_to_opus(audio_bytes)
    opus_tmp = Path(output).with_suffix(".opus")
    opus_tmp.write_bytes(opus_bytes)
    opus_duration = gen.get_duration(opus_tmp)
    click.echo(f"Opus: {len(opus_bytes)} bytes ({opus_duration}s)")

    file_key = transport.upload_file(
        opus_bytes, opus_tmp.name,
        file_type="opus", duration=opus_duration,
    )
    opus_tmp.unlink(missing_ok=True)
    if not file_key:
        click.echo("Error: file upload failed")
        sys.exit(1)
    msg_id = transport.send_audio(chat_id, file_key)
    if msg_id:
        click.echo(f"Sent to Feishu: {msg_id}")
    else:
        click.echo("Error: send audio failed")
        sys.exit(1)


@main.command("podcast")
@click.argument("note_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Save audio to file (default: <note_stem>_podcast.mp3).")
@click.option("--send", "send_to_feishu", is_flag=True, default=False,
              help="Send audio to Feishu chat.")
@click.option("--chat-id", default=None, help="Feishu chat_id for --send.")
@click.pass_context
def podcast_cmd(ctx: click.Context, note_path: str, output: str | None,
                send_to_feishu: bool, chat_id: str | None) -> None:
    """Generate a podcast episode from a topic note."""
    from .llm import LLMClient
    from .podcast import PodcastGenerator
    from .feishu_transport import FeishuTransport

    cfg = ctx.obj["config"]
    note = Path(note_path)
    gen = PodcastGenerator(cfg, llm=LLMClient(cfg.llm))

    click.echo(f"Generating podcast from: {note.name}")
    audio_bytes, duration = gen.generate(note)
    click.echo(f"Audio: {len(audio_bytes)} bytes (~{duration}s)")

    if output is None:
        output = str(note.with_name(f"{note.stem}_podcast.mp3"))
    Path(output).write_bytes(audio_bytes)
    click.echo(f"Saved: {output}")

    if send_to_feishu:
        _send_to_feishu(cfg, gen, audio_bytes, output, chat_id)


@main.command("podcast-multi")
@click.option("--since", required=True, help="Include notes modified on or after this date (YYYY-MM-DD).")
@click.option("--limit", default=10, show_default=True, help="Max number of notes.")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Save audio to file.")
@click.option("--send", "send_to_feishu", is_flag=True, default=False,
              help="Send audio to Feishu chat.")
@click.option("--chat-id", default=None, help="Feishu chat_id for --send.")
@click.pass_context
def podcast_multi_cmd(ctx: click.Context, since: str, limit: int, output: str | None,
                      send_to_feishu: bool, chat_id: str | None) -> None:
    """Generate a combined podcast from recent notes."""
    import datetime as dt

    from .llm import LLMClient
    from .podcast import PodcastGenerator, select_notes
    from .feishu_transport import FeishuTransport

    cfg = ctx.obj["config"]
    since_date = dt.date.fromisoformat(since)
    notes, total = select_notes(cfg.knowledge.topics_path, since_date, limit)

    if not notes:
        click.echo(f"No notes found since {since}")
        sys.exit(1)

    has_more = total > limit
    click.echo(f"Found {total} notes since {since}, using {len(notes)}")
    for n in notes:
        click.echo(f"  - {n.stem}")

    gen = PodcastGenerator(cfg, llm=LLMClient(cfg.llm))
    click.echo("Generating combined podcast...")
    audio_bytes, duration = gen.generate_multi(notes, has_more)
    click.echo(f"Audio: {len(audio_bytes)} bytes (~{duration}s)")

    if output is None:
        date_str = since_date.isoformat()
        output = str(cfg.knowledge.topics_path / f"podcast_{date_str}_multi.mp3")
    Path(output).write_bytes(audio_bytes)
    click.echo(f"Saved: {output}")

    if send_to_feishu:
        _send_to_feishu(cfg, gen, audio_bytes, output, chat_id)


if __name__ == "__main__":
    main()
