"""
Piper TTS auto-setup — locates the binary distribution in the user's
Downloads folder and stages it into the project directory.

Called once at startup.  Safe to call repeatedly: if the files are
already staged it returns immediately.

Expected layout inside ``%USERPROFILE%/Downloads/piper/``:
    piper.exe
    en_US-ryan-high.onnx
    en_US-ryan-high.onnx.json   (optional config sidecar — copied if present)
    *.dll                        (runtime DLLs — copied wholesale)
    espeak-ng-data/              (phoneme data directory — copied wholesale)
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from src.utils.logger import get_logger

_logger = get_logger("setup.piper")

# ── Constants ─────────────────────────────────────────────────────────────────

# Location of THIS file:  src/utils/piper_setup.py
#   parents[0] = src/utils/
#   parents[1] = src/
#   parents[2] = project root
_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

_STAGE_DIR: Path = _PROJECT_ROOT / "piper_tts"

_EXE_FILE: str = "piper.exe"
_MODEL_FILE: str = "en_US-ryan-high.onnx"
_REQUIRED: tuple[str, ...] = (_EXE_FILE, _MODEL_FILE)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _already_staged() -> bool:
    """Return True when both required files exist in the stage directory."""
    return all((_STAGE_DIR / f).exists() for f in _REQUIRED)


def _find_downloads_folder() -> Path | None:
    """
    Return the path to ``%USERPROFILE%/Downloads/piper`` if it exists and
    contains all required files.  Returns *None* otherwise.
    """
    downloads_piper = Path.home() / "Downloads" / "piper"
    if not downloads_piper.is_dir():
        _logger.debug("Downloads/piper not found — skipping auto-setup.")
        return None

    missing = [f for f in _REQUIRED if not (downloads_piper / f).exists()]
    if missing:
        _logger.warning(
            "Found Downloads/piper but required file(s) missing: %s  "
            "Expected: %s",
            missing,
            list(_REQUIRED),
        )
        return None

    return downloads_piper


def _copy_all(source_dir: Path) -> None:
    """Copy the entire contents of *source_dir* into ``piper_tts/``."""
    _STAGE_DIR.mkdir(exist_ok=True)
    count = 0
    for item in source_dir.iterdir():
        dest = _STAGE_DIR / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)
        count += 1
    _logger.info(
        "Staged %d item(s) from %s → %s", count, source_dir, _STAGE_DIR
    )


def _patch_env(env_path: Path) -> None:
    """
    Update (or create) the .env file, injecting Piper paths and activating
    the provider.  Existing values for a key are replaced; new keys are
    appended under a labelled section.
    """
    content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""

    updates = {
        "TTS__PROVIDER": "piper",
        "TTS__PIPER_EXE_PATH": (_STAGE_DIR / _EXE_FILE).as_posix(),
        "TTS__PIPER_MODEL_PATH": (_STAGE_DIR / _MODEL_FILE).as_posix(),
    }

    new_keys: dict[str, str] = {}
    for key, value in updates.items():
        pattern = rf"^{key}\s*=.*$"
        replacement = f'{key}="{value}"'
        if re.search(pattern, content, re.MULTILINE):
            content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
        else:
            new_keys[key] = value

    if new_keys:
        section = "\n# ─── Piper TTS (auto-configured) ────────────────────────────────────────────\n"
        for key, value in new_keys.items():
            section += f'{key}="{value}"\n'
        content = content.rstrip() + "\n" + section

    env_path.write_text(content, encoding="utf-8")
    _logger.info("Updated %s with Piper TTS configuration.", env_path.name)


# ── Public API ────────────────────────────────────────────────────────────────


def run_piper_setup(env_file: str | None = None) -> bool:
    """
    Locate, stage, and configure the Piper binary distribution.

    The function is **idempotent**: if ``piper_tts/piper.exe`` and
    ``piper_tts/en_US-ryan-high.onnx`` already exist it returns *True*
    immediately without touching the filesystem again.

    Steps when staging is needed:
    1. Look for ``%USERPROFILE%/Downloads/piper/``.
    2. Verify ``piper.exe`` and ``en_US-ryan-high.onnx`` are present.
    3. Copy the **entire** folder contents (DLLs, subdirs, model files)
       into ``<project_root>/piper_tts/``.
    4. Update the .env file with ``TTS__PROVIDER``,
       ``TTS__PIPER_EXE_PATH``, and ``TTS__PIPER_MODEL_PATH``.

    Args:
        env_file: Path to the .env file to update.  Defaults to
                  ``<project_root>/.env``.

    Returns:
        *True* if Piper files are available (already staged or just
        staged successfully), *False* if the Downloads folder was not
        found and no staging happened.
    """
    if _already_staged():
        _logger.debug(
            "Piper already staged at %s — skipping copy.", _STAGE_DIR
        )
        return True

    source = _find_downloads_folder()
    if source is None:
        return False

    _logger.info(
        "Piper distribution found at %s — staging to project directory…",
        source,
    )
    _copy_all(source)

    env_path = Path(env_file) if env_file else _PROJECT_ROOT / ".env"
    _patch_env(env_path)

    _logger.info(
        "Piper TTS staged successfully.  "
        "TTS__PROVIDER has been set to 'piper' in %s.",
        env_path.name,
    )
    return True


def get_staged_paths() -> tuple[Path, Path] | None:
    """
    Return ``(exe_path, model_path)`` from the stage directory, or *None*
    if the files are not yet staged.
    """
    exe = _STAGE_DIR / _EXE_FILE
    model = _STAGE_DIR / _MODEL_FILE
    if exe.exists() and model.exists():
        return exe, model
    return None
