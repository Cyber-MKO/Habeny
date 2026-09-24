# Habeny Support Terms

> **DRAFT: not reviewed by a lawyer.** Fill in the bracketed parts (hours, time zone, prices,
> the phone or video channel) before offering these terms. They are meant to be part of
> the customer's order, alongside the [EULA](EULA.md). Keep the targets in line with
> what you can actually staff: a missed commitment costs more trust than a modest one.

**Provider:** Habeny Platform
**Version:** draft 1, 2026-09-24

## 1. What's covered

Support covers the Habeny software, in a supported version (section 6), installed on a
supported system as described in the documentation ([requirements.md](../requirements.md)):

- answering questions about installing, configuring and using Habeny;
- diagnosing problems, and providing fixes, workarounds or updates for defects in Habeny;
- help with upgrades between supported versions;
- license issues: installing, renewals, and moving a license to a replacement server.

## 2. What's not covered

- The SIEM products and agents themselves (Wazuh, Elastic, OSSEC, UTMStack): their
  configuration, detection rules and defects. We help determine whether a problem is in
  Habeny or in the SIEM.
- The customer's infrastructure: the operating system, networks, firewalls, proxies,
  identity providers and mail servers, beyond checking Habeny's side of the connection.
- Changes to Habeny's code, and problems caused by them.
- Unsupported versions or systems, beyond helping to upgrade.
- On-site work, custom development, training and consulting, which can be ordered
  separately.

## 3. Plans

| | Standard | Premium |
|---|---|---|
| Channel | Email | Email, plus a phone or video call for P1 ([number or booking link]) |
| Support hours | [Monday–Friday, 09:00–17:00, time zone], excluding [public holidays of country] | [Monday–Friday, 07:00–20:00, time zone]; P1 around the clock |
| Named contacts who may open requests | 2 | 5 |
| Price | [included in the license / amount per server per year] | [amount per server per year] |

## 4. Response targets

The **first response** is a reply from a person who has read the request and says what
happens next. It isn't a fix. Targets count within the plan's support hours, except P1
under Premium, which counts around the clock.

| Severity (definitions in [SUPPORT.md](../../SUPPORT.md#severity-levels)) | Standard | Premium |
|---|---|---|
| P1 Critical | 1 business day | 4 hours |
| P2 High | 2 business days | 1 business day |
| P3 Normal | 5 business days | 2 business days |
| P4 Low | 5 business days | 2 business days |

After the first response, we work on **P1** continuously during support hours until
there's a fix or a workaround, with updates at least [daily (Standard) / every 4 hours
(Premium)]. For **P2** we send updates at least every [3 business days], and we schedule
**P3/P4** fixes into a regular release.

These are targets, not guarantees of resolution time. If we miss a P1 or P2 first-response
target in a calendar month, the customer may ask for a service credit of [5]% of that
month's support fee per miss, up to [25]%. **[Counsel: decide whether to offer credits at
all; if not, delete this paragraph.]**

## 5. Customer responsibilities

- Contact us through the channels in [SUPPORT.md](../../SUPPORT.md), from a named contact.
- Give the information it asks for, including a support bundle (`sudo habeny support-bundle`),
  and be available to try suggested steps. Response targets pause while we wait for
  the customer.
- Keep backups ([admin-guide.md](../admin-guide.md#backups)) and install updates that fix
  the problem.
- Report security vulnerabilities as described in [SECURITY.md](../../SECURITY.md).

## 6. Supported versions

The current minor release and the previous one (for example 2.2.x and 2.1.x) are
supported. Defect fixes go into the current minor release. Security fixes go into both. A
version stops being supported when the second minor release after it comes out. We
announce this in the release notes.

## 7. Data shared during support

We use support bundles, logs and anything else the customer sends only to resolve the
request, keep it no longer than [90 days] after the request closes, and don't share it
with third parties except [the email provider we use]. The customer should remove anything
they don't want to share first. **[Counsel: if personal data is involved, a data
processing agreement may be needed; see the EULA, section 5.]**

## 8. Term

Support runs for the period in the customer's order and renews with it. If support lapses,
the software keeps working under the EULA and license, but the customer gets no support or
updates until they renew.
