-- Tracky schema revision 3 fixture.  The test inserts only sanitized values.
CREATE TABLE known_devices (
    id TEXT PRIMARY KEY,
    connection_target TEXT NOT NULL,
    connection_key TEXT NOT NULL UNIQUE,
    address_hash TEXT NOT NULL,
    advertised_name TEXT,
    alias TEXT,
    model_label TEXT,
    first_seen_at_utc TEXT NOT NULL,
    last_seen_at_utc TEXT NOT NULL,
    advertised_service_uuids_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    CHECK (last_seen_at_utc >= first_seen_at_utc)
) STRICT;

CREATE TABLE measurement_sessions (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('open', 'complete', 'aborted')),
    started_at_utc TEXT NOT NULL,
    ended_at_utc TEXT,
    display_timezone TEXT NOT NULL,
    device_alias TEXT,
    model_label TEXT,
    address_hash TEXT,
    requested_unit TEXT,
    condition TEXT,
    capture_id TEXT UNIQUE,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    selected_frame_sequence INTEGER,
    CHECK (ended_at_utc IS NULL OR ended_at_utc >= started_at_utc),
    FOREIGN KEY (id, selected_frame_sequence)
        REFERENCES frames(session_id, sequence)
) STRICT;

CREATE TABLE acquisition_operations (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'running', 'complete', 'failed', 'cancelled')
    ),
    created_at_utc TEXT NOT NULL,
    started_at_utc TEXT,
    finished_at_utc TEXT,
    session_id TEXT REFERENCES measurement_sessions(id) ON DELETE RESTRICT,
    error_code TEXT,
    error_message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    CHECK (started_at_utc IS NULL OR started_at_utc >= created_at_utc),
    CHECK (finished_at_utc IS NULL OR finished_at_utc >= created_at_utc),
    CHECK (
        (status IN ('pending', 'running') AND finished_at_utc IS NULL)
        OR (status IN ('complete', 'failed', 'cancelled') AND finished_at_utc IS NOT NULL)
    ),
    CHECK (
        (status IN ('failed', 'cancelled'))
        OR (error_code IS NULL AND error_message IS NULL)
    )
) STRICT;

CREATE TABLE frames (
    session_id TEXT NOT NULL REFERENCES measurement_sessions(id) ON DELETE RESTRICT,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    observed_at_utc TEXT,
    elapsed_ms INTEGER CHECK (elapsed_ms IS NULL OR elapsed_ms >= 0),
    direction TEXT NOT NULL CHECK (direction IN ('rx', 'tx')),
    characteristic_uuid TEXT,
    raw BLOB NOT NULL,
    opcode INTEGER CHECK (opcode IS NULL OR opcode BETWEEN 0 AND 255),
    frame_kind TEXT NOT NULL,
    checksum_valid INTEGER CHECK (checksum_valid IS NULL OR checksum_valid IN (0, 1)),
    decoder_id TEXT NOT NULL,
    decoder_version INTEGER NOT NULL CHECK (decoder_version >= 1),
    decoded_fields_json TEXT NOT NULL DEFAULT '{}',
    decode_error TEXT,
    PRIMARY KEY (session_id, sequence)
) STRICT;

CREATE TABLE measurement_frames (
    session_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    protocol_type INTEGER NOT NULL CHECK (protocol_type BETWEEN 0 AND 255),
    weight_raw_u16_be INTEGER NOT NULL CHECK (weight_raw_u16_be BETWEEN 0 AND 65535),
    weight_scale_divisor INTEGER NOT NULL CHECK (weight_scale_divisor > 0),
    weight_unit TEXT NOT NULL,
    weight_formula TEXT NOT NULL,
    weight_provenance TEXT NOT NULL,
    b5 INTEGER NOT NULL CHECK (b5 BETWEEN 0 AND 255),
    b6 INTEGER NOT NULL CHECK (b6 BETWEEN 0 AND 255),
    resistance_layout TEXT,
    resistance_unit TEXT,
    resistance_provenance TEXT NOT NULL,
    PRIMARY KEY (session_id, sequence),
    FOREIGN KEY (session_id, sequence)
        REFERENCES frames(session_id, sequence) ON DELETE RESTRICT
) STRICT;

CREATE TABLE resistance_values (
    session_id TEXT NOT NULL,
    frame_sequence INTEGER NOT NULL,
    value_index INTEGER NOT NULL CHECK (value_index >= 0),
    raw_value INTEGER NOT NULL CHECK (raw_value BETWEEN 0 AND 65535),
    PRIMARY KEY (session_id, frame_sequence, value_index),
    FOREIGN KEY (session_id, frame_sequence)
        REFERENCES measurement_frames(session_id, sequence) ON DELETE RESTRICT
) STRICT;

CREATE INDEX devices_last_seen_idx ON known_devices(last_seen_at_utc DESC);
CREATE INDEX frames_opcode_idx ON frames(opcode);
CREATE INDEX sessions_started_at_idx ON measurement_sessions(started_at_utc DESC);
CREATE INDEX operations_created_at_idx ON acquisition_operations(created_at_utc DESC);
CREATE INDEX operations_status_idx ON acquisition_operations(status);
CREATE INDEX measurement_weight_raw_idx
    ON measurement_frames(weight_raw_u16_be, weight_scale_divisor);
