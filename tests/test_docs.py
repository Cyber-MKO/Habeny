"""
The documentation: relative links and #anchors resolve, and the generated API reference is
current (deploy/api_reference.py).
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", ROOT / "SUPPORT.md", ROOT / "SECURITY.md", ROOT / "CONTRIBUTING.md",
        *sorted((ROOT / "docs").rglob("*.md"))]
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def _anchors(path: Path) -> set[str]:
    anchors = set()
    in_code = False
    for line in path.read_text().splitlines():
        if line.startswith("```"):
            in_code = not in_code
        if not in_code and line.startswith("#"):
            title = line.lstrip("#").strip().lower()
            anchors.add(re.sub(r"[^\w\- ]", "", title).replace(" ", "-"))
    return anchors


def test_relative_links_resolve():
    problems = []
    for doc in DOCS:
        text = re.sub(r"```.*?```", "", doc.read_text(), flags=re.S)
        for target in LINK.findall(text):
            if re.match(r"^[a-z]+:", target):
                continue  # http(s), mailto
            file_part, _, anchor = target.partition("#")
            path = (doc.parent / file_part).resolve() if file_part else doc
            if not path.exists():
                problems.append(f"{doc.relative_to(ROOT)}: {target} (no such file)")
            elif anchor and path.suffix == ".md" and anchor not in _anchors(path):
                problems.append(f"{doc.relative_to(ROOT)}: {target} (no such heading)")
    assert not problems, "\n".join(problems)


def test_api_reference_is_current():
    env = {**os.environ, "PYTHONPATH": str(ROOT / "tests" / "stubs"), "HABENY_LXC_BACKEND": "direct"}
    result = subprocess.run([sys.executable, str(ROOT / "deploy" / "api_reference.py"), "--check"],
                            capture_output=True, text=True, env=env, cwd=ROOT, check=False)
    assert result.returncode == 0, result.stderr[-2000:]
