# crypto_utils.py
import hashlib
import json
import os
from eth_account import Account
from eth_account.messages import encode_defunct
from hexbytes import HexBytes
from typing import Tuple, Optional
from time import time

# Node key management (ECDSA using eth-account)
NODE_KEY_PATH = "node_key.hex"

def ensure_node_key():
    if os.path.exists(NODE_KEY_PATH):
        with open(NODE_KEY_PATH, "r") as f:
            key = f.read().strip()
    else:
        acct = Account.create()
        key = acct.key.hex()
        with open(NODE_KEY_PATH, "w") as f:
            f.write(key)
    return key

def node_address():
    key = ensure_node_key()
    acct = Account.from_key(key)
    return acct.address

def sign_message_hex(privkey_hex: str, text: str) -> str:
    acct = Account.from_key(privkey_hex)
    msg = encode_defunct(text=text)
    sig = Account.sign_message(msg, acct.key).signature.hex()
    return sig

def verify_signature(sender: str, message: str, sig_hex: str):
    try:
        msg = encode_defunct(text=message)
        recovered = Account.recover_message(msg, signature=HexBytes(sig_hex))
        return recovered.lower() == sender.lower()
    except Exception as e:
        print("Signature verification failed:", e)
        return False


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def cid_from_payload(payload: dict) -> str:
    # deterministic JSON canonicalization (sort keys)
    js = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    return sha256_hex(js)

# --- Conversations helpers ---
def conversation_root_id(a: str, b: str) -> str:
    """Deterministic root id for a 1:1 chat: sha256 of sorted addresses."""
    addrs = sorted([a.lower(), b.lower()])
    raw = (addrs[0] + '|' + addrs[1]).encode()
    return sha256_hex(raw)

def compute_session_id(root_id: str, ts: Optional[int] = None, window_secs: int = 3600) -> str:
    """Session id rotates by time window: sha256(root_id|window_start)."""
    if ts is None:
        ts = int(time())
    window_start = ts - (ts % int(window_secs))
    raw = f"{root_id}|{window_start}".encode()
    return sha256_hex(raw)
