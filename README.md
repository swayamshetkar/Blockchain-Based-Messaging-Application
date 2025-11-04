**BlockMessage — Decentralized Encrypted Messaging Blockchain**

A fully distributed, blockchain-based end-to-end encrypted messaging framework
built with Python, FastAPI, and NaCl crypto — enabling privacy-first, trustless communication.


<br><br>
--> **Overview**
<br>

BlockMessage is a peer-to-peer blockchain network that lets users exchange encrypted messages while maintaining a verifiable, tamper-proof ledger of communication events.

It combines:

1. Blockchain consensus (Merkle-rooted blocks, proposer-based validation)

2. NaCl public-key encryption (per-user keypairs for E2E privacy)

3. Decentralized storage (redundant relayer nodes)

4. Peer self-discovery (automatic peer registration and gossip propagation)

This means every message is:
 1.Encrypted end-to-end
 2.Stored redundantly across multiple relayers
 3.Signed and timestamped immutably
 4.Committed into blockchain blocks after consensus

Even if one server goes offline, the blockchain continues through other nodes.


<br><br>
-->> **Architecture**


| Layer                | Description                                                      | Implementation                                          |
| -------------------- | ---------------------------------------------------------------- | ------------------------------------------------------- |
| **Crypto**           | NaCl keypairs for encryption; Ethereum ECDSA keys for signatures | `crypto_utils.py`                                       |
| **User Layer**       | Users register, send, and receive encrypted messages             | `register_user.py`, `sender.py`, `receiver_realtime.py` |
| **Relayer Layer**    | Nodes store messages and replicate across the network            | `main.py`, `storage.py`, `relayer.py`                   |
| **Blockchain Layer** | Blocks proposals, Merkle trees, consensus, commit tracking       | `blockchain.py`, `main.py`                              |
| **Networking Layer** | Peer discovery, replication, and communication                   | `network.py`, `peer_init.py`                            |
<br><br>
<br>

-->> **Security Model**

| Feature                    | Description                                                                      |
| -------------------------- | -------------------------------------------------------------------------------- |
| **End-to-End Encryption**  | Messages are encrypted with the recipient’s NaCl public key                      |
| **Signature Verification** | Each message delivery is signed with sender’s Ethereum key                       |
| **CID Hashing**            | Content Identifiers (`cid`) = SHA256(payload) to ensure immutability             |
| **Merkle Tree Blocks**     | Blocks store message CIDs, hashed into Merkle roots                              |
| **Peer Validation**        | Each peer verifies proposals (signature + Merkle + continuity) before committing |
| **Consensus**              | Simple majority vote (≥ 51%) ensures block acceptance                            |
| **Replication**            | Each message replicated to 3 random online peers for redundancy                  |

<br><br>

-->> **Peer Discovery & Network Design**

 Peers self-discover dynamically:

 1. A new node registers itself with a bootstrap node (/api/register_peer).

 2. Fetches the live peer list (/api/peers).

 3.   Propagates itself to those peers.

 4. Periodically heartbeats (/api/ping) to remain active.

    If one node (like your server) shuts down, others continue the blockchain independently.

<br><br>

-->> **Blockchain Lifecycle**
<br>
1.Sender → Deliver: Sends metadata + encrypted payload. <br>

2.Relayers → Store: Message replicated on 3 relayers. <br>
 
3.Proposer → Block: Every 20s, a node proposes new block with pending message CIDs. <br>

4.Peers → Vote: Peers verify (Merkle, signature, hash continuity) and vote. <br>

5.Commit → Consensus: When majority agrees, block is committed. <br>

6.Ledger → Immutable: Messages marked committed=1 in DB, forming a permanent chain. <br>
<br>


-->> **Example Database Schema**
<br>
1.For messages

| Field      | Type    | Description                      |
| ---------- | ------- | -------------------------------- |
| id         | INTEGER | Autoincrement primary key        |
| cid        | TEXT    | SHA256(payload)                  |
| sender     | TEXT    | Ethereum address                 |
| recipient  | TEXT    | Ethereum address                 |
| timestamp  | INTEGER | Unix epoch                       |
| delivered  | INTEGER | 0 or 1                           |
| root_id    | TEXT    | Deterministic hash for chat pair |
| session_id | TEXT    | Time-windowed hash for session   |
| committed  | INTEGER | 0 or 1                           |

<br><br>
2. For Blocks

| Field         | Type    | Description                       |
| ------------- | ------- | --------------------------------- |
| idx           | INTEGER | Block height                      |
| previous_hash | TEXT    | Previous block hash               |
| merkle_root   | TEXT    | Merkle tree hash of included CIDs |
| cids          | TEXT    | Comma-separated message CIDs      |
| proposer      | TEXT    | Node proposing the block          |
| signature     | TEXT    | Signature of proposer             |
| timestamp     | INTEGER | Block timestamp                   |

<br><br>

-->> **Key Concepts**
| Concept         | Explanation                                                         |
| --------------- | ------------------------------------------------------------------- |
| **Relayer**     | A node that stores encrypted messages and participates in consensus |
| **CID**         | Content ID — hash of message payload (immutability)                 |
| **Root ID**     | Deterministic chat identifier for user pairs                        |
| **Session ID**  | Time-based rotating identifier for message grouping                 |
| **Merkle Root** | Tree hash ensuring message set integrity per block                  |
| **Consensus**   | Simple majority agreement for new blocks                            |
| **ACK**         | Signature-based message delivery confirmation                       |

<br><br>

-->> **Security**
1. All messages encrypted before upload
2. CIDs verified during replication
3. Blocks verified by all peers
4. WebSocket only pushes to authenticated addresses
5. No global mutable state (each task has its own DB connection)
6. WAL-enabled SQLite for concurrency

<br><br>
-->> Tech Stack

| Component     | Library / Tech                             |
| ------------- | ------------------------------------------ |
| API           | **FastAPI**                                |
| Blockchain DB | **SQLite (WAL)**                           |
| Network       | **HTTP + WebSockets**                      |
| Crypto        | **PyNaCl**, **eth-account**                |
| Consensus     | **Custom Proof-of-Vote (majority)**        |
| Storage       | **Local JSON / Redundant Relayer Storage** |


<br><br>
Authors

 **Swayam Shetkar** — *Developer, Architect, Cybersecurity , AI & Blockchain Enthusiast*


<br><br>
-->> **Setting Up a Node**

Each node (your computer or another server) acts as a relayer + blockchain validator.

<br>
1️⃣ Clone the repository <br>
    git clone https://github.com/swayamshetkar/Blockchain-Based-Messaging-Application/   <br>
    cd Blockchain-Based-Messaging-Application

<br><br>
2️⃣ Run migration  <br>
    python migrate.py
<br>

This ensures your database schema is up-to-date.

<br><br>
3️⃣ Start the relayer node  <br>
    uvicorn main:app --host 0.0.0.0 --port 3000 --reload  <br>

..To run multiple relayers:  <br>

uvicorn main:app --port 3001  <br>
uvicorn main:app --port 3002

<br><br>
4️⃣ Register peers (self-discovery)  <br>
 
   Each node announces itself:  <br>

   python peer_init.py

<br><br>
The bootstrap node (your main server) automatically adds new peers to its database, which then gossip the new peer across the network.

<br>
5️⃣ Register a user  <br>

  Run once per user: <br>

  python register_user.py  <br>
This generates:
<br>
keys/user_eth_private.key — Ethereum private key (for signing)
<br>
keys/user_nacl_private.key — NaCl key (for encryption)
<br><br>

6️⃣ Send a message
   python sender.py <br>
   Lists available registered users
<br>
   Prompts you to pick a recipient<br>

  Encrypts + signs + sends message     <br>

  Uploads encrypted payload to relayers       <br>

  Delivers metadata for blockchain inclusion   <br>

<br><br>
7️⃣ Receive messages (realtime)   <br>
    python receiver_realtime.py

<br>
   This opens a WebSocket connection and prints decrypted messages as they arrive, including:   <br>

   Message text   <br>

   Sender address    <br>

   Session & conversation IDs    <br>

   Message acknowledgment (ACK) confirmations
<br><br>


-->> **Future Roadmap**
1.Phase 1	Peer Auto-Discovery	Dynamic /api/register_peer, /api/peers, /api/ping endpoints.
2.Phase 2	Fork Resolution	Automatic rollback on conflicting block.
3.Phase 3	Block Sync	Nodes fetch missing blocks on reconnect.
4.Phase 4	Smart Contract Integration	Immutable on-chain message proofs.
5.Phase 5	Incentivization Layer	Tokenized miner rewards for relayers.
6.Phase 6	Network Visualization	Dashboard for live block + peer view.
7.Phase 7	AI Integration	Optional NLP chat agent or analytics.

<br><br>

-->> Authors

 **Swayam Shetkar** — *Developer, Architect, Cybersecurity , AI & Blockchain Enthusiast*
