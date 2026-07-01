"""Windows-specific: start Chrome subprocess, then immediately hide the
visible window so it doesn't bother the user.

Uses ctypes for direct Win32 calls (no pywin32 dependency).
"""
import ctypes
import ctypes.wintypes
import subprocess
import sys
import time
from typing import Optional

# Win32 constants
SW_HIDE = 0
SW_MINIMIZE = 6
SW_SHOWMINNOACTIVE = 7
HWND_BOTTOM = 1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_HIDEWINDOW = 0x0080
SWP_SHOWWINDOW = 0x0040

user32 = ctypes.windll.user32
user32.FindWindowW.argtypes = [ctypes.wintypes.LPCWSTR, ctypes.wintypes.LPCWSTR]
user32.FindWindowW.restype = ctypes.wintypes.HWND
user32.ShowWindow.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = ctypes.c_bool
user32.SetWindowPos.argtypes = [
    ctypes.wintypes.HWND, ctypes.wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_uint,
]
user32.SetWindowPos.restype = ctypes.c_bool
user32.GetWindowThreadProcessId.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.c_uint)]
user32.GetWindowThreadProcessId.restype = ctypes.c_uint
user32.EnumWindows = ctypes.windll.user32.EnumWindows
user32.EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
user32.IsWindowVisible.restype = ctypes.c_bool
user32.GetWindowTextW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int


def find_chrome_window(pid: int, timeout: float = 5.0) -> Optional[int]:
    """Find the first visible top-level window belonging to the given PID.

    Win32 quirk: GetWindowTextW doesn't work inside EnumWindows callback for
    many window types. We collect HWNDs first, then query title after.
    """
    import sys as _sys
    deadline = time.time() + timeout
    candidate_hwnds = []

    def callback(hwnd, lparam):
        owner_pid = ctypes.c_uint(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if owner_pid.value == pid and user32.IsWindowVisible(hwnd):
            candidate_hwnds.append(hwnd)
        return True

    while time.time() < deadline and not candidate_hwnds:
        user32.EnumWindows(user32.EnumWindowsProc(callback), 0)
        if not candidate_hwnds:
            time.sleep(0.2)

    if not candidate_hwnds:
        return None

    # Now query titles for each candidate (outside the callback)
    for hwnd in candidate_hwnds:
        length = user32.GetWindowTextW(hwnd, None, 0)
        if length == 0:
            continue
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if title and len(title) >= 3 and "MSCTFIME" not in title and "Default IME" not in title:
            return hwnd

    # Fallback: if no title matched, return the first visible HWND
    return candidate_hwnds[0] if candidate_hwnds else None


def hide_window(hwnd: int):
    """Hide the window completely (off-screen + not shown in taskbar)."""
    # Move it way off-screen first
    user32.SetWindowPos(
        hwnd, HWND_BOTTOM,
        -32000, -32000, 0, 0,
        SWP_NOSIZE | SWP_NOACTIVATE | SWP_HIDEWINDOW
    )
    # Then ensure it's hidden
    user32.ShowWindow(hwnd, SW_HIDE)


def launch_chrome_hidden(args: list, hide_after: float = 0.5) -> subprocess.Popen:
    """Launch Chrome with the given args, then immediately hide the visible window.

    Returns the Popen object for later termination.
    """
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Wait for window to appear
    time.sleep(hide_after)
    hwnd = find_chrome_window(proc.pid, timeout=3.0)
    if hwnd:
        hide_window(hwnd)
        sys.stderr.write(f"[gemini-search] Chrome PID {proc.pid} window hidden (HWND={hwnd})\n")
    else:
        sys.stderr.write(f"[gemini-search] WARN: Chrome PID {proc.pid} window not found in {3.0}s\n")
    return proc


if __name__ == "__main__":
    # Smoke test
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    args = [chrome, "--remote-debugging-port=19999",
            "--user-data-dir=C:/tmp/chrome-test-hidden",
            "--no-first-run", "--no-default-browser-check",
            "about:blank"]
    proc = launch_chrome_hidden(args)
    print(f"Launched PID {proc.pid}. Window should be hidden. Check taskbar.")
    time.sleep(2)
    proc.terminate()
    proc.wait(5)