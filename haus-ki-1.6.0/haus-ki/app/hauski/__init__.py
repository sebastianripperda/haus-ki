"""Haus-KI – lokaler KI-Assistent für die Familie."""
from pathlib import Path

_v = Path(__file__).resolve().parents[2] / "VERSION"
__version__ = _v.read_text().strip() if _v.exists() else "dev"
