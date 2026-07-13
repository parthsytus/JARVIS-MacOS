import asyncio
import subprocess
import json
import time
from rapidfuzz import process, fuzz
from bleak import BleakScanner
from AppKit import NSWorkspace


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


def phonetic_code(name):
    """Return a phonetic digit representation of a string for sound-alike matching."""
    name = "".join([c for c in name.lower() if c.isalpha()])
    if not name:
        return ""
    
    mapping = {
        'b': '1', 'f': '1', 'p': '1', 'v': '1',
        'c': '2', 'g': '2', 'j': '2', 'k': '2', 'q': '2', 's': '2', 'x': '2', 'z': '2',
        'd': '3', 't': '3',
        'l': '4',
        'm': '5', 'n': '5',
        'r': '6'
    }
    
    code = ""
    prev_val = ""
    for char in name:
        val = mapping.get(char, '')
        if val:
            if val != prev_val:
                code += val
                prev_val = val
        else:
            if char not in ['h', 'w', 'y']:
                prev_val = ''
                
    return code[:4].ljust(4, '0')


def find_best_device_match(input_name, device_list):
    """Finds the best matching device from device_list (dicts with 'name') for input_name.
    Matches against full device names AND individual words of device names using both
    fuzz.ratio and fuzz.partial_ratio, boosted by phonetic similarity.
    Returns: (best_matched_device_dict, score) or (None, 0)"""
    best_device = None
    best_score = 0
    
    input_name_lower = input_name.lower().strip()
    input_code = phonetic_code(input_name_lower)
    
    for d in device_list:
        dev_name = d.get('name', 'Unknown')
        dev_name_lower = dev_name.lower().strip()
        dev_words = dev_name_lower.split()
        
        # 1. Full string match ratio
        score_full = fuzz.ratio(input_name_lower, dev_name_lower)
        score_partial = fuzz.partial_ratio(input_name_lower, dev_name_lower)
        
        # 2. Word-by-word match (skip very short words to prevent false positives like 'M51' matching '17')
        word_scores = []
        for word in dev_words:
            if len(word) <= 2:
                continue
            word_scores.append(fuzz.ratio(input_name_lower, word))
            # Only use partial_ratio on longer words to avoid artificially high scores
            if len(word) >= 4:
                word_scores.append(fuzz.partial_ratio(input_name_lower, word))
            
        max_word_score = max(word_scores) if word_scores else 0
        device_best = max(score_full, score_partial, max_word_score)
        
        # 3. Phonetic matching boost
        phonetic_match = False
        if len(input_name_lower) >= 3:
            # Check full-to-full phonetic match
            if input_code == phonetic_code(dev_name_lower):
                phonetic_match = True
            else:
                # Check word-level phonetic match
                input_words = input_name_lower.split()
                for in_word in input_words:
                    if len(in_word) >= 3:
                        in_code = phonetic_code(in_word)
                        for dev_word in dev_words:
                            if len(dev_word) >= 3 and in_code == phonetic_code(dev_word):
                                phonetic_match = True
                                break
                    if phonetic_match:
                        break
        
        if phonetic_match:
            # Boost the score if there is a reasonable baseline similarity (to prevent false collisions)
            # Raised from 30 to 45 to reduce false positives on short/dissimilar names
            if device_best >= 45:
                device_best = max(device_best, 95)
        
        if device_best > best_score:
            best_score = device_best
            best_device = d
            
    return best_device, best_score


async def disconnect_device(name, paired_devices=None):
    """Disconnect a device by name (fuzzy matched against connected devices) using blueutil.
    Returns: (success_bool, message_str)"""
    import time
    print(f"\n--- Attempting to disconnect '{name}' ---")
    start = time.time()
    
    connected_devices = get_connected_devices()
    best_device, score = find_best_device_match(name, connected_devices)

    success = False
    message = ""

    if best_device and score >= 60:
        addr = best_device['address']
        matched_name = best_device['name']
        print(f"Fuzzy matched '{name}' to CONNECTED device '{matched_name}' (score: {score:.1f})")
        if addr != 'Unknown':
            result = subprocess.run(
                ['blueutil', '--disconnect', addr],
                capture_output=True
            )
            if result.returncode == 0:
                print(f"Successfully disconnected {matched_name}.")
                success = True
                message = f"Successfully disconnected '{matched_name}'."
                # Add note about macOS auto-reconnect behavior for BLE HID devices
                is_ble = len(addr) > 17 or "mouse" in matched_name.lower() or "keyboard" in matched_name.lower() or "toad" in matched_name.lower()
                if is_ble:
                    note = " Note: macOS automatically reconnects paired BLE HID devices immediately if they are active/moving. Turn off the device manually to keep it disconnected."
                    print("NOTE:" + note)
                    message += note
            else:
                print(f"Failed to disconnect {matched_name}.")
                message = f"Failed to disconnect '{matched_name}' (status code: {result.returncode})."
        else:
            print("Cannot disconnect — MAC address unknown.")
            message = f"Cannot disconnect '{matched_name}' because its MAC address is unknown."
    else:
        print(f"Could not find '{name}' in actively connected devices.")
        message = f"Could not find '{name}' in actively connected devices."

    print(f"[Time taken: {(time.time() - start) * 1000:.2f} ms]")
    return success, message


async def scan_classic_devices():
    """Scan for classic bluetooth devices using blueutil --inquiry."""
    try:
        proc = await asyncio.create_subprocess_exec(
            'blueutil', '--inquiry', '6', '--format', 'json',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0 and stdout:
            return json.loads(stdout.decode())
    except Exception as e:
        print(f"[Bluetooth] Classic scan error: {e}")
    return []


async def scan_nearby_devices(filter_keyword=None):
    """Scan for nearby Classic and BLE Bluetooth devices (6 second scan)."""
    import time
    print("\n--- Scanning for nearby Bluetooth devices (Classic + BLE) ---")
    start = time.time()
    
    # Run scans concurrently
    ble_task = BleakScanner.discover(timeout=6.0)
    classic_task = scan_classic_devices()
    
    ble_raw, classic_raw = await asyncio.gather(ble_task, classic_task, return_exceptions=True)
    
    if isinstance(ble_raw, Exception):
        print(f"BLE Scan failed: {ble_raw}")
        ble_raw = []
    if isinstance(classic_raw, Exception):
        print(f"Classic Scan failed: {classic_raw}")
        classic_raw = []
        
    found = {}
    
    # Add classic devices first
    for d in classic_raw:
        name = d.get('name', 'Unknown')
        addr = d.get('address', 'Unknown')
        if name == 'Unknown' or not addr or addr == 'Unknown':
            continue
        # Normalize MAC address to standard format xx:xx:xx:xx:xx:xx for deduplication
        norm_addr = addr.lower().replace('-', ':')
        
        if filter_keyword:
            kw = filter_keyword.lower()
            if kw not in name.lower() and fuzz.partial_ratio(kw, name.lower()) < 70:
                continue
                
        found[norm_addr] = {'name': name, 'address': addr, 'is_ble': False}
        
    # Add BLE devices
    for d in ble_raw:
        name = d.name or 'Unknown'
        addr = d.address
        if not addr:
            continue
        norm_addr = addr.lower().replace('-', ':')
        
        if filter_keyword:
            kw = filter_keyword.lower()
            if kw not in name.lower() and fuzz.partial_ratio(kw, name.lower()) < 70:
                continue
                
        # If device already found in classic scan, keep classic profile
        if norm_addr not in found:
            found[norm_addr] = {'name': name, 'address': addr, 'is_ble': True}
            
    result = list(found.values())
    
    for d in result:
        device_type = "BLE" if d['is_ble'] else "Classic"
        print(f" - {d['name']} [{d['address']}] ({device_type})")
        
    if not result:
        print("No devices found nearby.")
        
    print(f"[Time taken: {(time.time() - start) * 1000:.2f} ms]")
    return result


def _find_in_iobt_paired(device_name):
    """Check IOBluetooth's paired devices for a device by name (fuzzy match).
    
    IOBluetooth.pairedDevices() sees devices that blueutil --paired sometimes misses.
    Returns the MAC address string if found, or None.
    """
    try:
        from IOBluetooth import IOBluetoothDevice
        paired = IOBluetoothDevice.pairedDevices()
        if not paired:
            return None

        # Build a list of dicts for find_best_device_match
        iobt_devices = []
        for dev in paired:
            name = dev.name()
            addr = dev.addressString()
            if name and addr:
                iobt_devices.append({'name': name, 'address': addr})

        if not iobt_devices:
            return None

        best, score = find_best_device_match(device_name, iobt_devices)
        if best and score >= 90:
            return best['address']
        return None
    except Exception as e:
        print(f"[Bluetooth] IOBluetooth paired lookup error: {e}")
        return None


async def connect_to_device(name, paired_devices, scanned_devices):
    """Connect to a device using IOBluetoothDevice for silent connections.
    
    Paired devices connect silently via IOBluetoothDevice.openConnection() — 
    no popup, no Accessibility permissions needed.
    
    New (unpaired) devices: pair via blueutil first (macOS enforces the security
    dialog for first-time pairing — this is an OS-level security requirement that
    cannot be bypassed by any API), then connect silently via IOBluetooth.
    
    Returns: (success_bool, message_str)
    """
    print(f"\n--- Attempting to connect to '{name}' ---")
    start = time.time()

    if paired_devices is None:
        paired_devices = get_paired_devices()

    best_paired, score_paired = find_best_device_match(name, paired_devices)

    # Also check scanned devices (passed from fast_lane cache or fresh scan)
    if not scanned_devices:
        print(f"Device '{name}' not in paired list and no scan results available. Running a quick scan...")
        scanned_devices = await scan_nearby_devices(filter_keyword=name)

    best_scanned, score_scanned = find_best_device_match(name, scanned_devices)

    # Pick the better match (higher score) — threshold raised to 75
    THRESHOLD = 75
    use_paired = best_paired and score_paired >= THRESHOLD
    use_scanned = best_scanned and score_scanned >= THRESHOLD

    if not use_paired and not use_scanned:
        print(f"Could not find '{name}' in paired or scanned devices (threshold={THRESHOLD}).")
        return False, f"Could not find '{name}' in paired or scanned Bluetooth devices."

    # Prefer the higher-scoring match
    if use_paired and (not use_scanned or score_paired >= score_scanned):
        matched = best_paired
        score = score_paired
        source = "paired"
    else:
        matched = best_scanned
        score = score_scanned
        source = "scanned"

    addr = matched['address']
    print(f"Fuzzy matched '{name}' to {source.upper()} device '{matched['name']}' (score: {score:.1f})")

    if addr == 'Unknown':
        print("Cannot connect — MAC address unknown.")
        return False, f"Cannot connect to {source} device '{matched['name']}' because its MAC address is unknown."

    is_ble = matched.get('is_ble', False)

    # If matched from scan, check if it's actually already paired.
    # BLE scans return a CoreBluetooth UUID (e.g. 698503B9-...) as the address,
    # but blueutil and IOBluetooth need the real MAC (e.g. e8-93-60-47-db-ca).
    # Cross-reference the scanned device name against the paired list to recover
    # the real MAC and skip the redundant --pair step.
    if source == "scanned":
        # First check: blueutil's paired list
        found_paired = False
        if paired_devices:
            paired_match, paired_score = find_best_device_match(matched['name'], paired_devices)
            if paired_match and paired_score >= 90:
                print(f"[Bluetooth] Device '{matched['name']}' found in blueutil paired list (MAC: {paired_match['address']}), skipping --pair.")
                addr = paired_match['address']
                source = "paired"
                is_ble = False
                found_paired = True

        # Second check: IOBluetooth's paired devices (sees devices blueutil misses)
        if not found_paired:
            iobt_addr = _find_in_iobt_paired(matched['name'])
            if iobt_addr:
                print(f"[Bluetooth] Device '{matched['name']}' found in IOBluetooth paired list (MAC: {iobt_addr}), skipping --pair.")
                addr = iobt_addr
                source = "paired"
                is_ble = False

    # For truly new (unpaired) devices, resolve the best address for pairing.
    # BLE scans return UUIDs; blueutil --pair needs real MAC addresses.
    # Many devices (speakers, headphones) are dual-mode: they advertise on BLE
    # but actually connect via Classic. Check the classic scan results for a real MAC.
    if source == "scanned" and is_ble:
        # Check if the same device appeared in the classic scan with a real MAC
        classic_match = None
        if scanned_devices:
            for sd in scanned_devices:
                if not sd.get('is_ble', True) and sd.get('name', '') == matched['name']:
                    classic_match = sd
                    break
            if not classic_match:
                # Fuzzy match against classic-only devices from the scan
                classic_only = [sd for sd in scanned_devices if not sd.get('is_ble', True)]
                if classic_only:
                    cm, cs = find_best_device_match(matched['name'], classic_only)
                    if cm and cs >= 85:
                        classic_match = cm

        if classic_match:
            print(f"[Bluetooth] Found classic MAC for '{matched['name']}': {classic_match['address']} (dual-mode device)")
            addr = classic_match['address']
            is_ble = False  # Use classic pairing path

    # Pair new classic devices via blueutil (has real MAC address)
    if source == "scanned" and not is_ble:
        print(f"Initiating classic pairing with new device '{matched['name']}'...")
        res = subprocess.run(['blueutil', '--pair', addr], capture_output=True, text=True)
        if res.returncode != 0:
            print(f"[Bluetooth Error] blueutil --pair failed with code {res.returncode}: {res.stderr.strip()}")
            return False, f"Failed to pair device '{matched['name']}' (code {res.returncode}: {res.stderr.strip()})."
        print(f"Pairing complete for '{matched['name']}'.")

    # Connect using appropriate method
    if is_ble:
        # BLE devices: try direct Bleak connection first (no popup)
        # If that fails with pairing error, fall back to blueutil --pair which triggers system popup
        try:
            from bleak import BleakClient
            async with BleakClient(addr, timeout=15.0) as client:
                if client.is_connected:
                    print(f"Successfully connected to BLE device '{matched['name']}'.")
                    elapsed = (time.time() - start) * 1000
                    print(f"[Time taken: {elapsed:.2f} ms]")
                    return True, f"Successfully connected to BLE device '{matched['name']}'."
                else:
                    return False, f"Connection attempt finished for BLE device '{matched['name']}' but device reports not connected."
        except Exception as e:
            err_str = str(e).lower()
            # If Bleak fails with pairing/auth error, try blueutil --pair which triggers system popup
            if "pair" in err_str or "auth" in err_str or "encrypt" in err_str or "authentication" in err_str or "pairing" in err_str:
                print(f"[Bluetooth] BLE connection requires pairing, triggering system popup via blueutil...")
                # Run blueutil --pair which will show the system pairing dialog
                res = subprocess.run(['blueutil', '--pair', addr], capture_output=True, text=True)
                if res.returncode == 0:
                    print(f"Pairing complete for '{matched['name']}'.")
                    # Now try connecting again after pairing
                    try:
                        from bleak import BleakClient
                        async with BleakClient(addr, timeout=15.0) as client:
                            if client.is_connected:
                                elapsed = (time.time() - start) * 1000
                                print(f"[Time taken: {elapsed:.2f} ms]")
                                return True, f"Successfully paired and connected to BLE device '{matched['name']}'."
                            else:
                                return False, f"Paired but BLE device '{matched['name']}' reports not connected."
                    except Exception as e2:
                        return False, f"Paired but failed to connect: {e2}"
                else:
                    print(f"[Bluetooth Error] blueutil --pair failed (code {res.returncode}: {res.stderr.strip()})")
                    return False, f"Failed to pair with '{matched['name']}' (code {res.returncode})."
            else:
                print(f"[Bluetooth Error] Bleak connection failed: {e}")
                return False, f"Failed to connect to BLE device '{matched['name']}': {e}"
    else:
        # Classic (non-BLE) device: use IOBluetooth silent connection
        return await _connect_classic_silent(addr, matched['name'])


async def _connect_classic_silent(address, device_name):
    """Connect to a paired Classic Bluetooth device silently using IOBluetoothDevice.
    
    Uses openConnection_withPageTimeout_authenticationRequired_ with
    authenticationRequired=False to prevent macOS from showing the
    "Connection Request from:" confirmation dialog.
    
    Returns: (success_bool, message_str)
    """
    try:
        from IOBluetooth import IOBluetoothDevice
    except ImportError:
        print("[Bluetooth] IOBluetooth framework not available, falling back to blueutil.")
        return _connect_classic_blueutil_fallback(address, device_name)

    try:
        # Find the device by MAC address in the system's known devices
        device = IOBluetoothDevice.deviceWithAddressString_(address)
        if not device:
            print(f"[Bluetooth] IOBluetooth could not find device with address {address}, falling back to blueutil.")
            return _connect_classic_blueutil_fallback(address, device_name)

        print(f"[Bluetooth] Opening connection to '{device_name}' via IOBluetooth (silent, no popup)...")

        # Try up to 3 times with small delay - macOS sometimes shows popup 
        # for audio/HID devices even with authenticationRequired=False
        max_attempts = 3
        for attempt in range(max_attempts):
            print(f"[Bluetooth] Opening connection to '{device_name}' via IOBluetooth (attempt {attempt + 1}/{max_attempts}, silent, no popup)...")

            status = device.openConnection_withPageTimeout_authenticationRequired_(
                None,   # no delegate
                10000,  # page timeout ~6.25 seconds (in 0.625ms Bluetooth slots)
                False   # DO NOT require authentication — suppresses the popup
            )

            if status == 0:
                print(f"[Bluetooth] Successfully connected to '{device_name}' via IOBluetooth (attempt {attempt + 1}).")
                return True, f"Successfully connected to '{device_name}'."
            else:
                print(f"[Bluetooth] IOBluetooth openConnection returned error {status} (attempt {attempt + 1}/{max_attempts})")
                if attempt < max_attempts - 1:
                    time.sleep(0.5)  # Brief delay before retry

# All IOBluetooth attempts failed - fallback to blueutil
        print(f"[Bluetooth] IOBluetooth openConnection failed after {max_attempts} attempts, falling back to blueutil.")
        return _connect_classic_blueutil_fallback(address, device_name)

    except Exception as e:
        print(f"[Bluetooth] IOBluetooth error: {e}, falling back to blueutil.")
        return _connect_classic_blueutil_fallback(address, device_name)


def _run_auto_accept() -> bool:
    """Run the external auto-accept script once to click any pairing dialog.
    Returns True if the script reported clicking a button."""
    try:
        import os
        script_path = os.path.join(os.path.dirname(__file__), "bluetooth_auto_accept.py")
        if not os.path.exists(script_path):
            return False
        result = subprocess.run(
            ["python3", script_path],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[Bluetooth] Auto-accept script error: {e}")
        return False


def _connect_classic_blueutil_fallback(address, device_name):
    """Fallback: connect via blueutil --connect (for cases where IOBluetooth fails).
    
    Returns: (success_bool, message_str)
    """
    print(f"[Bluetooth] Connecting to '{device_name}' via blueutil fallback...")
    connect_res = subprocess.run(['blueutil', '--connect', address], capture_output=True, text=True)
    if connect_res.returncode == 0:
        print(f"[Bluetooth] Successfully connected to '{device_name}' via blueutil.")
        return True, f"Successfully connected to '{device_name}'."
    else:
        print(f"[Bluetooth] blueutil --connect failed (code {connect_res.returncode}: {connect_res.stderr.strip()}).")
        return False, f"Failed to connect to '{device_name}' (code {connect_res.returncode})."


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
