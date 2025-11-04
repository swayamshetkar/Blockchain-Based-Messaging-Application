# relayer.py
import os, json, hashlib
from typing import List

RELAYER_STORAGE_PATH = "relayer_storage"
REDUNDANCY = int(os.getenv("REDUNDANCY", 3))  # replicate message to N relayers
RELAYER_QUOTA_BYTES = int(os.getenv("RELAYER_QUOTA_BYTES", 5 * 1024**3))  # default 5 GB

os.makedirs(RELAYER_STORAGE_PATH, exist_ok=True)

# Simulate multiple relayers
relayers = [os.path.join(RELAYER_STORAGE_PATH, f"relayer_{i}") for i in range(REDUNDANCY)]
for path in relayers:
    os.makedirs(path, exist_ok=True)

def generate_cid(payload: dict) -> str:
    """Generate a deterministic hash as CID"""
    data = json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(data).hexdigest()

def _dir_size_bytes(path: str) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            fp = os.path.join(root, name)
            try:
                total += os.path.getsize(fp)
            except FileNotFoundError:
                # File might have been removed between walk and stat
                pass
    return total

def _json_bytes(payload: dict) -> bytes:
    # Compact, deterministic JSON to save space; CID uses dict hashing above
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

def store_message(payload: dict) -> str:
    """Store message on multiple relayers with quota checks and atomic writes"""
    cid = generate_cid(payload)
    json_bytes = _json_bytes(payload)
    file_name = f"{cid}.json"

    written = 0
    for path in relayers:
        dst = os.path.join(path, file_name)

        # Skip if already present
        if os.path.exists(dst):
            written += 1
            continue

        # Enforce per-relayer quota
        projected = _dir_size_bytes(path) + len(json_bytes)
        if projected > RELAYER_QUOTA_BYTES:
            continue

        tmp = os.path.join(path, f".{file_name}.tmp")
        with open(tmp, "wb") as f:
            f.write(json_bytes)
        # Atomic replace to avoid partial files
        os.replace(tmp, dst)
        written += 1

    if written == 0:
        raise RuntimeError("Insufficient storage across all relayers")
    return cid

def fetch_message(cid: str) -> dict:
    """Fetch message from first relayer that has it, verifying CID integrity"""
    file_name = f"{cid}.json"
    for path in relayers:
        filepath = os.path.join(path, file_name)
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Verify integrity independent of JSON formatting
                if generate_cid(data) == cid:
                    return data
            except Exception:
                # Corrupted or unreadable; try next relayer
                continue
    return None
