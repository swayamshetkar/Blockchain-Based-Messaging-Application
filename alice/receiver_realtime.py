# receiver_realtime.py
import asyncio
import base64
import json
import os
import time
import websockets
import requests
from nacl.public import PrivateKey, PublicKey, Box
from eth_account import Account
from eth_account.messages import encode_defunct

RELAYER_BASE = os.environ.get("RELAYER_BASE", "http://127.0.0.1:3000")
WS_BASE = RELAYER_BASE.replace("http", "ws")

# Load keys
os.makedirs("keys", exist_ok=True)
with open("keys/user_eth_private.key") as f:
    eth_priv = f.read().strip()
acct = Account.from_key(eth_priv)
with open("keys/user_nacl_private.key", "rb") as f:
    nacl_priv = PrivateKey(f.read())

receiver_address = acct.address

async def ack_messages(ids):
    if not ids:
        return
    msg = f"ack|{receiver_address}|{','.join(map(str, ids))}"
    sig = Account.sign_message(encode_defunct(text=msg), acct.key).signature.hex()
    r = requests.post(f"{RELAYER_BASE}/api/ack", json={
        "recipient": receiver_address,
        "messageIds": ids,
        "ethSignature": sig
    })
    if r.status_code == 200:
        print(f"✅ ACKed {ids}")
    else:
        print(f"⚠️ ACK failed: {r.text}")

async def fetch_and_decrypt(cid, sender_enc_pub_b64):
    pr = requests.get(f"{RELAYER_BASE}/api/fetch/{cid}")
    if pr.status_code != 200:
        print(f"⚠️ Fetch failed for {cid}")
        return None
    payload = pr.json()["payload"]
    cipher_b64 = payload["ciphertext"]
    sender_pub_b64 = payload.get("senderEncPub", sender_enc_pub_b64)
    try:
        sender_pub = PublicKey(base64.b64decode(sender_pub_b64))
        box = Box(nacl_priv, sender_pub)
        plaintext = box.decrypt(base64.b64decode(cipher_b64)).decode()
        return plaintext
    except Exception as e:
        print(f"⚠️ Decrypt failed for {cid}: {e}")
        return None

async def history(root_id, limit=20):
    try:
        r = requests.get(f"{RELAYER_BASE}/api/conversation/{root_id}", params={"limit": limit})
        if r.status_code == 200:
            data = r.json()
            print(f"\n🧾 Conversation history (last {limit}) for {root_id[:8]}…:")
            for m in reversed(data.get("messages", [])):
                print(f"[{m['timestamp']}] {m['sender']} -> {m['recipient']} (sid {m['sessionId'][:8]}…): {m['cid']}")
        else:
            print("⚠️ History fetch failed:", r.text)
    except Exception as e:
        print("History error:", e)

async def main():
    url = f"{WS_BASE}/ws/{receiver_address}"
    print(f"📡 Connecting WS {url}")
    ids_to_ack = []
    async for ws in websockets.connect(url, ping_interval=20, ping_timeout=20):
        try:
            async for msg in ws:
                try:
                    data = json.loads(msg)
                except Exception:
                    continue
                if data.get("event") == "new_message":
                    cid = data["cid"]
                    sender = data["sender"]
                    root_id = data.get("rootId")
                    session_id = data.get("sessionId")
                    mid = data.get("id")
                    plaintext = await fetch_and_decrypt(cid, None)
                    if plaintext is not None:
                        print(f"\n📩 [{session_id[:8]}…] From {sender}: {plaintext}")
                        ids_to_ack.append(mid)
                        # ACK promptly when batching grows
                        if len(ids_to_ack) >= 5:
                            await ack_messages(ids_to_ack)
                            ids_to_ack = []
                        # Optionally show quick history for this root
                        if root_id:
                            await history(root_id, limit=5)
            # connection ended
        except Exception as e:
            print("WS error:", e)
            await asyncio.sleep(3)
        finally:
            if ids_to_ack:
                await ack_messages(ids_to_ack)
                ids_to_ack = []

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
