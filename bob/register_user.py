# register_user.py
from eth_account import Account
from nacl.public import PrivateKey
import base64, requests, os, json

RELAYER_BASE = "http://127.0.0.1:3000"  # or LAN IP

os.makedirs("keys", exist_ok=True)
eth_key_path = "keys/user_eth_private.key"
nacl_key_path = "keys/user_nacl_private.key"

# 1️⃣ Create Ethereum account for signatures
acct = Account.create()
with open(eth_key_path, "w") as f:
    f.write(acct.key.hex())

# 2️⃣ Create NaCl keypair for encryption
nacl_priv = PrivateKey.generate()
with open(nacl_key_path, "wb") as f:
    f.write(bytes(nacl_priv))

# 3️⃣ Register on the network
enc_pub_b64 = base64.b64encode(bytes(nacl_priv.public_key)).decode()
data = {"address": acct.address, "encPub": enc_pub_b64, "signPub": acct.address}
resp = requests.post(f"{RELAYER_BASE}/api/register", json=data)
resp.raise_for_status()

print(f"✅ Registered user {acct.address}")
print(f"🔑 Ethereum key saved to: {eth_key_path}")
print(f"🧩 NaCl key saved to: {nacl_key_path}")