# Current implementation status

## Linux acquisition

- Bleak discovery uses tested active scanning on BlueZ; passive startup is not used.
- Linux owns BLE transport, wire decoding, burst assembly, quality policy, and canonical SQLite evidence.
- Revision-3 and revision-4 SQLite databases migrate transactionally to revision 5 without dropping raw frames, decoded fields, operations, or opaque word evidence.
- Quality is versioned and independent of lifecycle: `accepted`, `contact_failed`, or `indeterminate`.
- Completion waits for configured idle grace, stream close, or explicit stop; the safety timeout remains a last-resort failure.
- Weight-selection policy version 1 persists a source frame only after three repeated, positive, wire-valid display-weight observations; Android never selects a frame itself.
- Canonical storage keeps the ten words opaque. The downstream derivation contract uses the QN SDK-derived five-segment 20/100 kHz ordering, `raw × 0.1 Ω` scaling, and conditional byte de-obfuscation recorded in `context/PROTOCOL.md`. ACK-dependent capture acceptance requires a persisted TX observation.

## MCP projection

- MCP is launched on demand over stdio and is a read-only projection over daemon-owned SQLite history.
- The deployed surface is bounded to `list_sessions`, `get_latest_session`, `get_session`, and `get_session_evidence`; it does not instantiate acquisition or perform global operation recovery.
- Canonical session and frame resources remain available at `tracky://sessions/{session_id}` and `tracky://sessions/{session_id}/frames`; the two session tools provide equivalents for clients with weak resource support.
- Session summaries use aggregate SQLite queries for counts and metadata and do not load complete frame streams; metadata exposes an O(1) frame-resource URI/count descriptor. Evidence is loaded only through the explicit evidence tool or frame resource.
- `list_sessions` uses bounded opaque keyset cursors with stable newest-first `(timestamp, session_id)` ordering; equal timestamps are not skipped.
- Aggregate opaque blocks are exposed only from `BurstAssembler` wire-valid ordered pairs. Migrated decoded JSON remains lossless in storage while MCP removes or normalizes forbidden legacy semantic keys.
- Mixed decoder versions are represented as a distinct version list rather than a misleading maximum. Empty/latest and missing-session reads return stable structured outcomes.
- MCP views, the v1 observation contract, and `skills/bia-analyst/SKILL.md` use quality/version fields, structured source weight evidence, and opaque block terminology.

## Android Health Connect projection

- Android is a non-launcher integration surface reached through Health Connect's permission rationale/privacy entry points; it has no Bluetooth permission, BLE feature/transport, scale protocol, manual acquisition state, weigh-in UI, or canonical evidence database.
- The Room import ledger tracks source session identity, contract/derivation versions, `pending`/`imported`/`quarantined` disposition, retry state, and Health Connect record identity, plus one opaque cursor row. It stores no raw frames, profiles, or backup data.
- WorkManager uses connected-network constraints, exponential backoff, bounded HTTPS request/response timeouts, and one serialized sync path. The durable cursor advances only after each page item is imported or quarantined; retryable source state and failed Health Connect writes leave it unchanged.
- Endpoint validation requires HTTPS, rejects URL credentials/query/fragment/whitespace, ships no host or token default, and stores the bearer token with Android Keystore AES-GCM.
- Projection writes the complete supported Health Connect record suite (`WeightRecord`, `BodyFatRecord`, `LeanBodyMassRecord`, `BoneMassRecord`, `BasalMetabolicRateRecord`) using stable `clientRecordId`/`clientRecordVersion` metadata when valid BIA derivation is computed, falling back to idempotent `WeightRecord` projection when height or segmental burst evidence is absent.
- Health Connect read permissions cover height and historical data; write permissions cover weight, body fat, lean body mass, bone mass, and basal metabolic rate.
- Google Sans Flex v4.007 is bundled with its OFL-1.1 notice under `android/app/src/main/assets/licenses/`.

## Derivation

- `DerivationV1` (`derivation_version = 1`) reimplements the exact 8-electrode dual-frequency regression model recovered from the x86-64 `libyolanda_calc.so` binary (`calcSpecialtyBodyFat`, `calcSpecialtyBodySkeletalMuscle`) using IEEE-754 binary128 `.rodata` constants.
- The model operates over the five-segment 20/100 kHz impedance channels mapped from wire packets `0x21` and `0x22` using `raw × 0.1 Ω` scaling.
- Body fat percentage uses a 4-bracket piecewise regression over BMI with recovered coefficients.
- 4-compartment mass conservation and physiological identities govern body composition:
  - `LBM = Weight × (1 − BodyFat% / 100)`
  - `Water = 0.732 × LBM` (Pace-Rathbun fat-free mass hydration)
  - `Bone = max(0.039 × Weight, min(0.051 × Weight, 0.040 × Weight))`
  - `Protein = max(0.1, LBM − Water − Bone)`
  - `SkeletalMuscle = raw_regression` if within `(0, LBM)` else `0.70 × LBM`
  - `BMR = round(370.0 + 21.6 × LBM)` (Katch-McArdle)
- Identical reference implementations in Python (`linux/src/tracky_mcp/derivation.py`) and Kotlin (`android/.../DerivationV1.kt`) pass cross-platform golden-vector parity across underweight, normal, overweight, and obese strata.
- Physical scale `ERR2` error display is verified as an autonomous MCU hardware state triggered by upper-body electrode open-circuit/contact failure during frequency sweep; the BLE protocol accepts no external display commands, keeping Android strictly headless without UI cards or notifications.

## Sync API

- The Android observation endpoint requires bearer authentication for health and data routes, opens SQLite read-only, defaults to loopback, and runs with TLS termination or certificate/key pairs.
- The endpoint returns versioned pages with opaque keyset cursors and never advances past an open source session. It exposes persisted Linux-selected weight evidence and assembled wire-valid opaque burst blocks (`opaque_block_a` and `opaque_block_b`).
- Tokens are loaded from a protected file or environment, never from command-line arguments. Responses omit wildcard CORS and internal exception details.

## Verification

- Linux: 99 tests pass and Ruff is clean under UV-managed CPython 3.13.
- Android: 27 unit tests and `lintDebug` pass cleanly with zero errors.
- Documentation lint and `git diff --check` pass.
- End-to-end live device sync over authenticated TLS remains a deployment gate.
