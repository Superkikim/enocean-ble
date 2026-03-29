#!/usr/bin/env python3

import asyncio
import platform
from bleak import BleakScanner

TARGET_MAC = "E2:15:00:03:C6:D7"
ENOCEAN_MFR_ID = 0x03DA
IS_MACOS = platform.system() == "Darwin"

def decode_status(status: int) -> tuple[str, list[str]]:
    event = "press" if (status & 0x01) else "release"
    buttons = []
    for bit, name in [(0x02,"A0"),(0x04,"A1"),(0x08,"B0"),(0x10,"B1")]:
        if status & bit:
            buttons.append(name)
    return event, buttons

def callback(device, adv):
    data = adv.manufacturer_data.get(ENOCEAN_MFR_ID)
    if not data or len(data) < 9:
        return
    # On macOS, CoreBluetooth hides MAC addresses — filter by manufacturer ID only
    if not IS_MACOS and device.address.upper() != TARGET_MAC:
        return
    seq = int.from_bytes(data[0:4], "little")
    status = data[4]
    mic = data[5:9].hex()
    event, buttons = decode_status(status)
    print(f"addr={device.address}  seq={seq:6d}  {event:8s}  buttons={buttons}  rssi={adv.rssi}  mic={mic}")

async def main():
    target = "any EnOcean device" if IS_MACOS else TARGET_MAC
    print(f"Listening for {target}  (platform={platform.system()})...")
    scanner = BleakScanner(callback)
    await scanner.start()
    await asyncio.sleep(60)
    await scanner.stop()

asyncio.run(main())
