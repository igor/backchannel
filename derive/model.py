"""Plain data carriers for the source-neutral derivation layer."""
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Message:
    id: str
    chat_jid: str
    sender: str
    content: str
    timestamp: datetime
    is_from_me: bool
    media_type: str
    filename: str


@dataclass
class Chat:
    jid: str
    name: str


@dataclass
class ChatView:
    source: str
    jid: str
    type: str
    name: str
    slug: str
