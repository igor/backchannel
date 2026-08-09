from datetime import datetime, timezone, timedelta
from derive import render
from derive.model import Message, ChatView, Chat


def test_media_placeholder():
    assert render.media_placeholder("image") == "[image]"
    assert render.media_placeholder("video") == "[video]"
    assert render.media_placeholder("audio", "a.ogg") == "[voice note · a.ogg]"
    assert render.media_placeholder("document", "r.pdf") == "[document · r.pdf]"
    assert render.media_placeholder("unknown") == "[unknown]"


def test_format_line_text():
    ts = datetime(2026, 6, 15, 9, 5, tzinfo=timezone(timedelta(hours=2)))
    m = Message(id="X", chat_jid="a@b.c", sender="u", content="Morning", timestamp=ts, is_from_me=False, media_type="", filename="")
    assert render.format_line(m, "Igor", image_text=None) == "**09:05 — Igor**: Morning<!-- m:X -->\n"


def test_format_line_audio():
    ts = datetime(2026, 6, 15, 9, 5, tzinfo=timezone(timedelta(hours=2)))
    m = Message(id="A", chat_jid="a@b.c", sender="u", content="", timestamp=ts, is_from_me=True, media_type="audio", filename="a.ogg")
    assert render.format_line(m, "You", image_text=None) == "**09:05 — You**: [voice note · a.ogg]<!-- m:A -->\n"


def test_sender_display_from_me():
    ts = datetime(2026, 6, 15, 9, 5, tzinfo=timezone.utc)
    m = Message(id="X", chat_jid="a@b.c", sender="u", content="", timestamp=ts, is_from_me=True, media_type="", filename="")
    assert render.sender_display(m, ChatView(source="whatsapp", jid="a@b.c", type="dm", name="Anna", slug="anna"), {}) == "You"


def test_sender_display_dm():
    ts = datetime(2026, 6, 15, 9, 5, tzinfo=timezone.utc)
    m = Message(id="X", chat_jid="a@b.c", sender="u", content="", timestamp=ts, is_from_me=False, media_type="", filename="")
    view = ChatView(source="whatsapp", jid="a@b.c", type="dm", name="Anna", slug="anna")
    assert render.sender_display(m, view, {}) == "Anna"


def test_sender_display_group_known():
    ts = datetime(2026, 6, 15, 9, 5, tzinfo=timezone.utc)
    m = Message(id="X", chat_jid="g@g.us", sender="12025550101", content="", timestamp=ts, is_from_me=False, media_type="", filename="")
    view = ChatView(source="whatsapp", jid="g@g.us", type="group", name="G", slug="g")
    chats = {"12025550101@s.whatsapp.net": Chat(jid="12025550101@s.whatsapp.net", name="Joe")}
    assert render.sender_display(m, view, chats) == "Joe"


def test_sender_display_group_unknown():
    ts = datetime(2026, 6, 15, 9, 5, tzinfo=timezone.utc)
    m = Message(id="X", chat_jid="g@g.us", sender="49999", content="", timestamp=ts, is_from_me=False, media_type="", filename="")
    view = ChatView(source="whatsapp", jid="g@g.us", type="group", name="G", slug="g")
    assert render.sender_display(m, view, {}) == "+49999"


def test_sender_display_group_via_names():
    ts = datetime(2026, 6, 15, 9, 5, tzinfo=timezone.utc)
    m = Message(id="X", chat_jid="g@g.us", sender="49888", content="", timestamp=ts, is_from_me=False, media_type="", filename="")
    view = ChatView(source="whatsapp", jid="g@g.us", type="group", name="G", slug="g")
    assert render.sender_display(m, view, {}, names={"49888": "Bernd"}) == "Bernd"


def test_sender_display_names_beats_chats():
    ts = datetime(2026, 6, 15, 9, 5, tzinfo=timezone.utc)
    m = Message(id="X", chat_jid="g@g.us", sender="12025550101", content="", timestamp=ts, is_from_me=False, media_type="", filename="")
    view = ChatView(source="whatsapp", jid="g@g.us", type="group", name="G", slug="g")
    chats = {"12025550101@s.whatsapp.net": Chat(jid="12025550101@s.whatsapp.net", name="Joe DM")}
    assert render.sender_display(m, view, chats, names={"12025550101": "Joe Contact"}) == "Joe Contact"


def test_sender_display_group_names_empty_fallback():
    ts = datetime(2026, 6, 15, 9, 5, tzinfo=timezone.utc)
    m = Message(id="X", chat_jid="g@g.us", sender="49999", content="", timestamp=ts, is_from_me=False, media_type="", filename="")
    view = ChatView(source="whatsapp", jid="g@g.us", type="group", name="G", slug="g")
    assert render.sender_display(m, view, {}, names={}) == "+49999"


def test_format_line_audio_with_transcript():
    ts = datetime(2026, 6, 15, 9, 5, tzinfo=timezone(timedelta(hours=2)))
    m = Message(id="X", chat_jid="a@b.c", sender="u", content="", timestamp=ts, is_from_me=False, media_type="audio", filename="a.ogg")
    assert render.format_line(m, "Mam", transcripts={"X": "hallo welt"}, image_text=None) == "**09:05 — Mam**: 🎙 hallo welt<!-- m:X -->\n"


def test_format_line_audio_without_transcript():
    ts = datetime(2026, 6, 15, 9, 5, tzinfo=timezone(timedelta(hours=2)))
    m = Message(id="A", chat_jid="a@b.c", sender="u", content="", timestamp=ts, is_from_me=True, media_type="audio", filename="a.ogg")
    assert render.format_line(m, "You", transcripts={}, image_text=None) == "**09:05 — You**: [voice note · a.ogg]<!-- m:A -->\n"


def test_format_line_audio_empty_transcript():
    ts = datetime(2026, 6, 15, 9, 5, tzinfo=timezone(timedelta(hours=2)))
    m = Message(id="A", chat_jid="a@b.c", sender="u", content="", timestamp=ts, is_from_me=True, media_type="audio", filename="a.ogg")
    # empty-string transcript -> placeholder, not an empty 🎙
    assert render.format_line(m, "You", transcripts={"A": ""}, image_text=None) == "**09:05 — You**: [voice note · a.ogg]<!-- m:A -->\n"


def test_format_line_renders_document_like_image_text_with_collapsed_whitespace():
    ts = datetime(2026, 8, 8, 14, 2, tzinfo=timezone.utc)
    message = Message(id="fixture-image", chat_jid="fixture-chat", sender="fixture", content="", timestamp=ts, is_from_me=False, media_type="image", filename="fixture.png")
    image_text = {"fixture-image": {"text": "Venue\nconfirmed   for\tthe 14th", "document_like": True}}
    assert render.format_line(message, "Fixture", image_text=image_text) == "**14:02 — Fixture**: 🖼 Venue confirmed for the 14th<!-- m:fixture-image -->\n"


def test_format_line_cuts_at_last_word_boundary_at_or_before_two_hundred_characters():
    ts = datetime(2026, 8, 8, 14, 2, tzinfo=timezone.utc)
    message = Message(id="fixture-long", chat_jid="fixture-chat", sender="fixture", content="", timestamp=ts, is_from_me=False, media_type="image", filename="fixture.png")
    full = "a" * 199 + " " + "tail"
    image_text = {"fixture-long": {"text": full, "document_like": True}}
    rendered = render.format_line(message, "Fixture", image_text=image_text)
    assert "🖼 " + ("a" * 199) + "…" in rendered
    assert "tail" not in rendered


def test_format_line_keeps_image_placeholder_when_not_document_like():
    ts = datetime(2026, 8, 8, 14, 2, tzinfo=timezone.utc)
    message = Message(id="fixture-short", chat_jid="fixture-chat", sender="fixture", content="", timestamp=ts, is_from_me=False, media_type="image", filename="fixture.png")
    assert render.format_line(message, "Fixture", image_text={"fixture-short": {"text": "small caption", "document_like": False}}) == "**14:02 — Fixture**: [image]<!-- m:fixture-short -->\n"
