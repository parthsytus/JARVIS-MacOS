import asyncio
import subprocess
import json
import re
from rapidfuzz import process, fuzz
from bleak import BleakScanner


def _blueutil(args):
    """Run blueutil and return parsed JSON, or [] on failure."""
    try:
        result = subprocess.run(
            ['blueutil'] + args,
            capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[Bluetooth] blueutil error: {e}")
    return []


def get_paired_devices():
    """List paired Bluetooth devices using blueutil."""
    print("\n--- Listing Paired Bluetooth Devices ---")
    import time
    start = time.time()
    devices = _blueutil(['--paired', '--format', 'json'])
    result = [
        {'name': d.get('name', 'Unknown'), 'address': d.get('address', 'Unknown')}
        for d in devices
    ]
    if result:
        for d in result:
            print(f" - {d['name']} [{d['address']}]")
    else:
        print("No paired devices found.")
    print(f"[Time taken: {(time.time() - start) * 1000:.2f} ms]")
    return result


def get_connected_devices():
    """List actively connected Bluetooth devices using blueutil."""
    print("\n--- Listing Connected Bluetooth Devices ---")
    import time
    start = time.time()
    devices = _blueutil(['--connected', '--format', 'json'])
    result = [
        {'name': d.get('name', 'Unknown'), 'address': d.get('address', 'Unknown')}
        for d in devices
    ]
    if result:
        for d in result:
            print(f" - {d['name']} [{d['address']}]")
    else:
        print("No devices currently connected.")
    print(f"[Time taken: {(time.time() - start) * 1000:.2f} ms]")
    return result


async def disconnect_device(name, paired_devices):
    """Disconnect a device by name (fuzzy matched) using blueutil."""
    import time
    print(f"\n--- Attempting to disconnect '{name}' ---")
    start = time.time()
    paired_names = [d['name'] for d in paired_devices]
    best = process.extractOne(name, paired_names, scorer=fuzz.partial_ratio) \
        if paired_names else None

    if best and best[1] >= 60:
        matched = next(d for d in paired_devices if d['name'] == best[0])
        addr = matched['address']
        if addr != 'Unknown':
            result = subprocess.run(
                ['blueutil', '--disconnect', addr],
                capture_output=True
            )
            if result.returncode == 0:
                print(f"Successfully disconnected {matched['name']}.")
            else:
                print(f"Failed to disconnect {matched['name']}.")
        else:
            print("Cannot disconnect — MAC address unknown.")
    else:
        print(f"Could not find '{name}' in paired devices.")
    print(f"[Time taken: {(time.time() - start) * 1000:.2f} ms]")


async def scan_nearby_devices(filter_keyword=None):
    """Scan for nearby BLE devices using bleak (8 second scan)."""
    import time
    print("\n--- Scanning for nearby Bluetooth devices (BLE) ---")
    start = time.time()
    try:
        raw = await BleakScanner.discover(timeout=8.0)
        found = []
        for d in raw:
            name = d.name or 'Unknown'
            addr = d.address
            if filter_keyword:
                kw = filter_keyword.lower()
                if kw not in name.lower() and fuzz.partial_ratio(kw, name.lower()) < 70:
                    continue
            print(f" - {name} [{addr}]")
            found.append({'name': name, 'address': addr, 'is_ble': True})
        if not found:
            print("No devices found nearby.")
        print(f"[Time taken: {(time.time() - start) * 1000:.2f} ms]")
        return found
    except Exception as e:
        print(f"Error scanning: {e}")
        return []


async def connect_to_device(name, paired_devices, scanned_devices):
    """Connect to a device. Paired devices use blueutil. New devices require
    Mac system UI for pairing — JARVIS initiates and informs the user."""
    import time
    print(f"\n--- Attempting to connect to '{name}' ---")
    start = time.time()

    paired_names = [d['name'] for d in paired_devices]
    best_paired = process.extractOne(name, paired_names, scorer=fuzz.partial_ratio) \
        if paired_names else None

    if best_paired and best_paired[1] >= 60:
        matched = next(d for d in paired_devices if d['name'] == best_paired[0])
        addr = matched['address']
        print(f"Fuzzy matched '{name}' to PAIRED device '{matched['name']}'")
        if addr != 'Unknown':
            result = subprocess.run(
                ['blueutil', '--connect', addr],
                capture_output=True
            )
            if result.returncode == 0:
                print(f"Successfully connected to {matched['name']}.")
            else:
                print(f"Connection attempt finished. Status: {result.returncode}")
        else:
            print("Cannot connect — MAC address unknown.")
    else:
        # New device — Mac requires user confirmation in system UI
        scanned_names = [d['name'] for d in scanned_devices]
        best_scanned = process.extractOne(name, scanned_names, scorer=fuzz.partial_ratio) \
            if scanned_names else None
        if best_scanned and best_scanned[1] >= 60:
            matched = next(d for d in scanned_devices if d['name'] == best_scanned[0])
            addr = matched['address']
            print(f"Initiating pairing with new device '{matched['name']}'...")
            print("NOTE: macOS requires confirmation in the system pairing dialog.")
            subprocess.run(['blueutil', '--pair', addr], capture_output=True)
            print("Pairing request sent. Accept the dialog on your Mac if prompted.")
        else:
            print(f"Could not find '{name}' in paired or scanned devices.")

    print(f"[Time taken: {(time.time() - start) * 1000:.2f} ms]")


async def main():
    print("========================================")
    print("    Bluetooth Control Test Program")
    print("========================================")
    
    # List paired devices on startup
    paired_devices = get_paired_devices()
    
    # Scan for nearby devices
    scanned_devices = await scan_nearby_devices()
    
    print("\n----------------------------------------")
    print("Testing Commands:")
    print("- Type 'scan' to scan for nearby devices again")
    print("- Type 'paired' to list paired devices again")
    print("- Type a device name to connect (fuzzy match)")
    print("- Type 'disconnect <name>' to disconnect")
    print("- Type 'exit' to stop")
    print("----------------------------------------")
    
    while True:
        try:
            cmd = await asyncio.get_event_loop().run_in_executor(None, input, "\nTest Command > ")
            if cmd.lower() in ['exit', 'quit']:
                break
            elif cmd.lower() == 'scan':
                scanned_devices = await scan_nearby_devices()
            elif cmd.lower() == 'paired':
                paired_devices = get_paired_devices()
            elif cmd.lower().startswith('disconnect '):
                await disconnect_device(cmd[11:].strip(), paired_devices)
                paired_devices = get_paired_devices() # Refresh
            elif cmd.strip():
                await connect_to_device(cmd.strip(), paired_devices, scanned_devices)
                paired_devices = get_paired_devices() # Refresh after potential new pairing
        except KeyboardInterrupt:
            break

if __name__ == "__main__":
    asyncio.run(main())
