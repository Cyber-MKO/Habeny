"""
The license policy for bundled dependencies (deploy/third_party_notices.py).
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("third_party_notices", ROOT / "deploy" / "third_party_notices.py")
notices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notices)


def test_policy():
    allowed = notices._allowed
    for ok in ("MIT", "MIT License", "BSD-3-Clause", "Apache-2.0", "ISC", "Apache-2.0 OR BSD-3-Clause",
               "BSD License / Apache Software License", "PSF-2.0", "MPL-2.0"):
        assert allowed(ok, "Python"), ok
    for bad in ("GPL-3.0-only", "AGPL-3.0", "GNU General Public License v2 (GPLv2)", "SSPL-1.0",
                "Elastic License 2.0", "MIT AND GPL-2.0", "UNKNOWN", "Proprietary"):
        assert not allowed(bad, "Python"), bad
    assert allowed("GPL-2.0 OR MIT", "npm")  # a choice that includes a permissive license
    assert allowed("LGPL-2.1-or-later", "Python") and not allowed("LGPL-2.1-or-later", "npm")


def test_installed_python_dependencies_pass():
    packages = notices.python_packages()
    names = {p["name"].lower() for p in packages}
    assert {"fastapi", "cryptography", "matplotlib"} <= names
    assert notices.check(packages) == []


def test_render(monkeypatch):
    fake = [{"ecosystem": "Python", "name": "demo", "version": "1.0", "license": "MIT", "url": "https://x",
             "texts": [("LICENSE", "Permission is hereby granted")]},
            {"ecosystem": "npm", "name": "bare", "version": "2.0", "license": "ISC", "url": "", "texts": []}]
    text = notices.render(fake)
    assert "demo 1.0" in text and "Permission is hereby granted" in text and "ships no license file" in text
