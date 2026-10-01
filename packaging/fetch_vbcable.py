"""Fetch the official VB-CABLE package into third_party/vbcable/ so the build can ship it.

VB-Audio allows bundling the unmodified package (https://vb-audio.com/Services/licensing.htm). The download
must match the pinned SHA-256 in volumex/platform/vbcable.py and carry VB-Audio's code signature.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from volumex.platform import vbcable  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    dest = ROOT / "third_party" / "vbcable"
    if (dest / vbcable.SETUP_EXE).exists() and vbcable.verify_signature(dest / vbcable.SETUP_EXE):
        print(f"VB-CABLE already in {dest}")
        return 0
    dest.parent.mkdir(exist_ok=True)
    try:
        vbcable.download_package(dest, strict_hash=True)
    except vbcable.VbCableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"VB-CABLE ready in {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
