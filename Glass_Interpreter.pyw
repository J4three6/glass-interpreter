import json
import os
import re
import queue
import threading
import time
import unicodedata
import tkinter as tk
import urllib.request
import urllib.error

import libretranslate_manager as lt

try:
    import comtypes
    import uiautomation as auto
    UIA_DISPONIBLE = True
except Exception:
    UIA_DISPONIBLE = False


# ============================================================
# GLASS INTERPRETER — transcripción y traducción bidireccional
# ============================================================

APP_NAME = "Glass Interpreter"
VERSION = "2.5"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config_glass_interpreter.json")

URL_TRADUCCION = "http://127.0.0.1:5000/translate"
INTERVALO_LECTURA = 0.08
REINTENTO_SIN_TEXTO = 7.0
LIMITE_CARACTERES = 4500
MAX_PROFUNDIDAD_UIA = 12
MAX_CONTROLES_UIA = 250
TIMEOUT_TRADUCCION = 5

COLOR_FONDO = "#000000"
COLOR_TEXTO = "#FFFFFF"
COLOR_HEADER = "#111111"
COLOR_HEADER_TEXTO = "#AAAAAA"
FUENTE = "Segoe UI"
FONT_MIN = 6
FONT_MAX = 40
MIN_ANCHO = 400
MIN_ALTO = 144
BORDE = 6

# ============================================================
# ▼▼▼  CONFIGURACIÓN DEL TOOLTIP DE TIMESTAMP  ▼▼▼
# ============================================================
TIMESTAMP_MOSTRAR = True            # False desactiva el tooltip
TIMESTAMP_COLOR = "#88CCFF"         # Color del texto del tooltip
TIMESTAMP_FONDO = "#1A1A1A"         # Fondo del tooltip
TIMESTAMP_BORDE = "#3A3A3A"         # Color del borde
TIMESTAMP_FUENTE = "Consolas"       # Fuente monoespaciada
TIMESTAMP_FORMATO = "%I:%M:%S %p"  # Formato de 12 horas
TIMESTAMP_TAMANO = 9                # Tamaño de fuente del tooltip (px)
TIMESTAMP_OFFSET_X = 16             # Desplazamiento horizontal desde el cursor
TIMESTAMP_OFFSET_Y = 20             # Desplazamiento vertical desde el cursor
TIMESTAMP_PADDING_X = 8             # Padding horizontal del tooltip
TIMESTAMP_PADDING_Y = 3             # Padding vertical del tooltip

INTERVALO_TIMESTAMP = 30            # Segundos entre marcas visibles
PAUSA_SELLADO = 1.8                 # Silencio para cerrar un bloque interno
MAX_PALABRAS_BLOQUE = 45            # Fuerza cierre si el bloque crece demasiado
MIN_CARACTERES_BLOQUE = 25          # No sella bloques más cortos (excepto por .!?)

# ============================================================
# ▲▲▲  FIN DE CONFIGURACIÓN  ▲▲▲
# ============================================================

DEFAULTS = {"x": 100, "y": 100, "width": 1280, "height": 320, "font_size": 13}

CANALES = [
    ("en_es", "1. EN → ES (Traducción)"),
    ("en_original", "2. EN Original (Windows)"),
    ("es_original", "3. ES Original (Chrome)"),
    ("es_en", "4. ES → EN (Traducción)"),
]

PISTAS_WLC = (
    "live captions", "live caption", "captions", "caption",
    "subtítulos en vivo", "subtitulos en vivo",
    "subtítulos en directo", "subtitulos en directo",
    "subtítulos", "subtitulos",
)

PISTAS_CHROME = (
    "live caption", "chrome captions", "chrome caption",
    "subtítulos automáticos", "subtitulos automaticos",
    "subtitulado instantáneo", "subtitulado instantaneo",
)

EXCLUIR_CHROME = (
    "windows live captions", "live captions", "subtítulos en vivo",
    "subtitulos en vivo", "subtítulos en directo", "subtitulos en directo",
)

MENSAJES_ESTADO = (
    "el subtitulado instantaneo esta visible",
    "utiliza el boton de cambio de ventana para enfocar",
    "el subtitulado instantaneo no esta disponible en este momento",
    "subtitulos automaticos no esta disponible en estos momentos",
    "subtitulos automaticos no estan disponibles en estos momentos",
    "subtítulos automáticos",
    "subtitulos automaticos",
    "automatic subtitles",
    "translating",
    "traduciendo",
)

cola_ui = queue.Queue()
detener = threading.Event()
estado_lock = threading.Lock()

estado = {
    "en_original": {"bloques": [], "texto_actual": "", "ultimo_cambio": 0.0},
    "es_original": {"bloques": [], "texto_actual": "", "ultimo_cambio": 0.0},
}


def cargar_config():
    cfg = dict(DEFAULTS)
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                datos = json.load(f)
            if isinstance(datos, dict):
                cfg.update(datos)
    except Exception:
        pass
    try:
        cfg["width"] = max(MIN_ANCHO, int(cfg["width"]))
        cfg["height"] = max(MIN_ALTO, int(cfg["height"]))
        cfg["font_size"] = max(FONT_MIN, min(FONT_MAX, int(cfg["font_size"])))
        cfg["x"], cfg["y"] = int(cfg["x"]), int(cfg["y"])
    except Exception:
        cfg = dict(DEFAULTS)
    return cfg


def guardar_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).casefold().strip()


def parece_estado(texto):
    n = normalizar(texto)
    return any(normalizar(fragmento) in n for fragmento in MENSAJES_ESTADO)


def limpiar_texto_captura(texto_crudo):
    if not texto_crudo:
        return ""
    lineas_filtradas = []
    for linea in texto_crudo.splitlines():
        linea_limpia = linea.strip()
        if linea_limpia and not parece_estado(linea_limpia):
            lineas_filtradas.append(linea_limpia)
    return "\n".join(lineas_filtradas).strip()


def limpiar_para_traduccion(texto):
    """Convierte saltos de renglón en espacios y normaliza el texto continuo
    para que LibreTranslate reciba oraciones completas con contexto."""
    if not texto:
        return ""
    texto_continuo = re.sub(r'[\r\n]+', ' ', texto)
    return re.sub(r'\s+', ' ', texto_continuo).strip()


def recortar(texto):
    return texto[-LIMITE_CARACTERES:] if texto else ""


def recortar_bloques(bloques):
    total = sum(len(b["texto"]) for b in bloques)
    while total > LIMITE_CARACTERES and bloques:
        sobrante = total - LIMITE_CARACTERES
        primero = bloques[0]
        if len(primero["texto"]) <= sobrante:
            total -= len(primero["texto"])
            bloques.pop(0)
        else:
            primero["texto"] = primero["texto"][sobrante:]
            total -= sobrante
    return bloques


def termina_frase_fuerte(texto):
    t = texto.rstrip()
    if not t:
        return False
    return t[-1] in ".!?…" or t.endswith("...") or t.endswith("?!") or t.endswith("!?")


def contar_palabras(texto):
    return len(texto.split())


def actualizar_bloques(bloques, texto_nuevo, ahora):
    texto_previo = "".join(b["texto"] for b in bloques)

    i = 0
    n = min(len(texto_previo), len(texto_nuevo))
    while i < n and texto_previo[i] == texto_nuevo[i]:
        i += 1

    marcas_previas = {}
    desplazamiento = 0
    for b in bloques:
        texto_bloque = b["texto"]
        marcas_bloque = b.get("marcas", [])
        for m in re.finditer(r"\S+", texto_bloque):
            marca = b.get("t", ahora)
            for mb in marcas_bloque:
                if mb.get("start", -1) <= m.start() and mb.get("end", -1) >= m.end():
                    marca = mb.get("t", marca)
                    break
            marcas_previas[desplazamiento + m.start()] = marca
        desplazamiento += len(texto_bloque)

    conservado = []
    acumulado = 0
    for b in bloques:
        if acumulado + len(b["texto"]) <= i:
            conservado.append(dict(b))
            acumulado += len(b["texto"])
        else:
            resto = i - acumulado
            if resto > 0:
                conservado.append({
                    "t": b["t"],
                    "texto": b["texto"][:resto],
                    "sellado": b["sellado"],
                })
            break

    parte_nueva = texto_nuevo[i:]
    if parte_nueva:
        if conservado and not conservado[-1]["sellado"]:
            conservado[-1]["texto"] += parte_nueva
            conservado[-1]["t"] = ahora
        else:
            conservado.append({"t": ahora, "texto": parte_nueva, "sellado": False})
    elif not conservado:
        return conservado

    pos_global = 0
    for b in conservado:
        b.pop("marcas", None)
        b["marcas"] = []
        inicio_bloque = pos_global
        fin_bloque = inicio_bloque + len(b["texto"])
        for m in re.finditer(r"\S+", b["texto"]):
            inicio_palabra = inicio_bloque + m.start()
            fin_palabra = inicio_bloque + m.end()
            if fin_palabra <= i and inicio_palabra in marcas_previas:
                marca = marcas_previas[inicio_palabra]
            else:
                marca = ahora
            b["marcas"].append({
                "start": m.start(),
                "end": m.end(),
                "t": marca,
            })
        pos_global = fin_bloque

    for idx, b in enumerate(conservado):
        if b["sellado"]:
            continue
        if idx == len(conservado) - 1:
            if termina_frase_fuerte(b["texto"]) and len(b["texto"].strip()) >= MIN_CARACTERES_BLOQUE:
                b["sellado"] = True
            elif contar_palabras(b["texto"]) >= MAX_PALABRAS_BLOQUE:
                b["sellado"] = True
        else:
            b["sellado"] = True

    return conservado


def sellar_por_pausa(clave, ahora_monotonic):
    with estado_lock:
        info = estado[clave]
        bloques = info["bloques"]
        if not bloques:
            return False
        ultimo = bloques[-1]
        if ultimo["sellado"]:
            return False
        if ahora_monotonic - info.get("ultimo_cambio", 0) < PAUSA_SELLADO:
            return False
        if len(ultimo["texto"].strip()) < MIN_CARACTERES_BLOQUE:
            if ahora_monotonic - info.get("ultimo_cambio", 0) < PAUSA_SELLADO * 2:
                return False
        ultimo["sellado"] = True
        return True


def grupo_temporal(t):
    return int(t // INTERVALO_TIMESTAMP) if INTERVALO_TIMESTAMP > 0 else 0


def cabecera_grupo(t):
    hora = time.strftime(TIMESTAMP_FORMATO, time.localtime(t))
    hora = hora.replace("AM", "a. m.").replace("PM", "p. m.")
    return hora


def agrupar_por_minuto(bloques):
    grupos = []
    for indice, b in enumerate(bloques):
        texto_original = b["texto"]
        texto = texto_original.strip()
        if not texto:
            continue
        recorte = len(texto_original) - len(texto_original.lstrip())
        marcas = []
        for marca in b.get("marcas", []):
            inicio = marca["start"] - recorte
            fin = marca["end"] - recorte
            if inicio >= 0 and fin <= len(texto) and fin > inicio:
                marcas.append({
                    "start": inicio,
                    "end": fin,
                    "t": marca.get("t", b["t"]),
                })
        grupos.append({
            "grupo": indice,
            "t_inicio": b["t"],
            "texto": texto,
            "sellado": b["sellado"],
            "marcas": marcas,
        })
    return grupos


def encontrar_ventana(pistas, excluir=()):
    try:
        raiz = auto.GetRootControl()
        candidatas = []
        excluir_n = tuple(normalizar(x) for x in excluir)
        pistas_n = tuple(normalizar(x) for x in pistas)
        for ventana in raiz.GetChildren():
            try:
                if ventana.ControlTypeName != "WindowControl":
                    continue
                nombre = (ventana.Name or "").strip()
                n = normalizar(nombre)
                if not nombre or any(p in n for p in excluir_n):
                    continue
                coincidencias = [p for p in pistas_n if p in n]
                if coincidencias:
                    candidatas.append((max(map(len, coincidencias)), ventana))
            except Exception:
                pass
        if candidatas:
            candidatas.sort(key=lambda x: x[0], reverse=True)
            return candidatas[0][1]
    except Exception:
        pass
    return None


def leer_texto_wlc(ventana):
    encontrado = ""
    errores = 0

    def buscar(control, profundidad=0):
        nonlocal encontrado, errores
        if profundidad > MAX_PROFUNDIDAD_UIA:
            return
        try:
            if control.ControlTypeName == "TextControl":
                nombre = (control.Name or "").strip()
                if nombre and len(nombre) > len(encontrado):
                    encontrado = nombre
            for hijo in control.GetChildren():
                buscar(hijo, profundidad + 1)
        except Exception:
            errores += 1

    buscar(ventana)
    return limpiar_texto_captura(encontrado), errores


def leer_texto_chrome(ventana):
    textos = []
    errores = 0

    def buscar(control, profundidad=0):
        nonlocal errores
        if profundidad > MAX_PROFUNDIDAD_UIA or len(textos) >= MAX_CONTROLES_UIA:
            return
        try:
            tipo = control.ControlTypeName
            nombre = (control.Name or "").strip()
            if tipo == "TextControl" and nombre and not parece_estado(nombre):
                if nombre not in textos:
                    textos.append(nombre)
            for hijo in control.GetChildren():
                buscar(hijo, profundidad + 1)
        except Exception:
            errores += 1

    buscar(ventana)
    texto_combinado = "\n".join(textos)
    return limpiar_texto_captura(texto_combinado), errores


def publicar_texto(clave, texto):
    texto = recortar(texto.strip())
    with estado_lock:
        prev = estado[clave]
        if prev["texto_actual"] == texto:
            return
        ahora = time.time()
        prev["bloques"] = actualizar_bloques(prev["bloques"], texto, ahora)
        recortar_bloques(prev["bloques"])
        prev["texto_actual"] = "".join(b["texto"] for b in prev["bloques"])
        prev["ultimo_cambio"] = time.monotonic()
        bloques = [dict(b) for b in prev["bloques"]]
    cola_ui.put((clave, bloques))


def hilo_transcripcion(clave, tipo):
    if not UIA_DISPONIBLE:
        cola_ui.put((clave + "_estado", "Falta comtypes/uiautomation"))
        return
    inicializado = False
    try:
        comtypes.CoInitialize()
        inicializado = True
        ventana = None
        ultimo_texto = None
        ultimo_texto_no_vacio = time.monotonic()
        ultimo_estado = ""
        while not detener.is_set():
            try:
                valida = ventana is not None and ventana.Exists(0)
            except Exception:
                valida = False
            if not valida:
                estado_ui = "Buscando Live Captions…" if tipo == "wlc" else "Buscando Chrome Caption…"
                if estado_ui != ultimo_estado:
                    cola_ui.put((clave + "_estado", estado_ui))
                    ultimo_estado = estado_ui
                if tipo == "wlc":
                    ventana = encontrar_ventana(PISTAS_WLC)
                else:
                    ventana = encontrar_ventana(PISTAS_CHROME, EXCLUIR_CHROME)
                if ventana is None:
                    time.sleep(0.8)
                    continue
                cola_ui.put((clave + "_estado", "Conectado"))
                ultimo_estado = "Conectado"
                ultimo_texto_no_vacio = time.monotonic()

            if tipo == "wlc":
                texto, _ = leer_texto_wlc(ventana)
            else:
                texto, _ = leer_texto_chrome(ventana)
            ahora = time.monotonic()
            if not texto:
                if ahora - ultimo_texto_no_vacio >= REINTENTO_SIN_TEXTO:
                    ventana = None
                    ultimo_texto_no_vacio = ahora
                time.sleep(INTERVALO_LECTURA)
                continue

            ultimo_texto_no_vacio = ahora
            texto = recortar(texto)
            if texto != ultimo_texto:
                ultimo_texto = texto
                publicar_texto(clave, texto)
            time.sleep(INTERVALO_LECTURA)
    except Exception as exc:
        cola_ui.put((clave + "_estado", f"Error de lectura: {exc}"))
    finally:
        if inicializado:
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass


def traducir(texto, origen, destino):
    # Aplicar la limpieza continua justo antes de la llamada HTTP
    texto_limpio = limpiar_para_traduccion(texto)
    if not texto_limpio:
        return ""

    payload = json.dumps({
        "q": texto_limpio,
        "source": origen,
        "target": destino,
        "format": "text",
    }).encode("utf-8")
    
    req = urllib.request.Request(
        URL_TRADUCCION,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_TRADUCCION) as respuesta:
        datos = json.loads(respuesta.read().decode("utf-8", errors="replace"))
        
    traduccion = datos.get("translatedText", "")
    if not isinstance(traduccion, str):
        raise ValueError("Respuesta inesperada de LibreTranslate")
    return traduccion.strip()


def hilo_traductor(origen_clave, destino_clave, idioma_origen, idioma_destino):
    cache_grupos = {}
    ultima_firma = None

    while not detener.is_set():
        ahora_mono = time.monotonic()
        sellar_por_pausa(origen_clave, ahora_mono)

        with estado_lock:
            bloques = [dict(b) for b in estado.get(origen_clave, {}).get("bloques", [])]

        if not bloques:
            if ultima_firma is not None:
                ultima_firma = None
                cache_grupos.clear()
                cola_ui.put((destino_clave, []))
            time.sleep(0.12)
            continue

        grupos = agrupar_por_minuto(bloques)
        if not grupos:
            time.sleep(0.1)
            continue

        firma = tuple((g["grupo"], g["t_inicio"], g["texto"], g["sellado"], tuple((m["start"], m["end"], m["t"]) for m in g.get("marcas", []))) for g in grupos)
        if firma == ultima_firma:
            time.sleep(0.08)
            continue

        salida = []
        for g in grupos:
            idx = g["grupo"]
            entrada = cache_grupos.get(idx)

            if entrada is None or entrada["texto_origen"] != g["texto"]:
                if not g["sellado"]:
                    instante = time.monotonic()
                    while not detener.is_set() and time.monotonic() - instante < 0.4:
                        time.sleep(0.04)
                        with estado_lock:
                            actuales = estado.get(origen_clave, {}).get("bloques", [])
                        actuales_grupo = agrupar_por_minuto(actuales)
                        nuevo = ""
                        for ag in actuales_grupo:
                            if ag["grupo"] == idx:
                                nuevo = ag["texto"]
                                g["marcas"] = ag.get("marcas", [])
                                g["t_inicio"] = ag["t_inicio"]
                                break
                        if nuevo != g["texto"]:
                            g["texto"] = nuevo
                            instante = time.monotonic()

                try:
                    trad = traducir(g["texto"], idioma_origen, idioma_destino)
                    cola_ui.put((destino_clave + "_estado", "OK"))
                except (urllib.error.URLError, TimeoutError) as e:
                    msg_error = f"LibreTranslate no responde ({type(e).__name__})"
                    cola_ui.put((destino_clave + "_estado", msg_error))
                    trad = f"[ERROR TRADUCCIÓN: {msg_error}]"
                except Exception as e:
                    msg_error = f"Error: {e}"
                    cola_ui.put((destino_clave + "_estado", msg_error))
                    trad = f"[ERROR TRADUCCIÓN: {msg_error}]"

                cache_grupos[idx] = {"texto_origen": g["texto"], "traduccion": trad}
            else:
                trad = entrada["traduccion"]

            palabras_traducidas = list(re.finditer(r"\S+", trad))
            marcas_origen = g.get("marcas", [])
            marcas_traducidas = []
            if palabras_traducidas and marcas_origen:
                for wi, palabra in enumerate(palabras_traducidas):
                    origen_idx = min(
                        len(marcas_origen) - 1,
                        int(wi * len(marcas_origen) / len(palabras_traducidas)),
                    )
                    marcas_traducidas.append({
                        "start": palabra.start(),
                        "end": palabra.end(),
                        "t": marcas_origen[origen_idx].get("t", g["t_inicio"]),
                    })

            salida.append({
                "t": g["t_inicio"],
                "texto": trad,
                "grupo": idx,
                "sellado": g["sellado"],
                "marcas": marcas_traducidas,
            })

        cache_grupos = {k: v for k, v in cache_grupos.items() if any(g["grupo"] == k for g in grupos)}
        ultima_firma = firma
        cola_ui.put((destino_clave, salida))
        time.sleep(0.1)


class TooltipTimestamp:
    def __init__(self, maestro):
        self.maestro = maestro
        self.ventana = None
        self.etiqueta = None
        self.texto_actual = ""

    def _crear(self):
        if self.ventana is not None:
            return
        self.ventana = tk.Toplevel(self.maestro)
        self.ventana.overrideredirect(True)
        try:
            self.ventana.attributes("-topmost", True)
        except Exception:
            pass
        self.ventana.configure(bg=TIMESTAMP_BORDE)

        marco = tk.Frame(self.ventana, bg=TIMESTAMP_FONDO, bd=0)
        marco.pack(padx=1, pady=1)
        self.etiqueta = tk.Label(
            marco,
            text="",
            bg=TIMESTAMP_FONDO,
            fg=TIMESTAMP_COLOR,
            font=(TIMESTAMP_FUENTE, TIMESTAMP_TAMANO),
            padx=TIMESTAMP_PADDING_X,
            pady=TIMESTAMP_PADDING_Y,
        )
        self.etiqueta.pack()

    def mostrar(self, hora, x_root, y_root):
        if not TIMESTAMP_MOSTRAR or not hora:
            self.ocultar()
            return
        self._crear()
        if hora != self.texto_actual:
            self.etiqueta.configure(text=hora)
            self.texto_actual = hora
        self.ventana.geometry(
            f"+{x_root + TIMESTAMP_OFFSET_X}+{y_root + TIMESTAMP_OFFSET_Y}"
        )
        try:
            self.ventana.deiconify()
            self.ventana.lift()
        except Exception:
            pass

    def ocultar(self):
        if self.ventana is not None:
            try:
                self.ventana.withdraw()
            except Exception:
                pass
            self.texto_actual = ""

    def destruir(self):
        if self.ventana is not None:
            try:
                self.ventana.destroy()
            except Exception:
                pass
            self.ventana = None
            self.etiqueta = None


class CuadroTexto(tk.Frame):
    def __init__(self, master, clave, titulo, font_size, on_escape):
        super().__init__(master, bg=COLOR_FONDO, bd=0, highlightthickness=0)
        self.clave = clave
        self.titulo_base = titulo
        self._on_escape = on_escape
        self._font_size = font_size

        self._grupos_actuales = []
        self._rangos_grupos = []

        self._tooltip = TooltipTimestamp(self.winfo_toplevel())

        self.header = tk.Label(
            self, text=titulo, bg=COLOR_HEADER, fg=COLOR_HEADER_TEXTO,
            font=(FUENTE, max(6, font_size - 6), "bold"),
            anchor="w", padx=6, pady=2,
        )
        self.header.pack(fill="x", side="top")

        cuerpo = tk.Frame(self, bg=COLOR_FONDO, bd=0, highlightthickness=0)
        cuerpo.pack(fill="both", expand=True)

        self._renderizando = False
        self.scrollbar = tk.Scrollbar(
            cuerpo, orient="vertical", width=8, bd=0,
            highlightthickness=0, troughcolor=COLOR_FONDO,
            bg="#333333", activebackground="#555555",
        )
        self.texto = tk.Text(
            cuerpo, wrap="word", bg=COLOR_FONDO, fg=COLOR_TEXTO,
            insertbackground=COLOR_TEXTO, selectbackground="#dcdc00",
            selectforeground="#000000", relief="flat", bd=0,
            highlightthickness=0, padx=8, pady=6,
            font=(FUENTE, font_size), undo=False, cursor="xterm",
            yscrollcommand=self._on_scroll,
        )
        self.texto.pack(side="left", fill="both", expand=True)
        self.scrollbar.configure(command=self._desplazar_barra)

        self.texto.bind("<KeyPress>", self._bloquear_edicion)
        self.texto.bind("<<Paste>>", lambda e: "break")
        self.texto.bind("<<Cut>>", lambda e: "break")
        self.texto.bind("<MouseWheel>", self._scroll_rueda, add="+")
        self.texto.bind("<Escape>", self._escape)
        self.texto.bind("<Button-1>", self._clic_copiar_y_marcar, add="+")
        self.texto.bind("<Button-3>", self._copiar_con_clic_derecho)
        for tecla in ("Up", "Down", "Prior", "Next", "Home"):
            self.texto.bind(f"<KeyPress-{tecla}>", self._marcar_manual, add="+")
        self.texto.bind("<KeyPress-End>", self._ir_al_final, add="+")

        self.texto.bind("<Motion>", self._al_mover_raton, add="+")
        self.texto.bind("<Leave>", self._al_salir_raton, add="+")

        self._auto_scroll = True
        self._ultima_firma = None
        self.texto.bind("<Configure>", self._al_redimensionar_texto, add="+")

    def _grupo_bajo_cursor(self, x, y):
        try:
            indice = self.texto.index(f"@{x},{y}")
        except tk.TclError:
            return None
        for i, r in enumerate(self._rangos_grupos):
            try:
                if (self.texto.compare(r["start"], "<=", indice)
                        and self.texto.compare(indice, "<", r["end"])):
                    return i
            except tk.TclError:
                continue
        return None

    def _al_mover_raton(self, event):
        if not TIMESTAMP_MOSTRAR:
            return
        idx = self._grupo_bajo_cursor(event.x, event.y)
        if idx is None:
            self._tooltip.ocultar()
            return
        hora = cabecera_grupo(self._rangos_grupos[idx]["t"])
        self._tooltip.mostrar(hora, event.x_root, event.y_root)

    def _al_salir_raton(self, event=None):
        self._tooltip.ocultar()

    def _clic_copiar_y_marcar(self, event):
        try:
            seleccion = self.texto.get("sel.first", "sel.last")
            if seleccion.strip():
                self.master.clipboard_clear()
                self.master.clipboard_append(seleccion)
        except tk.TclError:
            pass
        self._marcar_manual(event)

    def _copiar_con_clic_derecho(self, event):
        try:
            seleccion = self.texto.get("sel.first", "sel.last")
            if seleccion:
                self.master.clipboard_clear()
                self.master.clipboard_append(seleccion)
        except tk.TclError:
            pass
        return "break"

    def _escape(self, event=None):
        self._tooltip.ocultar()
        self._on_escape()
        return "break"

    def _on_scroll(self, primero, ultimo):
        self.scrollbar.set(primero, ultimo)
        if float(primero) <= 0.0 and float(ultimo) >= 1.0:
            self.scrollbar.pack_forget()
        elif not self.scrollbar.winfo_ismapped():
            self.scrollbar.pack(side="right", fill="y")

    def _desplazar_barra(self, *args):
        self.texto.yview(*args)
        self.after_idle(self._actualizar_auto_scroll)

    def _scroll_rueda(self, event):
        self.texto.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.after_idle(self._actualizar_auto_scroll)
        self._tooltip.ocultar()
        return "break"

    def _actualizar_auto_scroll(self):
        try:
            self._auto_scroll = self.texto.yview()[1] >= 0.995
        except Exception:
            self._auto_scroll = True

    def _marcar_manual(self, event=None):
        self.after_idle(self._actualizar_auto_scroll)

    def _ir_al_final(self, event=None):
        self._auto_scroll = True
        self.texto.see("end")
        self.after_idle(self._seguir_final_si_corresponde)
        return "break"

    def _bloquear_edicion(self, event):
        ctrl = bool(event.state & 0x0004)
        permitidas = {
            "Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
            "Shift_L", "Shift_R", "Control_L", "Control_R", "Escape",
        }
        if ctrl and event.keysym.lower() in ("c", "a"):
            return None
        if event.keysym in permitidas:
            return None
        return "break"

    def _al_redimensionar_texto(self, event=None):
        def terminar_redimensionamiento():
            if self._auto_scroll:
                self.texto.see("end")
            self._recalcular_rangos()
        self.after_idle(terminar_redimensionamiento)

    def _recalcular_rangos(self):
        self._rangos_grupos = []
        if not self._grupos_actuales:
            return

        grupos_visibles = [
            g for g in self._grupos_actuales if g["texto"].strip()
        ]

        desplazamiento = 0
        for i, g in enumerate(grupos_visibles):
            texto = g["texto"].strip()
            if not texto:
                continue

            marcas = g.get("marcas") or []
            if marcas:
                for marca in marcas:
                    inicio = self.texto.index(
                        f"1.0 + {desplazamiento + marca['start']} chars"
                    )
                    fin = self.texto.index(
                        f"1.0 + {desplazamiento + marca['end']} chars"
                    )
                    self._rangos_grupos.append({
                        "t": marca.get("t", g["t"]),
                        "start": inicio,
                        "end": fin,
                    })
            else:
                inicio = self.texto.index(f"1.0 + {desplazamiento} chars")
                fin = self.texto.index(
                    f"1.0 + {desplazamiento + len(texto)} chars"
                )
                self._rangos_grupos.append({
                    "t": g.get("t", g.get("t_inicio", time.time())),
                    "start": inicio,
                    "end": fin,
                })

            desplazamiento += len(texto)
            if i < len(grupos_visibles) - 1:
                desplazamiento += 1

    def _renderizar(self, grupos):
        firma = tuple(
            (
                g.get("t", g.get("t_inicio")),
                g["texto"],
                tuple(
                    (m.get("start"), m.get("end"), m.get("t"))
                    for m in g.get("marcas", [])
                ),
            )
            for g in grupos
        )
        if firma == self._ultima_firma:
            return
        self._ultima_firma = firma
        self._grupos_actuales = grupos

        texto_nuevo = " ".join(
            g["texto"].strip() for g in grupos if g["texto"].strip()
        )

        texto_anterior = self.texto.get("1.0", "end-1c")
        limite = min(len(texto_anterior), len(texto_nuevo))
        prefijo = 0
        while prefijo < limite and texto_anterior[prefijo] == texto_nuevo[prefijo]:
            prefijo += 1

        seguir_final = self._auto_scroll
        try:
            indice_superior = self.texto.index("@0,0")
            offset_superior = int(
                self.texto.count("1.0", indice_superior, "chars")[0]
            )
        except (tk.TclError, TypeError, IndexError):
            indice_superior = "1.0"
            offset_superior = 0

        seleccion = None
        try:
            sel_inicio = self.texto.index("sel.first")
            sel_fin = self.texto.index("sel.last")
            sel_inicio_offset = int(self.texto.count("1.0", sel_inicio, "chars")[0])
            sel_fin_offset = int(self.texto.count("1.0", sel_fin, "chars")[0])
            if sel_fin_offset <= prefijo:
                seleccion = (sel_inicio_offset, sel_fin_offset)
        except (tk.TclError, TypeError, IndexError):
            pass

        self._renderizando = True
        try:
            self.texto.configure(state="normal")
            indice_cambio = f"1.0 + {prefijo} chars"
            self.texto.delete(indice_cambio, "end-1c")
            if len(texto_nuevo) > prefijo:
                self.texto.insert(indice_cambio, texto_nuevo[prefijo:])
            self.texto.configure(state="disabled")

            if seleccion:
                try:
                    inicio_sel = f"1.0 + {seleccion[0]} chars"
                    fin_sel = f"1.0 + {seleccion[1]} chars"
                    self.texto.tag_add("sel", inicio_sel, fin_sel)
                except tk.TclError:
                    pass

            if seguir_final:
                self.after_idle(self._seguir_final_si_corresponde)
            elif prefijo <= offset_superior:
                self.texto.yview(f"1.0 + {offset_superior} chars")
        finally:
            self._renderizando = False

        self.after_idle(self._recalcular_rangos)

    def _seguir_final_si_corresponde(self):
        if self._auto_scroll:
            self.texto.see("end")

    def establecer_originales(self, bloques):
        grupos = agrupar_por_minuto(bloques)
        vista = [
            {"t": g["t_inicio"], "texto": g["texto"], "marcas": g.get("marcas", [])}
            for g in grupos
        ]
        self._renderizar(vista)

    def establecer_traduccion(self, grupos_trad):
        vista = [
            {"t": g["t"], "texto": g["texto"], "marcas": g.get("marcas", [])}
            for g in grupos_trad
        ]
        self._renderizar(vista)

    def cambiar_fuente(self, size):
        self._font_size = size
        self.texto.configure(font=(FUENTE, size))
        self.header.configure(font=(FUENTE, max(6, size - 6), "bold"))
        self.after(20, self._recalcular_rangos)

    def mostrar_estado(self, estado_texto):
        sufijo = f"  —  {estado_texto}" if estado_texto else ""
        self.header.configure(text=self.titulo_base + sufijo)


class GlassInterpreterApp:
    def __init__(self):
        self.cfg = cargar_config()
        self.font_size = self.cfg["font_size"]
        orden_guardado = self.cfg.get("order", [clave for clave, _ in CANALES])
        claves_validas = [clave for clave, _ in CANALES]
        self.orden = [clave for clave in orden_guardado if clave in claves_validas]
        self.orden += [clave for clave in claves_validas if clave not in self.orden]
        self.arrastre = None
        self.arrastre_cuadro = None
        self._desfase_arrastre = (0, 0)
        self._tamano_arrastre = None
        self._orientacion = None
        self._animacion_reorden = None
        self._token_animacion_reorden = 0
        self._acomodo_pendiente = None
        self.resize = None
        self.activo = True
        self.x, self.y = self.cfg["x"], self.cfg["y"]
        self.w, self.h = self.cfg["width"], self.cfg["height"]

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.configure(bg=COLOR_FONDO)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.minsize(MIN_ANCHO, MIN_ALTO)
        self.root.geometry(f"{self.w}x{self.h}+{self.x}+{self.y}")

        self._crear_interfaz()
        self._crear_grips()
        self._vincular_eventos()
        self.root.bind("<Configure>", self._al_cambiar_tamano, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self.cerrar)

        lt.iniciar()

        threading.Thread(target=hilo_transcripcion, args=("en_original", "wlc"),
                         daemon=True, name="WLC-English").start()
        threading.Thread(target=hilo_transcripcion, args=("es_original", "chrome"),
                         daemon=True, name="Chrome-Spanish").start()
        threading.Thread(target=hilo_traductor,
                         args=("en_original", "en_es", "en", "es"),
                         daemon=True, name="Translate-EN-ES").start()
        threading.Thread(target=hilo_traductor,
                         args=("es_original", "es_en", "es", "en"),
                         daemon=True, name="Translate-ES-EN").start()
        self.root.after(30, self._procesar_cola)

    def _crear_interfaz(self):
        self.contenedor = tk.Frame(
            self.root, bg=COLOR_FONDO, bd=0, highlightthickness=0
        )
        self.contenedor.pack(fill="both", expand=True)

        self.cuadros = {}
        titulos = dict(CANALES)

        for clave in self.orden:
            cuadro = CuadroTexto(
                self.contenedor,
                clave,
                titulos[clave],
                self.font_size,
                self.cerrar,
            )
            self.cuadros[clave] = cuadro

            for widget in self._widgets_del_cuadro(cuadro):
                widget.bind(
                    "<Control-ButtonPress-1>",
                    lambda e, k=clave: self._inicio_reordenar(e, k),
                    add="+",
                )
                widget.bind("<B1-Motion>", self._mover_reordenar, add="+")
                widget.bind("<ButtonRelease-1>", self._fin_reordenar, add="+")

        self.contenedor.bind("<Configure>", self._al_cambiar_tamano_contenedor, add="+")
        self._acomodar_cuadros(forzar=True)
        self.root.after_idle(lambda: self._acomodar_cuadros(forzar=True))

    def _widgets_del_cuadro(self, widget):
        widgets = [widget]
        for hijo in widget.winfo_children():
            widgets.extend(self._widgets_del_cuadro(hijo))
        return widgets

    def _al_cambiar_tamano(self, event):
        if event.widget is self.root:
            self._programar_acomodo_cuadros()

    def _al_cambiar_tamano_contenedor(self, event):
        self._programar_acomodo_cuadros()

    def _programar_acomodo_cuadros(self):
        if not self.activo or not hasattr(self, "cuadros"):
            return
        if self._acomodo_pendiente is not None:
            try:
                self.root.after_cancel(self._acomodo_pendiente)
            except tk.TclError:
                pass
        self._acomodo_pendiente = self.root.after(12, self._aplicar_acomodo_pendiente)

    def _aplicar_acomodo_pendiente(self):
        self._acomodo_pendiente = None
        if self.activo:
            self._acomodar_cuadros()

    def _calcular_posiciones(self):
        ancho = max(1, self.contenedor.winfo_width())
        alto = max(1, self.contenedor.winfo_height())
        orientacion = "horizontal" if ancho >= alto else "vertical"
        posiciones = {}
        if orientacion == "horizontal":
            celda = ancho / 4
            for indice, clave in enumerate(self.orden):
                x0 = round(indice * celda)
                x1 = round((indice + 1) * celda)
                posiciones[clave] = (x0 + 1, 1, max(1, x1 - x0 - 2), max(1, alto - 2))
        else:
            celda = alto / 4
            for indice, clave in enumerate(self.orden):
                y0 = round(indice * celda)
                y1 = round((indice + 1) * celda)
                posiciones[clave] = (1, y0 + 1, max(1, ancho - 2), max(1, y1 - y0 - 2))
        return orientacion, posiciones

    def _acomodar_cuadros(self, forzar=False):
        if not hasattr(self, "cuadros") or not self.cuadros:
            return
        orientacion, posiciones = self._calcular_posiciones()
        self._orientacion = orientacion

        if self._animacion_reorden is not None:
            try:
                self.root.after_cancel(self._animacion_reorden)
            except tk.TclError:
                pass
            self._animacion_reorden = None
            self._token_animacion_reorden += 1

        for clave, cuadro in self.cuadros.items():
            x, y, w, h = posiciones[clave]
            if not cuadro.winfo_manager():
                cuadro.place(x=x, y=y, width=w, height=h)
            else:
                cuadro.place_configure(x=x, y=y, width=w, height=h)

    def _inicio_reordenar(self, event, clave):
        self.arrastre_cuadro = clave
        cuadro = self.cuadros[clave]
        self._desfase_arrastre = (
            event.x_root - cuadro.winfo_rootx(),
            event.y_root - cuadro.winfo_rooty(),
        )
        self._tamano_arrastre = (
            max(1, cuadro.winfo_width()),
            max(1, cuadro.winfo_height()),
        )
        self._ultimo_objetivo_reorden = None

        if self._animacion_reorden is not None:
            try:
                self.root.after_cancel(self._animacion_reorden)
            except tk.TclError:
                pass
            self._animacion_reorden = None
            self._token_animacion_reorden += 1

        cuadro.lift()
        return "break"

    def _mover_reordenar(self, event):
        if not self.arrastre_cuadro:
            return
        if not (event.state & 0x0004):
            return

        clave_origen = self.arrastre_cuadro
        cuadro_origen = self.cuadros[clave_origen]
        ancho, alto = self._tamano_arrastre or (
            cuadro_origen.winfo_width(), cuadro_origen.winfo_height()
        )
        offset_x, offset_y = self._desfase_arrastre
        x = event.x_root - self.contenedor.winfo_rootx() - offset_x
        y = event.y_root - self.contenedor.winfo_rooty() - offset_y
        max_x = max(0, self.contenedor.winfo_width() - ancho)
        max_y = max(0, self.contenedor.winfo_height() - alto)
        x = max(-ancho + 30, min(max_x, x))
        y = max(-alto + 30, min(max_y, y))

        cuadro_origen.place_configure(x=round(x), y=round(y), width=ancho, height=alto)
        cuadro_origen.lift()

        origen_x0 = self.contenedor.winfo_rootx() + x
        origen_y0 = self.contenedor.winfo_rooty() + y
        origen_x1 = origen_x0 + ancho
        origen_y1 = origen_y0 + alto
        objetivo = None
        mayor_solapamiento = 0

        for clave, cuadro in self.cuadros.items():
            if clave == clave_origen:
                continue
            destino_x0 = cuadro.winfo_rootx()
            destino_y0 = cuadro.winfo_rooty()
            destino_x1 = destino_x0 + cuadro.winfo_width()
            destino_y1 = destino_y0 + cuadro.winfo_height()
            ancho_solapado = max(0, min(origen_x1, destino_x1) - max(origen_x0, destino_x0))
            alto_solapado = max(0, min(origen_y1, destino_y1) - max(origen_y0, destino_y0))
            area_solapada = ancho_solapado * alto_solapado
            if area_solapada > mayor_solapamiento:
                mayor_solapamiento = area_solapada
                objetivo = clave

        if objetivo is None:
            menor_distancia = None
            for clave, cuadro in self.cuadros.items():
                if clave == clave_origen:
                    continue
                cx = cuadro.winfo_rootx() + cuadro.winfo_width() / 2
                cy = cuadro.winfo_rooty() + cuadro.winfo_height() / 2
                distancia = (event.x_root - cx) ** 2 + (event.y_root - cy) ** 2
                if menor_distancia is None or distancia < menor_distancia:
                    menor_distancia = distancia
                    objetivo = clave

        if objetivo is not None:
            self._reubicar_orden(clave_origen, objetivo, event)
        return "break"

    def _reubicar_orden(self, origen, destino, event):
        cuadro_origen = self.cuadros[origen]
        cuadro_destino = self.cuadros[destino]
        ox = cuadro_origen.winfo_rootx() + cuadro_origen.winfo_width() / 2
        oy = cuadro_origen.winfo_rooty() + cuadro_origen.winfo_height() / 2
        dx = cuadro_destino.winfo_rootx() + cuadro_destino.winfo_width() / 2
        dy = cuadro_destino.winfo_rooty() + cuadro_destino.winfo_height() / 2
        antes = ox < dx if self._orientacion == "horizontal" else oy < dy
        clave_objetivo = (destino, antes)
        if self._ultimo_objetivo_reorden == clave_objetivo:
            return
        self._ultimo_objetivo_reorden = clave_objetivo
        if origen in self.orden:
            self.orden.remove(origen)
        indice = self.orden.index(destino)
        self.orden.insert(indice if antes else indice + 1, origen)
        self._animar_reordenamiento(excluir=origen)

    def _animar_reordenamiento(self, excluir=None):
        if not self.cuadros:
            return
        if self._animacion_reorden is not None:
            try:
                self.root.after_cancel(self._animacion_reorden)
            except tk.TclError:
                pass
            self._animacion_reorden = None
        self._token_animacion_reorden += 1
        token = self._token_animacion_reorden
        self.root.update_idletasks()
        orientacion, destino = self._calcular_posiciones()
        self._orientacion = orientacion
        inicio = {}
        for clave, cuadro in self.cuadros.items():
            inicio[clave] = (
                cuadro.winfo_x(), cuadro.winfo_y(),
                max(1, cuadro.winfo_width()), max(1, cuadro.winfo_height()),
            )
        duracion_ms = 210
        intervalo_ms = 16
        inicio_tiempo = time.perf_counter()

        def paso_animacion():
            if not self.activo or token != self._token_animacion_reorden:
                return
            transcurrido = (time.perf_counter() - inicio_tiempo) * 1000
            t = min(1.0, transcurrido / duracion_ms)
            progreso = t * t * (3 - 2 * t)
            for clave, cuadro in self.cuadros.items():
                if clave == excluir:
                    continue
                x0, y0, w0, h0 = inicio[clave]
                x1, y1, w1, h1 = destino[clave]
                cuadro.place_configure(
                    x=round(x0 + (x1 - x0) * progreso),
                    y=round(y0 + (y1 - y0) * progreso),
                    width=max(1, round(w0 + (w1 - w0) * progreso)),
                    height=max(1, round(h0 + (h1 - h0) * progreso)),
                )
            if t < 1.0:
                self._animacion_reorden = self.root.after(intervalo_ms, paso_animacion)
            else:
                self._animacion_reorden = None
                for clave, cuadro in self.cuadros.items():
                    if clave == excluir:
                        continue
                    x, y, w, h = destino[clave]
                    cuadro.place_configure(x=x, y=y, width=w, height=h)
        paso_animacion()

    def _fin_reordenar(self, event):
        if self.arrastre_cuadro:
            self.arrastre_cuadro = None
            self._ultimo_objetivo_reorden = None
            self._tamano_arrastre = None
            self._animar_reordenamiento()
        return "break"

    def _crear_grips(self):
        b = BORDE
        definiciones = {
            "n":  dict(relx=0, rely=0, relwidth=1, height=b, cursor="top_side"),
            "s":  dict(relx=0, rely=1, relwidth=1, height=b, y=-b, cursor="bottom_side"),
            "w":  dict(relx=0, rely=0, width=b, relheight=1, cursor="left_side"),
            "e":  dict(relx=1, rely=0, width=b, relheight=1, x=-b, cursor="right_side"),
            "nw": dict(relx=0, rely=0, width=b, height=b, cursor="top_left_corner"),
            "ne": dict(relx=1, rely=0, width=b, height=b, x=-b, cursor="top_right_corner"),
            "sw": dict(relx=0, rely=1, width=b, height=b, y=-b, cursor="bottom_left_corner"),
            "se": dict(relx=1, rely=1, width=b, height=b, x=-b, y=-b, cursor="bottom_right_corner"),
        }
        self._grips = []
        for direccion, opciones in definiciones.items():
            cursor = opciones.pop("cursor")
            grip = tk.Frame(self.root, bg=COLOR_FONDO, cursor=cursor)
            grip.place(**opciones)
            grip.lift()
            grip.bind("<ButtonPress-1>", lambda e, d=direccion: self._inicio_resize(e, d))
            grip.bind("<B1-Motion>", self._hacer_resize)
            self._grips.append(grip)

    def _vincular_eventos(self):
        self.root.bind("<Alt-ButtonPress-1>", self._inicio_arrastre)
        self.root.bind("<Alt-B1-Motion>", self._hacer_arrastre)
        for cuadro in self.cuadros.values():
            cuadro.texto.bind("<Control-MouseWheel>", self._zoom, add="+")
        self.root.bind("<Control-MouseWheel>", self._zoom, add="+")
        self.root.bind_all("<Escape>", self._escape_global, add="+")

    def _escape_global(self, event=None):
        self.cerrar()
        return "break"

    def _inicio_arrastre(self, event):
        self.arrastre = (event.x_root, event.y_root,
                         self.root.winfo_x(), self.root.winfo_y())

    def _hacer_arrastre(self, event):
        if not self.arrastre:
            return
        sx, sy, wx, wy = self.arrastre
        self.x = wx + event.x_root - sx
        self.y = wy + event.y_root - sy
        self.root.geometry(f"+{self.x}+{self.y}")

    def _inicio_resize(self, event, direccion):
        self.resize = (direccion, event.x_root, event.y_root,
                       self.root.winfo_x(), self.root.winfo_y(),
                       self.root.winfo_width(), self.root.winfo_height())

    def _hacer_resize(self, event):
        if not self.resize:
            return
        d, sx, sy, x, y, w, h = self.resize
        dx, dy = event.x_root - sx, event.y_root - sy
        nx, ny, nw, nh = x, y, w, h
        if "e" in d:
            nw = max(MIN_ANCHO, w + dx)
        if "s" in d:
            nh = max(MIN_ALTO, h + dy)
        if "w" in d:
            nw = max(MIN_ANCHO, w - dx)
            nx = x + w - nw
        if "n" in d:
            nh = max(MIN_ALTO, h - dy)
            ny = y + h - nh
        self.x, self.y, self.w, self.h = nx, ny, nw, nh
        self.root.geometry(f"{nw}x{nh}+{nx}+{ny}")

    def _zoom(self, event):
        delta = 1 if event.delta > 0 else -1
        nuevo = max(FONT_MIN, min(FONT_MAX, self.font_size + delta))
        if nuevo != self.font_size:
            self.font_size = nuevo
            for cuadro in self.cuadros.values():
                cuadro.cambiar_fuente(nuevo)
        return "break"

    def _procesar_cola(self):
        try:
            while True:
                clave, valor = cola_ui.get_nowait()
                if clave.endswith("_estado"):
                    panel = clave[:-7]
                    if panel in self.cuadros:
                        self.cuadros[panel].mostrar_estado(valor)
                elif clave in self.cuadros:
                    if isinstance(valor, list):
                        if clave in ("en_original", "es_original"):
                            self.cuadros[clave].establecer_originales(valor)
                        else:
                            self.cuadros[clave].establecer_traduccion(valor)
                    else:
                        self.cuadros[clave].mostrar_estado(valor)
        except queue.Empty:
            pass
        if self.activo:
            self.root.after(30, self._procesar_cola)

    def cerrar(self):
        if not self.activo:
            return
        self.activo = False
        detener.set()
        self.cfg.update({
            "x": self.root.winfo_x(), "y": self.root.winfo_y(),
            "width": self.root.winfo_width(), "height": self.root.winfo_height(),
            "font_size": self.font_size,
            "order": self.orden,
        })
        guardar_config(self.cfg)
        self.root.destroy()
        lt.detener()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    GlassInterpreterApp().run()