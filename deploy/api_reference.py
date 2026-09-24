#!/usr/bin/env python3
"""
docs/api-reference.md: every HTTP and WebSocket endpoint, the role it needs, its
parameters and request body, generated from the app itself.

  python3 deploy/api_reference.py            # rewrite docs/api-reference.md
  python3 deploy/api_reference.py --check    # exit 1 if it's out of date (the tests do this)

Run from the repository root with the app's dependencies installed (and, without python3-lxc,
PYTHONPATH=tests/stubs). The guide around it is docs/api.md.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "api-reference.md"

# Sections, in order: (title, path prefixes)
SECTIONS = [
    ("Health and monitoring", ["/healthz", "/readyz", "/metrics", "/system/alerts", "/system/health"]),
    ("Sign-in and setup", ["/auth"]),
    ("Your account, users and API tokens", ["/users"]),
    ("Teams", ["/teams"]),
    ("License", ["/license"]),
    ("Containers", ["/agents"]),
    ("Groups", ["/groups"]),
    ("Manager profiles", ["/managers"]),
    ("Configuration templates", ["/configs"]),
    ("Syslog configurations", ["/syslog-configs", "/syslog"]),
    ("Simulations", ["/simulations"]),
    ("Benchmarks", ["/benchmarks"]),
    ("SIEM statistics", ["/siem"]),
    ("Reports", ["/reports"]),
    ("Activity (audit trail)", ["/activity"]),
    ("Notifications", ["/notifications"]),
    ("Backups", ["/system/backups"]),
    ("Other hosts", ["/hosts"]),
    ("System", ["/system", "/"]),
    ("Live data (WebSocket)", ["/ws"]),
]


def _dependency_calls(dependant) -> set:
    calls = set()
    for dep in dependant.dependencies:
        if dep.call is not None:
            calls.add(dep.call)
        calls |= _dependency_calls(dep)
    return calls


def _role(route, method: str) -> str:
    from app.services import auth
    calls = _dependency_calls(route.dependant)
    if auth.require_admin in calls:
        return "admin"
    if auth.require_access in calls:
        return "viewer" if method == "GET" else "operator"
    if auth.require_session in calls:
        return "signed in (browser session)"
    if auth.require_user in calls:
        return "signed in"
    return "none"


def _type_name(schema: dict, spec: dict) -> str:
    if "$ref" in schema:
        target = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
        if "enum" in target:  # list the choices rather than the enum's class name
            return _type_name(target, spec)
        return schema["$ref"].rsplit("/", 1)[-1]
    if "anyOf" in schema:
        names = [_type_name(s, spec) for s in schema["anyOf"] if s.get("type") != "null"]
        return " or ".join(names) + (" (optional)" if len(names) < len(schema["anyOf"]) else "")
    if schema.get("type") == "array":
        return f"list of {_type_name(schema.get('items', {}), spec)}"
    if "enum" in schema:
        return " \\| ".join(f"`{v}`" for v in schema["enum"])
    return schema.get("type", "any")


def _model_fields(model: dict, spec: dict, depth: int = 0) -> list[str]:
    required = set(model.get("required", []))
    fields = []
    for name, prop in model.get("properties", {}).items():
        default = f", default `{prop['default']}`" if "default" in prop and prop["default"] not in (None, [], {}) else ""
        fields.append(f"{'  ' * depth}- `{name}`{' (required)' if name in required else ''}: "
                      f"{_type_name(prop, spec)}{default}")
        nested = _nested_model(prop, spec)
        if nested and depth < 2:
            fields += _model_fields(nested, spec, depth + 1)
    return fields


def _nested_model(prop: dict, spec: dict) -> dict | None:
    """The object model a field holds (directly or as an optional), for listing its fields."""
    for candidate in [prop, *prop.get("anyOf", [])]:
        if "$ref" in candidate:
            target = spec["components"]["schemas"][candidate["$ref"].rsplit("/", 1)[-1]]
            if target.get("properties"):
                return target
    return None


def _body_fields(operation: dict, spec: dict) -> list[str]:
    content = operation.get("requestBody", {}).get("content", {})
    schema = content.get("application/json", {}).get("schema")
    if not schema or "$ref" not in schema:
        return []
    return _model_fields(spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]], spec)


def _params(operation: dict, spec: dict) -> list[str]:
    return [f"`{p['name']}`{' (required)' if p.get('required') and p['in'] == 'query' else ''}"
            for p in operation.get("parameters", []) if p["in"] == "query"]


def _section(path: str) -> str:
    for title, prefixes in SECTIONS:
        if any(path == p or path.startswith(p.rstrip("/") + "/") for p in prefixes if p != "/") or \
                ("/" in prefixes and path == "/"):
            return title
    return "System"


def render() -> str:
    os.environ["HABENY_DATA_DIR"] = tempfile.mkdtemp(prefix="habeny-api-reference-")
    sys.path.insert(0, str(ROOT))
    from fastapi.routing import APIRoute, APIWebSocketRoute

    from app import create_app

    app = create_app()
    spec = app.openapi()
    rows: dict[str, list[str]] = {title: [] for title, _ in SECTIONS}
    # FastAPI keeps included routers nested; iter_route_contexts gives each route with its
    # router's prefix and dependencies applied
    from fastapi.routing import iter_route_contexts
    for route in iter_route_contexts(app.routes):
        kind = route.route
        if isinstance(kind, APIRoute) and route.include_in_schema and route.path != "/{path:path}":
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                operation = spec["paths"].get(route.path, {}).get(method.lower(), {})
                summary = (operation.get("summary") or "").strip()
                doc = (route.endpoint.__doc__ or "").strip().split("\n")[0].strip()
                lines = [f"### `{method} {route.path}`", "", doc or summary, "",
                         f"- **Role:** {_role(route, method)}"]
                params = _params(operation, spec)
                if params:
                    lines.append(f"- **Query:** {', '.join(params)}")
                fields = _body_fields(operation, spec)
                if fields:
                    lines.append("- **Body (JSON):**")
                    lines += [f"  {f}" for f in fields]
                rows[_section(route.path)].append("\n".join(lines))
        elif isinstance(kind, APIWebSocketRoute):
            doc = (kind.endpoint.__doc__ or "").strip().split("\n")[0].strip()
            title = "Other hosts" if kind.path.startswith("/hosts") else "Live data (WebSocket)"
            rows[title].append(f"### `WS {kind.path}`\n\n{doc}\n\n- **Role:** "
                               f"{'operator' if 'console' in kind.path else 'viewer'}")

    out = [
        "# API reference",
        "",
        "Every endpoint of this version of Habeny, generated from the application by",
        "`deploy/api_reference.py` (the tests check it's current). Read [api.md](api.md) first:",
        "it explains authentication, the response format, errors and common tasks. Paths are",
        "relative to `https://<server>:9000/api`. **Role** is the least role that may call it;",
        "\"none\" needs no sign-in. The server's own `/docs` page has the full JSON schemas.",
        "",
        "## Contents",
        "",
    ]
    out += [f"- [{title}](#{title.lower().replace(' ', '-').replace('(', '').replace(')', '').replace(',', '')})"
            for title, _ in SECTIONS if rows[title]]
    for title, _ in SECTIONS:
        if rows[title]:
            out += ["", f"## {title}", "", "\n\n".join(rows[title])]
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            print("docs/api-reference.md is out of date: run python3 deploy/api_reference.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text)
    print(f"{OUT}: written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
