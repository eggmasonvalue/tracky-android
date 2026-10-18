#!/usr/bin/env python3
# Run with: /tmp/tracky-ble-capture/bin/python scripts/capture_ble_observe.py
"""Observe a BLE device's GATT layout and notifications without decoding them."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bleak import BleakClient, BleakScanner

TARGET_NAME = "QN-Scale"


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def characteristic_label(characteristic: Any) -> str:
    return f"handle={characteristic.handle} uuid={characteristic.uuid}"


async def find_address() -> str:
    print("Scanning for BLE devices...")
    devices = await BleakScanner.discover()
    for device in devices:
        print(f"  {device.address}\t{device.name or '(unnamed)'}")

    matches = [device for device in devices if (device.name or "") == TARGET_NAME]
    if len(matches) == 1:
        return matches[0].address
    if len(matches) > 1:
        raise RuntimeError(f"Found multiple {TARGET_NAME} devices; pass --address.")
    raise RuntimeError("No QN-Scale found; pass --address to observe a discovered device.")


async def observe(address: str, seconds: float, out_path: Path | None) -> None:
    output = out_path.open("a", encoding="utf-8") if out_path else None
    try:
        async with BleakClient(address) as client:
            print(f"Connected: {address}")
            print("GATT services:")
            notify_characteristics: list[Any] = []
            for service in client.services:
                print(f"Service handle={service.handle} uuid={service.uuid}")
                for characteristic in service.characteristics:
                    properties = ",".join(characteristic.properties)
                    print(f"  Characteristic {characteristic_label(characteristic)} properties={properties}")
                    for descriptor in characteristic.descriptors:
                        print(f"    Descriptor handle={descriptor.handle} uuid={descriptor.uuid}")
                    if "notify" in characteristic.properties or "indicate" in characteristic.properties:
                        notify_characteristics.append(characteristic)

            def on_notification(sender: Any, data: bytearray) -> None:
                payload = bytes(data)
                sender_uuid = getattr(sender, "uuid", str(sender))
                record = {
                    "timestamp": timestamp(),
                    "direction": "device->host",
                    "uuid": sender_uuid,
                    "hex": payload.hex(),
                }
                if payload:
                    record["opcode_first_byte"] = payload[0]
                line = json.dumps(record, separators=(",", ":"))
                print(">> " + line)
                if output:
                    output.write(line + "\n")
                    output.flush()

            for characteristic in notify_characteristics:
                print(f"Subscribing: {characteristic_label(characteristic)}")
                await client.start_notify(characteristic, on_notification)

            print(f"Observing for {seconds:g}s; press Ctrl-C to stop.")
            try:
                await asyncio.wait_for(asyncio.Event().wait(), timeout=seconds)
            except asyncio.TimeoutError:
                pass
            finally:
                for characteristic in notify_characteristics:
                    try:
                        await client.stop_notify(characteristic)
                    except Exception as exc:  # Best effort while disconnecting.
                        print(f"Warning: could not unsubscribe {characteristic.uuid}: {exc}")
    finally:
        if output:
            output.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", help="BLE address/identifier; scan and select QN-Scale if omitted")
    parser.add_argument("--seconds", type=float, default=30.0, help="observation duration (default: 30)")
    parser.add_argument("--out", type=Path, help="append notification JSONL records to this path")
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    return args


async def main() -> None:
    args = parse_args()
    address = args.address or await find_address()
    await observe(address, args.seconds, args.out)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user; disconnected.")
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
