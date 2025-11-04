# storage.py
import os, json
from pathlib import Path
from config import settings

BASE = Path(settings["relayer_storage_path"])
REDUNDANCY = int(settings.get("redundancy", 3))

# create directories relayer_0..relayer_{N-1}
for i in range(REDUNDANCY):
    (BASE / f"relayer_{i}").mkdir(parents=True, exist_ok=True)

def store_local(payload: dict) -> str:
    """
    Store payload to all local relayer_N directories and return CID.
    """
    from crypto_utils import cid_from_payload
    cid = cid_from_payload(payload)
    for i in range(REDUNDANCY):
        path = BASE / f"relayer_{i}" / f"{cid}.json"
        with open(path, "w") as f:
            json.dump(payload, f)
    return cid

def fetch_local(cid: str):
    for i in range(REDUNDANCY):
        path = BASE / f"relayer_{i}" / f"{cid}.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
    return None

def store_to_path(cid: str, payload: dict, relayer_idx: int):
    path = BASE / f"relayer_{relayer_idx}" / f"{cid}.json"
    with open(path, "w") as f:
        json.dump(payload, f)
    return True
