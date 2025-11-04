# main.py (patched)
import os
import json
import time
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware

from database import init_db, get_conn
from models import RegisterUser, UploadPayload, DeliverMessage, ReplicatePayload, BlockProposal
from storage import store_local, fetch_local, store_to_path
from network import replicate_to_peers, send_proposal_to_peers
from crypto_utils import cid_from_payload, verify_signature, ensure_node_key, node_address, sign_message_hex, conversation_root_id, compute_session_id
from blockchain import create_and_sign_proposal, append_block, merkle_root_from_cids, last_block_hash
from config import settings
from urllib.parse import urlparse

# initialize DB (runs migrations / ensures tables exist)
# we keep a top-level conn only for init/migrations; runtime DB access uses get_conn()
_init_conn = init_db()
_init_conn.close()

online = {}  # in-memory presence map (note: not shared across processes)


# -------------------- helper DB utilities --------------------
def ensure_committed_column():
    """Add committed column to messages table if missing (safe no-op if present)."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        # Try reading column info
        cols = [c[1] for c in cur.execute("PRAGMA table_info(messages)").fetchall()]
        if "committed" not in cols:
            cur.execute("ALTER TABLE messages ADD COLUMN committed INTEGER DEFAULT 0")
            conn.commit()
    except Exception:
        # If table doesn't exist or other issue, ignore (init_db should create it)
        pass
    finally:
        conn.close()


# ensure schema is ready
ensure_committed_column()


# -------------------- periodic proposer (must be defined before lifespan uses it) --------------------
async def periodic_proposer(interval_seconds: int):
    """
    Periodically collect pending (uncommitted) CIDs and propose a block to peers.
    Uses per-connection DB access to avoid sharing SQLite cursors across async tasks.
    """
    try:
        while True:
            try:
                await asyncio.sleep(interval_seconds)

                # collect uncommitted CIDs (messages not yet in any block)
                conn = get_conn()
                cur = conn.cursor()
                rows = cur.execute("SELECT DISTINCT cid FROM messages WHERE committed = 0 ORDER BY timestamp ASC LIMIT 200").fetchall()
                conn.close()

                all_cids = [r[0] for r in rows]
                if not all_cids:
                    continue

                # For demo we propose up to 20 cids
                to_propose = all_cids[:20]
                proposal = create_and_sign_proposal(to_propose)

                # send to peers (async)
                results = await send_proposal_to_peers(proposal)

                # count votes (include self as vote)
                yes = 1  # self vote
                for r in results:
                    try:
                        if isinstance(r, tuple) and r[0] == 200 and isinstance(r[1], dict) and r[1].get("vote"):
                            yes += 1
                    except Exception:
                        pass

                peers_count = max(1, len(settings.get("peers", [])))
                majority_needed = int(peers_count * float(settings.get("majority_fraction", 0.51))) + 1

                if yes >= majority_needed:
                    # commit block locally (this will validate continuity)
                    try:
                        commit_block(proposal)
                        print(f"Committed block with {len(to_propose)} cids (yes votes): {yes})")
                    except Exception as e:
                        print("Commit failed:", e)
                else:
                    print(f"Proposal failed (yes={yes}, needed>{majority_needed})")

            except asyncio.CancelledError:
                print("periodic_proposer cancelled; exiting")
                raise
            except Exception as exc:
                print("Error in periodic_proposer loop:", exc)
                await asyncio.sleep(5)

    except asyncio.CancelledError:
        return


async def periodic_peer_heartbeat(interval_seconds: int, stale_after: int):
    """Ping peers periodically and prune stale ones."""
    import httpx
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            # fetch peers
            conn = get_conn()
            cur = conn.cursor()
            rows = cur.execute("SELECT url, last_seen FROM peers").fetchall()
            now = int(time.time())
            peers = [r[0] for r in rows]
            conn.close()

            # ping peers
            for p in peers:
                base = p.rstrip("/")
                try:
                    async with httpx.AsyncClient(timeout=3) as client:
                        r = await client.get(base + "/health")
                        if r.status_code == 200:
                            c2 = get_conn()
                            k2 = c2.cursor()
                            k2.execute("UPDATE peers SET last_seen = ? WHERE url = ?", (now, base))
                            c2.commit()
                            c2.close()
                except Exception:
                    # ignore; pruning based on last_seen happens below
                    pass

            # prune stale
            cutoff = now - int(stale_after)
            c3 = get_conn()
            k3 = c3.cursor()
            k3.execute("DELETE FROM peers WHERE last_seen IS NOT NULL AND last_seen < ?", (cutoff,))
            removed = k3.rowcount
            c3.commit()
            c3.close()
            if removed:
                print(f"🧹 Pruned {removed} stale peers")
        except asyncio.CancelledError:
            return
        except Exception as e:
            print("Heartbeat error:", e)


# -------------------- lifespan (startup/shutdown) --------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Start background tasks here and ensure they are cancelled on shutdown.
    """
    interval = int(settings.get("proposal_interval_seconds", 20))
    proposer_task = asyncio.create_task(periodic_proposer(interval))
    hb_interval = int(settings.get("peer_heartbeat_interval_secs", 60))
    stale_after = int(settings.get("peer_stale_after_secs", 300))
    heartbeat_task = asyncio.create_task(periodic_peer_heartbeat(hb_interval, stale_after))

    # Best-effort bootstrap peer registration and initial peer sync
    try:
        from peer_init import register_with_bootstrap, fetch_peer_list
        # run sync functions in background threads so we don't block the loop
        await asyncio.to_thread(register_with_bootstrap)
        await asyncio.to_thread(fetch_peer_list)
    except Exception as e:
        # optional helper may be missing; ignore failure to keep node running
        print("Bootstrap peer init skipped or failed:", e)

    try:
        yield
    finally:
        proposer_task.cancel()
        heartbeat_task.cancel()
        try:
            await proposer_task
        except asyncio.CancelledError:
            pass
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


# create FastAPI app with lifespan
app = FastAPI(title="BlockNet Relayer Node", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# -------------------- WebSocket for push --------------------
@app.websocket("/ws/{address}")
async def ws_endpoint(ws: WebSocket, address: str):
    await ws.accept()
    online[address.lower()] = ws
    print("WS connected", address)
    try:
        while True:
            await ws.receive_text()
    except Exception:
        online.pop(address.lower(), None)
        print("WS disconnected", address)


# -------------------- API endpoints --------------------

# Peer registration (node-to-node)
@app.post("/api/register_peer")
async def register_peer(request: Request):
    data = await request.json()
    raw_url = data.get("url")
    address = data.get("address")
    signature = data.get("signature")
    ts = data.get("timestamp")

    if not raw_url or not isinstance(raw_url, str) or len(raw_url) > 2048:
        raise HTTPException(status_code=400, detail="invalid url")

    # Parse and validate URL
    parsed = urlparse(raw_url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="unsupported scheme")
    if not parsed.netloc or "@" in parsed.netloc:
        raise HTTPException(status_code=400, detail="invalid host")
    # Restrict path/query/fragment
    if parsed.query or parsed.fragment:
        raise HTTPException(status_code=400, detail="url must not contain query or fragment")
    if parsed.path not in ("", "/"):
        raise HTTPException(status_code=400, detail="url must be base origin only")
    canon = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

    # Optionally require peer authentication
    if bool(settings.get("require_peer_auth", False)):
        if not (address and isinstance(ts, int) and signature):
            raise HTTPException(status_code=401, detail="auth required")
        # prevent replay: 5-minute window
        now = int(time.time())
        if abs(now - int(ts)) > 300:
            raise HTTPException(status_code=401, detail="stale timestamp")
        message = f"register|{canon}|{ts}|{address}"
        if not verify_signature(address, message, signature):
            raise HTTPException(status_code=401, detail="invalid signature")
        allowlist = [a.lower() for a in settings.get("peer_allowlist", [])]
        if allowlist and address.lower() not in allowlist:
            raise HTTPException(status_code=403, detail="peer not allowed")

    # Local peer policy (allow/disallow localhost)
    if not bool(settings.get("allow_local_peers", True)):
        host = parsed.hostname or ""
        if host in ("localhost", "127.0.0.1") or host.startswith("10.") or host.startswith("192.168."):
            raise HTTPException(status_code=400, detail="local peers not allowed")

    now = int(time.time())
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS peers (url TEXT PRIMARY KEY, last_seen INTEGER)")
    cur.execute("INSERT OR REPLACE INTO peers (url, last_seen) VALUES (?, ?)", (canon, now))
    conn.commit()
    conn.close()
    print(f"🤝 Registered peer: {canon}")
    return {"ok": True, "peer": canon}


# List known peers
@app.get("/api/peers")
async def list_peers(activeOnly: bool = True, staleSeconds: int | None = None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS peers (url TEXT PRIMARY KEY, last_seen INTEGER)")
    if activeOnly:
        now = int(time.time())
        stale = int(staleSeconds or settings.get("peer_stale_after_secs", 300))
        cutoff = now - stale
        rows = cur.execute("SELECT url, last_seen FROM peers WHERE last_seen IS NOT NULL AND last_seen >= ?", (cutoff,)).fetchall()
    else:
        rows = cur.execute("SELECT url, last_seen FROM peers").fetchall()
    conn.close()
    peers = [{"url": r[0], "last_seen": r[1]} for r in rows]
    return {"ok": True, "peers": peers}


# Health endpoint for heartbeat
@app.get("/health")
async def health():
    return {"ok": True, "node": node_address()}

# Register user
@app.post("/api/register")
async def register_user(data: RegisterUser):
    ts = int(time.time())
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO users(address, enc_pub, sign_pub, created_at) VALUES (?,?,?,?)",
                (data.address, data.encPub, data.signPub, ts))
    conn.commit()
    conn.close()
    return {"ok": True, "address": data.address}


# Get user keys
@app.get("/api/user/{address}")
async def get_user(address: str):
    conn = get_conn()
    cur = conn.cursor()
    row = cur.execute("SELECT address, enc_pub, sign_pub FROM users WHERE address = ?", (address,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {"address": row[0], "encPub": row[1], "signPub": row[2]}


# Upload encrypted payload -> store locally + replicate
@app.post("/api/uploadEncrypted")
async def upload_encrypted(data: UploadPayload, bg: BackgroundTasks):
    # validate size
    payload = data.payload
    js = json.dumps(payload, sort_keys=True)
    if len(js.encode()) > settings.get("max_payload_bytes", 10_485_760):
        raise HTTPException(status_code=413, detail="Payload too large")

    cid = store_local(payload)

    # replicate to peers asynchronously using BackgroundTasks to tie lifecycle to request
    bg.add_task(replicate_to_peers, cid, payload)

    return {"ok": True, "cid": cid}


# List all registered users
@app.get("/api/users")
async def list_users():
    conn = get_conn()
    cur = conn.cursor()
    rows = cur.execute("SELECT address, enc_pub FROM users").fetchall()
    conn.close()
    return {"ok": True, "users": [{"address": r[0], "encPub": r[1]} for r in rows]}


# Replication endpoint (peer -> accept store)
@app.post("/api/replicate")
async def replicate_endpoint(data: ReplicatePayload):
    cid = data.cid
    payload = data.payload
    # verify the cid matches payload
    if cid_from_payload(payload) != cid:
        raise HTTPException(status_code=400, detail="CID mismatch")
    # store to one of the relayer slots (choose first free slot)
    store_to_path(cid, payload, relayer_idx=0)
    return {"ok": True, "cid": cid}


# Deliver: accept message metadata signed by sender, enqueue
@app.post("/api/deliver")
async def deliver(data: DeliverMessage):
    req = data
    if not all([req.cid, req.sender, req.recipient, req.timestamp, req.ethSignature]):
        raise HTTPException(status_code=400, detail="missing fields")
    msgstr = f"{req.cid}|{req.sender}|{req.recipient}|{req.timestamp}"
    if not verify_signature(req.sender, msgstr, req.ethSignature):
        raise HTTPException(status_code=400, detail="signature mismatch")

    # compute conversation root and session
    root_id = conversation_root_id(req.sender, req.recipient)
    # use provided sessionId if given, else compute server-side time-windowed session id
    session_id = getattr(req, "sessionId", None) or compute_session_id(root_id, req.timestamp, int(settings.get("session_window_secs", 3600)))

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (cid, sender, recipient, timestamp, delivered, root_id, session_id, committed) VALUES (?,?,?,?,?,?,?,?)",
        (req.cid, req.sender, req.recipient, req.timestamp, 0, root_id, session_id, 0),
    )
    conn.commit()
    msg_id = cur.lastrowid
    conn.close()

    # push to receiver if online
    ws = online.get(req.recipient.lower())
    if ws:
        # run send in background so request can finish quickly
        asyncio.create_task(ws.send_json({
            "event": "new_message",
            "cid": req.cid,
            "sender": req.sender,
            "recipient": req.recipient,
            "timestamp": req.timestamp,
            "rootId": root_id,
            "sessionId": session_id,
            "id": msg_id
        }))
        # optimistically mark delivered when pushed
        conn2 = get_conn()
        cur2 = conn2.cursor()
        cur2.execute("UPDATE messages SET delivered = 1 WHERE id = ?", (msg_id,))
        conn2.commit()
        conn2.close()

    return {"ok": True, "id": msg_id}


@app.post("/api/ack")
async def acknowledge_messages(request: Request):
    data = await request.json()
    recipient = data.get("recipient")
    ids = data.get("messageIds", [])
    sig = data.get("ethSignature")

    if not recipient or not ids or not sig:
        raise HTTPException(status_code=400, detail="missing fields")

    # verify signature
    msg = f"ack|{recipient}|{','.join(map(str, ids))}"
    if not verify_signature(recipient, msg, sig):
        raise HTTPException(status_code=400, detail="signature mismatch")

    conn = get_conn()
    cur = conn.cursor()
    for msg_id in ids:
        cur.execute("UPDATE messages SET delivered = 1 WHERE id = ?", (msg_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "acknowledged": ids}


# fetch undelivered messages
@app.get("/api/messages/{address}")
async def undelivered(address: str):
    conn = get_conn()
    cur = conn.cursor()
    rows = cur.execute("SELECT id, cid, sender, recipient, timestamp, root_id, session_id FROM messages WHERE recipient = ? AND delivered = 0", (address,)).fetchall()
    conn.close()
    return {"messages": [{"id": r[0], "cid": r[1], "sender": r[2], "recipient": r[3], "timestamp": r[4], "rootId": r[5], "sessionId": r[6]} for r in rows]}


# fetch payload by cid (from local storage)
@app.get("/api/fetch/{cid}")
async def fetch_api(cid: str):
    payload = fetch_local(cid)
    if not payload:
        raise HTTPException(status_code=404, detail="not found")
    return {"payload": payload}


# Conversation history across sessions
@app.get("/api/conversation/{root_id}")
async def conversation_history(root_id: str, limit: int = 50, before: int | None = None):
    if limit <= 0:
        limit = 50
    if limit > 500:
        limit = 500

    conn = get_conn()
    cur = conn.cursor()
    if before is None:
        q = "SELECT id, cid, sender, recipient, timestamp, root_id, session_id FROM messages WHERE root_id = ? ORDER BY timestamp DESC, id DESC LIMIT ?"
        rows = cur.execute(q, (root_id, limit)).fetchall()
    else:
        q = "SELECT id, cid, sender, recipient, timestamp, root_id, session_id FROM messages WHERE root_id = ? AND timestamp < ? ORDER BY timestamp DESC, id DESC LIMIT ?"
        rows = cur.execute(q, (root_id, before, limit)).fetchall()
    conn.close()

    msgs = [
        {"id": r[0], "cid": r[1], "sender": r[2], "recipient": r[3], "timestamp": r[4], "rootId": r[5], "sessionId": r[6]}
        for r in rows
    ]
    return {"rootId": root_id, "messages": msgs}


# Proposal endpoint: peers receive proposal and vote
@app.post("/api/proposal")
async def receive_proposal(proposal: BlockProposal):
    from blockchain import last_block_hash, merkle_root_from_cids
    from crypto_utils import verify_signature, sha256_hex

    # Check chain continuity
    local_head = last_block_hash()
    if proposal.previous_hash != local_head:
        return {"vote": False, "reason": "head_mismatch"}

    # Verify Merkle root
    local_merkle = merkle_root_from_cids(proposal.cids)
    if local_merkle != proposal.merkle_root:
        return {"vote": False, "reason": "merkle_mismatch"}

    # Verify proposer’s signature
    text = json.dumps(
        [proposal.previous_hash, proposal.merkle_root, proposal.cids, proposal.proposer, proposal.timestamp],
        sort_keys=True
    )
    if not verify_signature(proposal.proposer, text, proposal.signature):
        return {"vote": False, "reason": "invalid_signature"}

    # Ensure we actually hold some of the data being proposed
    have = sum(1 for c in proposal.cids if fetch_local(c) is not None)
    if have == 0:
        return {"vote": False, "reason": "no_local_data"}

    return {"vote": True, "have_count": have}



# Commit block locally (used when consensus reached)
def commit_block(payload_proposal):
    prev = payload_proposal["previous_hash"]
    cids = payload_proposal["cids"]
    proposer = payload_proposal.get("proposer", "")
    sig = payload_proposal.get("signature", "")

    # Guard: ensure we are extending the current head
    local_head = last_block_hash()
    if prev != local_head:
        raise RuntimeError(f"Chain head mismatch: proposal.previous_hash != local_head ({prev} != {local_head})")

    # verify merkle root consistency
    merkle = merkle_root_from_cids(cids)
    # you might also validate payload_proposal["merkle_root"] equals merkle here
    # commit to local chain
    bid = append_block(prev, merkle, cids, proposer, sig)

    # mark messages committed in DB (so proposer won't re-propose them)
    if cids:
        conn = get_conn()
        cur = conn.cursor()
        # update messages with matching cids (mark committed)
        for cid in cids:
            cur.execute("UPDATE messages SET committed = 1 WHERE cid = ?", (cid,))
        conn.commit()
        conn.close()

    return True
