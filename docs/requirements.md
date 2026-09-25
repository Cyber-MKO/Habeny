# Requirements and sizing

What a server needs to run Habeny, and how to size it for the number of containers you
plan to run.

## Supported systems

**Host (the server Habeny runs on)**, x86_64, with root access and systemd:

| OS | Status |
|---|---|
| Ubuntu 24.04 LTS | Supported; tested on every change (a real install and container deployment in CI) |
| Ubuntu 22.04 LTS | Supported |
| Debian 12 | Supported |
| Debian 13 | Supported |
| Other distributions | Not supported. The installer needs apt and the `lxc`, `lxc-utils` and `python3-lxc` packages |

- Python 3.10 or newer (the OS's own `python3`) and LXC from the OS packages. The `.deb`
  and the installer install what's missing.
- A physical machine or a VM. In a VM, containers run inside the VM, so size the VM, not the
  hypervisor. Nested virtualization isn't needed.
- Habeny can't run in Docker (see [admin-guide.md](admin-guide.md#installing)).
- ARM (aarch64) isn't supported yet.

**Container images** Habeny can deploy: Ubuntu 22.04 (default), Ubuntu 24.04 and Debian 12,
downloaded from the LXC image server (images.linuxcontainers.org) the first time each is
used. All three get standard security updates from their vendors.

**SIEM agents:** Wazuh 4.x, OSSEC (Atomicorp packages), Elastic Agent 8.x/9.x with Fleet,
and UTMStack. Habeny installs the agent version you choose (or the default shown on the
Deploy page), and your SIEM server must accept it.

**Browsers:** current versions of Chrome, Edge, Firefox and Safari. Internet Explorer and
other legacy browsers don't work.

## Network

| Direction | What | Why |
|---|---|---|
| In | TCP 9000 (HTTPS), or your reverse proxy's port | the web UI and API |
| Out | The SIEM managers you deploy agents for: Wazuh 1514 and 1515, OSSEC 1514/udp, Elastic Fleet 8220 plus your Elasticsearch output (usually 9200), UTMStack 9001 (agent download) plus the ports your UTMStack version's agents use | agents enroll and send events |
| Out | images.linuxcontainers.org, your OS package mirrors | container images and packages |
| Out | packages.wazuh.com, artifacts.elastic.co, updates.atomicorp.com | agent downloads |
| Out, optional | your identity provider, mail server, Slack or webhooks, other Habeny servers | SSO, notifications, the Hosts feature |

Habeny doesn't contact Habeny Platform: licensing is offline and there's no telemetry. The
full list of outbound connections is in [privacy.md](privacy.md#outbound-connections).
Without internet access, use the offline wheels (see
[admin-guide.md](admin-guide.md#installing)) and a local mirror for images and agents.

## Sizing

Almost all of a server's resources go to the containers, not to Habeny. Habeny itself uses
about **130 MB of memory** and little CPU when idle (see [Limits of one server](#limits-of-one-server)).

Plan with these starting points, then **measure your own**: deploy 10 containers of the
kind you'll use, let them run for a while, and read memory and disk use on the **Perf
Metrics** page or with `free -m` and `df -h`. Agents' memory use varies a lot with their
version and configuration, and with the traffic you send them.

| Per container (rough starting points) | Memory | Disk |
|---|---|---|
| Bare container (no agent) | 50–100 MB | about 0.5 GB |
| Wazuh or OSSEC agent | 100–200 MB | about 1 GB |
| UTMStack agent | 150–300 MB | about 1 GB |
| Elastic Agent | 300–600 MB | 1.5–2 GB |

Each container's **memory limit** (default 512 MB, set on the Deploy page or in a manager
profile) is a cap, not a reservation. Keep the sum of what containers really use below
about 80% of the server's memory.

| Deployment | vCPUs | Memory | Disk for `/var/lib/lxc` |
|---|---|---|---|
| Evaluation: up to 20 containers | 4 | 8 GB | 50 GB |
| Team: up to 100 Wazuh/OSSEC containers | 8 | 32 GB | 150 GB |
| Large: up to 500 containers | 16–32 | 128 GB or more | 600 GB or more |
| More than that | Run several servers and manage them from one console ([Several LXC hosts](admin-guide.md#several-lxc-hosts)) | | |

Also plan for:

- **Habeny's data** (`/var/lib/lxc-siem-platform`): a few GB, plus reports, plus the
  backups (14 kept by default; each is a few MB to a few hundred MB). Put backups on
  another disk or a share with `HABENY_BACKUP_DIR`.
- **Fast disks:** deploying many containers at once is disk-bound. Use SSDs.
- **CPU for traffic:** attack, log and syslog simulations at high event rates use CPU in
  the containers and on the host.

## Limits of one server

Habeny is **one process on one machine**: SQLite (WAL mode) for data, plus in-process
background work (deployments, simulations, schedules, maintenance). Only one Habeny can
use a data directory. A second instance, or uvicorn with several workers, refuses to
start with a message saying which process holds it.

Measured on a 4-vCPU VM, with LXC stubbed out so the numbers are Habeny's own,
20 concurrent clients:

| | Throughput | p95 latency |
|---|---|---|
| Reads (e.g. `GET /groups`) | ~330 requests/s | < 200 ms |
| Writes (e.g. creating groups) | ~230 requests/s | ~100 ms |
| Listing 500 containers (Containers page) | ~2 s per load | the rest of the API stays responsive meanwhile |
| Memory (web app) | ~130 MB | |

What limits a host in practice:

- **Containers:** the host's RAM and CPU (each container's `memory_limit`), not Habeny.
  Habeny's own side was measured with 500 containers (above); how many a host can
  actually run depends on its resources and the SIEM agents.
- **The Containers page:** each running container is asked for its SIEM agent status
  (one `lxc-attach`, 16 at a time). That's roughly 50–200 ms per container on real hosts,
  so several seconds per page load at around 500 containers.
- **Users:** tens of people using the UI at once is fine; writes are serialized by SQLite.

**Larger installs:** run **one Habeny per LXC host** and manage them all from one console
(see [Several LXC hosts](admin-guide.md#several-lxc-hosts)). Each host keeps its own containers, data,
users and backups. A single Habeny instance spanning several hosts, or sharing a database between instances,
isn't supported.
