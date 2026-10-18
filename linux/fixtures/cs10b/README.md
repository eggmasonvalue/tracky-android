# CS10B fixtures

Sanitized Linux captures for Tracky `TR-CS10B` / `TS-CS10B` (aliases).
The imported capture directories contain only the truncated placeholder address
hash `000000000000`; no raw BD_ADDR is present. New policy fixtures under
`conditions/` contain no timestamps, addresses, or personal measurements.

| Dir | What |
| --- | --- |
| `20260809T182636Z` | Handshake, unit **lb** (`0x02`); imported weight golden |
| `20260809T191051Z` | Handshake, unit **kg** (`0x01`); imported handle-contact evidence |
| `20260809T194335Z` | Imported handle path with a non-zero five-word block |
| `20260809T194641Z` | Imported unplugged-handle path with a zero five-word block |
| `conditions/handle_contact_complete.json` | Sanitized stable ordered two-packet burst; accepted quality |
| `conditions/foot_only_contact_failed.json` | Sanitized stable zero blocks; contact-failed quality |
| `conditions/foot_only_interrupted.json` | Sanitized irregular incomplete stream; indeterminate quality |

Each imported capture directory retains its source `session.json`,
`expected_decode.json`, and `notes.md`. Weight: BE u16 at bytes 3–4 / 100 → kg
(high confidence). Five-word blocks are structured, opaque, and unitless;
streams retain every 0x10 frame without averaging. The complete-burst fixture
also records the exact ACK payload used by tests; notification RX order alone is
not treated as ACK evidence.
