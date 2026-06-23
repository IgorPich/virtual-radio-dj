#!/usr/bin/env python3
"""
Virtual AI Radio DJ — CLI entry point.

Usage:
    python main.py                  # Normal run
    python main.py --debug          # Verbose logging
    python main.py --env .env.dev   # Custom .env file
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import threading

from src.api.app import create_app
from src.audio.ducker import AudioDucker, DuckingConfig
from src.audio.windows_provider import WindowsAudioProvider
from src.config.loader import load_settings
from src.config.schemas import AppSettings
from src.core.orchestrator import RadioDJOrchestrator
from src.llm.client import OllamaClient
from src.llm.trivia_generator import TriviaGenerator
from src.spotify.client import SpotifyClient
from src.spotify.poller import SpotifyPoller
from src.config.modules import load_module_config
from src.tts import create_cohost_tts_provider, create_tts_provider
from src.utils.logger import configure_logging, get_logger
from src.utils.piper_setup import run_piper_setup

_logger = get_logger("main")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="virtual-radio-dj",
        description="AI-powered radio DJ that talks between Spotify tracks.",
    )
    parser.add_argument(
        "--env",
        type=str,
        default=None,
        help="Path to a .env file (default: .env in current directory).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Force DEBUG-level logging for all handlers.",
    )
    return parser.parse_args()


def _build_orchestrator(settings: AppSettings) -> tuple[RadioDJOrchestrator, OllamaClient]:
    """
    Wire all components together and return the orchestrator plus any
    resources that need cleanup.
    """
    # ── Spotify ───────────────────────────────────────────────────────
    spotify_client = SpotifyClient(settings.spotify)
    spotify_client.connect()
    poller = SpotifyPoller(
        client=spotify_client,
        poll_interval_sec=settings.spotify.poll_interval_sec,
    )

    # ── Audio ducking ─────────────────────────────────────────────────
    audio_provider = WindowsAudioProvider(
        process_name=settings.audio.spotify_process_name,
    )
    ducking_config = DuckingConfig(
        duck_target_volume=settings.audio.duck_target_volume,
        duck_in_ms=settings.audio.duck_in_ms,
        duck_out_ms=settings.audio.duck_out_ms,
        tail_silence_ms=settings.audio.tail_silence_ms,
    )
    ducker = AudioDucker(provider=audio_provider, config=ducking_config)

    # ── LLM ───────────────────────────────────────────────────────────
    ollama = OllamaClient(settings.llm)
    trivia = TriviaGenerator(client=ollama)

    # ── TTS ───────────────────────────────────────────────────────────
    tts = create_tts_provider(settings.tts)
    tts_cohost = create_cohost_tts_provider(settings.tts)

    # ── Module config ─────────────────────────────────────────────────
    module_config = load_module_config()

    # ── Orchestrator ──────────────────────────────────────────────────
    orchestrator = RadioDJOrchestrator(
        poller=poller,
        ducker=ducker,
        trivia_generator=trivia,
        tts_provider=tts,
        spotify_client=spotify_client,
        trigger_before_end_sec=settings.spotify.trigger_before_end_sec,
        dj_config=settings.dj,
        module_config=module_config,
        tts_cohost=tts_cohost,
        cohost_name=settings.tts.cohost_name,
    )

    return orchestrator, ollama


async def _async_main(settings: AppSettings) -> None:
    """Run the orchestrator inside the asyncio event loop with clean shutdown."""
    orchestrator, ollama = _build_orchestrator(settings)

    # ── Start Flask web UI in a background daemon thread ──────────────
    flask_app = create_app(orchestrator)
    flask_thread = threading.Thread(
        target=flask_app.run,
        kwargs={
            "host": settings.api.host,
            "port": settings.api.port,
            "use_reloader": False,
            "threaded": True,
        },
        daemon=True,
        name="flask-ui",
    )
    flask_thread.start()
    _logger.info(
        "Midnight Radio UI → http://%s:%d/",
        settings.api.host, settings.api.port,
    )

    # Register signal handlers for graceful exit via Ctrl+C / SIGTERM.
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _request_shutdown() -> None:
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler for all signals.
            signal.signal(sig, lambda _s, _f: _request_shutdown())

    orchestrator_task = asyncio.create_task(orchestrator.start(), name="orchestrator")

    _logger.info("Virtual Radio DJ is running.  Press Ctrl+C to stop.")

    # Wait until a shutdown is requested.
    await shutdown_event.wait()

    _logger.info("Shutting down…")
    await orchestrator.stop()
    await ollama.aclose()
    orchestrator_task.cancel()
    try:
        await orchestrator_task
    except asyncio.CancelledError:
        pass
    _logger.info("Goodbye.")


def main() -> None:
    args = _parse_args()

    # ── Piper auto-setup (runs before settings load so .env is ready) ─
    # Looks for %USERPROFILE%/Downloads/piper/, stages files to piper_tts/,
    # and patches .env with TTS__PROVIDER=piper and the correct paths.
    # Safe to call on every startup — skips silently if already staged.
    run_piper_setup(env_file=args.env)

    settings = load_settings(env_file=args.env)
    configure_logging(debug=args.debug or settings.debug)

    _logger.info("Configuration loaded (debug=%s).", args.debug or settings.debug)
    _logger.info(
        "LLM: %s @ %s | TTS: %s | Audio duck target: %.0f%%",
        settings.llm.model,
        settings.llm.endpoint,
        settings.tts.provider,
        settings.audio.duck_target_volume * 100,
    )
    _logger.info(
        "DJ interval: %d–%d songs | Skip grace: %.0fs",
        settings.dj.song_interval_min,
        settings.dj.song_interval_max,
        settings.dj.skip_grace_period_sec,
    )
    _mc = load_module_config()
    _logger.info(
        "Modules: news=%s | duo=%s | imaging=%s",
        _mc.top_of_hour_news_enabled,
        _mc.duo_mode_enabled,
        _mc.radio_imaging_enabled,
    )

    try:
        asyncio.run(_async_main(settings))
    except KeyboardInterrupt:
        _logger.info("KeyboardInterrupt — exiting.")
    except Exception:
        _logger.exception("Fatal error:")
        sys.exit(1)


if __name__ == "__main__":
    main()
