# Operator notes: 20260809T194335Z

## Condition

`feet_handle_usbc_connected_on_ground`

Operator initially called this feet-only. Clarification: the **handle remained
plugged into USB-C** and rested on the ground (not held). Non-zero
`opaque_words` still appeared on every 0x10 frame, including a low fifth word
(133). This is **not** a true handle-disconnect control.

## Decode

- Weight formula unchanged: BE u16 bytes 3–4 / 100 → **78.9 kg** (`0x1ed2`).
- Measurement frames: 27; weight-only: 0; word-block present (b5=0x01,b6=0x21): 27.
- Resistance all-zero blocks: 0; non-zero blocks: 27.
- Last opaque_words: `[4549, 4215, 2190, 2039, 133]`.

## Multi-frame note

The scale streams many identical or near-identical 0x10 notifications. The client
**keeps every frame** in `measurements`; it does **not** average and does **not**
yet select a single stable sample as the product weigh-in result.

## Source

Raw log: `captures/feet-only-20260809T194335Z.jsonl` (gitignored). Device address redacted; hash `000000000000`.
