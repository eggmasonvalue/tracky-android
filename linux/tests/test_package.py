"""Smoke tests for the package skeleton."""

from importlib import import_module

import pytest

import tracky_mcp


@pytest.mark.parametrize(
    "module_name",
    [
        "tracky_mcp.acquisition",
        "tracky_mcp.ble",
        "tracky_mcp.protocol",
        "tracky_mcp.metrics",
        "tracky_mcp.storage",
        "tracky_mcp.mcp",
    ],
)
def test_subpackages_import(module_name: str) -> None:
    assert import_module(module_name).__doc__


def test_package_version() -> None:
    assert tracky_mcp.__version__ == "0.1.0"
