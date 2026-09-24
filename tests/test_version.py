"""The version is kept in one place and every release has changelog entries."""
import json
import re
import subprocess
from pathlib import Path

from app.version import __version__

ROOT = Path(__file__).resolve().parent.parent


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_changelog_has_notes_for_this_version():
    """deploy/release-notes.sh feeds the release; bumping the version needs a changelog section."""
    result = subprocess.run([str(ROOT / "deploy/release-notes.sh"), __version__],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert "## [Unreleased]" in changelog
    assert f"[{__version__}]: " in changelog


def test_version_is_not_hardcoded_elsewhere():
    assert "__APP_VERSION__" in (ROOT / "frontend/vite.config.js").read_text()
    package = json.loads((ROOT / "frontend/package.json").read_text())
    assert "version" not in package  # the UI takes app/version.py's at build time
    stray = [str(p.relative_to(ROOT)) for p in (ROOT / "app").rglob("*.py")
             if p.name != "version.py" and f'"{__version__}"' in p.read_text()]
    assert not stray
