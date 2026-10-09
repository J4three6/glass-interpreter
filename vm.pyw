"""Capture Windows Live Captions in the VM and send untranslated text to the Host."""
import json
import os
import time
import urllib.error
import urllib.request

import comtypes
import uiautomation as auto

HOST_CAPTION_URL = os.environ.get("GI_CAPTION_URL", "http://__GLASS_HOST_IP__:5050/caption")
POLL_SECONDS = 0.10
MAX_CHARS = 4500
RECONNECT_AFTER_EMPTY_SECONDS = 8.0
MAX_UIA_ERRORS = 15
CAPTION_HINTS = (
    "live captions", "live caption", "captions", "caption",
    "subtítulos en vivo", "subtitulos en vivo", "subtítulos en directo",
    "subtitulos en directo", "subtítulos", "subtitulos",
)


def looks_like_captions(name):
    lowered = (name or "").strip().lower()
    return bool(lowered) and any(hint in lowered for hint in CAPTION_HINTS)


def find_captions_window():
    try:
        matches = []
        for window in auto.GetRootControl().GetChildren():
            try:
                if window.ControlTypeName != "WindowControl" or not looks_like_captions(window.Name):
                    continue
                lowered = (window.Name or "").lower()
                score = max((len(hint) for hint in CAPTION_HINTS if hint in lowered), default=0)
                matches.append((score, window))
            except Exception:
                continue
        return max(matches, key=lambda item: item[0])[1] if matches else None
    except Exception:
        return None


def get_caption_text(window):
    longest = ""
    errors = 0

    def visit(control):
        nonlocal longest, errors
        try:
            if control.ControlTypeName == "TextControl":
                text = control.Name or ""
                if len(text) > len(longest):
                    longest = text
            for child in control.GetChildren():
                visit(child)
        except Exception:
            errors += 1

    visit(window)
    return longest.strip()[-MAX_CHARS:], errors


def send_snapshot(text):
    payload = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        HOST_CAPTION_URL, data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5.0) as response:
            response.read()
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def main():
    comtypes.CoInitialize()
    try:
        window = None
        last_text = None
        last_seen = time.monotonic()
        errors = 0
        while True:
            if window is None or not window.Exists(0):
                window = find_captions_window()
                if window is None:
                    time.sleep(1.0)
                    continue

            text, read_errors = get_caption_text(window)
            errors = errors + 1 if read_errors else 0
            if errors >= MAX_UIA_ERRORS:
                window, errors = None, 0
                time.sleep(0.2)
                continue

            if not text:
                if time.monotonic() - last_seen >= RECONNECT_AFTER_EMPTY_SECONDS:
                    window = None
                time.sleep(POLL_SECONDS)
                continue

            last_seen = time.monotonic()
            if text != last_text:
                last_text = text
                send_snapshot(text)
            time.sleep(POLL_SECONDS)
    finally:
        comtypes.CoUninitialize()


if __name__ == "__main__":
    main()
