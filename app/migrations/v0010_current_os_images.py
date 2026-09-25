"""SIEM targets move off retired container images.

Ubuntu 20.04 and Debian 11 are past standard support and are replaced by Ubuntu 24.04 and
Debian 12; centos_8 never had an image. Saved profiles that name them now deploy the
replacement. Existing containers are left as they are.

The schema doesn't change, so down() has nothing to undo: profiles keep the newer image
(an older Habeny refuses it when deploying; pick an image it offers). To get the old values
back, restore the backup taken before this migration.
"""
REPLACED = {"ubuntu_20_04": "ubuntu_24_04", "debian_11": "debian_12", "centos_8": "ubuntu_22_04"}


def up(conn):
    for old, new in REPLACED.items():
        conn.execute("UPDATE managers SET os_type = ? WHERE os_type = ?", (new, old))


def down(conn):
    pass
