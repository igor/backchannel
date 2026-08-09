import pytest

from describe import text


class Request:
    def __init__(self):
        self.levels = []

    def setRecognitionLevel_(self, level):
        self.levels.append(level)


def test_accurate_recognition_level_is_zero():
    request = Request()
    text._configure_request(request)
    assert request.levels == [0]


def test_real_vision_recognition_is_a_visible_optional_integration(tmp_path):
    pytest.importorskip("Vision", reason="pyobjc Vision is not installed")
    image_module = pytest.importorskip("PIL.Image", reason="PIL is not installed")
    draw_module = pytest.importorskip("PIL.ImageDraw", reason="PIL is not installed")
    image = image_module.new("RGB", (800, 240), "white")
    draw_module.Draw(image).text((40, 80), "fixture image text", fill="black")
    path = tmp_path / "vision-fixture.png"
    image.save(path)
    rows = text.recognize(path)
    assert isinstance(rows, list)
    assert all(isinstance(value, tuple) and len(value) == 2 for value in rows)
