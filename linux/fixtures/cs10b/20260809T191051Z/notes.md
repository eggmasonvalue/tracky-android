# Operator notes: 2026-08-09 Linux handshake (kg + handle)

## Run

- Capture: `cs10b-20260809T191051Z`.
- Host: Linux, `hci0`, BlueZ/Bleak capture aid.
- Device advertisement: `QN-Scale` with the same sanitized address hash as
  the first fixture: `000000000000`. The Bluetooth address is not stored here.
- The capture was run with the kg unit option (`--unit kg`). The observed FFF2
  unit write was `13092001100000004d`, so `unit_byte=0x01` is direct wire
  evidence for this kg path.
- The observer prompt was barefoot on the scale plus handle contact. This run
  is therefore not a feet-only control. Word-block 0x10 frames were
  observed, consistent with reaching the handle/BIA path.
- Source references are ignored
  `captures/handshake-20260809T191051Z.jsonl` and
  `captures/cs10b-hs-20260809T191051Z.btsnoop`.

The handshake shape matches the first fixture:

1. FFF1 notification 0x12 (`protocol_type=0x20`).
2. FFF2 unit config 0x13 with kg byte `0x01`, then FFF2 `time_push`.
3. FFF1 0x14 response, followed by FFF2 0x20 time sync.
4. FFF1 0x21 response, followed by two FFF2 0xA0 writes.
5. Repeated FFF1 0x10 live frames, first weight-only and then
   word-block.

Only FFF1 notifications were enabled. AE02 was discovered but not used. No
runtime Feelfit, Yolanda SDK, or vendor cloud dependency is implied by this
capture.

## Decode observations

- **Weight — high confidence:** the stable weight-only frame
  `1012201edc0011000000000000000000004d` has `0x1edc = 7900` at bytes 3–4.
  Applying the confirmed big-endian `/100` formula gives **79.00 kg**. The
  same value repeats in the word-block frame variant.
- The expected golden intentionally uses the weight-only frame. The capture
  script's `weight_hypothesis` records used legacy offsets and are omitted
  from the fixture; the fixture hypotheses use the protocol decoder instead.
- A repeated word-block example is
  `1012201edc01210d770bba0df90c140d5e38`, with raw words
  `[3447, 3002, 3577, 3092, 3422]` at bytes 7–16. The five-word boundary is
  repeatable, but units, frequency, ordering, and body-composition meaning
  remain unproven. These values are kept unitless.
- `b5=0x00,b6=0x11` marks the weight-only example; `b5=0x01,b6=0x21` occurs
  with the five-word block. Their exact status/stability meanings remain open.

## Comparison with the lb fixture

- The GATT map and 0x12 → unit/time → 0x14 → 0x20 → 0x21 → two 0xA0 → 0x10
  sequence match `20260809T182636Z`.
- The first fixture wrote lb `unit_byte=0x02` and had a stable `0x1ee6`
  weight (`79.10 kg`), alongside the same-session Feelfit reference of
  `174.4 lb`. This fixture writes kg `unit_byte=0x01` and has stable
  `0x1edc` (`79.00 kg`).
- No operator-reported scale-display kg value was provided for this run, so
  no display-kg match is claimed.

## Checksum verification

The additive check `sum(frame[:-1]) & 0xff == frame[-1]` matched **57/58**
packet records overall and **50/50** 0x10 records. The only exception is the
five-byte `time_push` `028b8d0b32`, which is treated as a time message rather
than a checksum-bearing frame. The session fixture records the summary and
per-example checksums.

## Open questions

- A feet-only capture is still needed to separate foot-only weight from the
  handle/BIA path; this run was kg plus handle contact.
- What units, frequencies, and segment mapping do the five raw values use?
- What are the exact meanings of 0x12, 0x14, 0x21, the two 0xA0 writes, and
  the `b5`/`b6` pair?
- Is AE02 ever required, and are TS-CS10B and TR-CS10B truly identical across
  firmware revisions?
