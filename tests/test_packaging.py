import tomllib
from pathlib import Path


def test_pyproject_includes_darwin_vision_and_describe_package():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert 'pyobjc-framework-Vision; sys_platform == "darwin"' in data["project"]["dependencies"]
    assert "describe*" in data["tool"]["setuptools"]["packages"]["find"]["include"]
