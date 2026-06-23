"""Piper TTS provider — local text-to-speech via the piper.exe binary."""

from __future__ import annotations

import asyncio
from pathlib import Path

from src.tts.exceptions import TTSSynthesisError
from src.tts.provider import TTSProvider
from src.utils.logger import get_logger
from src.utils.timing_utils import words_to_seconds

_logger = get_logger("tts.piper")

# Ryan (high quality) speaks at roughly 170 WPM.
_PIPER_WPM = 170

# Location of THIS file:  src/tts/piper_tts.py
#   parents[0] = src/tts/
#   parents[1] = src/
#   parents[2] = project root
_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
_STAGE_DIR: Path = _PROJECT_ROOT / "piper_tts"
_DEFAULT_EXE: str = "piper.exe"
_DEFAULT_MODEL: str = "en_US-ryan-high.onnx"


def _resolve_paths(model_path: str, exe_path: str) -> tuple[Path, Path]:
    """
    Resolve and validate the paths to the model and the piper.exe binary.

    If either path is empty, the staged ``piper_tts/`` directory is
    checked automatically so the application works out-of-the-box after
    the setup routine has run.

    Raises:
        ValueError: If the model path cannot be resolved.
        FileNotFoundError: If either resolved path does not exist.
    """
    # ── Model ─────────────────────────────────────────────────────────
    if not model_path:
        candidate = _STAGE_DIR / _DEFAULT_MODEL
        if candidate.exists():
            model_path = str(candidate)
        else:
            raise ValueError(
                "Piper model path is required.  "
                "Set TTS__PIPER_MODEL_PATH in your .env file, or place "
                f"{_DEFAULT_MODEL} in {_STAGE_DIR}."
            )

    resolved_model = Path(model_path)
    if not resolved_model.exists():
        raise FileNotFoundError(
            f"Piper model not found: {resolved_model}.  "
            "Download en_US-ryan-high.onnx from https://github.com/rhasspy/piper/releases "
            "and set TTS__PIPER_MODEL_PATH."
        )

    # ── Executable ────────────────────────────────────────────────────
    if not exe_path:
        # 1) Same directory as the model file.
        candidate = resolved_model.parent / _DEFAULT_EXE
        if candidate.exists():
            exe_path = str(candidate)
        # 2) Staged project directory.
        elif (_STAGE_DIR / _DEFAULT_EXE).exists():
            exe_path = str(_STAGE_DIR / _DEFAULT_EXE)
        else:
            raise FileNotFoundError(
                f"piper.exe not found near the model ({resolved_model.parent}) "
                f"or in the staged directory ({_STAGE_DIR}).  "
                "Set TTS__PIPER_EXE_PATH in your .env file."
            )

    resolved_exe = Path(exe_path)
    if not resolved_exe.exists():
        raise FileNotFoundError(
            f"piper.exe not found: {resolved_exe}.  "
            "Set TTS__PIPER_EXE_PATH in your .env file."
        )

    return resolved_model, resolved_exe


class PiperTTSProvider(TTSProvider):
    """
    Local text-to-speech using the `piper <https://github.com/rhasspy/piper>`_
    binary distribution (``piper.exe``).

    Spawns ``piper.exe`` as a subprocess, pipes the text to its stdin, and
    reads the WAV file it produces.  The binary must be staged (see
    ``src/utils/piper_setup.py``) before this provider can be used.

    The binary must run from its own directory so that Windows DLL
    resolution succeeds — this is handled automatically via ``cwd``.

    Args:
        model_path: Path to the ``.onnx`` voice model file.  If empty,
                    ``piper_tts/en_US-ryan-high.onnx`` is used.
        exe_path:   Path to ``piper.exe``.  If empty, it is auto-discovered
                    from the model directory or the staged folder.
        speaker_id: Speaker index for multi-speaker models (usually *None*).
    """

    def __init__(
        self,
        model_path: str,
        exe_path: str = "",
        speaker_id: int | None = None,
    ) -> None:
        self._model_path, self._exe_path = _resolve_paths(model_path, exe_path)
        self._speaker_id = speaker_id
        _logger.info(
            "Piper TTS ready — exe: %s  model: %s",
            self._exe_path.name,
            self._model_path.name,
        )

    # ── TTSProvider interface ─────────────────────────────────────────

    @property
    def audio_suffix(self) -> str:
        return ".wav"

    async def synthesize(self, text: str, output_path: Path) -> bool:
        """Synthesize *text* to a WAV file at *output_path* via piper.exe."""
        _logger.info("Synthesizing TTS (%d chars) → %s", len(text), output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await self._run_piper(text, output_path)
        except Exception as exc:
            raise TTSSynthesisError(f"Piper synthesis failed: {exc}") from exc

        exists = output_path.exists()
        if not exists:
            _logger.error(
                "piper.exe returned success but output file is missing: %s",
                output_path,
            )
        return exists

    async def estimate_duration(self, text: str) -> float:
        """Estimate speech duration at ~170 WPM with 20 % safety margin."""
        return words_to_seconds(text, wpm=_PIPER_WPM) * 1.2

    # ── Internal ──────────────────────────────────────────────────────

    async def _run_piper(self, text: str, output_path: Path) -> None:
        """
        Invoke ``piper.exe`` as an async subprocess.

        Text is written to stdin; the binary writes the WAV to
        *output_path*.  ``cwd`` is set to the binary's directory so
        Windows can locate the bundled DLLs.
        """
        cmd: list[str] = [
            str(self._exe_path),
            "--model", str(self._model_path),
            "--output_file", str(output_path),
        ]
        if self._speaker_id is not None:
            cmd += ["--speaker", str(self._speaker_id)]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._exe_path.parent),
        )
        _, stderr_bytes = await proc.communicate(input=text.encode("utf-8"))

        if proc.returncode != 0:
            raise RuntimeError(
                f"piper.exe exited with code {proc.returncode}: "
                f"{stderr_bytes.decode(errors='replace')[:400]}"
            )

