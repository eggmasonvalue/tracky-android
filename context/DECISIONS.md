# Decisions

Durable architecture only. Amend before competing. Not a changelog or worklog.

```text
## YYYY-MM-DD — title
Context: what forced the choice
Decision: what we chose
Tradeoff: what we gave up or rejected and why
Status: active | superseded by <date/title>
```

## 2026-09-16 — Linux exclusively owns acquisition and canonical evidence

Context: Reliable zero-touch capture requires an always-on host in the scale's room. Multiple BLE and protocol implementations had diverged, and Android background scanning cannot guarantee capture of the scale's short advertising window.

Decision: The Linux appliance exclusively owns BLE discovery, GATT, wire-protocol decoding, measurement quality, session lifecycle, stable source identity, and the canonical SQLite evidence store. Android, MCP, and skills consume Linux-owned interfaces and never acquire directly.

Tradeoff: Direct phone-only weighing is removed. Operation depends on the local Linux appliance, but protocol behavior and evidence have one authority.

Status: active

## 2026-09-16 — One acquisition path has two consumer projections

Context: AI agents need inspectable history while Android applications need Health Connect records. Those consumers require different presentation and interpretation behavior but the same observations.

Decision: An on-demand read-only MCP server plus skill serves agents. A non-launcher Android bridge synchronizes observations and writes supported, deterministic projections to Health Connect. Neither projection is a system of record.

Tradeoff: Each consumer owns a separate adapter and may support different outputs. Cross-component compatibility requires a versioned observation contract.

Status: active

## 2026-09-16 — One monorepo owns the Tracky product

Context: Separate repositories allowed architecture, fixtures, and contracts to diverge even though Linux, Android, and the skill form one release unit.

Decision: Keep Linux, Android, shared contracts, fixtures, skills, and canonical documentation in one repository while retaining independent language-specific builds.

Tradeoff: Repository migration and mixed-toolchain CI are more complex, but boundary changes and compatibility tests can be reviewed atomically.

Status: active

## 2026-09-16 — Preserve evidence separately from interpretation

Context: The wire format contains a display-confirmed weight and two physically observed five-word blocks, while electrical units, channel meanings, and body-composition formulas require additional validation.

Decision: Persist lossless ordered wire evidence and grade every interpretation. Keep unresolved electrical fields opaque. Enable a derived health metric only through a versioned algorithm with traceable coefficients, defined inputs, applicability, uncertainty, and explicit failure behavior. Never clamp invalid output into a plausible range.

Tradeoff: Health Connect and agent output may initially be weight-only, but future evidence can be reprocessed without another weigh-in and unsupported claims do not become health data.

Status: active

## 2026-09-17 — Recover scale-family derivation behavior

Context: No transparent modern prediction equation was found whose declared inputs
match Tracky's five-segment 20/100 kHz scalar impedance values. Published equations
use incompatible frequencies, electrical quantities, electrode paths, or calibration
populations, while matching commercial devices keep their algorithms undisclosed.
The QN SDK confirms that its native calculator consumes Tracky's exact profile and
ten-channel inputs, but its coefficient banks exist only in stripped native binaries.

Decision: Recover and independently reimplement the exact QN scale-family derivation
behavior from inspectable public artifacts. Do not ship vendor binaries. Require an
immutable algorithm version, coefficient-to-operand provenance, applicability rules,
and vendor-output golden vectors before enabling derived records. Describe successful
parity as vendor compatibility, not independent clinical validation.

Tradeoff: This can restore the intended smart-scale outputs without transplanting
incompatible academic equations, but reverse engineering is more costly and vendor
parity alone does not establish physiological accuracy. Derived records remain
disabled until the recovery and validation gates pass.

Status: active

## 2026-09-16 — Android uses Health Connect profile data without owning it

Context: Derivation may require profile inputs. Health Connect provides height as a time-series record but has no equivalent stable fitness records for every potentially required input.

Decision: Android reads the latest applicable height from Health Connect and never writes height. Initial onboarding collects only required inputs unavailable from Health Connect, with no fabricated defaults and a later correction path. No profile data crosses to Linux.

Tradeoff: Some local user input remains necessary before profile-dependent derivation can run.

Status: active

## 2026-09-16 — Android keeps an import ledger, not a backup

Context: Reliable synchronization requires retries and deduplication, but duplicating the canonical evidence database would create ownership and reconciliation problems.

Decision: Android stores only source identity, contract and derivation versions, disposition, retry state, and Health Connect identity required for idempotent imports. Linux backup and restore remain deployment responsibilities.

Tradeoff: Android cannot restore the Linux evidence database and offline inspection remains limited.

Status: active

## 2026-09-16 — Deploy acquisition as a system service and MCP on demand

Context: Acquisition must survive logout and reboot, while MCP is needed only when an agent queries history. Independent acquisition owners can corrupt operation state.

Decision: Run one Linux daemon as a system-level `systemd` service under a dedicated account and state directory. Launch MCP on demand over stdio with read-only access; MCP does not instantiate acquisition or recovery services. User lingering is not part of the deployment.

Tradeoff: Administrative setup is required and MCP cannot initiate weigh-ins, but acquisition remains reliable and single-owner.

Status: active

## 2026-09-16 — Android has no ordinary launcher entry

Context: Android is background integration infrastructure rather than a daily-use scale application, but Health Connect still requires onboarding and permission-rationale surfaces.

Decision: Expose Health Connect onboarding, permission rationale, and actionable diagnostics without an ordinary launcher entry. Use Google Sans Flex under SIL Open Font License 1.1 and ship its license notice with the asset.

Tradeoff: Diagnostics are less discoverable than a normal application and must be reachable from Health Connect or actionable notifications.

Status: active
