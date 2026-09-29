"""The generated tool table in docs/API.md must match the registry exactly
— the guard against the four-contradictory-tool-counts failure mode."""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_tool_table_matches_registry():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "dump_tool_table.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_version_matches_package_metadata():
    spec = importlib.util.spec_from_file_location("_ews_mcp_init", ROOT / "ewsmcp" / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.__version__ == "1.1.0"
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{mod.__version__}"' in pyproject
