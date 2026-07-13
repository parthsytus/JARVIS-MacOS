#!/usr/bin/env python3
"""
Minimal BLE pairing auto-accept script.
Only runs when invoked, clicks the pairing dialog, then exits.
No continuous polling/spam - runs once, clicks if dialog found, exits.
"""

import ctypes
import time
import sys

# CoreFoundation + Accessibility
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

ax.AXUIElementCreateSystemWide.restype = ctypes.c_void_p
ax.AXUIElementCreateSystemWide.argtypes = []
ax.AXUIElementCopyAttributeValue.restype = ctypes.c_int
ax.AXUIElementCopyAttributeValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
ax.AXUIElementPerformAction.restype = ctypes.c_int
ax.AXUIElementPerformAction.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

kCFStringEncodingUTF8 = 0x08000100

BUTTON_TITLES = {"Connect", "Pair", "Accept", "Allow"}

def _cfstring(s: str) -> ctypes.c_void_p:
    return cf.CFStringCreateWithCString(None, s.encode('utf-8'), 0x08000100)

def _from_cfstring(cf_str: ctypes.c_void_p) -> str:
    if not cf_str:
        return ""
    buf = ctypes.create_string_buffer(1024)
    ok = cf.CFStringGetCString(cf_str, buf, 1024, 0x08000100)
    return buf.value.decode('utf-8') if ok else ""

def _get_attr(elem: ctypes.c_void_p, attr: str):
    cf_attr = _cfstring(attr)
    val = ctypes.c_void_p()
    err = ax.AXUIElementCopyAttributeValue(elem, cf_attr, ctypes.byref(val))
    cf.CFRelease(cf_attr)
    if err != 0:
        return None, err
    return val, 0

def _click_button(elem: ctypes.c_void_p) -> bool:
    cf_action = _cfstring("AXPress")
    err = ax.AXUIElementPerformAction(elem, cf_action)
    cf.CFRelease(cf_action)
    return err == 0

def _find_and_click(elem: ctypes.c_void_p, depth=0, max_depth=10) -> bool:
    if depth > max_depth:
        return False

    role_val, _ = _get_attr(elem, "AXRole")
    role = _from_cfstring(role_val.value) if role_val else ""
    if role_val: cf.CFRelease(role_val)

    title_val, _ = _get_attr(elem, "AXTitle")
    title = _from_cfstring(title_val.value) if title_val else ""
    if title_val: cf.CFRelease(title_val)

    if not title:
        desc_val, _ = _get_attr(elem, "AXDescription")
        title = _from_cfstring(desc_val.value) if desc_val else ""
        if desc_val: cf.CFRelease(desc_val)

    if role == "AXButton" and title in BUTTON_TITLES:
        if _click_button(elem):
            print(f"[Auto-Accept] Clicked button: {title}")
            return True

    children_val, _ = _get_attr(elem, "AXChildren")
    if children_val:
        count = cf.CFArrayGetCount(children_val)
        for i in range(count):
            child = cf.CFArrayGetValueAtIndex(children_val, i)
            if child and _find_and_click(child, depth + 1):
                cf.CFRelease(children_val)
                return True
        cf.CFRelease(children_val)
    return False

def find_and_click_pair_dialog() -> bool:
    """Try to find and click the Bluetooth pairing dialog.
    Returns True if a button was clicked."""
    # 1. Try system-wide focused element first (catches dialogs anywhere)
    system_wide = ax.AXUIElementCreateSystemWide()
    if not system_wide:
        return False

    focused_val, _ = _get_attr(system_wide, "AXFocusedUIElement")
    if focused_val and focused_val.value:
        if _find_and_click(focused_val.value):
            cf.CFRelease(focused_val)
            return True
        cf.CFRelease(focused_val)

    # 2. Fallback: check common system apps that show pairing dialogs
    from AppKit import NSWorkspace
    suspect_names = [
        "UserNotificationCenter", "ControlCenter", "Control Center",
        "BluetoothUIServer", "SystemUIServer", "System Settings",
        "sharingd", "Notification Center", "NotificationCenter"
    ]
    workspace = NSWorkspace.sharedWorkspace()
    for app in workspace.runningApplications():
        name = app.localizedName()
        if name in suspect_names:
            import ctypes as _ctypes
            ax.AXUIElementCreateApplication.restype = ctypes.c_void_p
            ax.AXUIElementCreateApplication.argtypes = [_ctypes.c_int]
            app_ref = ax.AXUIElementCreateApplication(app.processIdentifier())
            if app_ref and _find_and_click(app_ref):
                return True
    return False

def main():
    """Run once: try to click the pairing dialog, print result, exit."""
    if find_and_click_pair_dialog():
        print("[Auto-Accept] Clicked pairing dialog button")
        sys.exit(0)
    else:
        print("[Auto-Accept] No pairing dialog found")
        sys.exit(1)

if __name__ == "__main__":
    main()