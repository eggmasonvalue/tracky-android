#!/usr/bin/env python3
# Run: /tmp/tracky-ble-capture/bin/python scripts/capture_ble_handshake.py
"""QN Type-2 (FFF0) handshake observer for capture only. Not product runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakClient, BleakScanner

FFF1 = "0000fff1-0000-1000-8000-00805f9b34fb"
FFF2 = "0000fff2-0000-1000-8000-00805f9b34fb"
# QN epoch: seconds since 2000-01-01 UTC
QN_EPOCH_OFFSET = 946684800


def ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def checksum(buf: bytes) -> int:
    return sum(buf) & 0xFF


def log(out, record: dict) -> None:
    line = json.dumps(record, separators=(",", ":"))
    print(line, flush=True)
    if out:
        out.write(line + "\n")
        out.flush()


async def find_scale() -> str:
    print("scanning...", flush=True)
    for _ in range(24):
        devices = await BleakScanner.discover(timeout=5.0, return_adv=True)
        for addr, (d, adv) in devices.items():
            name = d.name or ""
            uuids = [u.lower() for u in (adv.service_uuids or [])]
            print(f" seen {addr} {name!r} {uuids}", flush=True)
            if name == "QN-Scale" or "fff0" in " ".join(uuids) or "ffe0" in " ".join(uuids):
                return addr
    raise SystemExit("scale not found")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--address")
    ap.add_argument("--seconds", type=float, default=90)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--unit", choices=("kg", "lb"), default="kg")
    args = ap.parse_args()

    addr = args.address or await find_scale()
    out = args.out.open("a", encoding="utf-8") if args.out else None
    unit_byte = 0x02 if args.unit == "lb" else 0x01

    state = {
        "protocol_type": None,
        "configured": False,
        "weight_scale": None,
    }

    async with BleakClient(addr) as client:
        log(out, {"timestamp": ts(), "event": "connected", "address": addr})
        # GATT map
        for service in client.services:
            for ch in service.characteristics:
                log(
                    out,
                    {
                        "timestamp": ts(),
                        "event": "gatt_char",
                        "service": service.uuid,
                        "char": ch.uuid,
                        "props": list(ch.properties),
                        "handle": ch.handle,
                    },
                )

        write_char = FFF2
        # verify write char exists
        chars = {c.uuid.lower(): c for s in client.services for c in s.characteristics}
        if write_char not in chars and write_char.lower() not in chars:
            # try resolve
            found = None
            for u, c in chars.items():
                if u.endswith("fff2"):
                    found = c.uuid
            if not found:
                raise SystemExit("FFF2 write characteristic missing")
            write_char = found

        async def on_notify(_sender, data: bytearray) -> None:
            payload = bytes(data)
            rec = {
                "timestamp": ts(),
                "direction": "device->host",
                "uuid": FFF1,
                "hex": payload.hex(),
                "opcode": payload[0] if payload else None,
            }
            log(out, rec)

            if len(payload) < 3:
                return
            if state["protocol_type"] is None:
                state["protocol_type"] = payload[2]
                log(out, {"timestamp": ts(), "event": "protocol_type", "value": state["protocol_type"]})

            op = payload[0]
            ptype = state["protocol_type"] or payload[2]

            if op == 0x12 and not state["configured"]:
                # weight scale factor heuristic from family docs: byte10==1 => /100 else /10
                if len(payload) > 10:
                    state["weight_scale"] = 100.0 if payload[10] == 1 else 10.0
                # unit config 0x13
                cfg = bytearray([0x13, 0x09, ptype, unit_byte, 0x10, 0x00, 0x00, 0x00, 0x00])
                cfg[-1] = checksum(cfg[:-1])
                await client.write_gatt_char(write_char, bytes(cfg), response=False)
                log(out, {"timestamp": ts(), "direction": "host->device", "uuid": write_char, "hex": bytes(cfg).hex(), "name": "unit_config_0x13"})
                # simple time push (family alt form)
                epoch = int(time.time()) - QN_EPOCH_OFFSET
                time_msg = bytearray(
                    [
                        0x02,
                        epoch & 0xFF,
                        (epoch >> 8) & 0xFF,
                        (epoch >> 16) & 0xFF,
                        (epoch >> 24) & 0xFF,
                    ]
                )
                await client.write_gatt_char(write_char, bytes(time_msg), response=False)
                log(out, {"timestamp": ts(), "direction": "host->device", "uuid": write_char, "hex": bytes(time_msg).hex(), "name": "time_push"})
                state["configured"] = True

            elif op == 0x14:
                epoch = int(time.time()) - QN_EPOCH_OFFSET
                msg = bytearray(
                    [
                        0x20,
                        0x08,
                        ptype,
                        epoch & 0xFF,
                        (epoch >> 8) & 0xFF,
                        (epoch >> 16) & 0xFF,
                        (epoch >> 24) & 0xFF,
                        0x00,
                    ]
                )
                msg[-1] = checksum(msg[:-1])
                await client.write_gatt_char(write_char, bytes(msg), response=False)
                log(out, {"timestamp": ts(), "direction": "host->device", "uuid": write_char, "hex": bytes(msg).hex(), "name": "time_sync_0x20"})

            elif op == 0x21:
                msg1 = bytearray([0xA0, 0x0D, 0x04, 0xFE, 0, 0, 0, 0, 0, 0, 0, 0, 0])
                msg1[-1] = checksum(msg1[:-1])
                msg2 = bytearray([0xA0, 0x0D, 0x02, 0x01, 0x00, 0x08, 0x00, 0x21, 0x06, 0xB8, 0x04, 0x02, 0])
                msg2[-1] = checksum(msg2[:-1])
                await client.write_gatt_char(write_char, bytes(msg1), response=False)
                await client.write_gatt_char(write_char, bytes(msg2), response=False)
                log(out, {"timestamp": ts(), "direction": "host->device", "uuid": write_char, "hex": bytes(msg1).hex(), "name": "a0_1"})
                log(out, {"timestamp": ts(), "direction": "host->device", "uuid": write_char, "hex": bytes(msg2).hex(), "name": "a0_2"})

            elif op == 0x10:
                # live weight - dump decoded hypothesis
                if len(payload) >= 11:
                    # variant B: state@4 weight@5-6 r1@7-8 r2@9-10
                    st = payload[4]
                    w_raw = (payload[5] << 8) | payload[6]
                    r1 = (payload[7] << 8) | payload[8]
                    r2 = (payload[9] << 8) | payload[10]
                    scale = state["weight_scale"] or 100.0
                    log(
                        out,
                        {
                            "timestamp": ts(),
                            "event": "weight_hypothesis",
                            "state": st,
                            "weight_raw": w_raw,
                            "weight_div": w_raw / scale,
                            "r1": r1,
                            "r2": r2,
                            "scale": scale,
                        },
                    )

        await client.start_notify(FFF1, on_notify)
        log(out, {"timestamp": ts(), "event": "notify_on", "uuid": FFF1})
        print(f"observing {args.seconds}s — step on scale barefoot + handle", flush=True)
        await asyncio.sleep(args.seconds)
        log(out, {"timestamp": ts(), "event": "done"})


if __name__ == "__main__":
    asyncio.run(main())
