# Tracky

Private, local-first acquisition and Health Connect integration for the Tracky `TS-CS10B` / `TR-CS10B` eight-electrode scale.

## Architecture

```text
Scale → Linux acquisition appliance → SQLite system of record
                                  ├→ on-demand MCP → agent skill
                                  └→ Android bridge → Health Connect
```

Linux is the only BLE and scale-protocol owner. MCP reads captured history for agents. Android is a non-launcher background projection: it synchronizes canonical observations with authenticated HTTPS, reads (but never writes) Health Connect height, and writes idempotent records. Weight projection is implemented. Derived metrics remain disabled until the exact QN scale-family formulas are recovered with traceable coefficients, applicability rules, and vendor-output parity tests.

See:

- [`context/MAP.md`](context/MAP.md) — module boundaries and data flow
- [`context/DECISIONS.md`](context/DECISIONS.md) — durable tradeoffs
- [`context/CONVENTIONS.md`](context/CONVENTIONS.md) — coding and verification rules
- [`context/PROTOCOL.md`](context/PROTOCOL.md) — evidence-graded protocol knowledge
- [`context/DERIVATION.md`](context/DERIVATION.md) — BIA inputs and coefficient-validation handoff
- [`contracts/README.md`](contracts/README.md) — target cross-component contract
- [`context/DEPLOYMENT.md`](context/DEPLOYMENT.md) — target deployment

## Repository

```text
android/    Non-launcher Android Health Connect projection and import ledger
linux/      Python BlueZ acquisition, SQLite, sync API, and MCP implementation
contracts/  Shared observation contract; schema/fixture integration pending
skills/     Agent-facing analysis skill
context/    Canonical project map, decisions, conventions, and focused references
```

## Development

Linux:

```bash
cd linux
uv sync --python 3.13 --extra dev --extra ble --extra mcp
uv run pytest
uv run ruff check src tests
```

Android:

```bash
cd android
./gradlew testDebugUnitTest lintDebug assembleDebug
```

The current branch is an architectural migration, not a deployment-ready release. Android has no ordinary launcher entry; Health Connect opens its rationale/onboarding surface. Configure an HTTPS endpoint and bearer token through that surface. Run `todo list` for current implementation work.

## License

Tracky source code is licensed under the [MIT License](LICENSE). Bundled third-party assets retain their own compatible notices. The bundled Google Sans Flex Android asset is the official v4.007 release and includes its SIL Open Font License 1.1 notice under `android/app/src/main/assets/licenses/`.
