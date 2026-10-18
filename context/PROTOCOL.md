# QN-Scale / CS10B protocol record

**Validation status:** live path validated 2026-09-16; this record intentionally
keeps no sample weights, personal raw values, capture timestamps, addresses,
credentials, or conversation details.

## Evidence vocabulary

- **E3 — live-correlated:** observed in live validation and independently
  confirmed by the device display or by a repeatable wire response.
- **E2 — source-correlated:** reproduced by sanitized fixtures/tests and
  corroborated by public QN/Yolanda SDK-derived implementations or documentation.
- **E1 — implementation hypothesis:** a deterministic code label or candidate
  interpretation not established by an independent physical validation.
- **U — unknown:** do not infer or expose as a product fact.

A higher grade applies only to the claim stated; it does not promote adjacent
fields or interpretations.

## Discovery and GATT

| Claim | Grade |
| --- | --- |
| The device advertises as `QN-Scale`. | E3/E2 |
| The advertisement exposes the `FFE0` service family. | E3/E2 |
| The connected GATT service is `FFF0`; `FFF1` is the notification path and `FFF2` is the write path. | E3/E2 |
| `AE02` is not required by the validated path. | E2; not a universal exclusion |

The scanner may match the name or either `FFE0`/`FFF0` service family. The
validated protocol should nevertheless use the discovered `FFF0` service and
its `FFF1`/`FFF2` characteristics rather than assuming an advertisement UUID is
the connected service.

The Linux daemon uses Bleak's explicit `scanning_mode="active"` configuration.
BlueZ passive discovery can fail at startup when the adapter does not expose the
required `or_patterns` support; active discovery is the tested configuration and
still applies the name/service filter in the callback. This is a transport
choice, not protocol evidence.

## Handshake

After enabling notifications on `FFF1`, the observed sequence is:

1. RX `0x12` information frame.
2. TX `0x13` unit configuration and the short `0x02` time-push command on
   `FFF2`.
3. RX `0x14` status response.
4. TX `0x20` time-sync command.
5. RX `0x21` status response.
6. TX the two fixed `0xA0` setup writes.
7. RX live `0x10` measurement frames.

The state machine advances only on valid, ordered, checksum-bearing frames. The
short five-byte `0x02` time-push command is the documented checksum exception;
other known protocol frames use the additive trailer
`sum(frame_without_trailer) & 0xff`. The handshake succeeds in live validation
(E3) and is replayed by both imported clients (E2).

## Measurement frames

- A `0x10` frame is **18 bytes** long and carries the additive checksum (E3/E2).
- With zero-based indexing, bytes `3..4` are a big-endian unsigned weight
  field. `u16be(frame[3:5]) / 100` is kilograms (E3: independently display
  confirmed; E2: fixture and Android/Linux decoder agreement).
- `b5=0x01, b6=0x21` identifies the first observed five-word block. After it,
  the host writes `1f0620102176` to `FFF2`; the following block uses `b6=0x22`
  (E3/E2).
- Both block packets contain five consecutive big-endian unsigned 16-bit words
  at bytes `7..16` (E2, with live sequence confirmation at E3).
- Preserve every decoded frame and its checksum status. Do not average the
  stream or silently discard a repeated/near-repeated frame.

Linux stores each block as opaque wire evidence so protocol capture remains
lossless and independent of downstream interpretation. The QN SDK-derived mapping
for the eight-electrode path is nevertheless established at E2 and is the mapping
to use for versioned derivation:

| Packet | Word | Meaning | Scale |
| --- | ---: | --- | --- |
| `b6=0x21` | 0 | left foot/leg, 20 kHz | raw × 0.1 Ω |
| `b6=0x21` | 1 | left foot/leg, 100 kHz | raw × 0.1 Ω |
| `b6=0x21` | 2 | right foot/leg, 20 kHz | raw × 0.1 Ω |
| `b6=0x21` | 3 | right foot/leg, 100 kHz | raw × 0.1 Ω |
| `b6=0x21` | 4 | left hand/arm, 20 kHz | raw × 0.1 Ω |
| `b6=0x22` | 0 | left hand/arm, 100 kHz | raw × 0.1 Ω |
| `b6=0x22` | 1 | right hand/arm, 20 kHz | raw × 0.1 Ω |
| `b6=0x22` | 2 | right hand/arm, 100 kHz | raw × 0.1 Ω |
| `b6=0x22` | 3 | trunk, 20 kHz | raw × 0.1 Ω |
| `b6=0x22` | 4 | trunk, 100 kHz | raw × 0.1 Ω |

This mapping and `kRatio=0.1` conversion come from the QN decoder path documented
in the prior clean-room implementation, including `eightResTwoByte2Double` and
`calcSpecialtyBodyData`. The SDK conditionally de-obfuscates each impedance byte
by swapping bits 3/5 and 0/4 when the advertisement flag requests it; captured
Tracky frames use the plain representation. Relevant public artifacts are:

- <https://github.com/vayun-mathur/Modern-Apps/blob/c5d759c2ac086d8fe01e775db9496824561fb3a6/things/src/main/java/com/vayunmathur/things/platform/ScaleBleManager.kt>
- <https://github.com/vayun-mathur/Modern-Apps/blob/c5d759c2ac086d8fe01e775db9496824561fb3a6/things/src/main/java/com/vayunmathur/things/platform/ScaleBleProtocol.kt>
- <https://github.com/YolandaQingniu/qnscalesdk>
- <https://github.com/JackChan1999/boohee_v5.6>

`BurstAssembler` deliberately continues to expose blocks opaquely at the storage
and transport boundary. Semantic conversion belongs in a separately versioned
derivation layer and must not rewrite canonical evidence.

## Derivation status

The intended derivation class uses segmental multi-frequency
height-squared-over-impedance predictors, with weight, age, and biological sex where
required. Channel mapping and impedance scaling are established inputs; coefficient
selection is the outstanding problem.

No exact modern equation was selected during prior research. The earlier phrase
"Segmental Multi-Frequency Sum-of-Segments model" described a model structure, not
a published consensus formula with universal coefficients. Earlier Android and
skill implementations supplied conflicting, unsupported numbers and are rejected.
Yolanda's dated proprietary composition algorithm is not the target. Before
restoring derived metrics, select a modern published equation compatible with the
available 20/100 kHz segmental inputs and record its exact coefficients, primary
source, calibration population, applicability limits, and uncertainty. See
`DERIVATION.md`. Use one versioned coefficient set across consumers, reject
out-of-scope inputs explicitly, and never clamp output.

## Contact, foot-only, and completion quality

Live condition observations are qualitative by design:

- A **completed handle-contact** acquisition produced stable nonzero words
  (E3). This is evidence that the handle path can produce a usable-looking
  word block, not proof of units or anatomy.
- A **completed foot-only Err2** acquisition produced an all-zero word block
  (E3). Keep the weight field separate from word-block quality; zero words are
  not a BIA result and must not be converted into physiological values.
- An **interrupted foot-only** acquisition could produce irregular nonzero words
  (E3). Nonzero data alone is therefore insufficient evidence of valid contact,
  completion, or BIA quality.

Completion and quality are separate dimensions:

1. **Wire-valid:** the known frame shape is accepted and its checksum passes
   (the five-byte `0x02` time-push remains the documented checksum exception).
2. **Measurement-valid:** a wire-valid `0x10` frame supplies the independently
   validated weight field; a present block may still be zero.
3. **Burst-candidate:** both ordered `b6=0x21` and `b6=0x22` blocks are
   retained from wire-valid frames. A bad-checksum or intervening frame breaks
   pending assembly even though storage retains the evidence.
4. **Quality:** Linux quality version 1 persists exactly `accepted`,
   `contact_failed`, or `indeterminate`. `accepted` additionally requires the
   exact `1f0620102176` TX ACK to have been observed after persistence; RX
   packet order alone is insufficient. Quality does not assign meaning to an
   opaque word.

The evidence-backed completion policy uses three consecutive identical,
wire-valid measurement frames for one marker/signature run and then a
three-second measurement-idle grace period. Invalid or intervening frames break
the relevant run. A burst candidate enables that idle boundary but never ends
capture by itself. An ordered burst is `accepted` only when both opaque blocks
are present, all words are nonzero, each block has its own consecutive stability
run, and the persisted TX ACK evidence is available. A complete all-zero burst,
or a stable all-zero block without a burst, is `contact_failed` only when the
same conservative evidence is present; missing ACK or incomplete/irregular
streams are `indeterminate`. Nonzero values alone never establish contact.
These rules are conservative labels for capture quality, not body-composition
semantics.

A normal policy completion records operation/session lifecycle `complete` while
persisting the independent quality label. The safety timeout remains only a
last-resort failure when there is no stream end, explicit stop, or evidence-backed
idle boundary. Weight-selection policy version 1 may select the latest frame in
a run of three repeated, positive, wire-valid display-weight observations. This
selection uses only the independently validated weight field; opaque words and
contact quality do not influence it. If the selected bytes cannot be tied back
to a persisted measurement frame, no selection is stored. A terminal storage
status (`complete`, `aborted`, or an operation error) is recorded independently
of selection, and `selected_frame_sequence` remains optional. Interrupted or
device-error observations remain diagnostic evidence and are never promoted to
unsupported physiological output.

## Evidence sources

The durable repository basis is the sanitized material under:

- `linux\src\tracky_mcp\ble\client.py`
- `linux\src\tracky_mcp\protocol\checksum.py`
- `linux\src\tracky_mcp\protocol\decode.py`
- `linux\src\tracky_mcp\protocol\frames.py`
- `linux\src\tracky_mcp\protocol\session.py`
- `linux\fixtures\cs10b\README.md`, its sanitized `*\notes.md` records, and
  the address/timestamp-free `conditions/*.json` quality fixtures
- `linux\src\tracky_mcp\protocol\burst.py`
- `linux\src\tracky_mcp\protocol\quality.py`
- the corresponding Linux protocol, acquisition, storage, and fixture tests

Fixture and implementation agreement is evidence for decoding behavior, not a
substitute for independent validation of physical units or BIA semantics.
