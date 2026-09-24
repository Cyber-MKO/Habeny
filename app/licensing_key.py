"""
Public keys that sign Habeny licenses (Ed25519, raw 32 bytes, base64).

Empty: licensing is off. Every feature works and no license is asked for (source builds,
development, and installs from before licensing). The vendor adds their public key here
before building releases; `python3 tools/license_tool.py keygen` prints it. Several keys
can be listed so a new key can be introduced before the old one is retired.

Only public keys belong here. The private key that signs licenses must never be committed.
"""
PUBLIC_KEYS: list[str] = []
