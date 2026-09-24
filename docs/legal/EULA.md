# Habeny End User License Agreement

> **DRAFT: not reviewed by a lawyer.** This is a starting point prepared from how Habeny
> works (per-server licenses, offline license files, self-hosted installs, no telemetry).
> Have counsel in your jurisdiction review and adapt it before you use it with customers,
> in particular the sections marked **[Counsel]**. Terms of service are only needed if
> Habeny Platform ever operates Habeny as a hosted service; this EULA covers self-hosted
> installs only.

**Licensor:** Habeny Platform ("we", "us")
**Version:** draft 1, 2026-09-24

This agreement is between Habeny Platform and the organization that obtains a license
("Customer", "you"). By installing or using Habeny you agree to it. If you don't agree,
don't install or use Habeny.

## 1. Definitions

- **Software**: the Habeny server application, its web interface, command-line tools,
  documentation and updates we provide, excluding Open-Source Components.
- **Server**: one physical or virtual machine, identified by the server ID Habeny derives
  from the machine's identity (`habeny license request`).
- **License File**: a file we issue that names you, one Server, a term and any limits (for
  example, the number of containers).
- **Order**: the quote, order form or invoice that states what you licensed and the fees.
- **Open-Source Components**: third-party software included with the Software under its
  own license, listed in THIRD_PARTY_NOTICES.txt.
- **Third-Party Agents**: SIEM agents and other software (for example from Wazuh, Elastic,
  Atomicorp/OSSEC, LevelBlue/AlienVault or UTMStack) that the Software downloads from their
  publishers onto your Server when you deploy them.

## 2. License grant

Subject to this agreement and payment of the fees, we grant you a non-exclusive,
non-transferable, non-sublicensable license, for the term in your License File, to
install and use the Software on the Server named in each License File, for your internal
business purposes, within the limits stated in the License File and Order.

You may make a reasonable number of copies for backup and disaster recovery. A backup copy
may run in place of a failed Server; ask us for a License File for the replacement Server.

**Evaluation.** Without a License File, the Software runs as a trial for 30 days. You may
use the trial only to evaluate the Software. The trial is provided without any warranty or
support.

## 3. Restrictions

Except as this agreement or applicable law expressly allows, you will not:

1. use the Software on more Servers, or beyond the limits, that your License Files allow;
2. copy, modify, translate or create derivative works of the Software;
3. reverse engineer, decompile or disassemble the Software, except to the extent that
   applicable law permits despite this restriction **[Counsel: EU Software Directive art. 6
   interoperability exception]**;
4. remove, alter or circumvent the license check, License Files or proprietary notices;
5. rent, lease, lend, sell, sublicense, distribute or otherwise transfer the Software;
6. provide the Software to third parties as a hosted or managed service, or use it to
   provide services to third parties, unless your Order expressly allows it;
7. use the Software in violation of law, or to test systems you're not authorized to
   test.

## 4. Open-source components and third-party agents

Open-Source Components are licensed to you under their own licenses, listed in
THIRD_PARTY_NOTICES.txt. Nothing in this agreement restricts your rights under those
licenses.

The Software doesn't include Third-Party Agents. When you deploy them, your Server
downloads them from their publishers, and they are licensed to you by their publishers
under their own terms (see docs/legal/siem-vendors.md). You are responsible for complying
with those terms, and for having the right to connect to the SIEM systems you configure.
We make no warranty about Third-Party Agents or their availability; publishers can change
or withdraw them at any time.

Product names such as Wazuh, Elastic, OSSEC, AlienVault, OSSIM and UTMStack are
trademarks of their owners and are used only to identify the products the Software works
with. The Software is not affiliated with or endorsed by them.

## 5. Your data

The Software runs on your infrastructure. It stores its data, including any logs you
upload and the results of simulations and benchmarks, on your Server. It does not send
that data, usage data or crash reports to us. docs/privacy.md describes what is stored,
where, and for how long.

We have no access to your data unless you give it to us, for example in a support
request. We then use it only to provide that support. **[Counsel: add a data processing
agreement if support involves personal data under GDPR or similar laws.]**

## 6. Fees, term and termination

Fees are set out in the Order. A License File is valid for the term it states. A perpetual
License File has no end date, but support and updates are provided only while a
maintenance subscription is paid, if your Order includes one.

Either party may terminate this agreement if the other materially breaches it and doesn't
cure the breach within 30 days of written notice. When this agreement or a License File
ends, you must stop using the Software on the affected Servers. After a term license
expires, the Software keeps your data readable and lets you stop and delete existing
containers, so you can export or remove your data. It refuses new deployments and tests.

Sections 3, 4, 5, 7, 8, 9 and 11 survive termination.

## 7. Warranty

**[Counsel: adjust to your market; consumer-protection and implied-warranty rules differ
by country.]** For 90 days from delivery, we warrant that the Software will perform
substantially as described in its documentation. Your exclusive remedy for a breach of this
warranty is, at our option, that we fix the Software, replace it, or refund the fees you
paid for the non-conforming Software.

EXCEPT AS STATED ABOVE, THE SOFTWARE IS PROVIDED "AS IS". TO THE EXTENT PERMITTED BY LAW,
WE DISCLAIM ALL OTHER WARRANTIES, EXPRESS OR IMPLIED, INCLUDING MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NON-INFRINGEMENT. The Software is a test platform: it deploys
agents and generates simulated attack and log traffic. Run it against systems meant for
testing, not production systems.

## 8. Limitation of liability

**[Counsel: confirm caps and exclusions are enforceable where you sell.]** TO THE EXTENT
PERMITTED BY LAW, NEITHER PARTY IS LIABLE FOR INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL
OR PUNITIVE DAMAGES, OR FOR LOST PROFITS, REVENUE OR DATA, ARISING OUT OF THIS AGREEMENT.
EACH PARTY'S TOTAL LIABILITY IS LIMITED TO THE FEES YOU PAID IN THE 12 MONTHS BEFORE THE
EVENT GIVING RISE TO THE CLAIM. These limits don't apply to your breach of section 3, to
either party's indemnification obligations, or to liability that cannot be limited by law.

## 9. Intellectual property and feedback

We and our licensors own the Software and all intellectual property rights in it. This
agreement grants no rights except those stated. If you give us suggestions, we may use
them without obligation to you.

## 10. Verification

Once a year, on 30 days' written notice, you'll certify in writing the Servers on which
the Software is installed. **[Counsel: consider whether you want audit rights beyond
self-certification.]**

## 11. General

- **Export control.** You'll comply with export control and sanctions laws that apply to
  the Software.
- **Governing law and venue.** **[Counsel: choose, e.g. the laws of the country where
  Habeny Platform is established and its courts.]**
- **Assignment.** You may not assign this agreement without our written consent, except to
  a successor of your whole business that agrees to it in writing.
- **Entire agreement.** This agreement and the Order are the entire agreement about the
  Software. If they conflict, the Order prevails. Changes must be in writing and signed by
  both parties.
- **Severability.** If a provision is unenforceable, the rest remains in effect.
- **Notices.** **[Counsel: add Habeny Platform's legal name, registered address and
  contact email.]**
