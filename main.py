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

from src.audio.ducker import AudioDucker, DuckingConfig
from src.audio.windows_provider import WindowsAudioProvider
from src.config.loader import load_settings
from src.config.schemas import AppSettings
from src.core.orchestrator import RadioDJOrchestrator
from src.llm.client import OllamaClient
from src.llm.trivia_generator import TriviaGenerator
from src.spotify.client import SpotifyClient
from src.spotify.poller import SpotifyPoller
from src.tts import create_tts_provider
from src.utils.logger import configure_logging, get_logger

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

    # ── Orchestrator ──────────────────────────────────────────────────
    orchestrator = RadioDJOrchestrator(
        poller=poller,
        ducker=ducker,
        trivia_generator=trivia,
        tts_provider=tts,
        trigger_before_end_sec=settings.spotify.trigger_before_end_sec,
    )

    return orchestrator, ollama


async def _async_main(settings: AppSettings) -> None:
    """Run the orchestrator inside the asyncio event loop with clean shutdown."""
    orchestrator, ollama = _build_orchestrator(settings)

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

    try:
        asyncio.run(_async_main(settings))
    except KeyboardInterrupt:
        _logger.info("KeyboardInterrupt — exiting.")
    except Exception:
        _logger.exception("Fatal error:")
        sys.exit(1)


if __name__ == "__main__":
    main()
