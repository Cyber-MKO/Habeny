#!/usr/bin/env python3
"""
THIRD_PARTY_NOTICES.txt: the open-source software a Habeny release ships, with each
package's license and its license and notice files.

  python3 deploy/third_party_notices.py [--out FILE] [--summary]

Covers:
- the Python packages in requirements.txt and everything they depend on, as installed in
  the Python running this script (build-release.sh uses a fresh virtualenv with exactly
  requirements.txt)
- the npm packages bundled into the frontend (production dependencies, from
  frontend/node_modules; run `npm ci` first)

Not covered, because releases don't ship them: python3-lxc and the other OS packages the
.deb depends on (the OS installs them under their own licenses), SIEM agents (downloaded
by the customer's server from each vendor at deploy time, see docs/legal/siem-vendors.md),
and development-only tools.

It also enforces the license policy: it fails (exit 1) when a bundled package's license
is copyleft (GPL, AGPL, SSPL, ...), not recognized, or missing, unless REVIEWED lists it
with the reason it's acceptable. LGPL is allowed for Python packages, which are used
unmodified and can be replaced by the user.
"""
import argparse
import json
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Licenses bundled packages may have (SPDX IDs, or the names packages commonly use)
ALLOWED = [
    r"MIT( License)?", r"MIT-0", r"MIT-CMU", r"BSD License", r"Apache Software License", r"ISC", r"0BSD", r"BSD", r"BSD-\d-Clause", r"Apache[- ]?(Software )?(License)?[- ,]*(2\.0|Version 2\.0)?",
    r"Apache-2\.0", r"PSF(-2\.0)?", r"Python Software Foundation( License)?", r"Zlib", r"Unlicense", r"CC0-1\.0",
    r"MPL-2\.0", r"Mozilla Public License 2\.0.*", r"HPND", r"Historical Permission Notice and Disclaimer.*",
    r"BlueOak-1\.0\.0", r"CC-BY-4\.0", r"LGPL.*", r"GNU Lesser General Public License.*",
]
DENIED = re.compile(r"\b(A?GPL|GNU (Affero )?General Public|SSPL|Server Side Public|BUSL|Business Source|"
                    r"Commons Clause|Elastic License|CC-BY-NC|Non-?Commercial)", re.IGNORECASE)
LESSER = re.compile(r"LGPL|Lesser General Public", re.IGNORECASE)

# Packages checked by hand: name -> (license to report, why it's acceptable)
REVIEWED: dict[str, tuple[str, str]] = {}

NOTICE_FILE = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE|AUTHORS)([.-][^/]*)?$", re.IGNORECASE)
MAX_TEXT = 60_000  # a few packages bundle huge license collections; the rest are well under this


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _python_license(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    if meta.get("License-Expression"):
        return meta["License-Expression"].strip()
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    classifiers = [c for c in classifiers if c not in ("OSI Approved",)]
    if classifiers:
        return " / ".join(classifiers)
    text = (meta.get("License") or "").strip()
    if text and len(text) < 100 and "\n" not in text:
        return text
    return "UNKNOWN"


def python_packages() -> list[dict]:
    from packaging.requirements import Requirement  # a dependency of matplotlib, so always present here

    seen: dict[str, dict] = {}
    queue: list[tuple[str, set[str]]] = []
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            req = Requirement(line)
            queue.append((req.name, set(req.extras)))
    while queue:
        name, extras = queue.pop()
        key = _canonical(name)
        if key in seen:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            raise SystemExit(f"error: {name} isn't installed; install requirements.txt into this Python first") from None
        texts = []
        for file in dist.files or []:
            if NOTICE_FILE.search(str(file)) and not str(file).endswith((".py", ".pyc")):
                path = Path(dist.locate_file(file))
                if path.is_file():
                    texts.append((str(file), path.read_text(errors="replace")[:MAX_TEXT]))
        seen[key] = {"ecosystem": "Python", "name": dist.metadata["Name"], "version": dist.version,
                     "license": _python_license(dist), "url": dist.metadata.get("Home-page") or
                     next((u.split(",", 1)[1].strip() for u in dist.metadata.get_all("Project-URL") or []
                           if u.lower().startswith(("source", "homepage", "repository"))), ""),
                     "texts": texts}
        for spec in dist.requires or []:
            req = Requirement(spec)
            if req.marker is None or any(req.marker.evaluate({"extra": e}) for e in (extras or {""})):
                queue.append((req.name, set(req.extras)))
    return sorted(seen.values(), key=lambda p: p["name"].lower())


def npm_packages() -> list[dict]:
    frontend = ROOT / "frontend"
    if not (frontend / "node_modules").is_dir():
        raise SystemExit("error: frontend/node_modules is missing; run `npm ci` in frontend/ first")
    out = subprocess.run(["npm", "ls", "--omit=dev", "--all", "--parseable"], cwd=frontend, capture_output=True,
                         text=True, check=False)
    packages = {}
    for line in out.stdout.splitlines():
        path = Path(line.strip())
        if path == frontend or not (path / "package.json").is_file():
            continue
        info = json.loads((path / "package.json").read_text())
        license_ = info.get("license") or info.get("licenses") or "UNKNOWN"
        if isinstance(license_, dict):
            license_ = license_.get("type", "UNKNOWN")
        if isinstance(license_, list):
            license_ = " OR ".join(x.get("type", "?") if isinstance(x, dict) else str(x) for x in license_)
        repo = info.get("repository")
        texts = [(f.name, f.read_text(errors="replace")[:MAX_TEXT]) for f in sorted(path.iterdir())
                 if f.is_file() and NOTICE_FILE.search(f.name)]
        packages[(info["name"], info["version"])] = {
            "ecosystem": "npm", "name": info["name"], "version": info["version"], "license": str(license_),
            "url": (repo.get("url") if isinstance(repo, dict) else repo) or info.get("homepage") or "",
            "texts": texts}
    return sorted(packages.values(), key=lambda p: p["name"].lower())


def _allowed(license_: str, ecosystem: str) -> bool:
    # "A OR B": acceptable if any choice is; "A AND B": only if all are
    expr = license_.strip("() ")
    if " OR " in expr:
        return any(_allowed(part, ecosystem) for part in expr.split(" OR "))
    if " AND " in expr:
        return all(_allowed(part, ecosystem) for part in expr.split(" AND "))
    if " / " in expr:  # several license classifiers: the package is offered under each
        return any(_allowed(part, ecosystem) for part in expr.split(" / "))
    if LESSER.search(expr):
        return ecosystem == "Python"  # bundled into the JS bundle it would be a static combination
    if DENIED.search(expr):
        return False
    return any(re.fullmatch(pattern, expr.strip(), re.IGNORECASE) for pattern in ALLOWED)


def check(packages: list[dict]) -> list[str]:
    problems = []
    for p in packages:
        reviewed = REVIEWED.get(_canonical(p["name"]))
        if reviewed:
            p["license"] = f"{reviewed[0]}"
            continue
        if not _allowed(p["license"], p["ecosystem"]):
            problems.append(f"{p['ecosystem']} {p['name']} {p['version']}: license {p['license']!r} is not allowed "
                            "(or not recognized). Replace the package, or review it and add it to REVIEWED in "
                            "deploy/third_party_notices.py.")
        if not p["texts"]:
            p["missing_text"] = True
    return problems


def render(packages: list[dict]) -> str:
    from app.version import __version__

    lines = [
        f"Habeny {__version__}: third-party software notices",
        "=" * 60,
        "",
        "Habeny is proprietary software of Habeny Platform (see LICENSE). It includes the",
        "open-source packages below, each under its own license. Their license and notice",
        "files follow the list.",
        "",
        "Not included, so not listed: the OS packages the installer asks the system for",
        "(e.g. python3-lxc, LGPL-2.1+, installed by apt), and SIEM agents, which the",
        "customer's server downloads from each vendor when deploying.",
        "",
    ]
    for ecosystem in ("Python", "npm"):
        group = [p for p in packages if p["ecosystem"] == ecosystem]
        lines += [f"{ecosystem} packages ({len(group)})", "-" * 40]
        width = max((len(p["name"]) + len(p["version"]) + 1 for p in group), default=20)
        lines += [f"{p['name'] + ' ' + p['version']:<{width}}  {p['license']}" for p in group]
        lines.append("")
    for p in packages:
        lines += ["", "=" * 78, f"{p['name']} {p['version']} ({p['ecosystem']})", f"License: {p['license']}"]
        if p["url"]:
            lines.append(f"Source: {p['url']}")
        lines.append("=" * 78)
        if not p["texts"]:
            lines.append(f"(The package ships no license file. Its license is {p['license']}; the full text is at "
                         "https://spdx.org/licenses/ .)")
        for name, text in p["texts"]:
            lines += ["", f"--- {name} ---", text.rstrip()]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=str(ROOT / "THIRD_PARTY_NOTICES.txt"))
    parser.add_argument("--summary", action="store_true", help="print the package list only; write nothing")
    parser.add_argument("--only", choices=["python", "npm"], help="one ecosystem (policy checks in CI)")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))

    packages = ((python_packages() if args.only != "npm" else []) +
                (npm_packages() if args.only != "python" else []))
    problems = check(packages)
    if args.summary:
        for p in packages:
            print(f"{p['ecosystem']:<6} {p['name']:<32} {p['version']:<12} {p['license']}"
                  f"{'  (no license file)' if p.get('missing_text') else ''}")
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    if not args.summary:
        Path(args.out).write_text(render(packages))
        print(f"{args.out}: {len(packages)} packages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
