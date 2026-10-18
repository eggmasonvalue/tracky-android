# Linux-to-consumer observation contract

**Status: version 1 is implemented by the Linux canonical store, on-demand MCP projection, authenticated sync API, and Android Health Connect bridge.**

This is the versioned, read-only observation boundary for MCP and Android. Linux is
canonical. Android is a consumer and keeps only a minimal import ledger; it is not a
backup. No user profile or profile attributes cross from Android to Linux.

## Envelope

Every page and observation uses a declared `contract_version` and contains:

- `session_id`: canonical, immutable, Linux-issued opaque ID. It is stable across
  retries, pages, MCP reads, and Android imports.
- `raw_frames`: an immutable evidence reference. Metadata responses use an O(1)
  `{resource_uri, count}` descriptor; explicit evidence responses retain ordered
  frame references and full frame bodies.
- `selected`: optional measurement/burst selection, present only when the explicit,
  versioned `selection_policy_version` permits selection from the referenced frames.
- `versions`: `transport_version`, optional singular `decoder_version`,
  `decoder_versions`, `selection_policy_version`, and `quality_version`. The
  singular field is null when one session contains mixed decoder versions; the
  distinct-version list remains authoritative.
- `quality`: exactly one of `accepted`, `contact_failed`, or `indeterminate`, as
  defined by `quality_version`. It must not be inferred solely from nonzero values.
- `opaque_block_a` and `opaque_block_b`: two opaque blocks, each exactly five words,
  exposed together only when `BurstAssembler` can assemble a wire-valid ordered pair.
  Consumers must preserve and round-trip them without parsing, matching, or assigning
  meaning.

A selected weight, when present, is structured as `raw`, `divisor`, `unit`, and
`provenance`. Weight-selection policy version 1 selects the latest frame in a run
of three repeated, positive, wire-valid display-weight observations and persists
that frame reference before projection. `raw` and `divisor` are source values;
`unit` is a declared, versioned unit identifier; `provenance` identifies the
decoder/selection lineage. No consumer may manufacture, relabel, or convert these
fields. Unsupported impedance labels or units are not part of this contract.

## Linux MCP projection

The deployed MCP process is launched on demand over stdio and opens the canonical
SQLite store read-only by behavior. It does not construct an acquisition service,
run operation recovery, scan, connect, acquire, or mutate records. Its bounded tool
surface is exactly:

- `list_sessions(limit, cursor)`: bounded newest-first session summaries and
  aggregate frame counts, returning an opaque `next_cursor` when more rows exist;
- `get_latest_session()`: metadata for the newest session;
- `get_session(session_id)`: metadata for one session;
- `get_session_evidence(session_id)`: the complete ordered wire-evidence stream.

The canonical resources are `tracky://sessions/{session_id}` for metadata and
`tracky://sessions/{session_id}/frames` for evidence. The two session tools are
tool equivalents for clients with weak resource support. Summary queries use SQL
counts and metadata and do not materialize raw frame streams; metadata returns an
O(1) evidence resource URI/count descriptor. The evidence tool and frame resource
are the explicit full-stream reads.

`list_sessions` orders by `(started_at_utc DESC, session_id DESC)` and uses a
keyset cursor, so equal timestamps are neither skipped nor repeated. Clients pass
`next_cursor` back unchanged and never decode or construct it. Successful tool
responses carry `ok: true`; read failures carry `ok: false` and an `error` object
with stable `code`, `message`, and optional `session_id`. Invalid cursors return
`invalid_cursor`. Empty history returns `no_sessions` from `get_latest_session`;
missing IDs return `session_not_found` from the session tools and matching
resources.

Session metadata and evidence success responses declare `contract_version: 1`,
expose the canonical `session_id`, `raw_frames`, optional `selected` data,
`versions`, exact `quality`/`quality_version`, and `opaque_block_a`/
`opaque_block_b` when a wire-valid ordered burst pair was assembled. A session
`status` is lifecycle state and is independent of `quality`. The summary also
retains `id` as a compatibility alias for `session_id`.

## Read and pagination

MCP and Android reads are read-only observations of the Linux canonical store.
Pages carry an opaque `next_cursor`. A cursor is monotonic for its stream, must be
returned unchanged, and must not be decoded or constructed by consumers. Empty
pages still advance only according to the server's cursor rules.

## Acknowledgement and Android import

Acknowledgement means only that the consumer durably received and validated the
specified immutable `session_id` and page/item identity. It does not mutate Linux,
confirm measurement validity, or authorize deletion. Acknowledgements are safe to
retry and are separate from pagination.

The Android HTTP adapter consumes the authenticated `GET
/api/v1/sessions/unsynced` projection. Its response declares `contract_version`,
contains `sessions`, and returns the opaque cursor as `next_cursor`. A retryable
`source_state` returns no sessions or cursor advancement, including while an
acquisition session remains open. Each session has the common
identity/status/timestamp/quality fields and may contain a Linux-selected source
weight in this shape:

```json
{
  "selected": {
    "frame_sequence": 12,
    "weight": {
      "raw": 7890,
      "divisor": 100,
      "unit": "kg",
      "provenance": "..."
    }
  }
}
```

Android imports only a completed session with a validated selected weight whose
unit is the declared `kg`. It does not infer a value from raw frames, opaque words,
`weight_kg` compatibility fields, or any body-composition field. The endpoint must
be reached through HTTPS and bearer authentication; the Android app ships neither a
host-specific endpoint nor a token.

Android imports are idempotent using the Health Connect
`clientRecordId` + `clientRecordVersion` pair. The pair is the import key: repeating
an identical pair is a no-op; a newer version may replace the Android projection
according to the versioned import policy; an older version must not overwrite it.
The ledger stores only the minimum pair, source session reference, disposition
(`pending`, `imported`, or `quarantined`), retry/error state, Health Connect record
ID, and contract/derivation version metadata required for deduplication and audit.
A separate singleton state row holds the opaque page cursor. Android commits that
cursor only after every item in the page is imported or durably quarantined; a
network, permission, timeout, or Health Connect write failure leaves it unchanged.
It stores no Linux raw evidence, opaque word blocks, profile values, or backup data.

The current Android projection writes only `WeightRecord` and sets
`derivation_version` to null. The QN SDK-derived channel map and impedance scaling
are established, but prior work selected only a model structure—not a complete
published equation with compatible, source-backed coefficients. Until such an
algorithm is selected and versioned, Android reads (but never writes) the latest
applicable `HeightRecord`, requests no other profile inputs, and emits no derived
records. Once added, Android must collect only the algorithm's required
non-Health-Connect inputs and write every resulting metric that Health Connect
supports.
