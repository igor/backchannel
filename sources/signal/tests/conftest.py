import json
from datetime import datetime, timezone
import pytest

DM_UUID = "11111111-2222-4333-8444-555555555555"
GROUP_ID = "R3JvdXAtMDE="
OWN_UUID = "00000000-1111-4222-8333-444444444444"   # the archive's own linked account


def envelope(**fields):
    base = {"sourceUuid": DM_UUID, "sourceName": "Ada Example", "timestamp": 1785135600000}
    base.update(fields)
    return json.dumps({"envelope": base})


@pytest.fixture
def now():
    return datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def lines():
    return [
        envelope(dataMessage={"timestamp": 1785135600000, "message": "direct note"}),
        envelope(sourceUuid="22222222-3333-4444-8555-666666666666", sourceName="Bea Example",
                 dataMessage={"timestamp": 1785135660000, "message": "group note",
                              "groupInfo": {"groupId": GROUP_ID}}),
        envelope(dataMessage={"timestamp": 1785135720000, "message": "",
                              "attachments": [{"storedFilename": "voice.m4a", "contentType": "audio/mp4"}]}),
        envelope(dataMessage={"timestamp": 1785135780000,
                              "reaction": {"emoji": "👍", "targetSentTimestamp": 1785135600000}}),
        envelope(dataMessage={"timestamp": 1785135840000, "message": "revised",
                              "editMessage": {"targetSentTimestamp": 1785135600000}}),
        envelope(dataMessage={"timestamp": 1785135900000,
                              "remoteDelete": {"targetSentTimestamp": 1785135600000}}),
        envelope(sourceUuid="99999999-0000-4000-8000-999999999999", sourceName="", dataMessage={"timestamp": 1785135960000, "message": "no profile"}),
        envelope(dataMessage={"timestamp": 1785136020000,
                              "groupInfo": {"groupId": GROUP_ID, "type": "UPDATE", "name": "Renamed group"}}),
        envelope(dataMessage={"timestamp": 1785136030000, "message": "file attached",
                              "attachments": [{"storedFilename": "brief.pdf", "contentType": "application/pdf"}]}),
        # Outbound: sent from this account, synced back from the phone. The chat is the
        # RECIPIENT, the sender is us -- both must resolve correctly or the DM splits.
        envelope(sourceUuid=OWN_UUID, sourceName="", timestamp=1785136040000,
                 syncMessage={"sentMessage": {"timestamp": 1785136040000, "message": "my reply",
                                              "destinationUuid": DM_UUID}}),
    ]