"""Read project version from pyproject.toml."""

import tomllib
from pathlib import Path


def get_version() -> str:
    """Return the version string from pyproject.toml."""
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with open(pyproject, "rb") as f:
        return tomllib.load(f)["project"]["version"]
