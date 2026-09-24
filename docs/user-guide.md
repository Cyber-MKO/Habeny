# User guide

How to use Habeny's web interface to deploy SIEM agents in containers, send test traffic
to them and measure how your SIEM copes. For installing and running the server, see the
[administrator guide](admin-guide.md).

## Contents

- [Concepts](#concepts)
- [Signing in and your account](#signing-in-and-your-account)
- [Finding your way around](#finding-your-way-around)
- [Deploying containers](#deploying-containers)
- [Managing containers](#managing-containers)
- [Sending test traffic](#sending-test-traffic)
- [Measuring: benchmarks, metrics and reports](#measuring-benchmarks-metrics-and-reports)
- [Activity, monitoring and hosts](#activity-monitoring-and-hosts)
- [Administration pages](#administration-pages)
- [Typical workflows](#typical-workflows)

## Concepts

- **Container:** a small Linux system (an LXC container) on the Habeny server. Each one
  looks like a separate machine to your SIEM.
- **SIEM agent:** the Wazuh, OSSEC, Elastic or UTMStack agent Habeny installs in a
  container, enrolled with your SIEM manager. A container can also run **no agent** (a
  bare container), for example to act as a syslog source.
- **Manager profile:** saved settings for one SIEM manager (type, address, version,
  enrollment key, group, resources), so a deployment is a couple of clicks.
- **Group:** a named set of containers, for bulk operations, simulations and reports.
- **Simulation:** generated activity sent through the containers to your SIEM: attack
  patterns, log events at a chosen rate, or syslog from simulated network devices.
- **Benchmark:** a multi-phase run that deploys containers step by step and measures
  deployment speed, resource use and bottlenecks.
- **Roles:** **viewers** can see everything and change nothing; **operators** can also
  deploy, run tests and use the console; **admins** can also manage users, teams,
  notifications, backups and the license. If you belong to a **team**, you see only your
  team's containers, simulations and reports.

## Signing in and your account

Sign in with your user name and password, or **Sign in with SSO** if your organization set
it up. With two-factor authentication on, you're then asked for the 6-digit code from your
authenticator app (or one of your recovery codes).

**Account** (sidebar, or your name at the top right):

- **Change password.** This signs you out everywhere else.
- **Two-factor authentication:** scan the QR code with an authenticator app, enter a code
  to confirm, and store the 10 recovery codes somewhere safe.
- **Active sessions:** where you're signed in; end any you don't recognize.
- **API tokens:** for scripts and CI (see [api.md](api.md)). A token is shown once; copy it
  then. It can't do more than your role.
- **Language:** English or French.

## Finding your way around

- The **sidebar** groups pages into Overview, Fleet, Testing, Insights and Settings. On a
  phone, it's behind the menu button.
- The **header** shows the page, whether live updates are connected, active **alerts**,
  license warnings, and **Read-only** if you're a viewer.
- If your organization manages several Habeny servers, the **Server** menu at the top of the
  sidebar switches between them. A banner shows when you're on another server.
- **Dashboard:** containers by SIEM type and state, live resource use, quick actions and
  recent activity.
- **System:** the server's platform, resources, container counts and available images.

## Deploying containers

**Fleet → Deploy** (operators):

1. Pick a **manager profile** to fill in the SIEM settings, or choose **Manual
   configuration** and enter them:
   - **SIEM type:** Wazuh, OSSEC, UTMstack, Elastic, or None (bare container).
   - **Manager IP** (the SIEM server's address), **version** and, for UTMstack and Elastic,
     the **auth key or enrollment token**.
2. Set **how many** containers, their **base name** (containers are named
   `<base>-0001`, `<base>-0002`, …), the **OS image**, the **group**, and per-container
   **memory** and **CPU shares**.
3. Optionally pick a **config template** to apply to the agent (see Configs below).
4. **Deploy.** The **Deployment Activity** panel shows each container's progress live:
   creating, starting, installing the agent, enrolling.

Deployment time is mostly the agent download and install. Habeny caches agent packages,
so the second deployment of the same agent is faster. If your team or you have a
**container limit**, or the server's license has one, a deployment that would exceed it is
refused with the reason.

**Manager profiles** (Fleet → Managers) save a SIEM manager's settings. Auth keys are
stored encrypted and only their last 4 characters are ever shown again.

**Configs** (Insights → Configs) holds agent configuration templates, for example an
`ossec.conf` for Wazuh with your own settings. Import one, then pick it when deploying.

## Managing containers

**Fleet → Containers** lists the containers you can see, with their state, sequence
number, agent service state, manager and group. Filter by SIEM type, state and group.

- **Start**, **Stop** and **Delete** a container. Deleting destroys it and everything in
  it. The agent stops reporting, but your SIEM may keep listing it as disconnected until
  you remove it there.
- **Details** shows its configuration, network address, agent state and resource use.
- **Open Console** gives a root shell inside the container in your browser (operators),
  for checking agent logs or configuration. Commands run inside the container only.

**Fleet → Groups:** create groups, see how many containers each has, and assign containers
to them.

**Fleet → Bulk Ops:** start, stop or delete many containers at once. Select containers
(or all running ones), or choose a group to act on every container in it. Deleting asks
you to type "delete" to confirm.

## Sending test traffic

**Testing → Simulations** (operators) has three kinds:

- **Attack simulation:** pick a profile and an intensity (low, medium, high) and the
  target containers (by SIEM type, group, tags, state or count). Profiles:
  `auth_bruteforce`, `web_attacks`, `malware_beacon`, `lateral_movement`,
  `data_exfiltration` and `privilege_escalation`. They write realistic log entries in the
  containers, which the agents forward, so you can check what your SIEM detects.
- **Custom EPS log simulation:** send log lines from your own JSON templates at a chosen
  number of events per second, for load testing ingestion.
- **Syslog simulation:** send syslog from simulated routers, switches, firewalls or IDS
  devices (or a mix) to a SIEM's syslog port over TCP or UDP, at a chosen rate and for a
  chosen time.

Running simulations are listed with their progress; **Stop** ends one early. Simulations
generate real traffic to your SIEM: point them at test systems.

**Testing → Log Upload** (operators) writes log content you provide into a container's
file, for example `/var/log/auth.log`, where the agent picks it up:

- **Send once**, or **Send intermittently** every N seconds for a duration (or
  indefinitely). Target one container or a whole group.
- **Active Schedules** lists repeating uploads; **Stop** ends one.

**Testing → Syslog Config** saves syslog destinations (address, port, protocol), tests
that one is reachable, and turns on the syslog listener (port 7014) in UTMstack containers.

## Measuring: benchmarks, metrics and reports

**Testing → Benchmark Runner** (operators) runs a multi-phase benchmark: choose a scenario
(Linear Scale, Burst Load, Sustained Load, Mixed Workload or Stress Test) and the SIEM
settings. Each phase deploys more containers and records deployment rate, success, P90
deployment time and resource use. **Bottlenecks Detected** points out what limited the run:
host CPU load, memory or disk, deployment failures, API latency, the SIEM manager's CPU, or
agents disconnecting. Benchmarks create real containers; delete
them afterwards.

**Insights → Perf Metrics:** deployment performance, API latency, simulation throughput,
and live and historical memory, CPU and running-container charts.

**Insights → SIEM Stats:** for each SIEM type, how many agents there are and how many are
connected.

**Insights → Reports:** generate a report for a time range, optionally limited to
certain SIEMs or simulations, as **JSON**, **CSV** or **PDF**, with a summary, automated
findings and metrics. Earlier reports are listed under **Report History** and can be
downloaded again.

## Activity, monitoring and hosts

- **Activity:** every action anyone took (deployments, deletions, sign-ins, settings), with
  who, when, from which address and the result. Filter by action, user, result, dates and
  text, and export what matches as CSV or JSON Lines. Admins can **Verify integrity** to
  check that no entry was altered or removed.
- **Monitoring:** active alerts (low disk space, LXC unavailable, failed backup or
  deployment, unreachable host, license) and the addresses monitoring systems use.
- **Hosts:** the other Habeny servers you can manage from here, with their status, version,
  containers and alerts. Pick one to work on it.

## Administration pages

For admins; the [administrator guide](admin-guide.md) has the details.

- **Account → Users:** add people, set their role, reset passwords and two-factor, sign them
  out, delete them. **Account → Backups:** take and download backups.
- **Teams:** create teams, set container limits, and move people and containers between
  them.
- **Notifications:** send alerts and results to Slack, webhooks or email.
- **License:** this server's license state and server ID; install a license file.

## Typical workflows

**Check what your SIEM detects**

1. Save a manager profile for your test SIEM manager.
2. Deploy 5–10 containers with that profile into a new group.
3. Wait until the containers show the agent service running and SIEM Stats shows them
   connected.
4. Run an attack simulation (e.g. `auth_bruteforce`, medium) against the group.
5. Look for the alerts in your SIEM, and generate a report in Habeny for the same time
   range to compare.

**Load-test ingestion**

1. Deploy containers with the agent you want to measure.
2. Run a custom EPS log simulation, raising the rate step by step, or a syslog simulation
   straight to the SIEM.
3. Watch Perf Metrics here and your SIEM's own ingestion metrics; note the rate where
   events start arriving late or getting dropped.

**Measure how fast you can scale**

1. Run the Benchmark Runner's Linear Scale scenario with your SIEM settings.
2. Read the phase results and bottlenecks, then delete the benchmark's containers with
   Bulk Ops.
