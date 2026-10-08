#!/usr/bin/env python3
"""Print the environment facts the project depends on (doc 11 "Environment verification")."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys


def main() -> int:
    print(f"python      : {platform.python_version()} ({sys.executable})")
    print(f"os          : {platform.platform()}")
    for mod in ("numpy", "scipy", "soundfile", "fastapi", "pydantic", "uvicorn"):
        try:
            m = __import__(mod)
            print(f"{mod:<12}: {getattr(m, '__version__', '?')}")
        except Exception as e:  # noqa: BLE001
            print(f"{mod:<12}: MISSING ({e})")
    for tool in ("ffmpeg", "ffprobe", "mkcert", "node", "npm"):
        path = shutil.which(tool)
        ver = ""
        if path:
            try:
                out = subprocess.run([tool, "-version" if tool.startswith("ff") else "--version"], capture_output=True, text=True, timeout=5)
                ver = (out.stdout or out.stderr).splitlines()[0][:70]
            except Exception:  # noqa: BLE001
                ver = "?"
        print(f"{tool:<12}: {path or 'MISSING'} {ver}")
    if shutil.which("ffmpeg"):
        dec = subprocess.run(["ffmpeg", "-hide_banner", "-decoders"], capture_output=True, text=True).stdout
        for codec in ("opus", "aac", "vorbis", "mp3float", "flac"):
            print(f"  decoder {codec:<9}: {'yes' if f' {codec} ' in dec else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
