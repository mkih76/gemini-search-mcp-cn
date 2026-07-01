"""One-shot CAPTCHA priming: launch visible Chrome, navigate to Google,
   poll until user closes the window or /sorry/ disappears, then exit.

Usage:
    python prime_chrome.py --profile-dir <path>

Behavior:
    1. Launch chrome.exe (visible) with --remote-debugging-port=19250
    2. Open about:blank tab
    3. Wait up to N seconds for the user to either:
       a) close the window (success - cookies already saved to profile dir)
       b) navigate to google.com.hk/search?q=hello without /sorry/ (success)
    4. Cleanly shutdown Chrome and exit
"""
import argparse
import os
import subprocess
import sys
import time
import urllib.request
import json

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
PORT = 19250


def find_chrome() -> str:
    for p in CHROME_PATHS:
        if os.path.isfile(p):
            return p
    raise RuntimeError("Chrome not found in standard locations")


def wait_for_cdp(port: int, timeout: float = 20) -> str:
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            data = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=2
            ).read()
            return json.loads(data)["webSocketDebuggerUrl"]
        except Exception as e:
            last_err = e
            time.sleep(0.5)
    raise RuntimeError(f"CDP not ready after {timeout}s: {last_err}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile-dir", required=True, help="Persistent Chrome profile dir")
    ap.add_argument("--wait-seconds", type=int, default=180,
                    help="How long to wait for user to solve CAPTCHA (default 180s)")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()

    profile_dir = os.path.abspath(args.profile_dir)
    os.makedirs(profile_dir, exist_ok=True)

    chrome = find_chrome()
    print(f"Chrome:  {chrome}")
    print(f"Profile: {profile_dir}")
    print(f"Port:    {args.port}")
    print()

    proc = subprocess.Popen(
        [
            chrome,
            f"--remote-debugging-port={args.port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--start-maximized",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        wait_for_cdp(args.port, timeout=20)
        print(f"[OK] Chrome launched, CDP on port {args.port}")
        print()
        print("=" * 60)
        print("MANUAL STEPS:")
        print("  1. A Chrome window should now be visible.")
        print("  2. Open https://www.google.com.hk/search?q=hello in it.")
        print("  3. If Google shows /sorry/ CAPTCHA, solve it.")
        print("  4. Once you see normal search results, close the window.")
        print(f"  5. This script will auto-exit when Chrome closes, or after")
        print(f"     {args.wait_seconds}s timeout (whichever comes first).")
        print("=" * 60)
        print()

        deadline = time.time() + args.wait_seconds
        # Poll: proc.poll() returns None if still running
        while time.time() < deadline:
            if proc.poll() is not None:
                print("[OK] Chrome window closed by user. Assuming CAPTCHA solved.")
                return 0
            time.sleep(2)

        print(f"[TIMEOUT] {args.wait_seconds}s elapsed. Killing Chrome.")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        return 1
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
