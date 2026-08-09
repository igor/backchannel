from datetime import datetime, timezone
from derive.model import Message, Chat, ChatView


def test_message():
    m = Message(
        id="1", chat_jid="a@b.c", sender="u", content="hi",
        timestamp=datetime.now(timezone.utc), is_from_me=False,
        media_type="", filename="")
    assert m.id == "1"
    assert m.sender == "u"


def test_chat():
    c = Chat(jid="a@b.c", name="Test")
    assert c.name == "Test"


def test_chat_view():
    v = ChatView(source="whatsapp", jid="a@b.c", type="dm", name="Test", slug="test")
    assert v.slug == "test"
    assert v.type == "dm"
