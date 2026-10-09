"""Glass Interpreter Host: two-way WLC capture, translation and four-pane viewer."""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.request import Request, urlopen

try:
    import comtypes
    import uiautomation as auto
    UIA_AVAILABLE = True
except ImportError:
    comtypes = None
    auto = None
    UIA_AVAILABLE = False

HOST = os.environ.get("GI_HOST_BIND", "0.0.0.0")
PORT = int(os.environ.get("GI_HOST_PORT", "5050"))
TRANSLATE_URL = os.environ.get("GI_TRANSLATE_URL", "http://127.0.0.1:5000/translate")
VM_SOURCE = os.environ.get("GI_VM_SOURCE_LANG", "es")
VM_TARGET = os.environ.get("GI_VM_TARGET_LANG", "en")
HOST_SOURCE = os.environ.get("GI_HOST_SOURCE_LANG", "en")
HOST_TARGET = os.environ.get("GI_HOST_TARGET_LANG", "es")
POLL_SECONDS = 0.10
CAPTION_HINTS = (
    "live captions", "live caption", "captions", "caption",
    "subtítulos en vivo", "subtitulos en vivo", "subtítulos en directo",
    "subtitulos en directo", "subtítulos", "subtitulos",
)

ui_events: queue.Queue[tuple[str, str, str]] = queue.Queue()


def translate(text: str, source: str, target: str) -> str:
    payload = json.dumps({"q": text, "source": source, "target": target,
                          "format": "text"}, ensure_ascii=False).encode("utf-8")
    request = Request(TRANSLATE_URL, payload,
                      {"Content-Type": "application/json; charset=utf-8"}, method="POST")
    with urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    return str(result["translatedText"])


class TranslationQueue:
    """Keep only the newest pending full snapshot for each caption source."""

    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.pending: dict[str, tuple[str, int, str, str]] = {}
        self.revision = {"vm": 0, "host": 0}
        self.last_input = {"vm": None, "host": None}

    def submit(self, source_name: str, text: str, source_lang: str, target_lang: str) -> None:
        text = text.strip()[-4500:]
        if not text:
            return
        with self.condition:
            if self.last_input[source_name] == text:
                return
            self.last_input[source_name] = text
            self.revision[source_name] += 1
            self.pending[source_name] = (
                text, self.revision[source_name], source_lang, target_lang
            )
            ui_events.put(("original", source_name, text))
            self.condition.notify()

    def run(self) -> None:
        while True:
            with self.condition:
                while not self.pending:
                    self.condition.wait()
                source_name = next(iter(self.pending))
                text, revision, source_lang, target_lang = self.pending.pop(source_name)
            try:
                translated = translate(text, source_lang, target_lang)
                status = ""
            except (URLError, TimeoutError, KeyError, json.JSONDecodeError, OSError) as exc:
                translated = f"No se pudo traducir: {exc}"
                status = "LibreTranslate no disponible"
            with self.condition:
                is_current = self.revision[source_name] == revision
            if is_current:
                ui_events.put(("translated", source_name, translated))
                if status:
                    ui_events.put(("status", source_name, status))


translations = TranslationQueue()


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"ok": True, "service": "glass-interpreter-host"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/caption":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 65536:
                raise ValueError("body size must be 1..65536 bytes")
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            text = str(data.get("text", "")).strip()
            if not text:
                raise ValueError("text is required")
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
            return
        translations.submit("vm", text, VM_SOURCE, VM_TARGET)
        self._json(202, {"ok": True, "source": "vm"})

    def log_message(self, fmt: str, *args: object) -> None:
        print("[HTTP] " + fmt % args)


def _is_captions_window(name: str) -> bool:
    lowered = (name or "").strip().lower()
    return bool(lowered) and any(hint in lowered for hint in CAPTION_HINTS)


def find_captions_window():
    if not UIA_AVAILABLE:
        return None
    try:
        candidates = []
        for window in auto.GetRootControl().GetChildren():
            try:
                if window.ControlTypeName == "WindowControl" and _is_captions_window(window.Name):
                    name = (window.Name or "").lower()
                    score = max((len(hint) for hint in CAPTION_HINTS if hint in name), default=0)
                    candidates.append((score, window))
            except Exception:
                continue
        return max(candidates, key=lambda item: item[0])[1] if candidates else None
    except Exception:
        return None


def read_caption(window) -> str:
    longest = ""

    def visit(control) -> None:
        nonlocal longest
        try:
            if control.ControlTypeName == "TextControl":
                name = control.Name or ""
                if len(name) > len(longest):
                    longest = name
            for child in control.GetChildren():
                visit(child)
        except Exception:
            pass

    visit(window)
    return longest.strip()[-4500:]


def watch_host_captions() -> None:
    if not UIA_AVAILABLE:
        ui_events.put(("status", "host", "WLC no disponible: instala comtypes y uiautomation"))
        return
    comtypes.CoInitialize()
    try:
        window = None
        last_text = ""
        last_nonempty = time.monotonic()
        while True:
            try:
                if window is None or not window.Exists(0):
                    window = find_captions_window()
                    if window is None:
                        ui_events.put(("status", "host", "Buscando Live Captions…"))
                        time.sleep(1.0)
                        continue
                    ui_events.put(("status", "host", ""))
                text = read_caption(window)
                now = time.monotonic()
                if text:
                    last_nonempty = now
                    if text != last_text:
                        last_text = text
                        translations.submit("host", text, HOST_SOURCE, HOST_TARGET)
                elif now - last_nonempty >= 8.0:
                    window = None
                    last_text = ""
                time.sleep(POLL_SECONDS)
            except Exception as exc:
                ui_events.put(("status", "host", f"Reconectando: {exc}"))
                window = None
                time.sleep(0.5)
    finally:
        comtypes.CoUninitialize()


def serve() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Glass Interpreter Host escuchando en http://{HOST}:{PORT}")
    server.serve_forever()


class CaptionPane(tk.Frame):
    def __init__(self, master, title: str, font_size: int, on_zoom):
        super().__init__(master, bg="#000000", bd=0, highlightthickness=0)
        self.base_title = title
        self.on_zoom = on_zoom
        self._auto_scroll = True
        self._last_text = ""
        self.header = tk.Label(
            self, text=title, bg="#111111", fg="#AAAAAA",
            font=("Segoe UI", max(7, font_size - 6), "bold"),
            anchor="w", padx=6, pady=2,
        )
        self.header.pack(side="top", fill="x")
        body = tk.Frame(self, bg="#000000", bd=0, highlightthickness=0)
        body.pack(fill="both", expand=True)
        self.scrollbar = tk.Scrollbar(
            body, orient="vertical", width=8, bd=0, highlightthickness=0,
            troughcolor="#000000", bg="#333333", activebackground="#555555",
        )
        self.text = tk.Text(
            body, wrap="word", bg="#000000", fg="#FFFFFF",
            insertbackground="#FFFFFF", selectbackground="#3A3A3A",
            selectforeground="#FFFFFF", relief="flat", bd=0,
            highlightthickness=0, padx=8, pady=6,
            font=("Segoe UI", font_size), undo=False, cursor="xterm",
            yscrollcommand=self._on_scroll, state="disabled",
        )
        self.text.pack(side="left", fill="both", expand=True)
        self.scrollbar.configure(command=self.text.yview)
        self.text.bind("<KeyPress>", self._block_editing)
        self.text.bind("<<Paste>>", lambda _event: "break")
        self.text.bind("<<Cut>>", lambda _event: "break")
        self.text.bind("<MouseWheel>", self._wheel, add="+")
        for sequence in ("<Button-1>", "<KeyPress-Up>", "<KeyPress-Down>",
                         "<KeyPress-Prior>", "<KeyPress-Next>"):
            self.text.bind(sequence, self._mark_manual_scroll, add="+")

    def _on_scroll(self, first: str, last: str) -> None:
        self.scrollbar.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            if self.scrollbar.winfo_ismapped():
                self.scrollbar.pack_forget()
        elif not self.scrollbar.winfo_ismapped():
            self.scrollbar.pack(side="right", fill="y")

    def _wheel(self, event):
        if event.state & 0x0004:
            self.on_zoom(event)
            return "break"
        self.text.yview_scroll(int(-event.delta / 120), "units")
        self.after(50, self._update_auto_scroll)
        return "break"

    def _mark_manual_scroll(self, _event=None) -> None:
        self.after(50, self._update_auto_scroll)

    def _update_auto_scroll(self) -> None:
        try:
            self._auto_scroll = self.text.yview()[1] >= 0.995
        except Exception:
            self._auto_scroll = True

    @staticmethod
    def _block_editing(event):
        ctrl = bool(event.state & 0x0004)
        allowed = {"Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
                   "Shift_L", "Shift_R", "Control_L", "Control_R", "Escape"}
        if ctrl and event.keysym.lower() in ("c", "a"):
            return None
        if event.keysym in allowed:
            return None
        return "break"

    def set_text(self, content: str) -> None:
        if content == self._last_text:
            return
        self._last_text = content
        follow = self._auto_scroll
        selection = None
        try:
            selection = (self.text.index("sel.first"), self.text.index("sel.last"))
        except tk.TclError:
            pass
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.configure(state="disabled")
        if selection:
            try:
                self.text.tag_add("sel", *selection)
            except tk.TclError:
                pass
        if follow:
            self.text.see("end")

    def set_status(self, value: str) -> None:
        suffix = f" — {value}" if value else ""
        self.header.configure(text=self.base_title + suffix)

    def set_font_size(self, size: int) -> None:
        self.text.configure(font=("Segoe UI", size))
        self.header.configure(font=("Segoe UI", max(7, size - 6), "bold"))


def main() -> None:
    threading.Thread(target=serve, daemon=True, name="GlassHTTP").start()
    threading.Thread(target=translations.run, daemon=True, name="GlassTranslate").start()
    threading.Thread(target=watch_host_captions, daemon=True, name="GlassHostCaptions").start()

    root = tk.Tk()
    icon_path = Path(__file__).with_name("Glass.ico")
    if icon_path.is_file():
        try:
            root.iconbitmap(default=str(icon_path))
        except tk.TclError:
            pass
    config_path = Path(__file__).with_name("config_visor.json")
    defaults = {"x": 100, "y": 100, "width": 335, "height": 950, "font_size": 14}
    try:
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            defaults.update(saved)
    except Exception:
        pass
    font_size = max(8, min(40, int(defaults.get("font_size", 14))))
    width = max(250, int(defaults.get("width", 335)))
    height = max(300, int(defaults.get("height", 950)))

    root.title("Glass Interpreter — cuatro cuadros")
    root.geometry(f"{width}x{height}+{int(defaults.get('x', 100))}+{int(defaults.get('y', 100))}")
    root.minsize(250, 300)
    root.configure(bg="#000000")
    root.overrideredirect(True)
    root.attributes("-topmost", True)

    container = tk.Frame(root, bg="#000000")
    container.pack(fill="both", expand=True)
    titles = {
        "host_original": "1. EN Original (WLC)",
        "host_translated": f"2. EN → ES ({HOST_SOURCE.upper()}→{HOST_TARGET.upper()})",
        "vm_original": "3. ES Original (VM)",
        "vm_translated": f"4. ES → EN ({VM_SOURCE.upper()}→{VM_TARGET.upper()})",
    }
    pane_order = ("host_original", "host_translated", "vm_original", "vm_translated")
    panes: dict[str, CaptionPane] = {}

    def zoom_text(event) -> str:
        nonlocal font_size
        font_size = max(8, min(40, font_size + (1 if event.delta > 0 else -1)))
        for pane in panes.values():
            pane.set_font_size(font_size)
        return "break"

    for row, key in enumerate(pane_order):
        container.grid_rowconfigure(row, weight=1, uniform="caption_rows")
        container.grid_columnconfigure(0, weight=1)
        pane = CaptionPane(container, titles[key], font_size, zoom_text)
        pane.grid(row=row, column=0, sticky="nsew", padx=1, pady=1)
        panes[key] = pane

    drag = {"x": 0, "y": 0, "left": 0, "top": 0}

    def begin_drag(event) -> None:
        drag.update(x=event.x_root, y=event.y_root,
                    left=root.winfo_x(), top=root.winfo_y())

    def move_drag(event) -> None:
        root.geometry(f"+{drag['left'] + event.x_root - drag['x']}+"
                      f"{drag['top'] + event.y_root - drag['y']}")

    resize_state = {}

    def begin_resize(event, direction: str) -> None:
        resize_state.update(direction=direction, x=event.x_root, y=event.y_root,
                            left=root.winfo_x(), top=root.winfo_y(),
                            width=root.winfo_width(), height=root.winfo_height())

    active = {"value": True}

    def close() -> None:
        active["value"] = False
        defaults.update(x=root.winfo_x(), y=root.winfo_y(),
                        width=root.winfo_width(), height=root.winfo_height(),
                        font_size=font_size)
        try:
            config_path.write_text(json.dumps(defaults, indent=2), encoding="utf-8")
        except OSError:
            pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)

    def move_resize(event) -> None:
        if not resize_state:
            return
        direction = resize_state["direction"]
        dx, dy = event.x_root - resize_state["x"], event.y_root - resize_state["y"]
        x, y = resize_state["left"], resize_state["top"]
        old_width, old_height = resize_state["width"], resize_state["height"]
        new_x, new_y, new_width, new_height = x, y, old_width, old_height
        if "e" in direction:
            new_width = max(250, old_width + dx)
        if "s" in direction:
            new_height = max(300, old_height + dy)
        if "w" in direction:
            new_width = max(250, old_width - dx)
            new_x = x + old_width - new_width
        if "n" in direction:
            new_height = max(300, old_height - dy)
            new_y = y + old_height - new_height
        root.geometry(f"{new_width}x{new_height}+{new_x}+{new_y}")

    border = 6
    grips = {
        "n": (dict(relx=0, rely=0, relwidth=1, height=border), "sb_v_double_arrow"),
        "s": (dict(relx=0, rely=1, relwidth=1, height=border, y=-border), "sb_v_double_arrow"),
        "w": (dict(relx=0, rely=0, width=border, relheight=1), "sb_h_double_arrow"),
        "e": (dict(relx=1, rely=0, width=border, relheight=1, x=-border), "sb_h_double_arrow"),
        "nw": (dict(relx=0, rely=0, width=border, height=border), "size_nw_se"),
        "ne": (dict(relx=1, rely=0, width=border, height=border, x=-border), "size_ne_sw"),
        "sw": (dict(relx=0, rely=1, width=border, height=border, y=-border), "size_ne_sw"),
        "se": (dict(relx=1, rely=1, width=border, height=border, x=-border, y=-border), "size_nw_se"),
    }
    for direction, (placement, cursor) in grips.items():
        grip = tk.Frame(root, bg="#000000", cursor=cursor)
        grip.place(**placement)
        grip.lift()
        grip.bind("<ButtonPress-1>", lambda event, d=direction: begin_resize(event, d))
        grip.bind("<B1-Motion>", move_resize)

    def drain_events() -> None:
        if not active["value"]:
            return
        try:
            while True:
                kind, source_name, value = ui_events.get_nowait()
                if kind == "original":
                    pane_key = "host_original" if source_name == "host" else "vm_original"
                    panes[pane_key].set_text(value)
                elif kind == "translated":
                    pane_key = "host_translated" if source_name == "host" else "vm_translated"
                    panes[pane_key].set_text(value)
                elif kind == "status":
                    pane_key = "host_original" if source_name == "host" else "vm_original"
                    panes[pane_key].set_status(value)
        except queue.Empty:
            pass
        root.after(30, drain_events)

    root.bind_all("<Alt-ButtonPress-1>", begin_drag)
    root.bind_all("<Alt-B1-Motion>", move_drag)
    root.bind_all("<Control-MouseWheel>", zoom_text)
    root.bind_all("<Escape>", lambda _event: close())
    root.after(30, drain_events)
    root.mainloop()


if __name__ == "__main__":
    main()
