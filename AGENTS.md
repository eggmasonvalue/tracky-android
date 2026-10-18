# Agent guide

Tracky is one product with a Linux acquisition appliance, an on-demand MCP projection, an agent skill, and an Android Health Connect bridge. Code is the source of truth; documentation records layout and non-obvious choices.

## Guardrails

- Work on a branch and prepare a PR. Do not commit directly to the default branch; do not merge or push without human instruction.
- Run `git push` only from a repository under `D:\Misc2\06_backups`; use authenticated `gh` for GitHub operations when appropriate.
- Keep changes scoped and verify behavior before documenting claims.
- Keep Linux as the sole BLE, wire-protocol, and canonical-record owner.
- Keep MCP on-demand and read-only. Keep Android free of BLE and scale-protocol code.
- Preserve unknown electrical fields as opaque evidence. Admit derived health metrics only with traceable, versioned validation.
- Keep secrets, raw Bluetooth addresses, private captures, and personal measurements out of Git and normal logs.
- Keep runtime dependencies inspectable and permissively licensed. Use no vendor SDKs, proprietary binaries, analytics, telemetry, or cloud dependency.
- Treat `TS-CS10B` and `TR-CS10B` as aliases until physical evidence establishes a difference.
- Preserve zero-touch acquisition; a weigh-in must not require waking or unlocking a phone.

## Read

- Layout or data flow → [`context/MAP.md`](context/MAP.md)
- Durable tradeoffs → [`context/DECISIONS.md`](context/DECISIONS.md)
- Coding rules and verification → [`context/CONVENTIONS.md`](context/CONVENTIONS.md)
- BLE evidence or semantics → [`context/PROTOCOL.md`](context/PROTOCOL.md)
- Cross-component data → [`contracts/README.md`](contracts/README.md)
- Runtime installation or security → [`context/DEPLOYMENT.md`](context/DEPLOYMENT.md)
- Live work → run `todo list`; claim the task before editing

## Write

- Module structure or data flow change → `context/MAP.md`
- Durable architecture, behavior, data-shape, dependency-ownership, or expensive-migration choice → `context/DECISIONS.md`
- Repeatable coding rule → `context/CONVENTIONS.md`
- Protocol evidence change → `context/PROTOCOL.md`
- Cross-component schema change → `contracts/`
- User-facing setup or usage change → `README.md`

## Decision-log bar

`context/DECISIONS.md` is a curated ADR file, not a worklog, changelog, or status list. Record a choice only when it changes architecture, public behavior, data shape, dependency ownership, or an expensive migration path; a future agent could reasonably choose differently; the rationale is not obvious from code; and the choice remains relevant after the current task.

Exclude bug fixes, cleanup, dead-code removal, renames, mechanical refactors, one-feature tactics, routine checks, status updates, and obvious code behavior.

## Conventions and decisions

Conventions are terse imperatives with no rationale. Put rationale in `DECISIONS.md` only when it passes the decision-log bar.

Todos hold live working context. Before closing a todo, graduate durable rationale to `DECISIONS.md` only when it passes the bar.

## Definition of done

Code, static checks, tests, contracts, and durable docs agree. An unrecorded decision-log-bar choice means the task is incomplete.
