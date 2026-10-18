# Operator notes: 20260809T194641Z

## Condition

`feet_handle_usbc_unplugged`

**Handle unplugged from USB-C** so the handle electrode path could not run.
Barefoot on the platform only. Every 0x10 frame still used b5=0x01/b6=0x21
(word block layout) but all five words were **0**. Weight still decoded
normally. Source jsonl was reconstructed from the live smoke log after disconnect
hung before file flush (`reconstructed_from_live_log` on meas rows).

**EVIDENCE:** weight path does not require the handle. Resistance block presence
bits can be set with zeroed values when the handle is unplugged.

## Decode

- Weight formula unchanged: BE u16 bytes 3–4 / 100 → **78.9 kg** (`0x1ed2`).
- Measurement frames: 33; weight-only: 0; word-block present (b5=0x01,b6=0x21): 33.
- Resistance all-zero blocks: 33; non-zero blocks: 0.
- Last opaque_words: `[0, 0, 0, 0, 0]`.

## Multi-frame note

The scale streams many identical or near-identical 0x10 notifications. The client
**keeps every frame** in `measurements`; it does **not** average and does **not**
yet select a single stable sample as the product weigh-in result.

## Source

Raw log: `captures/handle-unplugged-20260809T194641Z.jsonl` (gitignored). Device address redacted; hash `000000000000`.
