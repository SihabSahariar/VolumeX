"""Files shipped inside the package (bundled by PyInstaller via the spec's datas)."""
from pathlib import Path

RESOURCES = Path(__file__).resolve().parent


def resource(name: str) -> Path:
    return RESOURCES / name
