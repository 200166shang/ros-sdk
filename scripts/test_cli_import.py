"""Regression tests for optional CLI dependencies."""

from __future__ import annotations

import subprocess
import sys
import unittest


class CliImportTest(unittest.TestCase):
    """The development CLI should not require Runtime client dependencies."""

    def test_cli_import_does_not_require_grpc(self) -> None:
        script = """
import builtins

real_import = builtins.__import__


def import_without_grpc(name, *args, **kwargs):
    if name == "grpc" or name.startswith("grpc."):
        raise ModuleNotFoundError("grpc is intentionally unavailable")
    return real_import(name, *args, **kwargs)


builtins.__import__ = import_without_grpc
import scripts.cli  # noqa: F401
"""
        subprocess.run([sys.executable, "-c", script], check=True)


if __name__ == "__main__":
    unittest.main()
