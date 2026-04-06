"""
Pre-flight check: verify all dependencies and external services.

Run:
  python scripts/verify_setup.py
"""

from __future__ import annotations

import importlib
import shutil
import sys


def _check(label: str, ok: bool, detail: str = "") -> bool:
    status = "OK" if ok else "FAIL"
    msg = f"  [{status}] {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return ok


def main() -> None:
    print("Virtual Radio DJ — Setup Verification\n")
    all_ok = True

    # ── Python version ────────────────────────────────────────────────
    py = sys.version_info
    all_ok &= _check(
        "Python >= 3.10",
        py >= (3, 10),
        f"Found {py.major}.{py.minor}.{py.micro}",
    )

    # ── Required packages ─────────────────────────────────────────────
    packages = [
        "pycaw",
        "spotipy",
        "httpx",
        "pydantic",
        "pydantic_settings",
        "flask",
        "gtts",
        "pygame",
        "yaml",     # PyYAML
        "pytest",
    ]
    for pkg in packages:
        try:
            mod = importlib.import_module(pkg)
            version = getattr(mod, "__version__", "unknown")
            all_ok &= _check(f"import {pkg}", True, f"v{version}")
        except ImportError:
            all_ok &= _check(f"import {pkg}", False, "not installed")

    # ── Ollama CLI ────────────────────────────────────────────────────
    ollama_path = shutil.which("ollama")
    all_ok &= _check(
        "ollama CLI on PATH",
        ollama_path is not None,
        ollama_path or "not found — install from https://ollama.ai",
    )

    # ── Ollama server reachability ────────────────────────────────────
    try:
        import httpx

        resp = httpx.get("http://localhost:11434/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        all_ok &= _check(
            "Ollama server running",
            resp.status_code == 200,
            f"models: {', '.join(models) or 'none pulled'}",
        )
    except Exception as exc:
        all_ok &= _check("Ollama server running", False, str(exc))

    # ── .env file ─────────────────────────────────────────────────────
    from pathlib import Path

    env_path = Path(".env")
    all_ok &= _check(
        ".env file exists",
        env_path.exists(),
        str(env_path.resolve()) if env_path.exists() else "copy .env.example → .env",
    )

    # ── Summary ───────────────────────────────────────────────────────
    print()
    if all_ok:
        print("All checks passed.  You're ready to run!")
    else:
        print("Some checks failed.  Fix the issues above before running.")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
