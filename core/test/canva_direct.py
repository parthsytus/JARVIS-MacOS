"""
==========================================================
JARVIS — Canva Direct Design Creator
==========================================================

Creates designs directly in your Canva account and opens
them in the Canva editor (app or browser).

First run: authenticates via browser OAuth.
After that: cached token is reused.

Usage:
  venv/bin/python core/test/canva_direct.py

Examples:
  > poster 1080x1920 "BGMI Tournament"
  > presentation "Quarterly Report"
  > instagram "Summer Sale"
  > open last         ← re-open last design in Canva
  > list              ← list recent designs
  > quit

Author: JARVIS-MacOS
"""

import sys
import os
import json
import time
import asyncio
import hashlib
import base64
import secrets
import webbrowser
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs
from threading import Thread
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
except ImportError:
    pass

try:
    import httpx
except ImportError:
    print("  ❌ httpx not installed. Run: venv/bin/pip install httpx")
    sys.exit(1)

# ── Configuration ─────────────────────────────────────────────
CANVA_CLIENT_ID = os.getenv("CANVA_CLIENT_ID", "")
CANVA_CLIENT_SECRET = os.getenv("CANVA_CLIENT_SECRET", "")

CANVA_AUTH_BASE = "https://www.canva.com/api/oauth/authorize"
CANVA_TOKEN_URL = "https://api.canva.com/rest/v1/oauth/token"
CANVA_API_BASE = "https://api.canva.com/rest/v1"

REDIRECT_PORT = 8765
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"

TOKEN_CACHE = os.path.join(PROJECT_ROOT, ".canva_user_token.json")

SCOPES = "design:content:write design:meta:read design:content:read"

# Canva preset design types
DESIGN_PRESETS = {
    "poster": {"name": "Poster", "width": 1080, "height": 1920},
    "presentation": {"name": "Presentation (16:9)", "preset": "presentation_16_9"},
    "instagram": {"name": "Instagram Post", "preset": "instagram_post"},
    "instagram_story": {"name": "Instagram Story", "preset": "instagram_story"},
    "facebook": {"name": "Facebook Post", "preset": "facebook_post"},
    "twitter": {"name": "Twitter Post", "preset": "twitter_post"},
    "youtube": {"name": "YouTube Thumbnail", "preset": "youtube_thumbnail"},
    "flyer": {"name": "Flyer", "width": 1270, "height": 1651},
    "a4": {"name": "A4 Document", "width": 2480, "height": 3508},
    "logo": {"name": "Logo", "width": 500, "height": 500},
    "banner": {"name": "Banner", "width": 2560, "height": 1440},
    "card": {"name": "Card", "width": 1050, "height": 750},
    "resume": {"name": "Resume", "width": 2480, "height": 3508},
    "invitation": {"name": "Invitation", "width": 1400, "height": 2000},
    "story": {"name": "Story", "width": 1080, "height": 1920},
    "reel": {"name": "Reel", "width": 1080, "height": 1920},
    "tiktok": {"name": "TikTok Video", "width": 1080, "height": 1920},
    "linkedin": {"name": "LinkedIn Post", "preset": "linkedin_post"},
    "pinterest": {"name": "Pinterest Pin", "width": 1000, "height": 1500},
    "custom": {"name": "Custom", "width": 1920, "height": 1080},
}


# ── PKCE Helpers ──────────────────────────────────────────────

def generate_pkce():
    """Generate PKCE code_verifier and code_challenge."""
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


# ── OAuth Callback Server ────────────────────────────────────

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler to capture OAuth callback."""
    auth_code = None
    state_received = None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/callback":
            params = parse_qs(parsed.query)
            OAuthCallbackHandler.auth_code = params.get("code", [None])[0]
            OAuthCallbackHandler.state_received = params.get("state", [None])[0]

            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
            <html><body style="background:#0A0A0A;color:#00FF88;font-family:sans-serif;
            display:flex;align-items:center;justify-content:center;height:100vh;margin:0;">
            <div style="text-align:center;">
            <h1 style="font-size:48px;">&#10003;</h1>
            <h2>JARVIS Connected to Canva!</h2>
            <p style="color:#888;">You can close this tab and return to the terminal.</p>
            </div></body></html>
            """)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Silence logs


def run_oauth_server(port: int) -> HTTPServer:
    """Start the OAuth callback server."""
    server = HTTPServer(("127.0.0.1", port), OAuthCallbackHandler)
    thread = Thread(target=server.handle_request, daemon=True)
    thread.start()
    return server


# ── Token Management ──────────────────────────────────────────

def load_cached_token() -> dict:
    """Load cached token if it exists and is not expired."""
    if not os.path.exists(TOKEN_CACHE):
        return None
    try:
        with open(TOKEN_CACHE) as f:
            data = json.load(f)
        # Check expiry (with 5 min buffer)
        if time.time() < data.get("expires_at", 0) - 300:
            return data
        # Try refresh
        if data.get("refresh_token"):
            return refresh_token(data["refresh_token"])
        return None
    except Exception:
        return None


def save_token(token_data: dict):
    """Save token to cache."""
    with open(TOKEN_CACHE, "w") as f:
        json.dump(token_data, f, indent=2)


def refresh_token(refresh_tok: str) -> dict:
    """Refresh an expired access token."""
    try:
        resp = httpx.post(
            CANVA_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_tok,
                "client_id": CANVA_CLIENT_ID,
                "client_secret": CANVA_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        token_data = {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", refresh_tok),
            "expires_at": time.time() + data.get("expires_in", 3600),
            "token_type": data.get("token_type", "Bearer"),
        }
        save_token(token_data)
        return token_data
    except Exception as e:
        print(f"  ⚠️  Token refresh failed: {e}")
        return None


def do_oauth_flow() -> dict:
    """Run the full OAuth flow with PKCE."""
    print("\n  🔐 Authenticating with Canva...")
    print("  A browser window will open for you to log in.\n")

    code_verifier, code_challenge = generate_pkce()
    state = secrets.token_urlsafe(32)

    # Start callback server
    server = run_oauth_server(REDIRECT_PORT)

    # Build auth URL
    auth_params = {
        "response_type": "code",
        "client_id": CANVA_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{CANVA_AUTH_BASE}?{urlencode(auth_params)}"

    # Open browser
    webbrowser.open(auth_url)
    print("  ⏳ Waiting for Canva login... (check your browser)")

    # Wait for callback (max 120s)
    deadline = time.time() + 120
    while OAuthCallbackHandler.auth_code is None and time.time() < deadline:
        time.sleep(0.5)

    server.server_close()

    if not OAuthCallbackHandler.auth_code:
        print("  ❌ OAuth timed out. Try again.")
        return None

    if OAuthCallbackHandler.state_received != state:
        print("  ❌ OAuth state mismatch (possible CSRF). Try again.")
        return None

    auth_code = OAuthCallbackHandler.auth_code
    # Reset for next time
    OAuthCallbackHandler.auth_code = None
    OAuthCallbackHandler.state_received = None

    # Exchange code for token
    try:
        resp = httpx.post(
            CANVA_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CANVA_CLIENT_ID,
                "client_secret": CANVA_CLIENT_SECRET,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

        token_data = {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", ""),
            "expires_at": time.time() + data.get("expires_in", 3600),
            "token_type": data.get("token_type", "Bearer"),
        }
        save_token(token_data)
        print("  ✅ Connected to Canva!")
        return token_data

    except httpx.HTTPStatusError as e:
        print(f"  ❌ Token exchange failed: {e.response.status_code}")
        print(f"     {e.response.text}")
        return None
    except Exception as e:
        print(f"  ❌ Token exchange error: {e}")
        return None


def get_token() -> str:
    """Get a valid access token, refreshing or re-authing if needed."""
    cached = load_cached_token()
    if cached:
        return cached["access_token"]

    result = do_oauth_flow()
    if result:
        return result["access_token"]
    return None


# ── Canva API Calls ───────────────────────────────────────────

def canva_create_design(token: str, title: str = "Untitled",
                        preset: str = None,
                        width: int = None, height: int = None) -> dict:
    """Create a design in Canva and return the response with edit_url."""

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Build request body according to Canva Connect API
    if preset:
        body = {
            "design_type": {
                "type": "preset",
                "name": preset,
            },
            "title": title,
        }
    elif width and height:
        body = {
            "design_type": {
                "type": "custom",
                "width": width,
                "height": height,
            },
            "title": title,
        }
    else:
        body = {
            "design_type": {
                "type": "custom",
                "width": 1080,
                "height": 1920,
            },
            "title": title,
        }

    resp = httpx.post(
        f"{CANVA_API_BASE}/designs",
        json=body,
        headers=headers,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def canva_get_design(token: str, design_id: str) -> dict:
    """Get design details including edit URL."""
    headers = {"Authorization": f"Bearer {token}"}
    resp = httpx.get(
        f"{CANVA_API_BASE}/designs/{design_id}",
        headers=headers,
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()


def canva_list_designs(token: str, limit: int = 10) -> dict:
    """List recent designs."""
    headers = {"Authorization": f"Bearer {token}"}
    resp = httpx.get(
        f"{CANVA_API_BASE}/designs",
        params={"limit": limit},
        headers=headers,
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()


def open_in_canva(url: str):
    """Open a Canva URL — tries Canva app first, falls back to browser."""
    # Try Canva desktop app on macOS
    try:
        result = subprocess.run(
            ["open", "-a", "Canva", url],
            capture_output=True, timeout=5
        )
        if result.returncode == 0:
            print("  🖥️  Opened in Canva app")
            return
    except Exception:
        pass

    # Fallback to browser
    webbrowser.open(url)
    print("  🌐 Opened in browser")


# ── Session ───────────────────────────────────────────────────

class CanvaSession:
    def __init__(self):
        self.token = None
        self.last_design_id = None
        self.last_edit_url = None
        self.designs_created = 0

    def ensure_auth(self) -> bool:
        if not self.token:
            self.token = get_token()
        if not self.token:
            print("  ❌ Not authenticated. Cannot continue.")
            return False
        return True

    def create_and_open(self, title: str, preset: str = None,
                        width: int = None, height: int = None):
        """Create a design and open it in Canva."""
        if not self.ensure_auth():
            return

        try:
            print(f"  ☁️  Creating design in Canva...")
            result = canva_create_design(
                self.token, title=title,
                preset=preset, width=width, height=height
            )

            # Extract design info from response
            design = result.get("design", result)
            design_id = design.get("id", "")
            urls = design.get("urls", {})
            edit_url = urls.get("edit_url", "")

            # If no edit_url in create response, fetch it
            if not edit_url and design_id:
                time.sleep(1)  # Brief pause for design to be ready
                detail = canva_get_design(self.token, design_id)
                design_detail = detail.get("design", detail)
                urls = design_detail.get("urls", {})
                edit_url = urls.get("edit_url", "")

            if not edit_url:
                # Construct URL manually as fallback
                edit_url = f"https://www.canva.com/design/{design_id}/edit"

            self.last_design_id = design_id
            self.last_edit_url = edit_url
            self.designs_created += 1

            print(f"  ✅ Design created: {title}")
            print(f"  📋 ID: {design_id}")

            # Open in Canva
            open_in_canva(edit_url)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                print("  ⚠️  Token expired, re-authenticating...")
                self.token = None
                if self.ensure_auth():
                    self.create_and_open(title, preset, width, height)
            else:
                print(f"  ❌ API error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            print(f"  ❌ Error: {e}")

    def list_designs(self):
        """List recent designs."""
        if not self.ensure_auth():
            return
        try:
            result = canva_list_designs(self.token)
            items = result.get("items", result.get("designs", []))
            if not items:
                print("  📭 No designs found")
                return
            print(f"\n  📋 Recent Designs:")
            for i, item in enumerate(items[:10], 1):
                d = item.get("design", item)
                title = d.get("title", "Untitled")
                did = d.get("id", "?")
                print(f"    {i}. {title}  (ID: {did})")
            print()
        except Exception as e:
            print(f"  ❌ Error listing designs: {e}")

    def open_last(self):
        """Re-open the last created design."""
        if self.last_edit_url:
            open_in_canva(self.last_edit_url)
        else:
            print("  ⚠️  No design created yet in this session")


# ── Command Parser ────────────────────────────────────────────

import re

def extract_quoted(text: str) -> str:
    match = re.search(r'["\'](.+?)["\']', text)
    return match.group(1) if match else ""

def extract_dimensions(text: str):
    match = re.search(r'(\d+)\s*[xX×]\s*(\d+)', text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def parse_command(session: CanvaSession, user_input: str):
    """Parse and execute a command."""
    text = user_input.strip()
    text_lower = text.lower()

    if not text:
        return

    # ── List ──
    if text_lower in ("list", "designs", "my designs", "show designs"):
        session.list_designs()
        return

    # ── Open Last ──
    if text_lower in ("open", "open last", "reopen", "edit"):
        session.open_last()
        return

    # ── Auth / Login ──
    if text_lower in ("login", "auth", "connect", "reconnect"):
        session.token = None
        if os.path.exists(TOKEN_CACHE):
            os.remove(TOKEN_CACHE)
        session.ensure_auth()
        return

    # ── Check for design type keywords ──
    title = extract_quoted(text) or "JARVIS Design"
    w, h = extract_dimensions(text)

    # Try to match a preset
    for key, preset_info in DESIGN_PRESETS.items():
        if key in text_lower:
            preset_name = preset_info.get("preset")
            pw = w or preset_info.get("width")
            ph = h or preset_info.get("height")

            if preset_name and not w:
                # Use Canva preset
                print(f"  📐 Type: {preset_info['name']}")
                session.create_and_open(title, preset=preset_name)
            else:
                # Custom dimensions
                print(f"  📐 Type: {preset_info['name']} ({pw}×{ph})")
                session.create_and_open(title, width=pw, height=ph)
            return

    # ── Generic "create" with dimensions ──
    if w and h:
        print(f"  📐 Custom: {w}×{h}")
        session.create_and_open(title, width=w, height=h)
        return

    # ── Just a title, default poster ──
    if any(kw in text_lower for kw in ["create", "make", "new", "design"]):
        title = extract_quoted(text) or "JARVIS Design"
        print(f"  📐 Type: Poster (1080×1920)")
        session.create_and_open(title, width=1080, height=1920)
        return

    print("  ❓ Could not parse. Type 'help' for commands.")


# ── Main ──────────────────────────────────────────────────────

def main():
    if not CANVA_CLIENT_ID or not CANVA_CLIENT_SECRET:
        print("  ❌ Missing Canva credentials!")
        print("     Set CANVA_CLIENT_ID and CANVA_CLIENT_SECRET in .env")
        sys.exit(1)

    print("=" * 56)
    print("  JARVIS — Canva Direct Design Creator")
    print("  Designs open directly in Canva for editing")
    print("=" * 56)
    print()
    print("  Commands:")
    print('    poster "BGMI Tournament"          ← 1080×1920 poster')
    print('    poster 800x1200 "Event Flyer"     ← custom size poster')
    print('    presentation "Q3 Report"          ← 16:9 slides')
    print('    instagram "Summer Sale"            ← 1080×1080 post')
    print('    instagram_story "Announcement"     ← 1080×1920 story')
    print('    youtube "Video Thumbnail"           ← 1280×720')
    print('    flyer "Music Night"                 ← standard flyer')
    print('    create 1200x628 "Ad Banner"        ← any custom size')
    print("    list                                ← show your designs")
    print("    open                                ← re-open last design")
    print("    login                               ← re-authenticate")
    print("    quit")
    print()
    print(f"  Available types: {', '.join(DESIGN_PRESETS.keys())}")
    print()

    session = CanvaSession()

    # Authenticate on startup
    print("  Checking authentication...")
    if not session.ensure_auth():
        print("  ⚠️  Could not authenticate. You can try 'login' later.")
    else:
        print("  🟢 Authenticated with Canva\n")

    while True:
        try:
            prompt = f"  [canva · {session.designs_created} created] > "
            user_input = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            break

        if user_input.lower() in ("help", "?"):
            print()
            print("  ── Design Types ──")
            for key, info in DESIGN_PRESETS.items():
                size = ""
                if "preset" in info:
                    size = f"(Canva preset)"
                elif "width" in info:
                    size = f"({info['width']}×{info['height']})"
                print(f"    {key:20s} {info['name']:25s} {size}")
            print()
            print("  ── Usage ──")
            print('    TYPE "Title"              ← create with preset size')
            print('    TYPE WxH "Title"          ← create with custom size')
            print('    create WxH "Title"        ← any custom dimensions')
            print("    list                       ← show recent designs")
            print("    open                       ← re-open last design")
            print("    login                      ← re-authenticate")
            print("    quit                       ← exit")
            print()
            continue

        parse_command(session, user_input)

    print(f"\n  📋 Session: {session.designs_created} design(s) created")
    print("  ✅ Done!\n")


if __name__ == "__main__":
    main()
