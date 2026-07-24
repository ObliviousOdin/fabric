# SOC 2 Readiness Audit — codename IRONLOOM (2026-07-24)

Point-in-time SOC 2 Trust Services Criteria gap analysis of the Fabric codebase.

- **[`SOC2-GAP-ANALYSIS.md`](SOC2-GAP-ANALYSIS.md)** — full report: executive summary, findings
  register (3 High / 21 Medium / 20 Low / 6 Info; 0 Critical), per-finding evidence and
  remediation, cross-cutting gap analysis, control-strengths inventory, a TSC readiness matrix,
  and a prioritized remediation roadmap.

## Method
Read-only static review across six evidence workstreams (secrets & credentials; skills/plugins/MCP
extension surface; auth & external surfaces; injection & code execution; dependency & supply chain;
CI/CD change management, logging, monitoring & privacy). No source files were modified.

## Headline
Preventive access and change controls are at or above SOC 2 expectations (fail-closed authorization,
strong credential redaction, disciplined dependency pinning, a self-auditing CI change surface). The
gaps concentrate in **detective/monitoring controls** (no automated SAST / secret / dependency
scanning; a documented supply-chain CI gate that does not exist), **change governance evidence**
(no CODEOWNERS; separation of duties is policy-only), **data governance** (no retention/purge, plaintext
state at rest), and the **extension supply chain** (unsigned plugin code load; first-party skills bypass
the scanner; a bypassable, fail-open MCP-launch preflight). One dependency anomaly — a `lodash` override
to the non-canonical version `4.18.1` — warrants urgent verification.

See the full report for the ranked register and roadmap.
