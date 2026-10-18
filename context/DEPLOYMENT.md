# Tracky deployment target

This is the target deployment design, not a readiness claim. Run `todo list` for current implementation gaps.

## Linux host

### Account and state

- Create a dedicated system user and group named `tracky`; do not run acquisition as root.
- Install the Linux package and its BLE dependencies into a controlled system virtual environment or equivalent immutable install.
- Use a system-level unit with `User=tracky`, `Group=tracky`, and `StateDirectory=tracky`. The resulting state directory is `/var/lib/tracky`, owned by the service account.
- Start the daemon with an explicit database path such as `/var/lib/tracky/tracky.sqlite3`; do not rely on `HOME`, XDG defaults, or a developer checkout.
- Grant only the Bluetooth permissions/device access required by BlueZ. Keep `ProtectSystem=strict`, `NoNewPrivileges=true`, a read-only home, and a narrow `ReadWritePaths=/var/lib/tracky` where compatible with the final package.
- Run one always-on daemon instance under `multi-user.target`, ordered after Bluetooth, with `Restart=always` and bounded stop/restart timeouts. The daemon owns scanning, connection attempts, acquisition cancellation, and raw-frame writes.
- Back up `/var/lib/tracky` while preserving SQLite consistency; define retention and restore procedures before production use.

The current `linux/systemd/tracky.service` is not this target: it has no dedicated user or state directory and does not pass the target database path.

### Sync API

The sync API is a separate, narrowly scoped read path over the daemon's SQLite state. It must not start BLE scanning or compete for acquisition ownership.

- Bind only to the interface/transport required by the Android client, preferably a private trusted transport or loopback behind a controlled proxy; never expose the default all-interface listener without an access policy.
- Require authentication for every data endpoint. Store the bearer secret in a root-readable, service-readable secret file or equivalent secret manager; never put it in unit command lines, source, logs, or documentation.
- Use TLS, or an explicitly trusted private tunnel whose encryption and peer authorization are managed outside this process. Restrict firewall ingress to the intended client path.
- Remove wildcard CORS and avoid returning raw exception details. Set request, response-size, and rate limits; log security-relevant failures without logging tokens, addresses, or raw measurements.
- Define whether health is public; the safer default is to authenticate it as well. Return only completed, sync-eligible sessions and use an idempotent cursor that cannot skip equal-time records.
- Run the API under the dedicated service account with only the state-directory access it needs. Prefer a read-only database connection or a separate read-only export/snapshot once the concurrency strategy is chosen.

The checked-in sync server now requires bearer authentication, defaults to loopback, opens SQLite read-only, supports direct TLS or explicit loopback-only external TLS termination, and uses opaque keyset cursors. Deployment still requires provisioning the certificate or trusted proxy, token file, firewall policy, rate limiting at the proxy, and end-to-end verification.

## MCP

- Do not install MCP as a permanently running system daemon.
- Launch it on demand through the local MCP host using stdio, with the same approved state/read path and no BLE ownership.
- Expose only the bounded read-only session history tools `list_sessions`, `get_latest_session`, `get_session`, and `get_session_evidence`, plus canonical session/frame resources. The MCP process does not instantiate acquisition or perform operation recovery.
- Keep the MCP process account and filesystem access least-privileged. It must not receive sync tokens or write access unless a separately reviewed administrative mode is introduced.

The checked-in MCP implementation now matches this on-demand read-only profile; deployment still requires least-privilege filesystem and process setup.

## Android setup

1. Install the Android bridge with a compatible Health Connect provider. Configure the authenticated sync endpoint and secret through the onboarding flow; ship no environment-specific endpoint or plaintext production token.
2. Through onboarding, grant read access to height and historical health data, plus write access only to approved output records. Tracky reads the latest applicable `HeightRecord` and never writes height.
3. Collect required profile inputs that Health Connect does not provide. Store no fabricated defaults and permit later correction.
4. Enable WorkManager with network constraints, retry/backoff, request timeouts, and idempotency. Advance a cursor only after every eligible record has a durable success or quarantine disposition.
5. Keep only the minimum import ledger on Android. Use stable `clientRecordId` and `clientRecordVersion` metadata for Health Connect upserts.
6. Expose onboarding, permission rationale, and actionable diagnostics without an ordinary launcher entry.
7. Test the complete path: daemon capture to SQLite, authenticated API retrieval, Android validation and retry behavior, Health Connect permission handling, and duplicate/replay safety.

The checked-in Android application now has no Bluetooth permission, feature, transport, scale protocol, evidence store, or ordinary launcher entry. It still requires endpoint/TLS deployment and connected-device Health Connect validation before release.

## Go-live gate

Deployment is not ready until the dedicated-user unit is installed and restart-tested, the database is confirmed at `/var/lib/tracky`, BLE scanning is verified under the service account, the sync API is authenticated and transport-protected, MCP is read-only/on-demand, and Android WorkManager plus Health Connect have completed a real end-to-end validation. No host-specific addresses, credentials, or private device identifiers belong in this document.
