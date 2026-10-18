# Operator notes: 2026-08-09 Linux handshake

## Run

- Capture: `cs10b-20260809T182636Z`
- Host: Linux, `hci0`, BlueZ/Bleak capture aid.
- Device advertisement: `QN-Scale`.
- Model label shown by the Feelfit bind UI: `TR-CS10B (Smart Body Fat Scale)`.
- The fixture stores only `address_hash=000000000000`; it does not store the
  Bluetooth address. Hash input is the uppercase address with colons removed;
  SHA-256 is truncated to the first 12 hex characters.
- Source references: ignored
  `captures/handshake-20260809T182636Z.jsonl` and
  `captures/cs10b-hs-20260809T182636Z.btsnoop`.

The earlier passive Linux run repeatedly received only the 0x12 info frame
`121220d1e0460003ff079308400005030027` and produced no weight without host
handshake writes. This successful run used the following observed sequence:

1. FFF1 notification 0x12 (`protocol_type=0x20`).
2. FFF2 unit config 0x13, with lb unit `0x02`.
3. FFF2 `time_push`.
4. FFF1 0x14 response.
5. FFF2 0x20 time sync.
6. FFF1 0x21 response.
7. Two FFF2 0xA0 writes.
8. Repeated FFF1 0x10 live frames, first weight-only and later with a
   word-block block.

Only FFF1 notifications were enabled in this run. AE02 was discovered but was
not used. No runtime Feelfit, Yolanda SDK, or vendor cloud dependency is
implied by this capture.

## Decode observations

- **Weight — high confidence:** in the 18-byte 0x10 frames, bytes 3–4 are a
  big-endian unsigned value. `0x1ee6 = 7910`; dividing by 100 gives **79.10
  kg**. Feelfit showed **174.4 lb**, which is 79.11 kg by the standard
  conversion, a same-session match within 0.01 kg.
- `b5=0x00` occurs on the weight-only path; `b5=0x01` occurs when the raw
  five-value block is present. `b6=0x11` and `b6=0x21` also differ between
  those paths. Their exact status/stability meanings remain open.
- `opaque_words[]` is five consecutive big-endian u16 candidates at bytes
  7–16. Examples include `[3386, 2950, 3516, 3050, 3392]`. Field boundaries
  and repetition are strong evidence; units, frequency, ordering mapping, and
  body-composition interpretation are not established. Do not label these
  values with electrical units yet.

## Checksum verification

A Python check used `sum(frame[:-1]) & 0xff == frame[-1]` on every raw packet
with a final byte. It matched **139/139 0x10 frames** and **146/147 packet
records** overall. The sole exception is the five-byte `time_push`
`02e4820b32`, which is treated as a time message rather than a
checksum-bearing frame. The fixture records this result and each example's
observed checksum.

## Feelfit and Android caveats

Feelfit was used only as same-session UI reference after correcting the device
type and binding as `TR-CS10B`. It displayed 174.4 lb and marketing metrics
such as water 55%, protein 14.4%, fat 25.7%, bone 4.9%, and BMI 24.4. Those
outputs are profile/app-derived reference values, not protocol ground truth or
v1 science targets, and are not copied into the session JSON.

A Pixel bugreport exposed only filtered `btsnooz` data without ATT payloads;
full HCI snoop was unavailable without root. The Linux capture is therefore
the authoritative raw-packet source for this fixture.

## Open questions

- Is the advertised FFE0 family a separate/alias surface or just advertising
  metadata for the connected FFF0 service?
- What are the exact meanings of 0x12, 0x14, 0x21, the two 0xA0 writes, and
  `b5`/`b6`?
- Are the five raw values electrical measurements, and if so what
  units, frequencies, and segment order do they use?
- Which writes are required for a minimal production handshake, and is AE02
  ever needed?
- Are TS-CS10B and TR-CS10B truly identical across firmware revisions?
