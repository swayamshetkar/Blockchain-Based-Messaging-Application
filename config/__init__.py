"""
Config loader that exposes a dict-like `settings` object.

It loads values from `settings.json` (JSON or JSONC) and falls back to sane
defaults. Supports:
- Trailing inline `//` comments and `/* ... */` block comments
- Numeric literals with underscores, e.g. 10_485_760

Usage:
    from config import settings
    settings["relayer_storage_path"]
    settings.get("redundancy", 3)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict


SETTINGS_PATH = Path(__file__).with_name("settings.json")


def _strip_jsonc(text: str) -> str:
    """Remove JSONC comments and numeric underscores to make it JSON-safe."""
    # Remove /* block */ comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    # Remove // line comments
    text = re.sub(r"//.*", "", text)
    # Remove underscores within numeric literals (e.g., 10_485_760 -> 10485760)
    text = re.sub(r"(?<=\d)_(?=\d)", "", text)
    return text


def _read_settings_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    cleaned = _strip_jsonc(raw)
    try:
        return json.loads(cleaned or "{}")
    except Exception as e:
        # Fall back to empty if parsing fails; callers will merge defaults.
        # You can print or log here if desired.
        return {}


DEFAULTS: Dict[str, Any] = {
    "node_url": "http://127.0.0.1:3000",
    "peers": [],
    "redundancy": 3,
    "proposal_interval_seconds": 20,
    "majority_fraction": 0.51,
    "relayer_storage_path": "relayer_storage",
    "max_payload_bytes": 10_485_760,
    # Peer discovery/health defaults
    "peer_heartbeat_interval_secs": 60,
    "peer_stale_after_secs": 300,
    "require_peer_auth": False,
    "peer_allowlist": [],  # list of allowed peer addresses (ETH addrs); empty -> allow any
    "allow_local_peers": True,
}


def _merged_settings() -> Dict[str, Any]:
    data = _read_settings_file(SETTINGS_PATH)
    out = DEFAULTS.copy()
    out.update(data)
    return out


class _Settings(dict):
    """Dict subclass with a handy reload() and attribute access."""

    def __getattr__(self, key: str) -> Any:  # settings.key support
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def reload(self) -> None:
        self.clear()
        self.update(_merged_settings())


# Public settings object
settings = _Settings(_merged_settings())
