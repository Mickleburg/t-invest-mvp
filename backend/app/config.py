"""Filesystem locations for the single TradeGuard backend."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "backend" / "runtime"
