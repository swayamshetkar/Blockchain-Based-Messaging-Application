# network.py
import httpx, asyncio, os, random, time
from config import settings
from typing import List
from database import get_conn

PEERS = list(settings.get("peers", []))
NODE_URL = settings.get("node_url")

async def post_to_peer(peer: str, path: str, json_payload: dict, timeout=10):
    url = peer.rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, json=json_payload)
            # On success, update last_seen for this peer
            if r.status_code < 500:
                try:
                    conn = get_conn()
                    cur = conn.cursor()
                    cur.execute("CREATE TABLE IF NOT EXISTS peers (url TEXT PRIMARY KEY, last_seen INTEGER)")
                    cur.execute("INSERT OR REPLACE INTO peers (url, last_seen) VALUES (?, ?)", (peer.rstrip("/"), int(time.time())))
                    conn.commit()
                    conn.close()
                except Exception:
                    pass
            return r.status_code, r.json() if r.content else {}
    except Exception as e:
        return 500, {"error": str(e)}

async def replicate_to_peers(cid: str, payload: dict):
    """
    Send /api/replicate to a random subset of known peers from DB (fallback to config).
    """
    # Fetch peers from DB
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS peers (url TEXT PRIMARY KEY, last_seen INTEGER)")
    db_peers = [r[0] for r in cur.execute("SELECT url FROM peers").fetchall()]
    conn.close()

    pool = db_peers or PEERS
    # de-dup and remove self
    cleaned = []
    self_url = (NODE_URL or "").rstrip("/")
    for p in pool:
        base = p.rstrip("/")
        if not base or base == self_url:
            continue
        if base not in cleaned:
            cleaned.append(base)

    k = min(int(settings.get("redundancy", 3)), max(0, len(cleaned)))
    selected = random.sample(cleaned, k) if k > 0 else []
    if not selected:
        return []

    print(f"🌍 Replicating {cid[:8]}… to {selected}")
    tasks = [post_to_peer(p, "/api/replicate", {"cid": cid, "payload": payload}) for p in selected]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results

async def send_proposal_to_peers(proposal: dict):
    """
    POST /api/proposal to all known peers (DB first, fallback to config), collect votes.
    """
    # Fetch peers from DB
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS peers (url TEXT PRIMARY KEY, last_seen INTEGER)")
    db_peers = [r[0] for r in cur.execute("SELECT url FROM peers").fetchall()]
    conn.close()

    pool = db_peers or PEERS
    # de-dup and remove self
    cleaned = []
    self_url = (NODE_URL or "").rstrip("/")
    for p in pool:
        base = p.rstrip("/")
        if not base or base == self_url:
            continue
        if base not in cleaned:
            cleaned.append(base)

    tasks = [post_to_peer(p, "/api/proposal", proposal, timeout=15) for p in cleaned]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results