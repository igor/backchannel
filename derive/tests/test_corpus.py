from datetime import datetime, timezone, date
from derive import corpus
from derive.model import Message, ChatView, Chat


def test_day_file_path_dm():
    root = __import__("pathlib").Path("/root")
    view = ChatView(source="whatsapp", jid="a@b.c", type="dm", name="Anna", slug="anna")
    assert corpus.day_file_path(root, view, date(2026, 6, 15)) == root / "whatsapp" / "dms" / "anna" / "2026-06-15.md"


def test_day_file_path_group():
    root = __import__("pathlib").Path("/root")
    view = ChatView(source="whatsapp", jid="g@g.us", type="group", name="G", slug="g")
    assert corpus.day_file_path(root, view, date(2026, 6, 15)) == root / "whatsapp" / "groups" / "g" / "2026-06-15.md"


def test_build_day_file():
    view = ChatView(source="whatsapp", jid="g@g.us", type="group", name="G", slug="g")
    day = date(2026, 6, 15)
    ts1 = datetime(2026, 6, 15, 9, 0, tzinfo=timezone(__import__("datetime").timedelta(hours=2)))
    ts2 = datetime(2026, 6, 15, 9, 1, tzinfo=timezone(__import__("datetime").timedelta(hours=2)))
    msgs = [
        Message(id="M1", chat_jid="g@g.us", sender="u", content="see https://example.com/x",
                timestamp=ts1, is_from_me=False, media_type="", filename=""),
        Message(id="M2", chat_jid="g@g.us", sender="u", content="ok",
                timestamp=ts2, is_from_me=True, media_type="", filename=""),
    ]
    text = corpus.build_day_file(view, day, msgs, {}, image_text=None)
    assert text.startswith("---\n")
    assert "type: group" in text
    assert "jid: g@g.us" in text
    assert "message_count: 2" in text
    assert "link_count: 1" in text
    assert "whatsapp" in text
    assert "# G — 2026-06-15" in text
    assert "**09:00 — u**: see https://example.com/x<!-- m:M1 -->" in text
    assert "**09:01 — You**: ok<!-- m:M2 -->" in text


def test_build_day_file_with_transcripts():
    view = ChatView(source="whatsapp", jid="g@g.us", type="group", name="G", slug="g")
    day = date(2026, 6, 15)
    ts = datetime(2026, 6, 15, 9, 0, tzinfo=timezone(__import__("datetime").timedelta(hours=2)))
    msgs = [
        Message(id="M1", chat_jid="g@g.us", sender="u", content="",
                timestamp=ts, is_from_me=False, media_type="audio", filename="a.ogg"),
    ]
    text = corpus.build_day_file(view, day, msgs, {}, transcripts={"M1": "hallo welt"}, image_text=None)
    assert "🎙 hallo welt" in text


def test_build_day_file_resolves_sender_names():
    view = ChatView(source="whatsapp", jid="g@g.us", type="group", name="G", slug="g")
    day = date(2026, 6, 15)
    ts = datetime(2026, 6, 15, 9, 0, tzinfo=timezone(__import__("datetime").timedelta(hours=2)))
    msgs = [Message(id="M1", chat_jid="g@g.us", sender="447700900109", content="hi",
                    timestamp=ts, is_from_me=False, media_type="", filename="")]
    text = corpus.build_day_file(view, day, msgs, {}, names={"447700900109": "Pia Beispiel"}, image_text=None)
    assert "**09:00 — Pia Beispiel**: hi<!-- m:M1 -->" in text


def test_frontmatter_indexes_non_document_like_image_text():
    view = ChatView(source="whatsapp", jid="fixture-group@g.us", type="group", name="Fixture Group", slug="fixture-group")
    day = date(2026, 8, 8)
    message = Message(id="fixture-image", chat_jid=view.jid, sender="fixture", content="", timestamp=datetime(2026, 8, 8, 14, 2, tzinfo=timezone.utc), is_from_me=False, media_type="image", filename="fixture.png")
    text = corpus.build_day_file(view, day, [message], {}, image_text={"fixture-image": {"text": "searchable fixture phrase", "document_like": False}})
    assert "has_image_text: true" in text
    assert "message_id: fixture-image" in text
    assert "text: searchable fixture phrase" in text
    assert "[image]" in text


def test_frontmatter_caps_each_image_text_at_two_thousand_characters():
    view = ChatView(source="signal", jid="fixture@signal", type="dm", name="Fixture", slug="fixture")
    day = date(2026, 8, 8)
    message = Message(id="fixture-long", chat_jid=view.jid, sender="fixture", content="", timestamp=datetime(2026, 8, 8, 14, 2, tzinfo=timezone.utc), is_from_me=False, media_type="image", filename="fixture.png")
    full = "x" * 2001
    text = corpus.build_day_file(view, day, [message], {}, image_text={"fixture-long": {"text": full, "document_like": False}})
    assert "truncated: true" in text
    assert ("x" * 2000) in text
    assert ("x" * 2001) not in text


def test_atomic_write(tmp_path):
    p = tmp_path / "a" / "b.md"
    corpus.atomic_write(p, "hello")
    assert p.read_text() == "hello"
    # idempotent same content
    corpus.atomic_write(p, "hello")
    assert p.read_text() == "hello"
