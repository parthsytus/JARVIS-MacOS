import time
import re
import math
import subprocess
import sys
import webbrowser
import traceback
import os
import sqlite3
import json
import urllib.request
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
    HAS_SPOTIPY = bool(os.getenv("SPOTIPY_CLIENT_ID"))
    if HAS_SPOTIPY:
        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(scope="user-read-playback-state,user-modify-playback-state"))
except ImportError:
    HAS_SPOTIPY = False

# Optional imports for system controls to allow testing even if not installed yet
try:
    import psutil
    import asyncio

    # Import bluetooth_handler from the root directory
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        import bluetooth_handler as bt_module
        HAS_BLUETOOTH = True
    except ImportError as e:
        print(f"Failed to import bluetooth_handler: {e}")
        HAS_BLUETOOTH = False

    HAS_SYS_LIBS = True
except ImportError:
    HAS_SYS_LIBS = False
    print("Warning: Missing system libraries.")

try:
    from rapidfuzz import process, fuzz
    HAS_FUZZ = True
except ImportError:
    HAS_FUZZ = False
    print("Warning: rapidfuzz not installed. Exact matching will be used instead.")

# Window management on macOS uses osascript (no pygetwindow needed)

# ---------------------------------------------------------------------------
# PRE-COMPILED PATTERNS & MODULE-LEVEL SINGLETONS
# ---------------------------------------------------------------------------
_CONV_PATTERN = re.compile(
    r'((?:\d+(?:\.\d+)?)|a|an|one|two|three|four|five|six|seven|eight|nine|ten|'
    r'eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|'
    r'twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)'
    r'\s+([a-zA-Z\s]+?)\s+'
    r'(?:to|in|into|is\s+how\s+many|how\s+many|in\s+how\s+many|equal\s+to|equals)'
    r'\s+([a-zA-Z\s]+)'
)

try:
    import pint as _pint_mod
    _ureg = _pint_mod.UnitRegistry()
except ImportError:
    _ureg = None

# ---------------------------------------------------------------------------
# HARDCODED DICTIONARIES AND CONFIG
# ---------------------------------------------------------------------------

HINDI_TO_ENGLISH = {
    "badhao": "increase",
    "ghatao": "decrease",
    "kam karo": "decrease",
    "kholo": "open",
    "chalu karo": "open",
    "band karo": "close",
    "bund karo": "close",
    "bajao": "play",
    "chalao": "play",
    "roko": "pause",
    "ruk ja": "pause",
    "agla": "next",
    "next": "next",
    "pichla": "previous",
    "mute karo": "mute",
    "awaaz band": "mute",
    "kitna hai": "tell me",
    "batao": "tell me",
    "status": "tell me",
    "on kar": "turn on",
    "chalu kar": "turn on",
    "off kar": "turn off",
    "band kar": "turn off",
    "volume": "volume",
    "awaaz": "volume",
    "brightness": "brightness",
    "chamak": "brightness",
    "search kar": "search",
    "dhundo": "search",
    "khojo": "search",
    "badlo": "switch",
    "doosra": "switch",
    "bhool ja": "forget",
    "aur": "and",
    "pe le jao": "switch to",
    "karo": "set",
    "sab": "all",
    "saare": "all",
    "ye": "this",
    "is": "this",
    "dikhao": "show",
    "mein": "in",
    "pe": "on",
    "kya": "what",
    "naya": "new",
    "banao": "create",
    "hatao": "delete",
    "naam badlo": "rename",
    "kitne": "how many",
    "into": "to"
}

# ---------------------------------------------------------------------------
# MOCK TV DATA
# ---------------------------------------------------------------------------

MOCK_DISCOVERED_TVS = [
    {"brand": "Sony", "model": "K-55S25M2", "ip": "192.168.1.105", "mac": "AA:BB:CC:DD:EE:FF"},
    {"brand": "Samsung", "model": "Crystal 4K", "ip": "192.168.1.107", "mac": "AA:BB:CC:DD:EE:11"},
    {"brand": "LG", "model": "OLED C3", "ip": "192.168.1.110", "mac": "AA:BB:CC:DD:EE:22"}
]

active_tv = None

# ---------------------------------------------------------------------------
# macOS SYSTEM CONTROL HELPERS
# ---------------------------------------------------------------------------

def _mac_get_volume():
    result = subprocess.run(
        ['osascript', '-e', 'output volume of (get volume settings)'],
        capture_output=True, text=True
    )
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 50

def _mac_set_volume(val):
    val = max(0, min(100, int(val)))
    subprocess.run(
        ['osascript', '-e', f'set volume output volume {val}'],
        check=True
    )

def _mac_mute():
    subprocess.run(
        ['osascript', '-e', 'set volume with output muted'],
        check=True
    )

def _mac_unmute():
    subprocess.run(
        ['osascript', '-e', 'set volume without output muted'],
        check=True
    )

def _mac_set_brightness(val):
    # Requires: brew install brightness
    level = max(0.0, min(1.0, val / 100.0))
    subprocess.run(['brightness', str(level)], capture_output=True)

def _mac_get_brightness():
    result = subprocess.run(['brightness', '-l'], capture_output=True, text=True)
    match = re.search(r'brightness:\s*([\d.]+)', result.stdout)
    return int(float(match.group(1)) * 100) if match else 50

def _mac_minimize_active():
    subprocess.run(['osascript', '-e',
        'tell application "System Events" to set miniaturized of '
        '(first window of (first application process whose frontmost is true)) to true'],
        capture_output=True)

def _mac_maximize_active():
    subprocess.run(['osascript', '-e',
        'tell application "System Events" to keystroke "f" '
        'using {control down, command down}'],
        capture_output=True)

def _mac_focus_app(app_name):
    subprocess.run(['osascript', '-e',
        f'tell application "{app_name}" to activate'],
        capture_output=True)

def _mac_copy():
    subprocess.run(['osascript', '-e',
        'tell application "System Events" to keystroke "c" using command down'],
        capture_output=True)

def _mac_paste():
    subprocess.run(['osascript', '-e',
        'tell application "System Events" to keystroke "v" using command down'],
        capture_output=True)

def _mac_cut():
    subprocess.run(['osascript', '-e',
        'tell application "System Events" to keystroke "x" using command down'],
        capture_output=True)

def _mac_select_all():
    subprocess.run(['osascript', '-e',
        'tell application "System Events" to keystroke "a" using command down'],
        capture_output=True)

# ---------------------------------------------------------------------------
# UTILITIES
# ---------------------------------------------------------------------------

def translate_hindi_keywords(text):
    text = text.lower()
    # Sort keys by length descending to replace longer phrases first (e.g. "kam karo" before "karo")
    sorted_keys = sorted(HINDI_TO_ENGLISH.keys(), key=len, reverse=True)
    for hindi_word in sorted_keys:
        english_word = HINDI_TO_ENGLISH[hindi_word]
        # Use regex to replace whole words/phrases
        pattern = r'\b' + re.escape(hindi_word) + r'\b'
        text = re.sub(pattern, english_word, text)
    return text

def extract_percentage(text):
    text_lower = text.lower()
    if "full" in text_lower or "max" in text_lower:
        return 100
    if "half" in text_lower:
        return 50
    if "zero" in text_lower:
        return 0
        
    match = re.search(r'(\d+)\s*(?:%|percent)?', text_lower)
    if match:
        return int(match.group(1))
    return None

def fuzzy_match(query, choices, threshold=70):
    if not HAS_FUZZ:
        for choice in choices:
            if query in choice or choice in query:
                return choice
        return None
    
    result = process.extractOne(query, choices, scorer=fuzz.partial_ratio)
    if result and result[1] >= threshold:
        return result[0]
    return None

# ---------------------------------------------------------------------------
# ACTION HANDLERS
# ---------------------------------------------------------------------------

def handle_system_controls(intent, entities):
    action = intent['action']
    target = intent['target']
    result_msg = ""
    
    if target == "volume":
        if not HAS_SYS_LIBS:
            result_msg = f"Mock System: {action} volume"
            if 'value' in entities: result_msg += f" to {entities['value']}%"
            return result_msg
            
        if action == "set" and 'value' in entities:
            _mac_set_volume(entities['value'])
            result_msg = f"Set volume to {entities['value']}%"
        elif action == "increase":
            current = _mac_get_volume()
            _mac_set_volume(min(100, current + 10))
            result_msg = "Increased volume"
        elif action == "decrease":
            current = _mac_get_volume()
            _mac_set_volume(max(0, current - 10))
            result_msg = "Decreased volume"
        elif action == "mute":
            _mac_mute()
            result_msg = "Muted system"
        elif action == "unmute":
            _mac_unmute()
            result_msg = "Unmuted system"
        elif action in ("get", "tell"):
            current = _mac_get_volume()
            result_msg = f"Current volume is {current}%"
            
    elif target == "brightness":
        if not HAS_SYS_LIBS:
            result_msg = f"Mock System: {action} brightness"
            if 'value' in entities: result_msg += f" to {entities['value']}%"
            return result_msg
            
        current_brightness = _mac_get_brightness()
        if action == "set" and 'value' in entities:
            val = max(0, min(100, entities['value']))
            _mac_set_brightness(val)
            result_msg = f"Set brightness to {val}%"
        elif action == "increase":
            _mac_set_brightness(min(100, current_brightness + 10))
            result_msg = "Increased brightness"
        elif action == "decrease":
            _mac_set_brightness(max(0, current_brightness - 10))
            result_msg = "Decreased brightness"
            
    elif target == "stats":
        if not HAS_SYS_LIBS:
            return "Mock System: Fetched system stats"
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        result_msg = f"CPU: {cpu}%, RAM: {ram}%"

    return result_msg

import time
_cached_apps = None
_cached_apps_time = 0

def get_installed_apps():
    global _cached_apps, _cached_apps_time
    if _cached_apps is not None and time.time() - _cached_apps_time < 300: # 5 minute TTL
        return _cached_apps
        
    try:
        # On Mac, use system_profiler to list installed applications
        output = subprocess.check_output(
            ['system_profiler', 'SPApplicationsDataType', '-json'],
            text=True
        )
        data = json.loads(output)
        apps_list = data.get('SPApplicationsDataType', [])
        _cached_apps = {}
        for app in apps_list:
            name = app.get('_name', '')
            path = app.get('path', '')
            if name and path:
                _cached_apps[name.lower()] = path
        _cached_apps_time = time.time()
        return _cached_apps
    except Exception as e:
        print(f"Warning: Failed to get installed apps: {e}")
        return {}

def handle_app_launcher(intent, entities):
    app_name = entities.get('app_name', '')
    if not app_name:
        return "Failed: No app name specified"
        
    apps = get_installed_apps()
    if not apps:
        return f"Failed: Could not retrieve app list to launch '{app_name}'"
        
    # Use rapidfuzz to find the best match
    matched_app_name = fuzzy_match(app_name.lower(), list(apps.keys()))
    
    if matched_app_name:
        app_path = apps[matched_app_name]
        print(f"[App Launcher] Opening {matched_app_name}...")
        try:
            subprocess.Popen(['open', '-a', app_path])
            return f"Launched {matched_app_name}"
        except Exception as e:
            return f"Failed to launch {matched_app_name}: {e}"
    else:
        # Fallback: try opening by name directly using 'open -a'
        try:
            subprocess.Popen(['open', '-a', app_name])
            return f"Launched {app_name}"
        except Exception as e:
            return f"Failed: Could not find any app matching '{app_name}'"

def handle_browser_control(intent, entities):
    query = entities.get('query', '')
    url = entities.get('url', '')
    
    if intent['action'] == "search" and query:
        search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        print(f"[Browser] Opening: {search_url}")
        webbrowser.open(search_url, new=1, autoraise=True)
        return f"Searched for '{query}' in browser"
    elif intent['action'] == "open" and url:
        if not url.startswith('http'):
            url = 'https://' + url
        print(f"[Browser] Opening: {url}")
        webbrowser.open(url, new=1, autoraise=True)
        return f"Opened {url} in browser"
    return "Browser action failed: missing details"

def handle_spotify_control(intent, entities):
    action = intent['action']
    song = entities.get('song', '')
    artist = entities.get('artist', '')
    
    # Clean up "on spotify" / "in spotify" from song name if present
    if song.lower().endswith("on spotify"):
        song = song[:-10].strip()
    elif song.lower().endswith("in spotify"):
        song = song[:-10].strip()
    
    try:
        # Check if we have spotipy configured
        if globals().get('HAS_SPOTIPY'):
            import spotipy
            import time
            try:
                if action == "open" or action == "launch":
                    subprocess.Popen(['open', '-a', 'Spotify'])
                    return "Opened Spotify App locally"
                
                # Device targeting
                target_device_id = None
                device_intent = entities.get('device', None)
                if device_intent:
                    try:
                        devices = sp.devices()['devices']
                        for d in devices:
                            name = d['name'].lower()
                            if device_intent == 'phone' and ('phone' in d['type'].lower() or 'iphone' in name or 'android' in name):
                                target_device_id = d['id']
                                break
                            elif device_intent == 'laptop' and ('computer' in d['type'].lower() or 'desktop' in name or 'laptop' in name):
                                target_device_id = d['id']
                                break
                    except:
                        pass
                
                def attempt_playback(retry=False):
                    try:
                        if action == "play":
                            if song or artist:
                                is_playlist = "playlist" in song.lower()
                                if is_playlist:
                                    query_clean = song.lower().replace("playlist", "").strip()
                                    if artist: query_clean += f" {artist}"
                                    results = sp.search(q=query_clean, type='playlist', limit=5, market='IN')
                                    if results['playlists']['items']:
                                        playlist_uri = results['playlists']['items'][0]['uri']
                                        if entities.get('shuffle'):
                                            try: sp.shuffle(state=True, device_id=target_device_id)
                                            except: pass
                                        sp.start_playback(device_id=target_device_id, context_uri=playlist_uri)
                                        dev_msg = f" on {device_intent}" if device_intent else ""
                                        return f"API: Started playing playlist '{results['playlists']['items'][0]['name']}'{dev_msg}"
                                    else:
                                        return f"API: Could not find any playlist matching '{query_clean}'"
                                else:
                                    if artist:
                                        query = f"track:{song} artist:{artist}"
                                    else:
                                        query = song
                                    results = sp.search(q=query, type='track', limit=5, market='IN')
                                    if not results['tracks']['items'] and artist:
                                        query_broad = f"{song} {artist}".strip()
                                        results = sp.search(q=query_broad, type='track', limit=5, market='IN')
                                        
                                    if results['tracks']['items']:
                                        selected_track = results['tracks']['items'][0]
                                        for track in results['tracks']['items']:
                                            if track['name'].lower() == song.lower():
                                                selected_track = track
                                                break
                                        track_uri = selected_track['uri']
                                        if entities.get('shuffle'):
                                            try: sp.shuffle(state=True, device_id=target_device_id)
                                            except: pass
                                        sp.start_playback(device_id=target_device_id, uris=[track_uri])
                                        dev_msg = f" on {device_intent}" if device_intent else ""
                                        return f"API: Started playing '{selected_track['name']}' on Spotify{dev_msg}"
                                    else:
                                        return f"API: Could not find any track matching '{song} {artist}'"
                            else:
                                if entities.get('shuffle'):
                                    try: sp.shuffle(state=True, device_id=target_device_id)
                                    except: pass
                                sp.start_playback(device_id=target_device_id)
                                return "API: Sent Play/Resume command to Spotify"
                        elif action == "pause":
                            sp.pause_playback(device_id=target_device_id)
                            return "API: Sent Pause command to Spotify"
                        elif action == "next":
                            sp.next_track(device_id=target_device_id)
                            return "API: Sent Next Track command"
                        elif action == "previous":
                            sp.previous_track(device_id=target_device_id)
                            return "API: Sent Previous Track command"
                        elif action == "restart":
                            sp.seek_track(position_ms=0, device_id=target_device_id)
                            return "API: Restarted current track"
                        elif action == "shuffle":
                            state = entities.get('state', True)
                            sp.shuffle(state=state, device_id=target_device_id)
                            return f"API: {'Enabled' if state else 'Disabled'} Shuffle on Spotify"
                        elif action == "loop":
                            loop_type = entities.get('loop_type', 'track')
                            sp.repeat(state=loop_type, device_id=target_device_id)
                            return f"API: Set Loop to '{loop_type}' on Spotify"
                        elif action == "queue":
                            if song or artist:
                                if artist:
                                    query = f"track:{song} artist:{artist}"
                                else:
                                    query = song
                                results = sp.search(q=query, type='track', limit=5)
                                if not results['tracks']['items'] and artist:
                                    query_broad = f"{song} {artist}".strip()
                                    results = sp.search(q=query_broad, type='track', limit=5)
                                    
                                if results['tracks']['items']:
                                    selected_track = results['tracks']['items'][0]
                                    for track in results['tracks']['items']:
                                        if track['name'].lower() == song.lower():
                                            selected_track = track
                                            break
                                    track_uri = selected_track['uri']
                                    sp.add_to_queue(track_uri, device_id=target_device_id)
                                    dev_val = entities.get('device', None)
                                    dev_msg = f" on {dev_val}" if dev_val else ""
                                    return f"Added {selected_track['name']} to queue{dev_msg}"
                                else:
                                    return f"API: Could not find any track matching '{song} {artist}'"
                            else:
                                return "API: No song specified for queue"
                    except spotipy.exceptions.SpotifyException as e:
                        if "No active device found" in str(e) and not retry:
                            subprocess.Popen(['open', '-a', 'Spotify'])
                            time.sleep(3)
                            return attempt_playback(retry=True)
                        return f"Spotify API Error: {str(e)}"
                    except Exception as e:
                        return f"API Error: {str(e)}"
                        
                return attempt_playback()
            except spotipy.exceptions.SpotifyException as e:
                return f"Spotify API Error: {str(e)}"
            except Exception as e:
                return f"API Error: {str(e)}"
                
        # Fallback — use osascript to control Spotify on Mac
        if action == "play":
            if song or artist:
                query = f"{song} {artist}".strip()
                import urllib.parse
                safe_query = urllib.parse.quote(query)
                subprocess.Popen(['open', f"spotify:search:{safe_query}"])
                return f"Searching Spotify for: '{query}'"
            else:
                subprocess.run(['osascript', '-e',
                    'tell application "Spotify" to play'], capture_output=True)
                return "Sent Play command to Spotify"
        elif action == "pause":
            subprocess.run(['osascript', '-e',
                'tell application "Spotify" to pause'], capture_output=True)
            return "Sent Pause command to Spotify"
        elif action == "next":
            subprocess.run(['osascript', '-e',
                'tell application "Spotify" to next track'], capture_output=True)
            return "Sent Next Track command"
        elif action == "previous":
            subprocess.run(['osascript', '-e',
                'tell application "Spotify" to previous track'], capture_output=True)
            return "Sent Previous Track command"
        else:
            subprocess.Popen(['open', '-a', 'Spotify'])
            return f"Opened Spotify (Action: {action})"
    except Exception as e:
        return f"Failed to control Spotify: {e}"

def handle_tv_control(intent, entities):
    global active_tv
    action = intent['action']
    
    if action == "discover":
        print("\n[Simulated SSDP] Broadcasting to 239.255.255.250:1900...")
        time.sleep(1)
        print("Discovered TVs:")
        for i, tv in enumerate(MOCK_DISCOVERED_TVS):
            print(f" {i+1}: {tv['brand']} {tv['model']} ({tv['ip']})")
        return "TV discovery completed"
        
    if action == "select":
        index = entities.get('tv_index')
        if index is not None and 1 <= index <= len(MOCK_DISCOVERED_TVS):
            active_tv = MOCK_DISCOVERED_TVS[index-1]
            return f"Selected TV: {active_tv['brand']} {active_tv['model']}"
        return "Invalid TV selection"
        
    if not active_tv:
        return "No active TV selected. Please find and select a TV first."
        
    network_mode = "Direct LAN Mode" # We'll mock this for now
    
    result_msg = f"[Simulated TV ({network_mode} to {active_tv['brand']})] Action: {action}"
    if 'value' in entities: result_msg += f", Value: {entities['value']}"
    if 'app' in entities: result_msg += f", App: {entities['app']}"
    if 'channel' in entities: result_msg += f", Channel: {entities['channel']}"
    if 'input' in entities: result_msg += f", Input: {entities['input']}"
    
    return result_msg

# ---------------------------------------------------------------------------
# INTENT PARSER
# ---------------------------------------------------------------------------

def handle_file_operations(intent, entities):
    action = intent['action']
    
    if action == "copy": _mac_copy(); return "Copied"
    elif action == "paste": _mac_paste(); return "Pasted"
    elif action == "cut": _mac_cut(); return "Cut"
    elif action == "select_all": _mac_select_all(); return "Selected All"
    elif action == "rename":
        # On Mac, press Enter to rename in Finder
        subprocess.run(['osascript', '-e',
            'tell application "System Events" to keystroke return'],
            capture_output=True)
        return "Triggered Rename"
    
    if action == "empty_bin":
        try:
            subprocess.run(['osascript', '-e',
                'tell application "Finder" to empty the trash'],
                capture_output=True)
            return "Emptied Trash"
        except Exception as e:
            return f"Failed to empty trash: {e}"
            
    folder = entities.get('folder', 'current')
    drive = entities.get('drive')
    
    if action == "create_folder" and folder == "current":
        subprocess.run(['osascript', '-e',
            'tell application "System Events" to keystroke "n" using {command down, shift down}'],
            capture_output=True)
        return "Created new folder in active window"
        
    if action == "delete" and folder == "current":
        subprocess.run(['osascript', '-e',
            'tell application "System Events" to keystroke (ASCII character 8) using command down'],
            capture_output=True)
        return "Sent Delete command to active window"
        
    path = ""
    home_dir = os.path.expanduser("~")
    
    if folder == "downloads": path = os.path.join(home_dir, "Downloads")
    elif folder == "desktop": path = os.path.join(home_dir, "Desktop")
    elif folder == "documents": path = os.path.join(home_dir, "Documents")
    elif folder == "pictures": path = os.path.join(home_dir, "Pictures")
    elif folder == "music": path = os.path.join(home_dir, "Music")
    elif folder == "videos": path = os.path.join(home_dir, "Movies")
    elif folder == "current":
        path = os.getcwd()
    else:
        path = folder
        
    if not os.path.exists(path) and not os.path.isabs(path) and folder != "current":
        found = False
        partial_match_path = None
        search_roots = [home_dir, "/Applications", "/Volumes"]
        target_lower = folder.lower()
        
        for root in search_roots:
            if not root or not os.path.exists(root): continue
            
            queue = [(root, 0)]
            max_depth = 2
            
            while queue and not found:
                current_path, depth = queue.pop(0)
                if depth > max_depth: continue
                
                try:
                    with os.scandir(current_path) as it:
                        for entry in it:
                            if entry.is_dir():
                                name_lower = entry.name.lower()
                                if name_lower == target_lower:
                                    path = entry.path
                                    found = True
                                    break
                                elif target_lower in name_lower and not partial_match_path:
                                    partial_match_path = entry.path
                                    
                                if depth < max_depth:
                                    queue.append((entry.path, depth + 1))
                except (PermissionError, FileNotFoundError, OSError):
                    pass
            if found: break
            
        if not found and partial_match_path:
            path = partial_match_path
            found = True
                
    if not os.path.exists(path):
        return f"Folder not found: {folder}"
        
    if action == "open":
        try:
            subprocess.Popen(['open', path])
            return f"Opened: {path}"
        except Exception as e:
            return f"Failed to open: {e}"
            
    elif action == "list":
        try:
            files = os.listdir(path)
            file_list = ", ".join(files[:10])
            if len(files) > 10:
                file_list += f" ... and {len(files)-10} more"
            return f"Files in {path}:\n{file_list}"
        except Exception as e:
            return f"Failed to list files: {e}"
            
    if action == "delete":
        return f"Please select '{folder}' manually and say 'delete' to safely remove it."
    if action == "create_folder":
        return f"Please navigate to '{folder}' and say 'create folder' to safely create it."
        
    return "Unknown file action"

def handle_window_control(intent, entities):
    action = intent['action']
    target = entities.get('window_name', 'this')
    
    try:
        if target == 'all':
            if action == "minimize":
                # Minimize all windows using Mission Control
                subprocess.run(['osascript', '-e',
                    'tell application "System Events" to keystroke "m" using {command down, option down}'],
                    capture_output=True)
                return f"Minimized all windows"
            elif action == "close":
                subprocess.run(['osascript', '-e',
                    'tell application "System Events" to keystroke "w" using {command down, option down}'],
                    capture_output=True)
                return f"Closed all windows"
            return f"{action.capitalize()}d all windows"
            
        elif target == 'this':
            if action == "minimize":
                _mac_minimize_active()
                return "Minimized active window"
            elif action == "maximize":
                _mac_maximize_active()
                return "Maximized active window"
            elif action == "close":
                subprocess.run(['osascript', '-e',
                    'tell application "System Events" to keystroke "w" using command down'],
                    capture_output=True)
                return "Closed active window"
            elif action == "restore":
                subprocess.run(['osascript', '-e',
                    'tell application "System Events" to keystroke "f" using {control down, command down}'],
                    capture_output=True)
                return "Restored active window"
            return "No active window found"
            
        else:
            # Focus the app by name, then perform action
            _mac_focus_app(target)
            import time
            time.sleep(0.5)
            if action == "minimize":
                _mac_minimize_active()
            elif action == "maximize":
                _mac_maximize_active()
            elif action == "close":
                subprocess.run(['osascript', '-e',
                    'tell application "System Events" to keystroke "w" using command down'],
                    capture_output=True)
            elif action == "restore":
                subprocess.run(['osascript', '-e',
                    'tell application "System Events" to keystroke "f" using {control down, command down}'],
                    capture_output=True)
            return f"{action.capitalize()}d window '{target}'"
    except Exception as e:
        return f"Window control failed: {str(e)}"

def get_exchange_rate(from_curr, to_curr):
    curr_map = {
        "rupees": "INR", "rupee": "INR", "inr": "INR",
        "dollars": "USD", "dollar": "USD", "usd": "USD",
        "euros": "EUR", "euro": "EUR", "eur": "EUR",
        "pounds": "GBP", "pound": "GBP", "gbp": "GBP",
        "yen": "JPY", "japanese yen": "JPY", "jpy": "JPY",
        "dirham": "AED", "aed": "AED", "canadian dollars": "CAD", "cad": "CAD",
        "australian dollars": "AUD", "aud": "AUD", "riyal": "SAR", "sar": "SAR",
        "yuan": "CNY", "cny": "CNY", "ruble": "RUB", "rubles": "RUB", "rub": "RUB"
    }
    f = curr_map.get(from_curr, from_curr.upper())
    t = curr_map.get(to_curr, to_curr.upper())
    
    db_path = os.path.join(os.path.dirname(__file__), "currency_cache.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS rates (pair TEXT PRIMARY KEY, rate REAL, timestamp TEXT)''')
    
    pair = f"{f}_{t}"
    c.execute("SELECT rate, timestamp FROM rates WHERE pair=?", (pair,))
    row = c.fetchone()
    
    now = datetime.now()
    
    if row:
        rate, timestamp_str = row
        last_fetch = datetime.fromisoformat(timestamp_str)
        if now - last_fetch < timedelta(days=1):
            conn.close()
            return rate, last_fetch
            
    try:
        url = f"https://open.er-api.com/v6/latest/{f}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
            if data['result'] == 'success':
                rate = data['rates'].get(t)
                if rate:
                    c.execute("REPLACE INTO rates (pair, rate, timestamp) VALUES (?, ?, ?)", (pair, rate, now.isoformat()))
                    conn.commit()
                    conn.close()
                    return rate, now
    except Exception as e:
        pass
        
    conn.close()
    if row:
        return row[0], datetime.fromisoformat(row[1])
    return None, None

_spoken_conversion_date = False

def handle_conversion(intent, entities):
    global _spoken_conversion_date
    amount = entities['amount']
    from_unit = entities['from_unit']
    to_unit = entities['to_unit']
    
    currencies = ["usd", "inr", "rupees", "rupee", "dollar", "dollars", "eur", "euro", "euros", 
                  "pound", "pounds", "gbp", "yen", "japanese yen", "jpy", "dirham", "aed", "canadian dollars", "cad", 
                  "australian dollars", "aud", "riyal", "sar", "yuan", "cny", "ruble", "rubles", "rub"]
    if from_unit in currencies or to_unit in currencies:
        rate, timestamp = get_exchange_rate(from_unit, to_unit)
        if rate:
            converted = amount * rate
            if not _spoken_conversion_date:
                date_str = timestamp.strftime("%d %B %Y")
                _spoken_conversion_date = True
                return f"{amount} {from_unit} is equal to {converted:.2f} {to_unit} (as per {date_str})"
            else:
                return f"{amount} {from_unit} is equal to {converted:.2f} {to_unit}"
        else:
            return f"Could not fetch exchange rate for {from_unit} to {to_unit}."
            
    try:
        if _ureg is None:
            return "The 'pint' library is not installed."
        unit_map = {
            "kilometers": "kilometer",
            "miles": "mile",
            "kilograms": "kilogram",
            "grams": "gram",
            "liters": "liter",
            "kilometer per hour": "kph",
            "kilometers per hour": "kph",
            "kmph": "kph",
            "miles per hour": "mph"
        }
        f_unit = unit_map.get(from_unit, from_unit)
        t_unit = unit_map.get(to_unit, to_unit)
        
        q1 = _ureg.Quantity(amount, f_unit)
        q2 = q1.to(t_unit)
        return f"{amount} {from_unit} = {q2.magnitude:.4f} {to_unit}"
    except ImportError:
        return "The 'pint' library is not installed."
    except Exception as e:
        return f"Conversion error: {e}"

def parse_intent(text, context=None):
    if context is None:
        context = []
        
    text = text.lower()
    for w in ["hey jarvis", "hi jarvis", "hello jarvis", "jarvis", "जार्विस", "जारविस", "जारvis"]:
        if text.startswith(w):
            text = text[len(w):].strip()
    if text.startswith(","):
        text = text[1:].strip()
    
    text = translate_hindi_keywords(text)
    
    intents = []
    
    # Split by 'and' to handle multi-actions
    clauses = [clause.strip() for clause in text.split(" and ")]
    
    for clause in clauses:
        intent = None
        entities = {}
        
        # CONVERSION
        conv_match = _CONV_PATTERN.search(clause)
        if conv_match:
            from_u = conv_match.group(2).strip().lower()
            to_u = conv_match.group(3).strip().lower()
            known_units = ["km", "kilometer", "kilometers", "mile", "miles", "kg", "kilogram", "kilograms", "gram", "grams", 
                           "celsius", "fahrenheit", "ml", "liter", "liters", "usd", "inr", "rupees", "rupee", "dollar", "dollars", 
                           "eur", "euro", "euros", "pound", "pounds", "gbp", "yen", "japanese yen", "jpy", "dirham", "aed", "cad", "aud", "sar", "cny", "rub", "ruble", "rubles",
                           "kilometer per hour", "kilometers per hour", "kmph", "miles per hour", "mph"]
            if from_u in known_units or to_u in known_units:
                word_to_num = {
                    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
                    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
                    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
                    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
                    "ninety": 90, "hundred": 100
                }
                amt_str = conv_match.group(1).lower()
                amount = float(word_to_num.get(amt_str, amt_str))
                
                intent = {"category": "conversion", "action": "convert"}
                entities['amount'] = amount
                entities['from_unit'] = from_u
                entities['to_unit'] = to_u
                intents.append((intent, entities))
                continue
                
        # SYSTEM CONTROLS
        if "volume" in clause or "awaaz" in clause:
            val = extract_percentage(clause)
            if "increase" in clause or "up" in clause: action = "increase"
            elif "decrease" in clause or "down" in clause: action = "decrease"
            elif "mute" in clause: action = "mute"
            elif "unmute" in clause: action = "unmute"
            else: action = "set"
            
            intent = {"category": "system", "action": action, "target": "volume"}
            if val is not None: entities['value'] = val
            
        elif "brightness" in clause:
            val = extract_percentage(clause)
            if "increase" in clause or "up" in clause: action = "increase"
            elif "decrease" in clause or "down" in clause: action = "decrease"
            else: action = "set"
            
            intent = {"category": "system", "action": action, "target": "brightness"}
            if val is not None: entities['value'] = val
            
        elif "status" in clause or ("tell me" in clause and ("cpu" in clause or "ram" in clause)):
            intent = {"category": "system", "action": "tell", "target": "stats"}
            
        # TV CONTROL
        elif "tv" in clause or "hdmi" in clause or "channel" in clause:
            if "find" in clause or "search" in clause and "tv" in clause:
                intent = {"category": "tv", "action": "discover"}
            elif "number 1" in clause or "the sony" in clause: # simplified selection
                intent = {"category": "tv", "action": "select"}
                entities['tv_index'] = 1 if "1" in clause or "sony" in clause else 2
            elif "turn on" in clause: intent = {"category": "tv", "action": "power_on"}
            elif "turn off" in clause or "close" in clause: intent = {"category": "tv", "action": "power_off"}
            elif "mute" in clause: intent = {"category": "tv", "action": "mute"}
            elif "unmute" in clause: intent = {"category": "tv", "action": "unmute"}
            elif "volume" in clause:
                val = extract_percentage(clause)
                action = "increase" if "increase" in clause else "decrease" if "decrease" in clause else "set"
                intent = {"category": "tv", "action": f"volume_{action}"}
                if val is not None: entities['value'] = val
            elif "open" in clause or "launch" in clause:
                intent = {"category": "tv", "action": "launch_app"}
                entities['app'] = clause.replace("open ", "").replace(" on tv", "").strip()
            elif "switch to" in clause or "hdmi" in clause:
                intent = {"category": "tv", "action": "switch_input"}
                match = re.search(r'hdmi\s*(\d+)', clause)
                if match: entities['input'] = f"HDMI {match.group(1)}"
                
        # SPOTIFY
        elif any(k in clause for k in ["play", "pause", "stop", "queue", "song", "spotify", "next", "previous", "skip", "loop", "repeat", "shuffle", "restart", "start over", "beginning"]):
            cleaned_clause = clause.strip()
            if re.match(r'^(play\s+)?(the\s+)?next(\s+song|\s+track)?(\s+in\s+queue)?$', cleaned_clause) or "skip" in cleaned_clause:
                action = "next"
            elif re.match(r'^(play\s+)?(the\s+)?previous(\s+song|\s+track)?$', cleaned_clause) or "restart" in cleaned_clause or "start over" in cleaned_clause or "from beginning" in cleaned_clause:
                if "restart" in cleaned_clause or "start over" in cleaned_clause or "beginning" in cleaned_clause:
                    action = "restart"
                else:
                    action = "previous"
            elif "shuffle" in cleaned_clause and ("play" not in cleaned_clause or cleaned_clause == "play on shuffle" or cleaned_clause == "play shuffle"):
                action = "shuffle"
                if "off" in cleaned_clause or "band" in cleaned_clause:
                    entities['state'] = False
                else:
                    entities['state'] = True
            elif "loop" in cleaned_clause or "repeat" in cleaned_clause:
                action = "loop"
                if "off" in cleaned_clause or "band" in cleaned_clause:
                    entities['loop_type'] = 'off'
                elif "playlist" in cleaned_clause:
                    entities['loop_type'] = 'context'
                else:
                    entities['loop_type'] = 'track'
            elif "pause" in clause or "stop" in clause: 
                action = "pause"
            elif "play" in clause:
                action = "play"
                song_str = clause
                if song_str.startswith("play "):
                    song_str = song_str[5:]
                elif song_str == "play":
                    song_str = ""
                else:
                    song_str = song_str.replace("play ", "")
                
                if "shuffle" in song_str:
                    entities['shuffle'] = True
                    song_str = song_str.replace("on shuffle", "").replace("shuffle", "").strip()
                
                song = song_str.split(" at ")[0].strip()
                if " by " in song:
                    parts = song.split(" by ", 1)
                    song = parts[0].strip()
                    entities['artist'] = parts[1].strip()
                    
                # Strip device keywords from song
                for dev_kw in [" on phone", " in phone", " on laptop", " in laptop", " on pc", " in pc", " on tv", " in tv"]:
                    if song.endswith(dev_kw):
                        song = song[:-len(dev_kw)].strip()
                    
                if song and song != "spotify": entities['song'] = song
            elif "queue" in clause:
                action = "queue"
                song = clause.replace("queue ", "").strip()
                if song.endswith(" next"):
                    song = song[:-5].strip()
                entities['song'] = song
            elif "open" in clause or "launch" in clause:
                action = "open"
            else: 
                action = "play"
            
            if " on phone" in clause or " in phone" in clause:
                entities['device'] = 'phone'
            elif " on laptop" in clause or " in laptop" in clause or " on computer" in clause or " on pc" in clause or " in pc" in clause:
                entities['device'] = 'laptop'
                
            val = extract_percentage(clause)
            if val is not None: entities['value'] = val
                
            intent = {"category": "spotify", "action": action}
            
        # BROWSER
        elif "search" in clause and ("for" in clause or "browser" in clause):
            intent = {"category": "browser", "action": "search"}
            entities['query'] = clause.replace("search for", "").replace("search", "").strip()
        elif "open" in clause and (".com" in clause or ".org" in clause or "url" in clause):
            intent = {"category": "browser", "action": "open"}
            entities['url'] = clause.replace("open ", "").strip()
            
        # WINDOW CONTROL
        elif "minimize" in clause or "maximize" in clause or "restore" in clause or "close" in clause:
            action = None
            if "minimize" in clause: action = "minimize"
            elif "maximize" in clause: action = "maximize"
            elif "close" in clause: action = "close"
            elif "restore" in clause: action = "restore"
            
            if action:
                intent = {"category": "window", "action": action}
                if "all" in clause or "sab" in clause or "saare" in clause:
                    entities['window_name'] = "all"
                elif "this" in clause or "ye" in clause or "current" in clause:
                    entities['window_name'] = "this"
                else:
                    target = clause.replace(action, "").replace("window", "").replace("windows", "").replace("set", "").replace("karo", "").strip()
                    if target:
                        entities['window_name'] = target
                    else:
                        entities['window_name'] = "this"

        # FILE OPERATIONS
        if not intent:
            file_actions = ["copy", "paste", "cut", "rename", "select all", "delete"]
            has_file_action = any(a in clause for a in file_actions)
            
            if has_file_action or "folder" in clause or "drive" in clause or "desktop" in clause or "download" in clause or "document" in clause or "recycle bin" in clause or "trash" in clause or (("file" in clause) and ("what" in clause or "show" in clause or "list" in clause)):
                action = None
                if ("recycle bin" in clause or "trash" in clause) and ("empty" in clause or "clear" in clause):
                    action = "empty_bin"
                elif "what files" in clause or "show files" in clause or "list" in clause:
                    action = "list"
                elif "open" in clause:
                    action = "open"
                elif "create" in clause and ("folder" in clause or "file" in clause):
                    action = "create_folder"
                elif "copy" in clause: action = "copy"
                elif "paste" in clause: action = "paste"
                elif "cut" in clause: action = "cut"
                elif "rename" in clause: action = "rename"
                elif "select all" in clause: action = "select_all"
                elif "delete" in clause: action = "delete"
                
                if action:
                    intent = {"category": "file", "action": action}
                    
                    if action in ["open", "list", "create_folder", "delete"]:
                        folder = ""
                        drive_letter = None
                        
                        drive_match = re.search(r'\b([a-z])\s*drive\b', clause)
                        if drive_match:
                            drive_letter = drive_match.group(1).upper()
                            clause = clause.replace(drive_match.group(0), "")
                            
                        if "desktop" in clause: folder = "desktop"
                        elif "download" in clause: folder = "downloads"
                        elif "document" in clause: folder = "documents"
                        elif "picture" in clause: folder = "pictures"
                        elif "music" in clause: folder = "music"
                        elif "video" in clause: folder = "videos"
                        
                        if not folder:
                            clean_clause = clause
                            stop_words = ["open", "create", "delete", "list", "show", "what", "files", "file", "folder", "in", "on", "this", "set", "karo", "the", "a", "new"]
                            for w in stop_words:
                                clean_clause = re.sub(r'\b' + re.escape(w) + r'\b', '', clean_clause, flags=re.IGNORECASE)
                            clean_clause = re.sub(r'\s+', ' ', clean_clause).strip()
                            
                            if clean_clause:
                                folder = clean_clause
                            elif drive_letter:
                                folder = f"{drive_letter} drive"
                            else:
                                folder = "current"
                                
                        entities['folder'] = folder
                        if drive_letter and folder != f"{drive_letter} drive":
                            entities['drive'] = drive_letter

        # APP LAUNCHER (Fallback for "open X")
        if not intent and "open" in clause:
            intent = {"category": "app", "action": "launch"}
            entities['app_name'] = clause.replace("open ", "").strip()
            
        # BLUETOOTH (Explicit keywords)
        elif "bluetooth" in clause or "device" in clause or "earphones" in clause or "earbuds" in clause or "headphones" in clause or "pair" in clause or "unpair" in clause:
            if "show" in clause and "previous" in clause:
                intent = {"category": "bluetooth", "action": "list_previous"}
            elif "show" in clause and "paired" in clause:
                intent = {"category": "bluetooth", "action": "list_active"}
            elif "scan" in clause or "search" in clause or "nay" in clause or "new" in clause or "available" in clause:
                intent = {"category": "bluetooth", "action": "scan"}
                clean = clause.replace("scan", "").replace("search", "").replace("bluetooth", "").replace("devices", "").replace("device", "").replace("for", "").replace("new", "").replace("available", "").replace("the", "").replace("my", "").strip()
                if clean:
                    entities['filter_keyword'] = clean
            elif "disconnect" in clause or "unpair" in clause:
                intent = {"category": "bluetooth", "action": "disconnect"}
                dev = clause.replace("disconnect from ", "").replace("disconnect ", "").replace("unpair from ", "").replace("unpair ", "").replace("bluetooth", "").replace("devices", "").replace("device", "").strip()
                if "all" in dev or "saare" in dev or "sab" in dev:
                    entities['device_name'] = "all"
                elif "latest" in dev or "last" in dev or "current" in dev or dev == "the":
                    entities['device_name'] = "latest"
                elif dev: 
                    entities['device_name'] = dev
                else:
                    entities['device_name'] = "latest"
            elif "connect" in clause or "pair" in clause:
                intent = {"category": "bluetooth", "action": "connect"}
                dev = clause.replace("connect to ", "").replace("connect ", "").replace("pair with ", "").replace("pair ", "").replace("mera ", "").replace(" earphones", "").replace(" earbuds", "").replace(" headphones", "").replace(" device", "").replace(" bluetooth", "").replace(" karo", "").replace(" set", "").strip()
                if dev: entities['device_name'] = dev

        # AMBIGUOUS CONNECT/DISCONNECT (Relies on Context)
        elif "connect " in clause or "disconnect " in clause:
            inferred_category = "bluetooth" # Default to bluetooth for natural phrasing
            # Check last 5 commands for context
            for past_intent in reversed(context[-5:]):
                if past_intent['category'] in ['wifi', 'bluetooth']:
                    inferred_category = past_intent['category']
                    break
            
            if inferred_category:
                if "disconnect" in clause:
                    intent = {"category": inferred_category, "action": "disconnect"}
                    dev = clause.replace("disconnect from ", "").replace("disconnect ", "").strip()
                    if dev:
                        if inferred_category == "bluetooth": entities['device_name'] = dev
                        else: entities['ssid'] = dev
                else:
                    intent = {"category": inferred_category, "action": "connect"}
                    dev = clause.replace("connect to ", "").replace("connect ", "").replace("mera ", "").replace(" karo", "").replace(" set", "").strip()
                    if dev:
                        if inferred_category == "bluetooth": entities['device_name'] = dev
                        else: entities['ssid'] = dev

        if intent:
            intents.append((intent, entities))
            
    return intents

_bt_paired_devices = None
_bt_scanned_devices = []
_bt_last_connected_device = None

def handle_bluetooth(intent, entities):
    global _bt_paired_devices, _bt_scanned_devices, _bt_last_connected_device
    action = intent['action']
    if action == "pair":
        action = "connect"
    elif action == "unpair":
        action = "disconnect"
        
    dev = entities.get('device_name', '')
    
    if not HAS_BLUETOOTH:
        return "Real Bluetooth is unavailable (import failed)."
        
    if _bt_paired_devices is None:
        _bt_paired_devices = bt_module.get_paired_devices()
        
    if action == "scan":
        print("Real Bluetooth: Scanning for nearby devices...")
        filter_kw = entities.get('filter_keyword')
        _bt_scanned_devices = asyncio.run(bt_module.scan_nearby_devices(filter_keyword=filter_kw))
        names = [d['name'] for d in _bt_scanned_devices]
        
        if filter_kw:
            if names:
                if len(names) == 1:
                    return f"Found 1 {filter_kw} bluetooth device. It is {names[0]}."
                else:
                    return f"Found {len(names)} {filter_kw} bluetooth devices. Do not read any names. Just ask the user if they want to pair a specific device, or if they want you to list them all (by using the 'list_scanned' action later)."
            else:
                return f"No {filter_kw} bluetooth devices found."
        else:
            if names:
                if len(names) == 1:
                    return f"Found 1 bluetooth device. It is {names[0]}."
                else:
                    return f"Found {len(names)} bluetooth devices. Do not read any names. Just ask the user if they want to pair a specific device, or if they want you to list them all (by using the 'list_scanned' action later)."
            else:
                return "No new bluetooth devices found."
    elif action == "list_scanned":
        if not _bt_scanned_devices:
            return "No recently scanned devices found. You may need to run a scan first."
        names = [d['name'] for d in _bt_scanned_devices]
        return f"Recently scanned devices: {', '.join(names)}"
    elif action == "list_previous":
        if _bt_paired_devices is None:
            _bt_paired_devices = bt_module.get_paired_devices()
        names = [d['name'] for d in _bt_paired_devices]
        return f"Previously paired devices: {', '.join(names)}" if names else "No previously paired devices found."
    elif action == "list_active":
        active = bt_module.get_connected_devices()
        names = [d['name'] for d in active]
        return f"Actively paired devices: {', '.join(names)}" if names else "No devices currently connected."
    elif action == "connect":
        print(f"Real Bluetooth: Attempting to connect to '{dev}'...")
        asyncio.run(bt_module.connect_to_device(dev, _bt_paired_devices, _bt_scanned_devices))
        _bt_paired_devices = bt_module.get_paired_devices() # Refresh list
        _bt_last_connected_device = dev
        return f"Finished connection sequence for '{dev}'."
    elif action == "disconnect":
        if dev == "all":
            active = bt_module.get_connected_devices()
            if not active:
                return "Real Bluetooth: No active connections to disconnect."
            names = []
            for d in active:
                name = d['name']
                print(f"Real Bluetooth: Attempting to disconnect '{name}'...")
                asyncio.run(bt_module.disconnect_device(name, _bt_paired_devices))
                names.append(name)
            _bt_paired_devices = bt_module.get_paired_devices()
            _bt_last_connected_device = None
            return f"Disconnected all active devices: {', '.join(names)}."
        else:
            if not dev or dev == "latest":
                if _bt_last_connected_device:
                    dev = _bt_last_connected_device
                    print(f"Real Bluetooth: No device specified. Falling back to last connected device '{dev}'.")
                else:
                    active = bt_module.get_connected_devices()
                    if active:
                        dev = active[0]['name']
                        print(f"Real Bluetooth: Falling back to first active connection '{dev}'.")
                    else:
                        return "Real Bluetooth: No active connection found to disconnect."
                
            if dev:
                print(f"Real Bluetooth: Attempting to disconnect '{dev}'...")
                asyncio.run(bt_module.disconnect_device(dev, _bt_paired_devices))
                _bt_paired_devices = bt_module.get_paired_devices() # Refresh list
                if _bt_last_connected_device == dev:
                    _bt_last_connected_device = None
                return f"Finished disconnect sequence for '{dev}'."
    return f"Real Bluetooth Action: {action}"

def execute_intent(intent, entities):
    cat = intent['category']
    if cat == "system": return handle_system_controls(intent, entities)
    elif cat == "app": return handle_app_launcher(intent, entities)
    elif cat == "browser": return handle_browser_control(intent, entities)
    elif cat == "spotify": return handle_spotify_control(intent, entities)
    elif cat == "tv": return handle_tv_control(intent, entities)
    elif cat == "window": return handle_window_control(intent, entities)
    elif cat == "file": return handle_file_operations(intent, entities)
    elif cat == "conversion": return handle_conversion(intent, entities)
    elif cat == "bluetooth": return handle_bluetooth(intent, entities)
    return "Unknown category"

# ---------------------------------------------------------------------------
# JARVIS INTEGRATION
# ---------------------------------------------------------------------------

def process_fast_lane(text, context_history=None):
    if context_history is None:
        context_history = []
        
    intents = parse_intent(text, context_history)
    
    if not intents:
        return False, None
        
    msgs = []
    for intent, entities in intents:
        context_history.append(intent)
        if len(context_history) > 20:
            context_history.pop(0)
            
        try:
            res = execute_intent(intent, entities)
            msgs.append(res)
        except Exception as e:
            msgs.append(f"Fast Lane Error: {e}")
            traceback.print_exc()
            
    return True, " | ".join(msgs)


# ---------------------------------------------------------------------------
# TRIVIAL FAST LANE — instant execution for unambiguous simple commands
# ---------------------------------------------------------------------------
_TRIVIAL_MEDIA = {
    "pause": ("pause", {}), "stop": ("pause", {}), "stop the music": ("pause", {}),
    "pause the music": ("pause", {}), "pause music": ("pause", {}),
    "play": ("play", {}), "resume": ("play", {}), "resume music": ("play", {}),
    "play music": ("play", {}), "continue": ("play", {}),
    "next": ("next", {}), "next song": ("next", {}), "next track": ("next", {}),
    "skip": ("next", {}), "skip this": ("next", {}), "skip song": ("next", {}),
    "previous": ("previous", {}), "previous song": ("previous", {}),
    "previous track": ("previous", {}), "go back": ("previous", {}),
    "repeat": ("restart", {}), "repeat this": ("restart", {}),
    "repeat this song": ("restart", {}), "restart": ("restart", {}),
    "restart song": ("restart", {}), "restart this song": ("restart", {}),
    "loop": ("loop", {"loop_type": "track"}), "loop this": ("loop", {"loop_type": "track"}),
    "loop this song": ("loop", {"loop_type": "track"}),
    "shuffle": ("shuffle", {"state": True}), "shuffle on": ("shuffle", {"state": True}),
    "shuffle off": ("shuffle", {"state": False}),
}

_TRIVIAL_SYSTEM = {
    "mute": ("mute", "volume", {}), "mute system": ("mute", "volume", {}),
    "unmute": ("unmute", "volume", {}), "unmute system": ("unmute", "volume", {}),
    "volume up": ("increase", "volume", {}), "increase volume": ("increase", "volume", {}),
    "louder": ("increase", "volume", {}),
    "volume down": ("decrease", "volume", {}), "decrease volume": ("decrease", "volume", {}),
    "lower volume": ("decrease", "volume", {}), "quieter": ("decrease", "volume", {}),
    "brightness up": ("increase", "brightness", {}), "increase brightness": ("increase", "brightness", {}),
    "brighter": ("increase", "brightness", {}),
    "brightness down": ("decrease", "brightness", {}), "decrease brightness": ("decrease", "brightness", {}),
    "dimmer": ("decrease", "brightness", {}), "dim": ("decrease", "brightness", {}),
}

_TRIVIAL_FILE = {
    "copy": "copy", "copy this": "copy",
    "paste": "paste", "paste it": "paste",
    "cut": "cut", "cut this": "cut",
    "select all": "select_all",
}

_VOL_SET_RE = re.compile(r'^(?:set\s+)?volume\s+(?:to\s+)?(\d+)(?:\s*%)?$')
_BR_SET_RE = re.compile(r'^(?:set\s+)?brightness\s+(?:to\s+)?(\d+)(?:\s*%)?$')


def try_trivial_fast_lane(text):
    """Try to match trivial, unambiguous commands that don't need LLM.

    Returns (True, result_msg) if matched, (False, None) otherwise.
    Only handles dead-simple single commands; everything else goes to Ollama.
    """
    clean = text.lower().strip().rstrip(".,!?")

    # Strip wake word prefix
    from config.config import WAKE_WORDS
    for w in WAKE_WORDS:
        if clean.startswith(w):
            clean = clean[len(w):].strip()
    if clean.startswith(","):
        clean = clean[1:].strip()

    # Translate Hindi keywords for matching
    clean = translate_hindi_keywords(clean)

    if not clean:
        return False, None

    # Media controls (exact matches)
    if clean in _TRIVIAL_MEDIA:
        action, extra_entities = _TRIVIAL_MEDIA[clean]
        return True, handle_spotify_control({"category": "spotify", "action": action}, extra_entities)

    # System controls (exact matches)
    if clean in _TRIVIAL_SYSTEM:
        action, target, entities = _TRIVIAL_SYSTEM[clean]
        return True, handle_system_controls({"category": "system", "action": action, "target": target}, entities)

    # Volume set with value (e.g., "volume 50", "set volume to 80")
    vol_match = _VOL_SET_RE.match(clean)
    if vol_match:
        val = int(vol_match.group(1))
        return True, handle_system_controls(
            {"category": "system", "action": "set", "target": "volume"}, {"value": val}
        )

    # Brightness set with value
    br_match = _BR_SET_RE.match(clean)
    if br_match:
        val = int(br_match.group(1))
        return True, handle_system_controls(
            {"category": "system", "action": "set", "target": "brightness"}, {"value": val}
        )

    # File operations (exact matches)
    if clean in _TRIVIAL_FILE:
        action = _TRIVIAL_FILE[clean]
        return True, handle_file_operations({"category": "file", "action": action}, {})

    return False, None
