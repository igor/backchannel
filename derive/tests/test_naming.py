from derive import naming
from derive.model import Chat


def test_slugify():
    assert naming.slugify("Sample Group 🎲") == "sample-group"
    assert naming.slugify("AGI") == "agi"
    assert naming.slugify("José / Jose!!") == "jos-jose"
    assert naming.slugify("") == ""


def test_chat_type():
    assert naming.chat_type("whatsapp", "447700900101@s.whatsapp.net") == "dm"
    assert naming.chat_type("whatsapp", "120363100000000001@g.us") == "group"
    assert naming.chat_type("whatsapp", "x@newsletter") is None
    assert naming.chat_type("whatsapp", "status@broadcast") is None
    assert naming.chat_type("whatsapp", "x@lid") is None


def test_resolve_slugs():
    chats = {
        "120363100000000001@g.us": Chat("120363100000000001@g.us", "Sample Group 🎲"),
        "447700900101@s.whatsapp.net": Chat("447700900101@s.whatsapp.net", ""),   # blank -> number
        "447700900123@s.whatsapp.net": Chat("447700900123@s.whatsapp.net", "Chris Muster"),
        "447700900102@s.whatsapp.net": Chat("447700900102@s.whatsapp.net", "Chris Muster"),  # collision
        "x@newsletter": Chat("x@newsletter", "Channel"),   # skipped type
    }
    slugs = naming.resolve_slugs("whatsapp", chats)
    # unique names -> bare slug
    assert slugs["120363100000000001@g.us"] == "sample-group"
    assert slugs["447700900101@s.whatsapp.net"] == "447700900101"
    # collision -> both kept, disambiguated by phone number (no data loss)
    assert slugs["447700900123@s.whatsapp.net"] == "chris-muster-447700900123"
    assert slugs["447700900102@s.whatsapp.net"] == "chris-muster-447700900102"
    # skipped types absent
    assert "x@newsletter" not in slugs
