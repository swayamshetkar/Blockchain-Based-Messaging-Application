# blockchain.py
import time, json
from crypto_utils import sha256_hex, sign_message_hex, node_address, ensure_node_key
from database import get_conn

def merkle_root_from_cids(cids):
    # super-simple merkle: hash concat of cids
    data = "".join(cids).encode()
    return sha256_hex(data)

def last_block_hash():
    conn = get_conn()
    cur = conn.cursor()
    r = cur.execute("SELECT idx, previous_hash, merkle_root, cids, proposer, signature, timestamp FROM blocks ORDER BY idx DESC LIMIT 1").fetchone()
    if not r:
        return "0"*64
    payload = f"{r[0]}|{r[1]}|{r[2]}|{r[3]}|{r[4]}|{r[6]}"
    return sha256_hex(payload.encode())

def append_block(previous_hash, merkle_root, cids, proposer, signature):
    conn = get_conn()
    cur = conn.cursor()
    ts = int(time.time())
    cur.execute("INSERT INTO blocks (previous_hash, merkle_root, cids, proposer, signature, timestamp) VALUES (?,?,?,?,?,?)",
                (previous_hash, merkle_root, ",".join(cids), proposer, signature, ts))
    conn.commit()
    return cur.lastrowid

def create_and_sign_proposal(cids_list):
    prev = last_block_hash()
    merkle = merkle_root_from_cids(cids_list)
    ts = int(time.time())
    payload = {"previous_hash": prev, "merkle_root": merkle, "cids": cids_list, "proposer": node_address(), "timestamp": ts}
    key = ensure_node_key()
    text = json.dumps([prev, merkle, cids_list, node_address(), ts], sort_keys=True)
    sig = sign_message_hex(key, text)
    payload["signature"] = sig
    return payload
