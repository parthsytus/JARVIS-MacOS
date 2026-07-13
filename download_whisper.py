#!/usr/bin/env python3
"""Robust downloader for whisper-large-v3-turbo with retries and resume support."""
import os
import time
import sys

def download_with_retries(max_retries=50, retry_delay=10):
    """Download the model with aggressive retry logic."""
    from huggingface_hub import snapshot_download
    from huggingface_hub.utils import HfHubHTTPError
    
    repo_id = "mlx-community/whisper-large-v3-turbo"
    token = None
    token_path = os.path.expanduser("~/.cache/huggingface/token")
    if os.path.exists(token_path):
        token = open(token_path).read().strip()
        print(f"[INFO] Using HF token from {token_path}")
    
    for attempt in range(1, max_retries + 1):
        try:
            print(f"\n[ATTEMPT {attempt}/{max_retries}] Downloading {repo_id}...")
            path = snapshot_download(
                repo_id,
                token=token,
                # force_download=False means it resumes from where it left off
                force_download=False,
                # Local dir caching
                local_files_only=False,
            )
            print(f"\n✅ SUCCESS! Model downloaded to: {path}")
            print("You can now run JARVIS normally.")
            return True
        except KeyboardInterrupt:
            print("\n[CANCELLED] Download cancelled by user.")
            sys.exit(1)
        except Exception as e:
            print(f"\n[ERROR] Attempt {attempt} failed: {type(e).__name__}: {e}")
            if attempt < max_retries:
                print(f"[RETRY] Waiting {retry_delay}s before retry...")
                time.sleep(retry_delay)
            else:
                print(f"\n❌ FAILED after {max_retries} attempts.")
                print("Try: connecting to a different network or using a VPN")
                return False

if __name__ == "__main__":
    download_with_retries()
