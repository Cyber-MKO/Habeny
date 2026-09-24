#!/usr/bin/env python3
"""
Habeny license tool, for the vendor. Not shipped in releases.

  # once: make the signing key pair. Keep the private key offline and backed up;
  # put the printed public key in app/licensing_key.py before building releases.
  python3 tools/license_tool.py keygen --out ~/habeny-signing.pem

  # per customer server (the customer runs `habeny license request` for the server ID)
  python3 tools/license_tool.py sign --key ~/habeny-signing.pem --id L-2026-0001 \\
      --customer "Example Corp" --server-id 3F9A-0C21-77DE-B410-5A6E \\
      --expires 2027-09-30 --max-containers 200 --out example-corp.license

  # check a license file against the keys in app/licensing_key.py (or --key)
  python3 tools/license_tool.py inspect example-corp.license

Run from the repository root.
"""
import argparse
import base64
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from app import licensing_key  # noqa: E402
from app.services import licensing  # noqa: E402


def _public_b64(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def _load_private(path: str) -> Ed25519PrivateKey:
    data = Path(path).read_bytes()
    password = os.environ.get("HABENY_LICENSE_KEY_PASSWORD")
    key = serialization.load_pem_private_key(data, password=password.encode() if password else None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit(f"{path} is not an Ed25519 private key")
    return key


def cmd_keygen(args) -> int:
    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"{out} exists; not overwriting a signing key")
    key = Ed25519PrivateKey.generate()
    password = os.environ.get("HABENY_LICENSE_KEY_PASSWORD")
    encryption = (serialization.BestAvailableEncryption(password.encode()) if password
                  else serialization.NoEncryption())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    print(f"Private key written to {out}{' (encrypted)' if password else ' (NOT encrypted: set HABENY_LICENSE_KEY_PASSWORD to encrypt it)'}.")
    print("Keep it offline and backed up; anyone with it can issue licenses. Never commit it.\n")
    print("Public key, for PUBLIC_KEYS in app/licensing_key.py:")
    print(f'    "{_public_b64(key)}",')
    return 0


def cmd_sign(args) -> int:
    key = _load_private(args.key)
    if args.expires:
        date.fromisoformat(args.expires)
    payload = {
        "v": 1,
        "id": args.id,
        "customer": args.customer,
        "server_id": args.server_id.strip().upper(),
        "issued": datetime.now(timezone.utc).date().isoformat(),
        "expires": args.expires or None,
        "max_containers": args.max_containers,
        "features": args.feature or [],
    }
    text = licensing.sign(key, payload)
    if _public_b64(key) not in licensing_key.PUBLIC_KEYS:
        print("warning: this key's public half isn't in app/licensing_key.py; builds from this tree won't accept "
              "the license", file=sys.stderr)
    content = (f"# Habeny license {payload['id']} for {payload['customer']}, server {payload['server_id']}, "
               f"expires {payload['expires'] or 'never'}\n{text}\n")
    if args.out:
        Path(args.out).write_text(content)
        print(f"Written to {args.out}")
    else:
        print(content, end="")
    return 0


def cmd_inspect(args) -> int:
    text = Path(args.file).read_text()
    if args.key:
        licensing_key.PUBLIC_KEYS[:] = [_public_b64(_load_private(args.key))]
    try:
        payload = licensing.decode(text)
    except licensing.LicenseError as e:
        print(f"INVALID: {e}", file=sys.stderr)
        return 1
    print("Signature OK")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue Habeny licenses (vendor only)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("keygen", help="create the signing key pair")
    p.add_argument("--out", required=True, help="where to write the private key (PEM)")
    p = sub.add_parser("sign", help="issue a license for one server")
    p.add_argument("--key", required=True, help="the private key (PEM)")
    p.add_argument("--id", required=True, help="your license number, e.g. L-2026-0001")
    p.add_argument("--customer", required=True)
    p.add_argument("--server-id", required=True, help="from `habeny license request` on the customer's server")
    p.add_argument("--expires", help="YYYY-MM-DD, last valid day; omit for a perpetual license")
    p.add_argument("--max-containers", type=int, help="omit for no limit")
    p.add_argument("--feature", action="append", help="feature flag (repeatable); none are checked yet")
    p.add_argument("--out", help="write here instead of standard output")
    p = sub.add_parser("inspect", help="check a license's signature and show its contents")
    p.add_argument("file")
    p.add_argument("--key", help="check against this private key's public half instead of app/licensing_key.py")
    args = parser.parse_args()
    return {"keygen": cmd_keygen, "sign": cmd_sign, "inspect": cmd_inspect}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
