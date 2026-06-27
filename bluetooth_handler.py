import asyncio
import subprocess
import json
import ctypes
import threading
import time
from rapidfuzz import process, fuzz
from bleak import BleakScanner
from AppKit import NSWorkspace

# CoreFoundation and Accessibility APIs
cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
ax = ctypes.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')

CFStringRef = ctypes.c_void_p
CFTypeRef = ctypes.c_void_p
AXUIElementRef = ctypes.c_void_p
AXError = ctypes.c_int

cf.CFStringCreateWithCString.restype = CFStringRef
cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]

cf.CFStringGetCString.restype = ctypes.c_bool
cf.CFStringGetCString.argtypes = [CFStringRef, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]

cf.CFRelease.restype = None
cf.CFRelease.argtypes = [ctypes.c_void_p]

cf.CFArrayGetCount.restype = ctypes.c_long
cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]

cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]

ax.AXUIElementCreateApplication.restype = AXUIElementRef
ax.AXUIElementCreateApplication.argtypes = [ctypes.c_int]

ax.AXUIElementCopyAttributeValue.restype = AXError
ax.AXUIElementCopyAttributeValue.argtypes = [AXUIElementRef, CFStringRef, ctypes.POINTER(CFTypeRef)]

ax.AXUIElementPerformAction.restype = AXError
ax.AXUIElementPerformAction.argtypes = [AXUIElementRef, CFStringRef]

kCFStringEncodingUTF8 = 0x08000100

def _to_cfstring(s):
    return cf.CFStringCreateWithCString(None, s.encode('utf-8'), kCFStringEncodingUTF8)

def _from_cfstring(cf_str):
    if not cf_str:
        return ""
    buf = ctypes.create_string_buffer(1024)
    success = cf.CFStringGetCString(cf_str, buf, 1024, kCFStringEncodingUTF8)
    if success:
        return buf.value.decode('utf-8')
    return ""

def _get_attribute(element, attr_name):
    cf_attr = _to_cfstring(attr_name)
    val = CFTypeRef()
    err = ax.AXUIElementCopyAttributeValue(element, cf_attr, ctypes.byref(val))
    cf.CFRelease(cf_attr)
    if err == 0 and val.value:
        return val
    return None

def _release_cf(val):
    if val:
        cf.CFRelease(val)

def _find_and_click_button(element, depth=0, max_depth=10):
    if depth > max_depth:
        return False

    # Get Role
    role_cf = _get_attribute(element, "AXRole")
    role = _from_cfstring(role_cf)
    _release_cf(role_cf)
    
    # Get Title
    title_cf = _get_attribute(element, "AXTitle")
    title = _from_cfstring(title_cf)
    _release_cf(title_cf)
    
    if not title:
        # Try AXDescription
        desc_cf = _get_attribute(element, "AXDescription")
        title = _from_cfstring(desc_cf)
        _release_cf(desc_cf)

    if role == "AXButton" and title in ["Connect", "Pair", "Accept", "Allow"]:
        print(f"[Bluetooth Auto-Accept] Found button: {title}")
        cf_action = _to_cfstring("AXPress")
        err = ax.AXUIElementPerformAction(element, cf_action)
        cf.CFRelease(cf_action)
        if err == 0:
            print("[Bluetooth Auto-Accept] Successfully clicked button!")
            return True
        else:
            print(f"[Bluetooth Auto-Accept] Failed to click button, err: {err}")
            return False

    # Traverse children
    children_cf = _get_attribute(element, "AXChildren")
    if children_cf:
        count = cf.CFArrayGetCount(children_cf)
        for i in range(count):
            child = cf.CFArrayGetValueAtIndex(children_cf, i)
            if child:
                if _find_and_click_button(child, depth + 1, max_depth):
                    _release_cf(children_cf)
                    return True
        _release_cf(children_cf)
    return False

def _scan_gui_apps():
    try:
        workspace = NSWorkspace.sharedWorkspace()
        suspect_names = ["UserNotificationCenter", "ControlCenter", "Control Center", "BluetoothUIServer", "SystemUIServer", "System Settings", "sharingd", "Notification Center", "NotificationCenter"]
        for app in workspace.runningApplications():
            name = app.localizedName()
            if name in suspect_names:
                pid = app.processIdentifier()
                app_ref = ax.AXUIElementCreateApplication(pid)
                if app_ref:
                    if _find_and_click_button(app_ref):
                        return True
    except Exception as e:
        print(f"[Bluetooth Auto-Accept] GUI scan error: {e}")
    return False


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


def find_best_device_match(input_name, device_list):
    """Finds the best matching device from device_list (dicts with 'name') for input_name.
    Matches against full device names AND individual words of device names using both
    fuzz.ratio and fuzz.partial_ratio.
    Returns: (best_matched_device_dict, score) or (None, 0)"""
    best_device = None
    best_score = 0
    
    input_name_lower = input_name.lower().strip()
    
    for d in device_list:
        dev_name = d.get('name', 'Unknown')
        dev_name_lower = dev_name.lower().strip()
        
        # 1. Full string match ratio
        score_full = fuzz.ratio(input_name_lower, dev_name_lower)
        score_partial = fuzz.partial_ratio(input_name_lower, dev_name_lower)
        
        # 2. Word-by-word match
        word_scores = []
        for word in dev_name_lower.split():
            word_scores.append(fuzz.ratio(input_name_lower, word))
            word_scores.append(fuzz.partial_ratio(input_name_lower, word))
            
        max_word_score = max(word_scores) if word_scores else 0
        device_best = max(score_full, score_partial, max_word_score)
        
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


import threading
import time

def auto_accept_pair_request():
    """Start a non-blocking background loop to click Pair/Connect on macOS dialogs instantly using native accessibility APIs."""
    def loop():
        print("[Bluetooth] Starting background auto-accept dialog listener...")
        for _ in range(150): # 15 seconds max
            if _scan_gui_apps():
                print("[Bluetooth Auto-Accept] Native auto-accept clicked the pairing button!")
                break
            time.sleep(0.1)
            
    t = threading.Thread(target=loop, daemon=True)
    t.start()

async def connect_to_device(name, paired_devices, scanned_devices):
    """Connect to a device. Paired devices use blueutil. New devices require
    Mac system UI for pairing — JARVIS initiates and informs the user.
    Returns: (success_bool, message_str)"""
    print(f"\n--- Attempting to connect to '{name}' ---")
    start = time.time()

    if paired_devices is None:
        paired_devices = get_paired_devices()

    best_paired, score_paired = find_best_device_match(name, paired_devices)

    success = False
    message = ""

    if best_paired and score_paired >= 60:
        matched = best_paired
        addr = matched['address']
        print(f"Fuzzy matched '{name}' to PAIRED device '{matched['name']}' (score: {score_paired:.1f})")
        if addr != 'Unknown':
            # Start background auto-accept process
            auto_accept_pair_request()
            
            result = subprocess.run(
                ['blueutil', '--connect', addr],
                capture_output=True
            )
            if result.returncode == 0:
                print(f"Successfully connected to {matched['name']}.")
                success = True
                message = f"Successfully connected to paired device '{matched['name']}'."
            else:
                print(f"Connection attempt finished. Status: {result.returncode}")
                message = f"Failed to connect to paired device '{matched['name']}' (status code: {result.returncode})."
        else:
            print("Cannot connect — MAC address unknown.")
            message = f"Cannot connect to paired device '{matched['name']}' because its MAC address is unknown."
    else:
        # New device — check scanned devices.
        # If not scanned, run a quick scan to see if it's nearby.
        if not scanned_devices:
            print(f"Device '{name}' not in paired list and no scan results available. Running a quick scan...")
            scanned_devices = await scan_nearby_devices(filter_keyword=name)

        best_scanned, score_scanned = find_best_device_match(name, scanned_devices)

        if best_scanned and score_scanned >= 60:
            matched = best_scanned
            addr = matched['address']
            is_ble = matched.get('is_ble', False)

            if is_ble:
                print(f"Initiating BLE connection to new device '{matched['name']}' using Bleak...")
                print("NOTE: macOS requires confirmation in the system pairing dialog (automatically accepting...).")
                
                # Start background auto-accept process
                auto_accept_pair_request()
                
                try:
                    from bleak import BleakClient
                    async with BleakClient(addr, timeout=15.0) as client:
                        if client.is_connected:
                            print(f"Successfully connected to BLE device '{matched['name']}'.")
                            success = True
                            message = f"Successfully paired and connected to new BLE device '{matched['name']}'."
                        else:
                            print(f"Bleak connection finished but is_connected is False.")
                            message = f"Bleak connection finished for new BLE device '{matched['name']}' but is_connected is False."
                except Exception as e:
                    print(f"[Bluetooth Error] Bleak connection failed: {e}")
                    message = f"Failed to pair or connect to BLE device '{matched['name']}': {e}"
            else:
                print(f"Initiating pairing with new classic device '{matched['name']}'...")
                print("NOTE: macOS requires confirmation in the system pairing dialog (automatically accepting...).")
                
                # Start background auto-accept process
                auto_accept_pair_request()
                
                res = subprocess.run(['blueutil', '--pair', addr], capture_output=True, text=True)
                if res.returncode != 0:
                    print(f"[Bluetooth Error] blueutil --pair failed with code {res.returncode}: {res.stderr.strip()}")
                    message = f"Failed to pair classic device '{matched['name']}' (code {res.returncode}: {res.stderr.strip()})."
                else:
                    print(f"Pairing request sent and accepted. Connecting to classic device '{matched['name']}'...")
                    connect_res = subprocess.run(['blueutil', '--connect', addr], capture_output=True, text=True)
                    if connect_res.returncode == 0:
                        print(f"Successfully connected to classic device '{matched['name']}'.")
                        success = True
                        message = f"Successfully paired and connected to classic device '{matched['name']}'."
                    else:
                        print(f"Failed to connect to classic device after pairing. Status: {connect_res.returncode}")
                        message = f"Successfully paired classic device '{matched['name']}' but failed to connect (status code {connect_res.returncode})."
        else:
            print(f"Could not find '{name}' in paired or scanned devices.")
            message = f"Could not find '{name}' in paired or scanned Bluetooth devices."

    print(f"[Time taken: {(time.time() - start) * 1000:.2f} ms]")
    return success, message


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
