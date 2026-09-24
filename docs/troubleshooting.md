# Troubleshooting

Symptoms, likely causes and fixes, roughly in the order people meet them. If none of this
helps, create a support bundle (`sudo habeny support-bundle`) and contact support (see
[SUPPORT.md](../SUPPORT.md)).

**First steps for any problem**

```bash
systemctl status habeny habeny-helper            # both should be "active (running)"
journalctl -u habeny -u habeny-helper --since -1h # recent log lines, errors first to look at
sudo habeny config check                          # settings valid?
sudo habeny license status                        # license state
curl -k https://localhost:9000/api/readyz         # database, LXC and disk all "ok"?
```

Error messages in the interface that say **"request ID …"** point to the exact log lines:
`journalctl -u habeny | grep <request id>`.

## Contents

- [Installing and starting](#installing-and-starting)
- [Signing in](#signing-in)
- [Deploying containers](#deploying-containers)
- [Agents don't show up in the SIEM](#agents-dont-show-up-in-the-siem)
- [Simulations and log uploads](#simulations-and-log-uploads)
- [License](#license)
- [Backups and upgrades](#backups-and-upgrades)
- [Notifications and other hosts](#notifications-and-other-hosts)
- [Performance](#performance)

## Installing and starting

**The service doesn't start.** `journalctl -u habeny` gives the reason; common ones:

| Message | Fix |
|---|---|
| a configuration problem (e.g. "HABENY_PORT: expected a whole number") | Fix `/etc/habeny/habeny.conf`; `sudo habeny config check` lists every problem |
| "Another Habeny (pid N) is already running with data directory …" | Only one Habeny can run per data directory. Stop the process it names (a leftover `start.sh`, a second service) |
| "The database … is at schema vN, but this Habeny only knows vM" | You installed an older version over a newer one. Install the newer version again, or restore the backup taken before the upgrade ([admin-guide.md](admin-guide.md#upgrading-and-rolling-back)) |
| a TLS certificate or key can't be read | Check the paths in `HABENY_TLS_CERT`/`HABENY_TLS_KEY` and that the `habeny` user can read them |

**The browser can't reach the server.**

- Check the service is running and listening: `sudo ss -tlnp | grep 9000`.
- A firewall (`ufw`, `firewalld`, a cloud security group) must allow TCP 9000.
- `HABENY_HOST=127.0.0.1` only listens locally, which is meant for a reverse proxy on the
  same machine.
- The address is **https**://, not http://. The self-signed certificate triggers a browser
  warning the first time; accept it, or install your own certificate.

**"Can't reach the server" in the interface after it loaded:** the server restarted or the
network dropped. Wait a moment and select Retry. If it keeps happening, check
`journalctl -u habeny` for crashes.

## Signing in

**The first visit asks for a setup token.** It's in the server's log and a file only root
can read: `sudo cat /var/lib/lxc-siem-platform/setup-token`.

**"Too many failed sign-in attempts".** After 10 failed sign-ins from one address in 15
minutes, that address has to wait. The message says for how long.

**Lost the two-factor device.** Use one of your recovery codes instead of the 6-digit
code. Without those, an admin can reset your two-factor (Account → Users → Reset 2FA).

**Forgot the password.** An admin resets it on Account → Users. If the only admin is
locked out, see "Forgotten password" in the [administrator guide](admin-guide.md#authentication).

**Single sign-on fails.**

- "redirect URI mismatch" at the identity provider: the redirect URI registered there
  must be exactly `https://<your address>/api/auth/oidc/callback`. Behind a proxy, set
  `HABENY_OIDC_REDIRECT_URI` to the address users see.
- Signed in at the provider but refused by Habeny: with group mapping set
  (`HABENY_OIDC_*_GROUPS`), people in none of the groups are refused. Check the groups claim
  (`HABENY_OIDC_GROUPS_CLAIM`); some providers need a `groups` scope or claim configured.
- "A Habeny account named '…' already exists": an SSO sign-in never takes over a local
  account with the same user name. Rename or delete the local account.

## Deploying containers

**Error 402 "trial has ended" or "license expired".** See [License](#license).

**Error 403 "Your limit is…" or "Team … is limited to…".** The deployment would pass a user
or team container limit. Delete containers, or ask an admin to raise the limit (Teams page).

**"LXC unavailable" alert, or deployments fail at once.** The web app talks to LXC through
the helper service:

```bash
systemctl status habeny-helper
sudo systemctl restart habeny-helper
lxc-checkconfig                        # kernel support for containers
```

**Deployments fail while creating the container ("download" template errors).** The
server downloads container images from images.linuxcontainers.org the first time. Check
the server can reach it (`curl -I https://images.linuxcontainers.org`), including through
your proxy.

**Containers are created but the agent install fails.** The agent is downloaded from its
vendor (packages.wazuh.com, artifacts.elastic.co, updates.atomicorp.com) or, for
UTMStack, from your UTMStack server on port 9001. From the container:

```bash
sudo lxc-attach -n <container> -- curl -sI https://packages.wazuh.com
```

Containers reach the network through the host (NAT on `lxcbr0`). If the host needs a proxy,
the containers do too. Deploy details (Containers → Details) show the install output.

**"UTMstack and Elastic deployments need siem_auth_key".** Enter the UTMStack auth key or
the Elastic Fleet enrollment token, or save it in the manager profile. "The manager
profile's auth key can't be read" means the encryption key changed (for example, a restore
without `secret.key`): enter the key in the profile again.

**Containers show as "interrupted".** Habeny stopped (restart, upgrade, crash) while they
were deploying. Delete them and deploy again.

**"OSSIM is no longer supported".** A manager profile saved before version 2.2 names OSSIM.
Change its SIEM type.

## Agents don't show up in the SIEM

1. Check the agent runs: Containers shows **Agent Svc** as running, or use the console:
   `systemctl status wazuh-agent` (or `elastic-agent`, `ossec`, `utmstack`).
2. From the container, check the SIEM manager is reachable on its ports, e.g. for Wazuh:
   `nc -zv <manager> 1514` and `nc -zv <manager> 1515`.
3. The **manager IP** must be an address the containers can reach, not `localhost`.
4. Enrollment keys and passwords: a wrong Wazuh password, UTMStack key or Elastic token
   fails enrollment; the agent's log says so (Wazuh: `/var/ossec/logs/ossec.log`).
5. Agent version: some SIEM managers refuse agents newer than themselves. Deploy the same
   version as the manager (the SIEM version field, or the manager profile).
6. **SIEM Stats** counts agents Habeny sees as connected; your SIEM's own view is the
   reference.

## Simulations and log uploads

- **A simulation starts but the SIEM shows nothing:** the agents must be connected (above),
  and the SIEM must have rules for those events. Try `auth_bruteforce` first; most SIEMs
  detect it out of the box.
- **Syslog simulation traffic doesn't arrive:** check the target address and port, the
  protocol (TCP or UDP) the SIEM listens on, and firewalls between the Habeny server and the
  SIEM. **Syslog Config → Test** checks connectivity.
- **Log upload says the path is invalid:** the destination must be an absolute path inside
  the container, such as `/var/log/auth.log`, using only letters, digits and `_ . @ + / -`;
  `..` isn't allowed.
- **A scheduled upload stopped:** schedules end after their duration. After a restart,
  schedules resume for the time they had left.

## License

| Message or state | Cause | Fix |
|---|---|---|
| "Trial: N days left" | No license installed yet | `sudo habeny license request`, send the server ID to Habeny Platform, then install the file you receive |
| "The trial has ended" | 30 days since the first account, with no license | Install a license. Everything stays viewable meanwhile, and existing containers can be managed |
| "The installed license is for server …, not this one" | The server ID changed: new hardware, a moved or cloned VM, or a regenerated `/etc/machine-id` | Ask Habeny Platform for a license for the new server ID |
| "The license's signature doesn't match" | The file was edited or damaged, or isn't from Habeny Platform | Install the original file again |
| "The license expired on …" | The term ended; new work continues for a 14-day grace period | Renew |
| "This server's license allows N containers" | The license's container limit | Delete containers, or ask for a larger license |

Cloning VMs: clones share the original's machine ID, and so its server ID, until you run
`sudo rm /etc/machine-id && sudo systemd-machine-id-setup` on the clone.

## Backups and upgrades

- **"Backup failed" alert.** `journalctl -u habeny | grep -i backup` shows why. With
  `HABENY_BACKUP_DIR` outside the data directory, the service needs permission to write
  there (`ReadWritePaths=`, see [admin-guide.md](admin-guide.md#backups)); also check free space.
- **An upgrade failed during migration.** The migration ran in a transaction and the
  database is unchanged. Habeny keeps the pre-upgrade backup. Send the log and a support
  bundle to support before retrying.
- **Restoring on another server:** after `habeny backup restore`, request a license for
  the new server, because the old license is tied to the old server's ID.

## Notifications and other hosts

- **No notifications arrive.** Use **Test** on the Notifications page; the page shows each
  channel's last error. For email, check `HABENY_SMTP_*` (host, port, `starttls` or `ssl`,
  user and password). Slack and webhook URLs must be reachable from the Habeny server.
- **"Host unreachable" alert, or a host shows as offline.** Check the other server is
  running and reachable on its port. If its certificate was replaced, the pinned
  fingerprint no longer matches: edit the host and confirm the new fingerprint
  (`sudo habeny tls fingerprint` on that server). If its API token was revoked, create a new
  one there and update the host here.

## Performance

- **The Containers page is slow with hundreds of containers.** Each running container is
  asked for its agent state. Filter by group or SIEM type, or page through fewer at a time.
  See [requirements.md](requirements.md#limits-of-one-server).
- **"Low disk space" alert.** Delete containers you no longer use, lower
  `HABENY_REPORT_RETENTION_DAYS`/`HABENY_BACKUP_KEEP`, or move backups elsewhere. The
  agent package cache (`/var/lib/lxc-siem-platform/agent-cache`) can be deleted safely.
- **Deployments are slow.** Most time goes into downloading and installing agents. The
  package cache speeds up repeats; SSDs help; very large batches are limited by
  `HABENY_DEPLOY_WORKERS` (default: the CPU count).
- **`/api/docs` shows a blank page.** It loads its page assets from a public CDN; the
  browser needs internet access. `/api/openapi.json` and [api-reference.md](api-reference.md)
  work offline.
