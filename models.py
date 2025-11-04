# models.py
from pydantic import BaseModel
from typing import Dict, List, Any, Optional

class RegisterUser(BaseModel):
    address: str
    encPub: str
    signPub: str

class UploadPayload(BaseModel):
    payload: Dict[str, Any]

class DeliverMessage(BaseModel):
    cid: str
    sender: str
    recipient: str
    timestamp: int
    ethSignature: str
    sessionId: Optional[str] = None

class ReplicatePayload(BaseModel):
    cid: str
    payload: Dict[str, Any]

class BlockProposal(BaseModel):
    previous_hash: str
    merkle_root: str
    cids: List[str]
    proposer: str
    timestamp: int
    signature: str  # proposer's signature over block data

class ConversationMessage(BaseModel):
    id: int
    cid: str
    sender: str
    recipient: str
    timestamp: int
    rootId: str
    sessionId: str

class ConversationResponse(BaseModel):
    rootId: str
    messages: List[ConversationMessage]
