
import tkinter as tk
import time
import json
import os
import sys
import ctypes
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL

# --- Forzar el directorio de trabajo al del script ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)
# -----------------------------------------------------

# -------------------------------------------------
# EVITAR MÚLTIPLES INSTANCIAS
# -------------------------------------------------
mutex = ctypes.windll.kernel32.CreateMutexW(
    None, False, "FloatingTimerMutex"
)
last_error = ctypes.windll.kernel32.GetLastError()
ERROR_ALREADY_EXISTS = 183

if last_error == ERROR_ALREADY_EXISTS:
    sys.exit(0)

CONFIG_FILE = "timer_config.json"
TOGGLE_FILE = "toggle_mic.txt"


class FloatingTimer:
    def __init__(self, root):
        self.root = root

        self.root.title("Floating Timer")

        self.bg_active = "#000000"
        self.bg_muted = "#7A0000"
        self.text_muted_color = "#AAAAAA"

        self.mic_muted = False
        self.tasa_cambio = 15.0

        # --- Consultar el estado real del micrófono al iniciar ---
        try:
            devices = AudioUtilities.GetMicrophone()
            interface = devices.Activate(
                IAudioEndpointVolume._iid_,
                CLSCTX_ALL,
                None
            )
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            current = volume.GetMute()
            self.mic_muted = (current == 1)
        except Exception:
            pass

        self.root.configure(bg=self.bg_active)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", False)

        # Tamaño de texto por defecto
        self.font_size = 40

        self.load_config()

        self.running = False
        self.start_time = 0
        self.elapsed_paused = 0

        self.resize_margin = 12
        self.resize_mode = None

        self.last_is_horizontal = None
        self._last_active_keys = None

        # --- Detección de arrastre ---
        self.drag_threshold = 5
        self.mouse_down_pos = None
        self.is_dragging = False

        self._click_on_entry = False
        self._click_on_timer_text = False
        self._pressed_widget = None

        # Frame contenedor principal
        self.container = tk.Frame(
            root,
            bg=self.bg_active,
            padx=8,
            pady=8
        )
        self.container.pack(expand=True, fill="both")

        periodo_font_size = max(6, int(self.font_size * 0.25))
        tasa_font_size = max(5, int(periodo_font_size * 0.75))

        # --- CONTENEDOR SUPERIOR ---
        self.top_frame = tk.Frame(
            self.container,
            bg=self.bg_active
        )
        self.top_frame.pack(side="top", fill="x")

        # Botón de micrófono
        self.mic_btn = tk.Button(
            self.top_frame,
            text="🎙️",
            fg=self.text_muted_color,
            bg=self.bg_active,
            activebackground=self.bg_active,
            activeforeground="white",
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=("Arial", 18),
            cursor="hand2",
            command=self.toggle_microphones
        )
        self.mic_btn.pack(side="left", anchor="nw")

        # Contenedor de tasa de cambio
        self.tasa_container = tk.Frame(
            self.top_frame,
            bg=self.bg_active
        )
        self.tasa_container.pack(
            side="right",
            anchor="ne",
            padx=(5, 0)
        )

        self.tasa_titulo_label = tk.Label(
            self.tasa_container,
            text="Tasa:",
            fg=self.text_muted_color,
            bg=self.bg_active,
            font=("Arial", tasa_font_size)
        )
        self.tasa_titulo_label.pack(side="top", anchor="e")

        self.tasa_var = tk.StringVar(
            value=f"{self.tasa_cambio:.2f}"
        )

        self.tasa_entry = tk.Entry(
            self.tasa_container,
            textvariable=self.tasa_var,
            fg=self.text_muted_color,
            bg=self.bg_active,
            insertbackground="white",
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=("Arial", tasa_font_size),
            justify="right",
            width=12
        )
        self.tasa_entry.pack(side="top", anchor="e")

        self.tasa_entry.bind(
            "<Return>",
            self.validar_y_guardar_tasa
        )
        self.tasa_entry.bind(
            "<FocusOut>",
            self.validar_y_guardar_tasa
        )
        self.tasa_entry.bind(
            "<Button-1>",
            self.seleccionar_todo_tasa
        )

        self.tasa_moneda_label = tk.Label(
            self.tasa_container,
            text="MXN/USD",
            fg=self.text_muted_color,
            bg=self.bg_active,
            font=("Arial", tasa_font_size)
        )
        self.tasa_moneda_label.pack(side="top", anchor="e")

        # --- CONTENEDOR INFERIOR ---
        self.bottom_group_frame = tk.Frame(
            self.container,
            bg=self.bg_active
        )
        self.bottom_group_frame.pack(
            side="bottom",
            fill="x",
            pady=(0, 2)
        )

        self.periodo_label = tk.Label(
            self.bottom_group_frame,
            text="Calculando...",
            fg=self.text_muted_color,
            bg=self.bg_active,
            font=("Arial", periodo_font_size),
            anchor="center",
            justify="center",
            wraplength=280
        )
        self.periodo_label.pack(
            side="top",
            fill="x",
            expand=True
        )

        self.importes_subcontainer = tk.Frame(
            self.bottom_group_frame,
            bg=self.bg_active
        )
        self.importes_subcontainer.pack(
            side="top",
            anchor="center",
            pady=(2, 0)
        )

        self.dolares_label = tk.Label(
            self.importes_subcontainer,
            text="",
            fg="#00FF00",
            bg=self.bg_active,
            font=("Arial", periodo_font_size),
            justify="center"
        )

        self.mxn_label = tk.Label(
            self.importes_subcontainer,
            text="",
            fg="#008CFF",
            bg=self.bg_active,
            font=("Arial", periodo_font_size),
            justify="center"
        )

        # --- CONTENEDOR CENTRAL ---
        self.center_frame = tk.Frame(
            self.container,
            bg=self.bg_active
        )
        self.center_frame.pack(expand=True, fill="both")

        # -------------------------------------------------
        # RELOJ HORIZONTAL
        # -------------------------------------------------
        self.horiz_frame = tk.Frame(
            self.center_frame,
            bg=self.bg_active
        )

        self.h_numeros_subframe = tk.Frame(
            self.horiz_frame,
            bg=self.bg_active
        )
        self.h_numeros_subframe.pack(
            side="top",
            anchor="center"
        )

        self.h_min_val = tk.Label(
            self.h_numeros_subframe,
            text="00",
            fg="white",
            bg=self.bg_active,
            font=("Arial", self.font_size)
        )

        self.h_sep = tk.Label(
            self.h_numeros_subframe,
            text=":",
            fg="white",
            bg=self.bg_active,
            font=("Arial", self.font_size)
        )

        self.h_sec_val = tk.Label(
            self.h_numeros_subframe,
            text="00.00",
            fg="white",
            bg=self.bg_active,
            font=("Arial", self.font_size)
        )

        self.h_min_val.pack(side="left")
        self.h_sep.pack(side="left")
        self.h_sec_val.pack(side="left")

        horiz_desc_font_size = max(
            7,
            int(self.font_size * 0.3)
        )

        self.h_desc_label = tk.Label(
            self.horiz_frame,
            text="",
            fg=self.text_muted_color,
            bg=self.bg_active,
            font=("Arial", horiz_desc_font_size),
            justify="center",
            wraplength=400
        )
        self.h_desc_label.pack(
            side="top",
            anchor="center",
            pady=(2, 0)
        )

        # -------------------------------------------------
        # RELOJ VERTICAL
        # -------------------------------------------------
        self.vert_units_frame = tk.Frame(
            self.center_frame,
            bg=self.bg_active
        )

        self.timer_parts = {}

        for key in [
            "meses",
            "semanas",
            "dias",
            "horas",
            "minutos",
            "segundos"
        ]:
            f = tk.Frame(
                self.vert_units_frame,
                bg=self.bg_active
            )

            lbl_title = tk.Label(
                f,
                text="",
                fg=self.text_muted_color,
                bg=self.bg_active,
                font=(
                    "Arial",
                    max(6, int(self.font_size * 0.25))
                )
            )

            lbl_val = tk.Label(
                f,
                text="00" if key in ["minutos", "segundos"] else "0",
                fg="white",
                bg=self.bg_active,
                font=("Arial", self.font_size)
            )

            self.timer_parts[key] = {
                "frame": f,
                "title": lbl_title,
                "val": lbl_val
            }

        # -------------------------------------------------
        # EVENTOS DE LA VENTANA
        # -------------------------------------------------
        self.root.bind("<Motion>", self.detect_zone)
        self.root.bind("<ButtonPress-1>", self.start_action)
        self.root.bind("<B1-Motion>", self.perform_action)
        self.root.bind("<ButtonRelease-1>", self.on_click_release)

        self.root.bind(
            "<Control-MouseWheel>",
            self.resize_text
        )

        self.root.bind("<Button-3>", self.reset_timer)
        self.root.bind("<Escape>", self.close_app)
        self.root.bind("<space>", self.on_space_pressed)

        # IMPORTANTE:
        # Ya no se manipulan los estilos de ventana de Windows
        # ni se fuerza la activación de la ventana.

        self.update_timer()
        self.update_colors()
        self.check_hotkey_file()

    # -------------------------------------------------
    # TASA DE CAMBIO
    # -------------------------------------------------
    def seleccionar_todo_tasa(self, event):
        self.tasa_entry.focus_set()
        self.tasa_entry.selection_range(0, tk.END)
        return "break"

    def validar_y_guardar_tasa(self, event=None):
        texto = self.tasa_var.get().strip().replace(",", ".")

        try:
            valor = float(texto)

            if valor < 0:
                raise ValueError()

            self.tasa_cambio = valor
            self.tasa_var.set(f"{self.tasa_cambio:.2f}")

        except ValueError:
            self.tasa_var.set(f"{self.tasa_cambio:.2f}")

        self.save_config()
        self.root.focus_set()

    # -------------------------------------------------
    # BARRA ESPACIADORA
    # -------------------------------------------------
    def on_space_pressed(self, event):
        if self.root.focus_get() == self.tasa_entry:
            return

        try:
            hwnd_fg = ctypes.windll.user32.GetForegroundWindow()
            my_hwnd = self.root.winfo_id()

            hwnd_parent = ctypes.windll.user32.GetParent(my_hwnd)

            if hwnd_parent:
                my_hwnd = hwnd_parent

        except Exception:
            hwnd_fg = None
            my_hwnd = None

        if hwnd_fg is None or my_hwnd is None:
            if self.root.focus_get() is None:
                return
        else:
            if hwnd_fg != my_hwnd:
                return

        self.toggle_microphones()
        return "break"

    # -------------------------------------------------
    # CÁLCULO DEL SIGUIENTE PERIODO
    # -------------------------------------------------
    def calcular_tiempo_siguiente_periodo(self):
        zona_chicago = ZoneInfo("America/Chicago")
        ahora = datetime.now(zona_chicago)

        primer_inicio = datetime(
            2026, 1, 10, 0, 0, 0,
            tzinfo=zona_chicago
        )

        dias_desde_inicio = (
            ahora.date() - primer_inicio.date()
        ).days

        periodo_actual = dias_desde_inicio // 14

        inicio_periodo_actual = (
            primer_inicio + timedelta(days=periodo_actual * 14)
        )

        inicio_siguiente_periodo = (
            inicio_periodo_actual + timedelta(days=14)
        )

        resto = (
            inicio_siguiente_periodo.astimezone(ZoneInfo("UTC"))
            - ahora.astimezone(ZoneInfo("UTC"))
        )

        return max(resto, timedelta(0))

    def formatear_tiempo_periodo(self, tiempo):
        if tiempo.total_seconds() <= 0:
            return "Periodo en curso"

        dias = tiempo.days
        horas = tiempo.seconds // 3600
        minutos = (tiempo.seconds % 3600) // 60
        segundos = tiempo.seconds % 60

        partes = []

        if dias > 0:
            partes.append(
                f"{dias} día{'s' if dias != 1 else ''}"
            )

        if horas > 0:
            partes.append(
                f"{horas} hora{'s' if horas != 1 else ''}"
            )

        if minutos > 0:
            partes.append(
                f"{minutos} minuto{'s' if minutos != 1 else ''}"
            )

        if segundos > 0 or not partes:
            partes.append(
                f"{segundos} segundo{'s' if segundos != 1 else ''}"
            )

        if len(partes) == 1:
            return partes[0]

        elif len(partes) == 2:
            return f"{partes[0]} y {partes[1]}"

        else:
            return (
                f"{', '.join(partes[:-1])} y {partes[-1]}"
            )

    def actualizar_texto_periodo(self):
        tiempo_restante = self.calcular_tiempo_siguiente_periodo()

        texto_formateado = self.formatear_tiempo_periodo(
            tiempo_restante
        )

        self.periodo_label.config(
            text=f"Faltan: {texto_formateado}"
        )

        total_horas_restantes = (
            tiempo_restante.total_seconds() / 3600.0
        )

        total_dolares = total_horas_restantes * 7.2

        self.dolares_label.config(
            text=f"${total_dolares:,.2f} USD"
        )

        total_mxn = total_dolares * self.tasa_cambio

        self.mxn_label.config(
            text=f"${total_mxn:,.2f} MXN"
        )

    # -------------------------------------------------
    # CONFIGURACIÓN
    # -------------------------------------------------
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)

                w = data.get("width", 300)
                h = data.get("height", 150)
                x = data.get("x", 500)
                y = data.get("y", 300)

                self.font_size = data.get("font_size", 40)
                self.tasa_cambio = data.get("tasa_cambio", 15.0)

                if hasattr(self, "tasa_var"):
                    self.tasa_var.set(
                        f"{self.tasa_cambio:.2f}"
                    )

                self.root.geometry(
                    f"{w}x{h}+{x}+{y}"
                )

                return

            except Exception:
                pass

        self.root.geometry("300x150+500+300")

    def save_config(self):
        data = {
            "width": self.root.winfo_width(),
            "height": self.root.winfo_height(),
            "x": self.root.winfo_x(),
            "y": self.root.winfo_y(),
            "font_size": self.font_size,
            "tasa_cambio": self.tasa_cambio
        }

        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f)

    # -------------------------------------------------
    # MICRÓFONO
    # -------------------------------------------------
    def toggle_microphones(self):
        try:
            devices = AudioUtilities.GetMicrophone()

            interface = devices.Activate(
                IAudioEndpointVolume._iid_,
                CLSCTX_ALL,
                None
            )

            volume = cast(
                interface,
                POINTER(IAudioEndpointVolume)
            )

            current = volume.GetMute()
            new_state = 0 if current == 1 else 1

            volume.SetMute(new_state, None)

            self.mic_muted = (new_state == 1)

        except Exception:
            self.mic_muted = not self.mic_muted

        if self.mic_muted and not self.running:
            self.running = True
            self.start_time = time.time() - self.elapsed_paused

        elif not self.mic_muted and self.running:
            self.running = False
            self.elapsed_paused = time.time() - self.start_time

        self.update_colors()

    def update_colors(self):
        bg = (
            self.bg_muted
            if self.mic_muted
            else self.bg_active
        )

        self.root.configure(bg=bg)
        self.container.configure(bg=bg)
        self.top_frame.configure(bg=bg)

        self.mic_btn.configure(
            bg=bg,
            fg=self.text_muted_color,
            activebackground=bg
        )

        self.center_frame.configure(bg=bg)

        self.horiz_frame.configure(bg=bg)
        self.h_numeros_subframe.configure(bg=bg)
        self.h_min_val.configure(bg=bg)
        self.h_sep.configure(bg=bg)
        self.h_sec_val.configure(bg=bg)
        self.h_desc_label.configure(bg=bg)

        self.vert_units_frame.configure(bg=bg)

        for k in self.timer_parts:
            self.timer_parts[k]["frame"].configure(bg=bg)
            self.timer_parts[k]["title"].configure(bg=bg)
            self.timer_parts[k]["val"].configure(bg=bg)

        self.tasa_container.configure(bg=bg)
        self.tasa_titulo_label.configure(bg=bg)
        self.tasa_entry.configure(bg=bg)
        self.tasa_moneda_label.configure(bg=bg)

        self.bottom_group_frame.configure(bg=bg)
        self.importes_subcontainer.configure(bg=bg)
        self.periodo_label.configure(bg=bg)
        self.dolares_label.configure(bg=bg)
        self.mxn_label.configure(bg=bg)

    def check_hotkey_file(self):
        if os.path.exists(TOGGLE_FILE):
            try:
                os.remove(TOGGLE_FILE)
            except Exception:
                pass

            self.toggle_microphones()

        self.root.after(100, self.check_hotkey_file)

    # -------------------------------------------------
    # DETECTAR TEXTO DEL CRONÓMETRO
    # -------------------------------------------------
    def es_texto_timer(self, widget):
        # Elementos blancos del reloj horizontal
        widgets_timer = {
            self.h_min_val,
            self.h_sep,
            self.h_sec_val
        }

        # Elementos blancos del reloj vertical
        for parte in self.timer_parts.values():
            widgets_timer.add(parte["val"])

        return widget in widgets_timer

    # -------------------------------------------------
    # CRONÓMETRO
    # -------------------------------------------------
    def toggle_timer(self, event=None):
        if not self.running:
            self.running = True
            self.start_time = time.time() - self.elapsed_paused

        else:
            self.running = False
            self.elapsed_paused = time.time() - self.start_time

    def reset_timer(self, event):
        if not self.es_texto_timer(event.widget):
            return

        self.running = False
        self.start_time = 0
        self.elapsed_paused = 0

    def update_timer(self):
        if self.running:
            elapsed = time.time() - self.start_time
        else:
            elapsed = self.elapsed_paused

        total_secs = int(elapsed)
        frac = elapsed - total_secs

        meses = total_secs // (30 * 86400)
        rem = total_secs % (30 * 86400)

        semanas = rem // (7 * 86400)
        rem %= (7 * 86400)

        dias = rem // 86400
        rem %= 86400

        horas = rem // 3600
        rem %= 3600

        minutos = rem // 60
        segundos_enteros = rem % 60

        centesimas = int(frac * 100)
        segundos_con_frac = segundos_enteros + frac

        # Actualizar reloj horizontal
        self.h_min_val.config(text=f"{minutos:02}")
        self.h_sec_val.config(
            text=f"{segundos_con_frac:05.2f}"
        )

        # Descripción completa del tiempo
        desc_partes = []

        if meses > 0:
            desc_partes.append(
                f"{meses} mes{'es' if meses != 1 else ''}"
            )

        if semanas > 0:
            desc_partes.append(
                f"{semanas} semana{'s' if semanas != 1 else ''}"
            )

        if dias > 0:
            desc_partes.append(
                f"{dias} día{'s' if dias != 1 else ''}"
            )

        if horas > 0:
            desc_partes.append(
                f"{horas} hora{'s' if horas != 1 else ''}"
            )

        if minutos > 0:
            desc_partes.append(
                f"{minutos} minuto{'s' if minutos != 1 else ''}"
            )

        desc_partes.append(
            f"{segundos_enteros} segundo"
            f"{'s' if segundos_enteros != 1 else ''}"
        )

        desc_partes.append(
            f"{centesimas} centésima"
            f"{'s' if centesimas != 1 else ''}"
        )

        if len(desc_partes) == 1:
            desc_texto = desc_partes[0]

        elif len(desc_partes) == 2:
            desc_texto = (
                f"{desc_partes[0]} y {desc_partes[1]}"
            )

        else:
            desc_texto = (
                f"{', '.join(desc_partes[:-1])} "
                f"y {desc_partes[-1]}"
            )

        self.h_desc_label.config(text=desc_texto)

        # Componentes activos del reloj vertical
        active_components = []

        if meses > 0:
            active_components.append(
                ("meses", "Meses", f"{meses}")
            )

        if semanas > 0:
            active_components.append(
                ("semanas", "Semanas", f"{semanas}")
            )

        if dias > 0:
            active_components.append(
                ("dias", "Días", f"{dias}")
            )

        if horas > 0:
            active_components.append(
                ("horas", "Horas", f"{horas:02}")
            )

        active_components.append(
            ("minutos", "Minutos", f"{minutos:02}")
        )

        active_components.append(
            ("segundos", "Segundos", f"{segundos_con_frac:05.2f}")
        )

        for k, title_text, val_text in active_components:
            self.timer_parts[k]["title"].config(
                text=title_text
            )
            self.timer_parts[k]["val"].config(
                text=val_text
            )

        # Calcular ancho necesario para el reloj horizontal
        self.horiz_frame.update_idletasks()

        ancho_necesario_horiz = (
            self.horiz_frame.winfo_reqwidth() + 20
        )

        win_w = max(
            100,
            self.center_frame.winfo_width()
        )

        is_horizontal = win_w >= ancho_necesario_horiz

        active_keys = tuple(
            k for k, _, _ in active_components
        )

        # Actualizar distribución solo cuando sea necesario
        if (
            is_horizontal != self.last_is_horizontal
            or active_keys != self._last_active_keys
        ):
            self.last_is_horizontal = is_horizontal
            self._last_active_keys = active_keys

            if is_horizontal:
                self.vert_units_frame.place_forget()

                self.horiz_frame.place(
                    relx=0.5,
                    rely=0.5,
                    anchor="center"
                )

            else:
                self.horiz_frame.place_forget()

                for k in self.timer_parts:
                    self.timer_parts[k]["frame"].pack_forget()

                for k, _, _ in active_components:
                    f = self.timer_parts[k]["frame"]
                    t_lbl = self.timer_parts[k]["title"]
                    v_lbl = self.timer_parts[k]["val"]

                    f.pack(
                        side="top",
                        anchor="center",
                        pady=1
                    )

                    t_lbl.pack(
                        side="top",
                        anchor="center"
                    )

                    v_lbl.pack(
                        side="top",
                        anchor="center"
                    )

                self.vert_units_frame.place(
                    relx=0.5,
                    rely=0.5,
                    anchor="center"
                )

        self.actualizar_texto_periodo()

        current_width = self.container.winfo_width()

        if current_width > 20:
            self.periodo_label.config(
                wraplength=current_width - 20
            )

            self.h_desc_label.config(
                wraplength=current_width - 20
            )

        self.dolares_label.pack_forget()
        self.mxn_label.pack_forget()

        if current_width < 240:
            self.dolares_label.pack(
                side="top",
                anchor="center",
                pady=(0, 2)
            )

            self.mxn_label.pack(
                side="top",
                anchor="center"
            )

        else:
            self.dolares_label.pack(
                side="left",
                padx=(0, 8)
            )

            self.mxn_label.pack(side="left")

        # Mantener actualización cada 75 milisegundos
        self.root.after(75, self.update_timer)

    # -------------------------------------------------
    # CAMBIAR TAMAÑO DEL TEXTO
    # -------------------------------------------------
    def resize_text(self, event):
        if event.delta > 0:
            self.font_size += 2
        else:
            self.font_size = max(
                10,
                self.font_size - 2
            )

        self.h_min_val.config(
            font=("Arial", self.font_size)
        )

        self.h_sep.config(
            font=("Arial", self.font_size)
        )

        self.h_sec_val.config(
            font=("Arial", self.font_size)
        )

        horiz_desc_font_size = max(
            7,
            int(self.font_size * 0.3)
        )

        self.h_desc_label.config(
            font=("Arial", horiz_desc_font_size)
        )

        for k in self.timer_parts:
            self.timer_parts[k]["val"].config(
                font=("Arial", self.font_size)
            )

            self.timer_parts[k]["title"].config(
                font=(
                    "Arial",
                    max(6, int(self.font_size * 0.25))
                )
            )

        periodo_font_size = max(
            6,
            int(self.font_size * 0.25)
        )

        tasa_font_size = max(
            5,
            int(periodo_font_size * 0.75)
        )

        self.periodo_label.config(
            font=("Arial", periodo_font_size)
        )

        self.dolares_label.config(
            font=("Arial", periodo_font_size)
        )

        self.mxn_label.config(
            font=("Arial", periodo_font_size)
        )

        self.tasa_titulo_label.config(
            font=("Arial", tasa_font_size)
        )

        self.tasa_entry.config(
            font=("Arial", tasa_font_size)
        )

        self.tasa_moneda_label.config(
            font=("Arial", tasa_font_size)
        )

        self.save_config()

    # -------------------------------------------------
    # DETECTAR BORDES PARA REDIMENSIONAR
    # -------------------------------------------------
    def detect_zone(self, event):
        x = event.x_root - self.root.winfo_rootx()
        y = event.y_root - self.root.winfo_rooty()

        w = self.root.winfo_width()
        h = self.root.winfo_height()
        m = self.resize_margin

        mode = None
        cursor = "arrow"

        if x < m and y < m:
            mode, cursor = "nw", "top_left_corner"

        elif x > w - m and y < m:
            mode, cursor = "ne", "top_right_corner"

        elif x < m and y > h - m:
            mode, cursor = "sw", "bottom_left_corner"

        elif x > w - m and y > h - m:
            mode, cursor = "se", "bottom_right_corner"

        elif x < m:
            mode, cursor = "w", "left_side"

        elif x > w - m:
            mode, cursor = "e", "right_side"

        elif y < m:
            mode, cursor = "n", "top_side"

        elif y > h - m:
            mode, cursor = "s", "bottom_side"

        self.resize_mode = mode
        self.root.config(cursor=cursor)

    # -------------------------------------------------
    # ARRASTRAR Y REDIMENSIONAR
    # -------------------------------------------------
    def start_action(self, event):
        # No se fuerza la activación de la ventana.
        # Tkinter administra el foco de forma normal.

        self.start_x = event.x_root
        self.start_y = event.y_root

        self.mouse_down_pos = (
            event.x_root,
            event.y_root
        )

        self.is_dragging = False

        self._click_on_entry = (
            event.widget is self.tasa_entry
        )

        self._click_on_timer_text = (
            self.es_texto_timer(event.widget)
        )

        self._pressed_widget = event.widget

        geo = self.root.geometry().split("+")[0]

        self.start_w, self.start_h = map(
            int,
            geo.split("x")
        )

        self.win_x = self.root.winfo_x()
        self.win_y = self.root.winfo_y()

    def perform_action(self, event):
        dx = event.x_root - self.start_x
        dy = event.y_root - self.start_y

        if self.mouse_down_pos:
            mx, my = self.mouse_down_pos

            if (
                abs(event.x_root - mx) > self.drag_threshold
                or abs(event.y_root - my) > self.drag_threshold
            ):
                self.is_dragging = True

        min_w, min_h = 150, 80

        x, y = self.win_x, self.win_y
        w, h = self.start_w, self.start_h

        if self.resize_mode:
            if "e" in self.resize_mode:
                w = max(min_w, self.start_w + dx)

            if "s" in self.resize_mode:
                h = max(min_h, self.start_h + dy)

            if "w" in self.resize_mode:
                w = max(min_w, self.start_w - dx)
                x = self.win_x + dx

            if "n" in self.resize_mode:
                h = max(min_h, self.start_h - dy)
                y = self.win_y + dy

            self.root.geometry(
                f"{w}x{h}+{x}+{y}"
            )

            self.save_config()

    # -------------------------------------------------
    # DETECTAR CLIC
    # -------------------------------------------------
    def on_click_release(self, event):
        if self.is_dragging or self.resize_mode:
            self.mouse_down_pos = None
            self._pressed_widget = None
            return

        if self._click_on_entry:
            self.mouse_down_pos = None
            self._pressed_widget = None
            return

        if event.widget is self.mic_btn:
            self.mouse_down_pos = None
            self._pressed_widget = None
            return

        if self.root.focus_get() is self.tasa_entry:
            self.mouse_down_pos = None
            self._pressed_widget = None
            return

        # El clic debe comenzar sobre los números blancos
        if not self._click_on_timer_text:
            self.mouse_down_pos = None
            self._pressed_widget = None
            return

        # El clic debe terminar sobre el mismo elemento
        if event.widget is not self._pressed_widget:
            self.mouse_down_pos = None
            self._pressed_widget = None
            return

        self.mouse_down_pos = None
        self._pressed_widget = None

        self.toggle_timer()

    # -------------------------------------------------
    # CERRAR
    # -------------------------------------------------
    def close_app(self, event):
        self.save_config()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = FloatingTimer(root)
    root.mainloop()
