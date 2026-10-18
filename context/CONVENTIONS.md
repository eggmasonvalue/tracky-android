# Conventions

## Boundaries

- Keep Linux as the sole BLE, wire-protocol, and canonical-record owner.
- Keep MCP on-demand and read-only.
- Keep Android free of BLE, scale-protocol, and canonical evidence storage.
- Put cross-component schemas and semantics under `contracts/`.
- Keep user profile data on Android.

## Evidence

- Label protocol claims with the grades defined in `PROTOCOL.md`.
- Preserve raw frames before derived fields.
- Keep unvalidated electrical words opaque.
- Separate wire validity, burst completeness, contact quality, sample selection, and scientific validity.
- Use sanitized fixtures; exclude addresses, credentials, timestamps tied to a person, and personal measurements.
- Fail unsupported derivations explicitly.
- Never clamp derived output into a plausible range.

## Data and privacy

- Use stable opaque identifiers across boundaries.
- Make synchronization and Health Connect writes idempotent.
- Store secrets outside source, logs, command lines, fixtures, and documentation.
- Exclude raw Bluetooth addresses from normal logs and consumer surfaces.
- Attribute imported Health Connect records with stable client record IDs and source-device metadata.

## Verification

- Use the UV-managed Python pinned by `linux/.python-version`; do not use the system Python.
- Install Linux environments with `cd linux && uv sync --extra dev --extra ble --extra mcp`.
- Run Linux tests with `cd linux && uv run pytest`.
- Run Linux lint with `cd linux && uv run ruff check src tests`.
- Run Android checks with `cd android && ./gradlew testDebugUnitTest lintDebug assembleDebug`.
- Run documentation lint with `npx --yes markdownlint-cli2 "README.md" "AGENTS.md" "context/*.md" "contracts/*.md" "skills/**/*.md" "linux/fixtures/**/*.md"`.
- Update the affected contract and fixture tests with every boundary change.
