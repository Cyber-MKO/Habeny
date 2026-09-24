"""
Public keys that sign Habeny licenses (Ed25519, raw 32 bytes, base64).

Empty: licensing is off, every feature works and no license is asked for. With a key
listed, every build (releases and source installs alike) needs a license after its trial.
`python3 tools/license_tool.py keygen` prints a key. Several keys can be listed so a new
key can be introduced before the old one is retired.

Only public keys belong here. The private key that signs licenses must never be committed.
"""
PUBLIC_KEYS: list[str] = [
    "NLptyHQ1qNcQdnHaevohaaVfn20lrfg0DgE77D3NCag=",  # Habeny Platform, 2026-09
]
