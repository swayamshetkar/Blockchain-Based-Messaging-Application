# peer_init.py
"""
Bootstrap helper for peer discovery.

On node startup, call:
    register_with_bootstrap()
    fetch_peer_list()

Environment:
- BOOTSTRAP_NODE: base URL of a known node (e.g., http://yourserverip:3000)
Falls back to config.settings.node_url if not set.
"""

from __future__ import annotations

import os
import time
import requests
from typing import Optional

from config import settings
from crypto_utils import ensure_node_key, node_address, sign_message_hex
from database import get_conn

BOOTSTRAP = os.getenv("BOOTSTRAP_NODE", settings.get("node_url"))
NODE_URL = settings.get("node_url")


def _ensure_peers_table():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS peers (url TEXT PRIMARY KEY, last_seen INTEGER)")
    conn.commit()
    conn.close()


def register_with_bootstrap() -> None:
    if not BOOTSTRAP or not NODE_URL:
        return
    try:
        # Prepare optional signed registration (works even if server doesn't require it)
        ts = int(time.time())
        addr = node_address()
        key = ensure_node_key()
        message = f"register|{NODE_URL.rstrip('/')}|{ts}|{addr}"
        sig = sign_message_hex(key, message)
        body = {"url": NODE_URL, "address": addr, "timestamp": ts, "signature": sig}
        r = requests.post(f"{BOOTSTRAP.rstrip('/')}/api/register_peer", json=body, timeout=5)
        if r.status_code == 200:
            print("✅ Registered with bootstrap node.")
        else:
            print(f"⚠️ Bootstrap register failed: {r.text}")
    except Exception as e:
        print("⚠️ Could not reach bootstrap:", e)


def fetch_peer_list() -> None:
    if not BOOTSTRAP:
        return
    try:
        r = requests.get(f"{BOOTSTRAP.rstrip('/')}/api/peers", timeout=5)
        if r.status_code == 200:
            data = r.json() or {}
            peers = data.get("peers", [])
            _ensure_peers_table()
            conn = get_conn()
            cur = conn.cursor()
            now = int(time.time())
            for p in peers:
                url = (p.get("url") or "").rstrip("/")
                if not url or url == NODE_URL.rstrip("/"):
                    continue
                cur.execute("INSERT OR REPLACE INTO peers (url, last_seen) VALUES (?, ?)", (url, now))
            conn.commit()
            conn.close()
            print(f"✅ Synced {len(peers)} peers from bootstrap.")
        else:
            print(f"⚠️ Failed to fetch peers: {r.status_code}")
    except Exception as e:
        print("⚠️ Failed to fetch peers:", e)
