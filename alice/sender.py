# sender.py
import base64, time, json, requests, os
from nacl.public import PrivateKey, PublicKey, Box
from eth_account import Account
from eth_account.messages import encode_defunct

RELAYER_BASE = "http://127.0.0.1:3000"  # or your LAN IP

os.makedirs("keys", exist_ok=True)
eth_key_path = "keys/user_eth_private.key"
nacl_key_path = "keys/user_nacl_private.key"

# Load or create Ethereum key
if os.path.exists(eth_key_path):
    with open(eth_key_path) as f:
        eth_priv = f.read().strip()
    acct = Account.from_key(eth_priv)
    print(f"🔐 Loaded account: {acct.address}")
else:
    acct = Account.create()
    with open(eth_key_path, "w") as f:
        f.write(acct.key.hex())
    print(f"🆕 Created new account: {acct.address}")

# Load or create NaCl key
if os.path.exists(nacl_key_path):
    with open(nacl_key_path, "rb") as f:
        nacl_priv = PrivateKey(f.read())
else:
    nacl_priv = PrivateKey.generate()
    with open(nacl_key_path, "wb") as f:
        f.write(bytes(nacl_priv))
    print("🆕 Created new NaCl encryption key")

# ✅ Check registration before proceeding
r = requests.get(f"{RELAYER_BASE}/api/user/{acct.address}")
if r.status_code != 200:
    print("⚠️ Not registered on network. Run register_user.py first.")
    exit()

# Get users
resp = requests.get(f"{RELAYER_BASE}/api/users")
users = resp.json()["users"]
others = [u for u in users if u["address"].lower() != acct.address.lower()]
if not others:
    print("No other users found.")
    exit()

print("\n📜 Registered users:")
for i, u in enumerate(others):
    print(f"[{i}] {u['address']}")
choice = int(input("\nSelect recipient number: "))
recipient = others[choice]["address"]

# Fetch recipient pubkey
r = requests.get(f"{RELAYER_BASE}/api/user/{recipient}")
recipient_pub = PublicKey(base64.b64decode(r.json()["encPub"]))

# Encrypt message
msg = input("Enter your message: ")
box = Box(nacl_priv, recipient_pub)
cipher = box.encrypt(msg.encode())
cipher_b64 = base64.b64encode(cipher).decode()
sender_pub_b64 = base64.b64encode(bytes(nacl_priv.public_key)).decode()
payload = {"version": 1, "ciphertext": cipher_b64, "senderEncPub": sender_pub_b64}

# Upload payload
u = requests.post(f"{RELAYER_BASE}/api/uploadEncrypted", json={"payload": payload})
cid = u.json()["cid"]
print(f"✅ Uploaded CID: {cid}")

# Deliver metadata
timestamp = int(time.time())
msg_str = f"{cid}|{acct.address}|{recipient}|{timestamp}"
sig = Account.sign_message(encode_defunct(text=msg_str), acct.key).signature.hex()
d = requests.post(f"{RELAYER_BASE}/api/deliver", json={
    "cid": cid,
    "sender": acct.address,
    "recipient": recipient,
    "timestamp": timestamp,
    "ethSignature": sig
})
print("📤 Delivered:", d.json())
