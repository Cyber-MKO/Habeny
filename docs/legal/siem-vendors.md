# SIEM agents: licenses, redistribution and names

> **Research notes, not legal advice.** Compiled on 2026-09-24 from the vendors' public
> license files and policies, linked below. Licenses and trademark policies change; check
> the sources again before relying on this, and have counsel answer the open questions at
> the end before marketing Habeny commercially.

## Summary

- **Habeny doesn't redistribute any SIEM agent.** Its releases (tarball, `.deb`, offline
  wheels) contain no agent binaries. When a customer deploys, the customer's own server
  downloads each agent from its publisher (or, for UTMStack, from the customer's own
  UTMStack server) and installs it in a container on that server. The customer obtains the
  agent directly from the vendor, under the vendor's license, the same way they would by
  following the vendor's install guide.
- That keeps the copyleft licenses of the agents (GPLv2 for Wazuh and OSSEC, AGPLv3 for
  UTMStack) away from Habeny's own code: Habeny talks to the agents over command lines
  and the network, it doesn't link with them, and it doesn't ship them.
- The one proprietary-style license is Elastic's (Elastic License 2.0). It allows use and
  redistribution with three limits, which Habeny's use doesn't touch (see below).
- **Names:** using a vendor's name to say which products Habeny works with ("deploys Wazuh
  agents") is generally *nominative* use. It's normally allowed if the name is used only as
  much as needed, without logos, and without suggesting endorsement. Wazuh publishes a
  trademark policy with specific rules; the others don't publish "compatible with"
  guidelines. Get counsel's sign-off before using any vendor name in advertising, product
  names, domain names or comparisons.
- **OSSIM is retired** (end of life 31 December 2024) and Habeny's OSSIM installer
  downloads from a GitHub repository that may no longer serve the agent. Consider removing
  OSSIM support, or at least not marketing it.

## What Habeny downloads, and from where

| SIEM | Where the agent comes from | Code | Stored |
|---|---|---|---|
| Wazuh | `https://packages.wazuh.com/4.x/apt/pool/main/w/wazuh-agent/…deb` | `app/installers/wazuh.py` | host cache `DATA_DIR/agent-cache`, then each container |
| Elastic | `https://artifacts.elastic.co/downloads/beats/elastic-agent/…deb` | `app/installers/elastic.py` | host cache, then each container |
| OSSEC | Atomicorp's repository installer `https://updates.atomicorp.com/installers/atomic`, then its packages | `app/installers/ossec.py` | inside each container |
| OSSIM | `https://github.com/AlienVault-OTX/OSSIM/raw/master/ossim-agent/ossim-agent.deb` | `app/installers/ossim.py` | inside each container |
| UTMStack | the customer's own UTMStack server, `https://<server>:9001/private/dependencies/agent/…` | `app/installers/utmstack.py` | host cache, then each container |

The host cache is a download cache on the customer's server. It's excluded from Habeny's
backups and never leaves that server.

## Per vendor

### Wazuh

- **License:** the Wazuh agent is GPLv2 ([LICENSE](https://github.com/wazuh/wazuh-agent/blob/main/LICENSE)).
- **Redistribution:** GPLv2 allows redistribution, including commercial, if the source is
  offered and the license is kept. Habeny doesn't redistribute it anyway: the customer's
  server downloads Wazuh's own packages. If Habeny ever bundles the agent (for example in
  an offline installer), it must ship the GPLv2 text and offer the corresponding source.
- **Name:** Wazuh has a [trademark policy](https://wazuh.com/legal-resources/trademark-policy/),
  [overall guidelines](https://wazuh.com/legal-resources/trademark-overall-guidelines/) and a
  [brand policy (May 2024, PDF)](https://wazuh.com/docs/legal-resources/Trademark_and_Brand_Policy_May_2024.pdf).
  Follow them for any use in marketing: plain-text name, no logo without permission, no
  implied partnership, and a trademark attribution.

### Elastic (Elastic Agent)

- **License:** [Elastic License 2.0](https://www.elastic.co/licensing/elastic-license) (ELv2);
  see the [FAQ](https://www.elastic.co/licensing/elastic-license/faq).
- **Redistribution:** ELv2 allows use, copying and redistribution, including in commercial
  products, with three limits: don't provide the software to others as a managed service;
  don't move, change, disable or circumvent its license-key functionality; don't remove
  or obscure licensing, copyright or other notices. Habeny downloads the agent from
  Elastic's own server and enrolls it in the customer's own Fleet. It doesn't host
  Elastic as a service for others, doesn't touch license keys, and doesn't alter notices.
  If Habeny ever bundles the agent, keep Elastic's notices with it.
- **Name:** ELv2 grants no trademark rights; use of "Elastic" and "Elasticsearch" is
  "subject to applicable law" per the FAQ. We found no published guidelines for
  "compatible with" statements. Use the name only descriptively, and ask counsel.

### OSSEC (Atomicorp)

- **License:** OSSEC HIDS is GPLv2 ([LICENSE](https://github.com/ossec/ossec-hids/blob/master/LICENSE));
  maintained by [Atomicorp](https://atomicorp.com/about-ossec/), see also [ossec.net](https://www.ossec.net/).
- **Redistribution:** as for Wazuh (GPLv2). Habeny runs Atomicorp's repository installer in
  the container, which adds Atomicorp's package repository to it. That repository and its
  terms are Atomicorp's; check the repository installer's own terms, since it can install
  more than the GPL agent.
- **Name:** no public trademark guidelines found. Descriptive use only; ask counsel.

### OSSIM (AlienVault, now LevelBlue)

- **License:** GPL, stated as v2 or v3 depending on the source
  ([AlienVault OSSIM licensing](https://success.alienvault.com/s/article/OSSIM-OSS-licensing),
  [Wikipedia](https://en.wikipedia.org/wiki/OSSIM)). The licensing article asks that
  trademark notices be kept.
- **Status:** retired by LevelBlue effective 31 December 2024
  ([announcements](https://success.alienvault.com/s/topic/0TO0Z000000oRSsWAM/ossim-product-announcements)).
  Habeny's download source (a file in a GitHub repository) may already be gone.
- **Name:** AlienVault and OSSIM are trademarks, now of LevelBlue. Advertising support
  for a retired product can mislead; recommend dropping it from marketing.

### UTMStack

- **License:** AGPLv3, including the agent
  ([UTMStack](https://github.com/utmstack/UTMStack), [agent](https://github.com/AtlasInsideCorp/UTMStackAgent),
  [licensing](https://portal.utmstack.com/index.php?rp=%2Fknowledgebase%2F33%2FLicensing.html)).
- **Redistribution:** Habeny doesn't redistribute it. The agent comes from the customer's
  own UTMStack server. AGPL's network clause applies to whoever modifies UTMStack and
  offers it over a network; Habeny doesn't modify or host UTMStack.
- **Name:** no public trademark guidelines found. Descriptive use only; ask counsel.

## What would change this analysis

- **Bundling agents** (offline packages, container images with agents pre-installed): you'd
  then redistribute them. GPL/AGPL need license texts and a source offer, ELv2 needs its
  notices kept, and each package must be listed in THIRD_PARTY_NOTICES.txt. Do this only
  with counsel's review.
- **Hosting Habeny as a service** with vendor software running on your infrastructure for
  customers: ELv2's managed-service limit and AGPL's network clause need a fresh look.
- **Modifying an agent.**

## Open questions for counsel

1. Is the "customer downloads from the vendor" model enough everywhere you sell, or should
   the EULA (section 4) and the Deploy page tell users more explicitly that they accept each
   vendor's license?
2. Exactly how may each vendor name appear on the website, in the product and in sales
   material (text only, a "works with" list, comparisons)? Do we need written permission
   from Wazuh under its brand policy?
3. Does Atomicorp's repository installer bring in anything under non-GPL terms?
4. Should OSSIM support be removed now that the product is retired?
