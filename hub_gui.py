"""
hub_gui.py — HUB de datos HTTP — Traductor Rusertech ® v2.1
================================================
Compilar (el .exe queda en la raíz junto al .env):
    pyinstaller --onefile --windowed --icon=hub_icon.ico --distpath . --name "HubSatelital" hub_gui.py

IMPORTANTE: El .exe debe estar en la misma carpeta que .env y main.py
"""

import asyncio
import json
import logging
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import customtkinter as ctk
import httpx

# ── Directorio base ───────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.chdir(BASE_DIR)
RUTA_ENV = BASE_DIR / ".env"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# ── Paleta Deep Space ─────────────────────────────────────────────────────────
C_BG_TOP   = "#1F2A5A"   # Azul Índigo Profundo
C_BG_BOT   = "#2B2F6E"   # Azul Marino Violáceo
C_SURF     = "#1a2040"   # Superficie sobre el gradiente
C_SURF2    = "#242b52"   # Superficie secundaria
C_BORDE    = "#3a4272"   # Bordes

C_GRAD1    = "#7CFF3C"   # Verde Eléctrico
C_GRAD2    = "#33E1A1"   # Cian Menta
C_GRAD3    = "#2AB3FF"   # Azul Cian Eléctrico

C_TEXTO    = "#E5E7EB"   # Blanco hueso
C_APAGADO  = "#6B7DB3"   # Azul apagado
C_VERDE    = "#33E1A1"   # Cian Menta (éxito)
C_ROJO     = "#FF4B6E"   # Rojo neón
C_AMARILLO = "#FFD166"   # Amarillo suave

F_TITULO  = ("Inter", 22, "bold")
F_GRANDE  = ("Inter", 15, "bold")
F_NORMAL  = ("Inter", 13)
F_PEQUENA = ("Inter", 11)
F_MONO    = ("Courier New", 11)

_FILTRAR_LOGS = {
    "uvicorn.access", "uvicorn.error",
    "httpx", "httpcore", "httpcore.connection", "httpcore.http11",
}

# =========================================================================== #
# .env helpers                                                                #
# =========================================================================== #

def leer_env() -> dict:
    datos = {}
    if not RUTA_ENV.exists():
        return datos
    try:
        texto = RUTA_ENV.read_text(encoding="utf-8-sig")
    except Exception:
        texto = RUTA_ENV.read_text(encoding="utf-8", errors="replace")
    for linea in texto.splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            c, _, v = linea.partition("=")
            datos[c.strip()] = v.strip()
    return datos


def escribir_env(datos: dict, limpiar_prefijos: list = None) -> None:
    """
    Actualiza el .env preservando comentarios y líneas no modificadas.
    limpiar_prefijos: elimina del .env todas las claves con esos prefijos
    antes de escribir. Ej: ["DESTINOS_"] para limpiar proveedores pasivos
    eliminados de la GUI.
    """
    if not RUTA_ENV.exists():
        with open(RUTA_ENV, "w", encoding="utf-8") as f:
            for c, v in datos.items():
                f.write(f"{c}={v}\n")
        return

    limpiar = limpiar_prefijos or []
    lineas = RUTA_ENV.read_text(encoding="utf-8").splitlines(keepends=True)
    actualizadas = set()
    nuevas = []

    for linea in lineas:
        s = linea.strip()
        if s and not s.startswith("#") and "=" in s:
            c = s.split("=")[0].strip()
            # Si la clave tiene un prefijo a limpiar, omitirla (borrarla del .env)
            if any(c.startswith(p) for p in limpiar):
                continue
            if c in datos:
                nuevas.append(f"{c}={datos[c]}\n")
                actualizadas.add(c)
            else:
                nuevas.append(linea)
        else:
            nuevas.append(linea)

    for c, v in datos.items():
        if c not in actualizadas:
            nuevas.append(f"{c}={v}\n")

    RUTA_ENV.write_text("".join(nuevas), encoding="utf-8")


# =========================================================================== #
# Cola de logs                                                                #
# =========================================================================== #

cola_logs: queue.Queue = queue.Queue()


class _HandlerGUI(logging.Handler):
    def emit(self, record):
        if record.name in _FILTRAR_LOGS:
            return
        if record.name.startswith("httpcore") or record.name.startswith("httpx"):
            return
        cola_logs.put((record.levelname, self.format(record)))


_handler_gui = _HandlerGUI()
_handler_gui.setFormatter(logging.Formatter("%(name)s — %(message)s"))


# =========================================================================== #
# Servidor Hub                                                                #
# =========================================================================== #

class ServidorHub:
    def __init__(self):
        self._uvicorn = None
        self._hilo: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.en_ejecucion = False

    def iniciar(self) -> bool:
        if self.en_ejecucion:
            return True
        try:
            from dotenv import load_dotenv
            load_dotenv(RUTA_ENV, override=True)
            try:
                from core.config import obtener_configuracion
                obtener_configuracion.cache_clear()
            except Exception:
                pass
            import importlib
            import main as m
            importlib.reload(m)
            import uvicorn
            from core.config import obtener_configuracion
            cfg = obtener_configuracion()
            config_uv = uvicorn.Config(
                m.app, host="0.0.0.0", port=cfg.PUERTO,
                log_level="info", loop="asyncio", log_config=None,
            )
            self._uvicorn = uvicorn.Server(config_uv)
            root = logging.getLogger()
            root.setLevel(logging.INFO)
            if _handler_gui not in root.handlers:
                root.addHandler(_handler_gui)
            self._loop = asyncio.new_event_loop()
            self._hilo = threading.Thread(target=self._run, daemon=True)
            self._hilo.start()
            self.en_ejecucion = True
            return True
        except Exception as e:
            cola_logs.put(("ERROR", f"Error al iniciar el Hub: {e}"))
            return False

    def _run(self):
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._uvicorn.serve())
        except Exception as e:
            cola_logs.put(("ERROR", f"Error en servidor: {e}"))
        finally:
            self.en_ejecucion = False

    def detener(self):
        if self._uvicorn:
            self._uvicorn.should_exit = True
        if self._hilo:
            self._hilo.join(timeout=5)
        self.en_ejecucion = False
        logging.getLogger().removeHandler(_handler_gui)


_servidor = ServidorHub()


# =========================================================================== #
# Login                                                                       #
# =========================================================================== #

class VentanaLogin(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Acceso")
        self.geometry("420x480")
        self.resizable(False, False)
        self.configure(fg_color=C_BG_TOP)
        self.acceso_ok = False
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 420) // 2
        y = (self.winfo_screenheight() - 480) // 2
        self.geometry(f"420x480+{x}+{y}")

        datos = leer_env()
        self._u = datos.get("CONFIG_USUARIO", "").strip()
        self._c = datos.get("CONFIG_CLAVE", "").strip()

        if not self._u and not self._c:
            self.acceso_ok = True
            self.after(50, self.destroy)
        else:
            self._construir()
            self.bind("<Return>", lambda e: self._validar())
            self.after(300, lambda: self._ent_u.focus())
            self.protocol("WM_DELETE_WINDOW", self._cancelar)

    def _construir(self):
        # Ícono — usa imagen real del .ico
        try:
            from PIL import Image as _PILImg
            _pil = _PILImg.open(str(BASE_DIR / "hub_icon.ico")).convert("RGBA").resize((100, 100))
            self._login_icon = ctk.CTkImage(light_image=_pil, dark_image=_pil, size=(100, 100))
            ctk.CTkLabel(self, image=self._login_icon, text="").pack(pady=(28, 8))
        except Exception:
            frame_icon = ctk.CTkFrame(self, width=72, height=72, corner_radius=16,
                                       fg_color=C_GRAD2)
            frame_icon.pack(pady=(28, 8))
            frame_icon.pack_propagate(False)
            ctk.CTkLabel(frame_icon, text="🛰️", font=("Segoe UI Emoji", 36)).place(
                relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(self, text="Rusertech® HUB",
                     font=F_TITULO, text_color=C_TEXTO).pack()
        ctk.CTkLabel(self, text="Ingresá tus credenciales de acceso",
                     font=F_PEQUENA, text_color=C_APAGADO).pack(pady=(4, 24))

        f = ctk.CTkFrame(self, fg_color="transparent")
        f.pack(fill="x", padx=48)

        ctk.CTkLabel(f, text="Usuario", font=F_PEQUENA,
                     text_color=C_TEXTO, anchor="w").pack(fill="x")
        self._ent_u = ctk.CTkEntry(f, height=40, placeholder_text="admin",
                                    fg_color=C_SURF2, border_color=C_BORDE,
                                    text_color=C_TEXTO)
        self._ent_u.pack(fill="x", pady=(4, 12))

        ctk.CTkLabel(f, text="Contraseña", font=F_PEQUENA,
                     text_color=C_TEXTO, anchor="w").pack(fill="x")
        self._ent_c = ctk.CTkEntry(f, show="●", height=40,
                                    fg_color=C_SURF2, border_color=C_BORDE,
                                    text_color=C_TEXTO)
        self._ent_c.pack(fill="x", pady=(4, 8))

        self._lbl_err = ctk.CTkLabel(f, text="", font=F_PEQUENA, text_color=C_ROJO)
        self._lbl_err.pack(fill="x", pady=(0, 12))

        ctk.CTkButton(f, text="Ingresar", height=44,
                      font=("Inter", 14, "bold"),
                      fg_color=C_GRAD2, hover_color=C_GRAD3,
                      text_color=C_BG_TOP,
                      command=self._validar).pack(fill="x")

    def _validar(self):
        if (self._ent_u.get().strip() == self._u and
                self._ent_c.get().strip() == self._c):
            self.acceso_ok = True
            self.destroy()
        else:
            hint = f" (usuario: '{self._u[:3]}...')" if self._u else ""
            self._lbl_err.configure(text=f"Credenciales incorrectas{hint}")
            self._ent_c.delete(0, "end")
            self._ent_c.focus()

    def _cancelar(self):
        self.acceso_ok = False
        self.destroy()


# =========================================================================== #
# Modal de edición — para APIs y proveedores pasivos                          #
# =========================================================================== #

class ModalEdicion(ctk.CTkToplevel):
    """
    Ventana modal para editar un proveedor (activo o pasivo).
    Recibe un dict con los valores actuales y llama a callback al guardar.
    """

    TIPOS = ["activo", "pasivo"]

    def __init__(self, parent, titulo: str, datos: dict, callback, tipo="activo"):
        super().__init__(parent)
        self.title(titulo)
        self.geometry("520x640")
        self.resizable(False, True)
        self.configure(fg_color=C_BG_TOP)
        self.grab_set()
        self._datos = datos.copy()
        self._callback = callback
        self._tipo = tipo
        self._campos: dict = {}

        self.update_idletasks()
        x = (self.winfo_screenwidth() - 520) // 2
        y = (self.winfo_screenheight() - 640) // 2
        self.geometry(f"520x640+{x}+{y}")

        self._construir()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _lbl(self, parent, texto):
        ctk.CTkLabel(parent, text=texto, font=F_PEQUENA,
                     text_color=C_TEXTO, anchor="w").pack(fill="x", padx=20, pady=(8, 0))

    def _entry(self, parent, key, placeholder="", mono=False):
        e = ctk.CTkEntry(parent, placeholder_text=placeholder,
                         font=F_MONO if mono else F_NORMAL, height=36,
                         fg_color=C_SURF2, border_color=C_BORDE, text_color=C_TEXTO)
        e.pack(fill="x", padx=20, pady=(2, 0))
        if self._datos.get(key):
            e.insert(0, self._datos[key])
        self._campos[key] = ("entry", e)

    def _pwd_field(self, parent, key, placeholder=""):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=20, pady=(2, 0))
        frame.grid_columnconfigure(0, weight=1)
        e = ctk.CTkEntry(frame, show="●", placeholder_text=placeholder,
                         font=F_MONO, height=36,
                         fg_color=C_SURF2, border_color=C_BORDE, text_color=C_TEXTO)
        e.grid(row=0, column=0, sticky="ew")
        if self._datos.get(key):
            e.configure(show="")
            e.insert(0, self._datos[key])
            e.configure(show="●")

        def toggle(btn=None, en=e):
            if en.cget("show") == "●":
                en.configure(show="")
                if btn: btn.configure(text="Ocultar")
            else:
                en.configure(show="●")
                if btn: btn.configure(text="Ver")

        b = ctk.CTkButton(frame, text="Ver", width=72, height=36,
                          font=F_PEQUENA, fg_color=C_SURF2, hover_color=C_BORDE,
                          text_color=C_TEXTO, command=lambda: None)
        b.configure(command=lambda btn=b: toggle(btn))
        b.grid(row=0, column=1, padx=(4, 0))
        self._campos[key] = ("pwd", e)

    def _opt(self, parent, key, valores):
        w = ctk.CTkOptionMenu(parent, values=valores,
                              fg_color=C_SURF2, button_color=C_GRAD2,
                              button_hover_color=C_GRAD3,
                              text_color=C_TEXTO, dropdown_fg_color=C_SURF)
        w.pack(fill="x", padx=20, pady=(2, 0))
        v = self._datos.get(key, "")
        if v and v in valores:
            w.set(v)
        self._campos[key] = ("optionmenu", w)

    def _sw(self, parent, key, label):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=20, pady=(8, 0))
        var = ctk.BooleanVar(value=str(self._datos.get(key, "false")).lower() == "true")
        ctk.CTkLabel(f, text=label, font=F_PEQUENA, text_color=C_TEXTO).pack(side="left")
        lbl_sn = ctk.CTkLabel(f, font=("Inter", 11, "bold"),
                               text="Sí" if var.get() else "No",
                               text_color=C_VERDE if var.get() else C_APAGADO,
                               width=28)
        lbl_sn.pack(side="right", padx=(0, 8))
        sw_w = ctk.CTkSwitch(f, variable=var, text="",
                              button_color=C_GRAD2, button_hover_color=C_GRAD3)
        sw_w.pack(side="right")

        def _on(*_):
            lbl_sn.configure(text="Sí" if var.get() else "No",
                              text_color=C_VERDE if var.get() else C_APAGADO)
        var.trace_add("write", _on)
        self._campos[key] = ("switch", var)

    def _construir(self):
        # Header
        ctk.CTkLabel(self, text=self.title(), font=F_GRANDE,
                     text_color=C_TEXTO).pack(pady=(20, 4), padx=20, anchor="w")
        ctk.CTkFrame(self, height=1, fg_color=C_BORDE).pack(fill="x", padx=20, pady=(0, 8))

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=0, pady=0)

        if self._tipo == "activo":
            self._lbl(scroll, "Nombre identificador (ej: control_group)")
            self._entry(scroll, "nombre", "mi_proveedor", mono=True)

            self._sw(scroll, "activo", "Activo")

            self._lbl(scroll, "URL del gateway / API")
            self._entry(scroll, "url", "https://...", mono=True)

            self._lbl(scroll, "Usuario")
            self._entry(scroll, "usuario", mono=True)

            self._lbl(scroll, "Contraseña")
            self._pwd_field(scroll, "clave")

            self._lbl(scroll, "Intervalo de consulta (segundos)")
            self._opt(scroll, "intervalo", ["30", "60", "90", "120", "180", "300"])

            self._lbl(scroll, "Enviar datos a:")
            self._opt(scroll, "destino",
                      ["recurso_confiable", "simon", "recurso_confiable,simon"])

        else:  # pasivo
            self._lbl(scroll, "Nombre en la URL  — POST /ingresar/{nombre}")
            self._entry(scroll, "nombre", "mi_proveedor", mono=True)

            self._lbl(scroll, "Enviar datos a:")
            self._opt(scroll, "destino",
                      ["recurso_confiable", "simon", "recurso_confiable,simon"])

            ctk.CTkLabel(scroll,
                         text="El prestador debe hacer POST a:\nhttp://tu-servidor:8000/ingresar/{nombre}",
                         font=F_MONO, text_color=C_APAGADO, justify="left").pack(
                fill="x", padx=20, pady=(12, 0))

        # Botones
        ctk.CTkFrame(self, height=1, fg_color=C_BORDE).pack(fill="x", padx=20, pady=(8, 0))
        frame_btns = ctk.CTkFrame(self, fg_color="transparent")
        frame_btns.pack(fill="x", padx=20, pady=12)

        ctk.CTkButton(frame_btns, text="Cancelar", height=38, width=100,
                      fg_color=C_SURF2, hover_color=C_BORDE, text_color=C_TEXTO,
                      command=self.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(frame_btns, text="💾  Guardar", height=38,
                      fg_color=C_GRAD2, hover_color=C_GRAD3,
                      text_color=C_BG_TOP, font=("Inter", 13, "bold"),
                      command=self._guardar).pack(side="right")

        if self._datos.get("_puede_eliminar"):
            ctk.CTkButton(frame_btns, text="🗑  Eliminar", height=38, width=100,
                          fg_color="#3a1820", hover_color=C_ROJO,
                          text_color=C_ROJO,
                          command=self._eliminar).pack(side="left")

    def _guardar(self):
        resultado = {}
        for key, (tipo, widget) in self._campos.items():
            if tipo == "switch":
                resultado[key] = "true" if widget.get() else "false"
            elif tipo in ("entry", "pwd"):
                resultado[key] = widget.get().strip()
            elif tipo == "optionmenu":
                resultado[key] = widget.get()
        self._callback(resultado, "guardar")
        self.destroy()

    def _eliminar(self):
        self._callback(self._datos, "eliminar")
        self.destroy()


# =========================================================================== #
# Ventana principal                                                           #
# =========================================================================== #

class HubApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("HUB de datos HTTP — Traductor Rusertech ®")
        self.geometry("1200x740")
        self.minsize(1000, 640)
        self.configure(fg_color=C_BG_TOP)
        try:
            self.iconbitmap(str(BASE_DIR / "hub_icon.ico"))
        except Exception:
            pass

        self._campos: dict = {}
        # Inicializar variables de ngrok ANTES de construir la UI
        # (los botones de la UI referencian estos atributos)
        self._ngrok_url: str = ""
        self._proceso_ngrok = None
        self._construir_ui()
        self.after(200, self._cargar_todo)
        self._actualizar_metricas()
        self._actualizar_logs()
        self._ciclo_ngrok()  # Detectar ngrok si está corriendo
        self.protocol("WM_DELETE_WINDOW", self._al_cerrar)

    # ------------------------------------------------------------------ #
    # UI principal                                                        #
    # ------------------------------------------------------------------ #

    def _construir_ui(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._panel_izquierdo()
        self._panel_derecho()

    def _panel_izquierdo(self):
        panel = ctk.CTkFrame(self, width=310, corner_radius=0,
                              fg_color=C_SURF)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.grid_propagate(False)
        panel.grid_rowconfigure(8, weight=1)

        # Ícono — usa imagen real del .ico
        try:
            from PIL import Image as _PILImg2
            _pil2 = _PILImg2.open(str(BASE_DIR / "hub_icon.ico")).convert("RGBA").resize((96, 96))
            self._sidebar_icon = ctk.CTkImage(light_image=_pil2, dark_image=_pil2, size=(96, 96))
            ctk.CTkLabel(panel, image=self._sidebar_icon, text="").grid(row=0, column=0, pady=(20, 6))
        except Exception:
            frame_icon = ctk.CTkFrame(panel, width=68, height=68, corner_radius=16,
                                       fg_color=C_GRAD2)
            frame_icon.grid(row=0, column=0, pady=(32, 6))
            frame_icon.grid_propagate(False)
            ctk.CTkLabel(frame_icon, text="🛰️", font=("Segoe UI Emoji", 34),
                         text_color=C_BG_TOP).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(panel, text="Rusertech® HUB",
                     font=F_TITULO, text_color=C_TEXTO).grid(row=1, column=0)
        ctk.CTkLabel(panel, text="Traductor de datos AVL",
                     font=F_PEQUENA, text_color=C_APAGADO).grid(row=2, column=0, pady=(0, 20))
        ctk.CTkFrame(panel, height=1, fg_color=C_BORDE).grid(
            row=3, column=0, sticky="ew", padx=16, pady=4)

        f = ctk.CTkFrame(panel, fg_color="transparent")
        f.grid(row=4, column=0, padx=16, pady=12)
        self._circulo = ctk.CTkLabel(f, text="●", font=("Inter", 24),
                                      text_color=C_APAGADO)
        self._circulo.pack(side="left", padx=(0, 8))
        self._lbl_estado = ctk.CTkLabel(f, text="Detenido",
                                         font=F_GRANDE, text_color=C_APAGADO)
        self._lbl_estado.pack(side="left")

        self._btn = ctk.CTkButton(
            panel, text="▶  INICIAR", font=("Inter", 15, "bold"),
            height=50, width=235, corner_radius=12,
            fg_color=C_GRAD2, hover_color=C_GRAD3,
            text_color=C_BG_TOP,
            command=self._toggle)
        self._btn.grid(row=5, column=0, padx=20, pady=8)

        # Métricas
        fm = ctk.CTkFrame(panel, fg_color=C_SURF2, corner_radius=10)
        fm.grid(row=6, column=0, padx=16, pady=8, sticky="ew")
        fm.grid_columnconfigure((0, 1), weight=1)
        self._metricas = {}
        for i, (k, lbl) in enumerate([
            ("ingestados", "Ingestados"), ("enviados", "Enviados"),
            ("fallidos", "Fallidos"),     ("cola",     "En cola"),
        ]):
            fi = ctk.CTkFrame(fm, fg_color="transparent")
            fi.grid(row=i // 2, column=i % 2, padx=8, pady=8, sticky="ew")
            v = ctk.CTkLabel(fi, text="0", font=("Inter", 20, "bold"),
                             text_color=C_TEXTO)
            v.pack()
            ctk.CTkLabel(fi, text=lbl, font=F_PEQUENA, text_color=C_APAGADO).pack()
            self._metricas[k] = v

        # Botones de acceso rápido
        frame_btns_quick = ctk.CTkFrame(panel, fg_color="transparent")
        frame_btns_quick.grid(row=7, column=0, padx=16, pady=(4, 2), sticky="ew")
        frame_btns_quick.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            frame_btns_quick, text="🌐  Dashboard",
            height=32, font=F_PEQUENA,
            fg_color="transparent", hover_color=C_SURF2,
            border_color=C_BORDE, border_width=1,
            text_color=C_GRAD3, corner_radius=8,
            command=lambda: __import__("webbrowser").open("http://localhost:8000/dashboard")
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))

        ctk.CTkButton(
            frame_btns_quick, text="📄  Ver Logs",
            height=32, font=F_PEQUENA,
            fg_color="transparent", hover_color=C_SURF2,
            border_color=C_BORDE, border_width=1,
            text_color=C_GRAD3, corner_radius=8,
            command=self._abrir_logs,
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # Panel ngrok
        frame_ngrok = ctk.CTkFrame(panel, fg_color=C_SURF2, corner_radius=8)
        frame_ngrok.grid(row=8, column=0, padx=16, pady=(4, 2), sticky="ew")
        frame_ngrok.grid_columnconfigure(0, weight=1)

        frame_ngrok_top = ctk.CTkFrame(frame_ngrok, fg_color="transparent")
        frame_ngrok_top.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 0))
        frame_ngrok_top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame_ngrok_top, text="ngrok",
                     font=("Inter", 10, "bold"), text_color=C_APAGADO,
                     anchor="w").grid(row=0, column=0, sticky="w")
        self._btn_ngrok = ctk.CTkButton(
            frame_ngrok_top, text="▶ Iniciar", width=72, height=22,
            font=("Inter", 9, "bold"),
            fg_color=C_GRAD2, hover_color=C_GRAD3,
            text_color=C_BG_TOP, corner_radius=6,
            command=self._toggle_ngrok,
        )
        self._btn_ngrok.grid(row=0, column=1, sticky="e")

        self._lbl_ngrok = ctk.CTkLabel(
            frame_ngrok, text="No activo",
            font=F_MONO, text_color=C_APAGADO,
            cursor="hand2", wraplength=260, anchor="w",
        )
        self._lbl_ngrok.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 2))
        self._lbl_ngrok.bind("<Button-1>", self._copiar_url_ngrok)

        self._lbl_ngrok_hint = ctk.CTkLabel(
            frame_ngrok, text="",
            font=("Inter", 9), text_color=C_APAGADO, anchor="w",
        )
        self._lbl_ngrok_hint.grid(row=2, column=0, sticky="w", padx=10, pady=(0, 6))

        self._ngrok_url: str = ""
        self._proceso_ngrok = None

        # Uptime
        self._lbl_uptime = ctk.CTkLabel(panel, text="",
                                         font=F_PEQUENA, text_color=C_APAGADO)
        self._lbl_uptime.grid(row=9, column=0, pady=(2, 2))
        self._uptime_inicio: float = 0.0

        ctk.CTkLabel(panel, text="v2.1.0",
                     font=F_PEQUENA, text_color=C_APAGADO).grid(row=10, column=0, pady=(0, 12))

    def _panel_derecho(self):
        self._tabs = ctk.CTkTabview(
            self, fg_color=C_SURF,
            segmented_button_fg_color=C_SURF2,
            segmented_button_selected_color=C_GRAD2,
            segmented_button_unselected_color=C_SURF2,
            text_color=C_TEXTO,
            segmented_button_selected_hover_color=C_GRAD3,
        )
        self._tabs.grid(row=0, column=1, sticky="nsew")
        self._tabs.add("📊  Monitor")
        self._tabs.add("⚙️  Configuración")
        self._construir_monitor()
        self._construir_config()

    def _construir_monitor(self):
        tab = self._tabs.tab("📊  Monitor")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        tb = ctk.CTkFrame(tab, fg_color="transparent")
        tb.grid(row=0, column=0, sticky="ew", pady=(8, 4))
        ctk.CTkLabel(tb, text="Log en vivo", font=F_GRANDE,
                     text_color=C_TEXTO).pack(side="left", padx=8)
        self._lbl_uptime_monitor = ctk.CTkLabel(tb, text="",
                     font=F_PEQUENA, text_color=C_VERDE)
        self._lbl_uptime_monitor.pack(side="left", padx=4)
        ctk.CTkButton(tb, text="📤  Exportar", width=90, height=28,
                      font=F_PEQUENA, fg_color=C_SURF2,
                      hover_color=C_BORDE, text_color=C_GRAD3,
                      command=self._exportar_log).pack(side="right", padx=(4, 8))
        ctk.CTkButton(tb, text="🗑  Limpiar", width=80, height=28,
                      font=F_PEQUENA, fg_color=C_SURF2,
                      hover_color=C_BORDE, text_color=C_TEXTO,
                      command=self._limpiar).pack(side="right")

        self._txt = ctk.CTkTextbox(tab, font=F_MONO, fg_color=C_SURF2,
                                    text_color=C_TEXTO, corner_radius=8, wrap="word")
        self._txt.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self._txt.configure(state="disabled")

        for tag, color in [("INFO", C_TEXTO), ("DEBUG", C_APAGADO),
                           ("WARNING", C_AMARILLO), ("ERROR", C_ROJO),
                           ("SUCCESS", C_VERDE)]:
            self._txt._textbox.tag_configure(tag, foreground=color)

    def _construir_config(self):
        tab = self._tabs.tab("⚙️  Configuración")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent",
                                         scrollbar_button_color=C_SURF2)
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        fila = [0]

        def sec(titulo, desc):
            f = ctk.CTkFrame(scroll, fg_color=C_SURF2, corner_radius=10)
            f.grid(row=fila[0], column=0, sticky="ew", padx=16, pady=(12, 4))
            f.grid_columnconfigure(0, weight=1)
            fila[0] += 1
            ctk.CTkLabel(f, text=titulo, font=F_GRANDE, text_color=C_TEXTO,
                         anchor="w").grid(row=0, column=0, sticky="w", padx=16, pady=(12, 2))
            ctk.CTkLabel(f, text=desc, font=F_PEQUENA, text_color=C_APAGADO,
                         anchor="w").grid(row=1, column=0, sticky="w", padx=16, pady=(0, 10))
            return f

        def gr(parent):
            f = ctk.CTkFrame(parent, fg_color="transparent")
            f.grid(row=parent.grid_size()[1], column=0, sticky="ew")
            f.grid_columnconfigure((0, 1), weight=1)
            return f

        def sw(parent, key, label, col=None, idx=0, rh=None):
            t = col if col else parent
            r = rh if rh is not None else t.grid_size()[1]
            ctk.CTkLabel(t, text=label, font=F_PEQUENA, text_color=C_TEXTO,
                         anchor="w").grid(row=r, column=idx, sticky="w", padx=16, pady=(4, 0))
            var = ctk.BooleanVar()
            frame_sw = ctk.CTkFrame(t, fg_color="transparent")
            frame_sw.grid(row=r+1, column=idx, sticky="w", padx=16, pady=(2, 8))
            sw_widget = ctk.CTkSwitch(frame_sw, variable=var, text="",
                                       button_color=C_GRAD2, button_hover_color=C_GRAD3)
            sw_widget.pack(side="left")
            lbl_estado = ctk.CTkLabel(frame_sw, text="No", font=("Inter", 11, "bold"),
                                       text_color=C_APAGADO, width=28)
            lbl_estado.pack(side="left", padx=(6, 0))

            def _on_change(*_):
                if var.get():
                    lbl_estado.configure(text="Sí", text_color=C_VERDE)
                else:
                    lbl_estado.configure(text="No", text_color=C_APAGADO)

            var.trace_add("write", _on_change)
            self._campos[key] = ("switch", var)

        def tx(parent, key, label, ph="", mono=False, col=None, idx=0, rh=None):
            t = col if col else parent
            r = rh if rh is not None else t.grid_size()[1]
            ctk.CTkLabel(t, text=label, font=F_PEQUENA, text_color=C_TEXTO,
                         anchor="w").grid(row=r, column=idx, sticky="w", padx=16, pady=(4, 0))
            e = ctk.CTkEntry(t, placeholder_text=ph,
                             font=F_MONO if mono else F_NORMAL, height=36,
                             fg_color=C_SURF, border_color=C_BORDE, text_color=C_TEXTO)
            e.grid(row=r+1, column=idx, sticky="ew", padx=16, pady=(2, 8))
            self._campos[key] = ("entry", e)

        def pw(parent, key, label, col=None, idx=0, rh=None):
            t = col if col else parent
            r = rh if rh is not None else t.grid_size()[1]
            ctk.CTkLabel(t, text=label, font=F_PEQUENA, text_color=C_TEXTO,
                         anchor="w").grid(row=r, column=idx, sticky="w", padx=16, pady=(4, 0))
            fr = ctk.CTkFrame(t, fg_color="transparent")
            fr.grid(row=r+1, column=idx, sticky="ew", padx=16, pady=(2, 8))
            fr.grid_columnconfigure(0, weight=1)
            e = ctk.CTkEntry(fr, show="●", font=F_MONO, height=36,
                             fg_color=C_SURF, border_color=C_BORDE, text_color=C_TEXTO)
            e.grid(row=0, column=0, sticky="ew")

            def toggle(b, en=e):
                if en.cget("show") == "●":
                    en.configure(show="")
                    b.configure(text="Ocultar")
                else:
                    en.configure(show="●")
                    b.configure(text="Ver")

            b = ctk.CTkButton(fr, text="Ver", width=72, height=36,
                              font=F_PEQUENA, fg_color=C_SURF2, hover_color=C_BORDE,
                              text_color=C_TEXTO, command=lambda: None)
            b.configure(command=lambda btn=b: toggle(btn))
            b.grid(row=0, column=1, padx=(4, 0))
            self._campos[key] = ("pwd", e)

        def op(parent, key, label, vals, col=None, idx=0, rh=None):
            t = col if col else parent
            r = rh if rh is not None else t.grid_size()[1]
            ctk.CTkLabel(t, text=label, font=F_PEQUENA, text_color=C_TEXTO,
                         anchor="w").grid(row=r, column=idx, sticky="w", padx=16, pady=(4, 0))
            w = ctk.CTkOptionMenu(t, values=vals,
                                  fg_color=C_SURF, button_color=C_GRAD2,
                                  button_hover_color=C_GRAD3, text_color=C_TEXTO)
            w.grid(row=r+1, column=idx, sticky="ew", padx=16, pady=(2, 8))
            self._campos[key] = ("optionmenu", w)

        # ── General ──────────────────────────────────────────────────────
        s = sec("🔧  General", "Servidor y comportamiento")
        # DRY_RUN en su propia fila (switch no mezcla bien con dropdown en misma fila)
        sw(s, "DRY_RUN", "Modo Prueba (sin envíos reales)")
        # Los 3 dropdowns alineados juntos en 2 filas
        g1 = gr(s)
        op(g1, "LOG_LEVEL", "Nivel de logs",
           ["INFO", "DEBUG", "WARNING", "ERROR"], col=g1, idx=0, rh=0)
        op(g1, "LOG_RETENTION_HOURS", "Retención de logs (horas)",
           ["1", "2", "4", "6", "12", "24", "48", "72", "168"],
           col=g1, idx=1, rh=0)
        op(s, "COLA_MAX_HORAS", "Máx. horas en cola de reintento",
           ["6", "12", "24", "48"])

        # ── Recurso Confiable ─────────────────────────────────────────────
        s_rc = sec("📡  Recurso Confiable", "Protocolo SOAP/XML — D-TI-15 v14")
        sw(s_rc, "SEND_TO_RECURSO_CONFIABLE", "Activo")
        tx(s_rc, "RC_SOAP_URL", "URL del servicio SOAP",
           "http://gps.rcontrol.com.mx/Tracking/wcf/RCService.svc", mono=True)
        g_rc = gr(s_rc)
        tx(g_rc, "RC_USER_ID", "Usuario", mono=True, col=g_rc, idx=0, rh=0)
        pw(g_rc, "RC_PASSWORD", "Contraseña", col=g_rc, idx=1, rh=0)

        # ── Simon 4.0 ─────────────────────────────────────────────────────
        s_si = sec("📡  Simon 4.0", "Destino REST/JSON — Recibe los registros AVL normalizados")
        sw(s_si, "SEND_TO_SIMON", "Activo")

        # Explicación visual de cómo funciona la autenticación
        info_si = ctk.CTkFrame(s_si, fg_color=C_SURF, corner_radius=6)
        info_si.grid(row=s_si.grid_size()[1], column=0, sticky="ew", padx=16, pady=(0, 10))
        ctk.CTkLabel(info_si, text="Cómo funciona el envío:",
                     font=("Inter", 11, "bold"), text_color=C_APAGADO,
                     anchor="w").pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(info_si,
                     text="POST {URL del endpoint}?rpaIntegrationKey={tu clave}",
                     font=F_MONO, text_color=C_GRAD3, anchor="w").pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkLabel(info_si,
                     text="El Hub completa la URL automáticamente usando los campos de abajo.",
                     font=F_PEQUENA, text_color=C_APAGADO, anchor="w").pack(fill="x", padx=10, pady=(0, 8))

        tx(s_si, "SIMON_BASE_URL", "URL base del endpoint Simon",
           "https://simon-pre-webapi.assistcargo.com/ReceiveAvlRecords", mono=True)
        g_si = gr(s_si)
        tx(g_si, "SIMON_USER_AVL", "Usuario AVL (campo User_avl en cada registro)",
           "Rusertech", col=g_si, idx=0, rh=0)
        pw(g_si, "SIMON_INTEGRATION_KEY",
           "Integration Key (se agrega a la URL como ?rpaIntegrationKey=...)",
           col=g_si, idx=1, rh=0)

        # ── Zona horaria ──────────────────────────────────────────────────
        s_tz = sec("🕐  Zona Horaria", "RC requiere UTC — Simon requiere hora local")
        g_tz = gr(s_tz)
        op(g_tz, "RC_TIMEZONE_OFFSET", "RC — offset UTC",
           ["+00:00", "-03:00", "-04:00", "-05:00", "-06:00"],
           col=g_tz, idx=0, rh=0)
        op(g_tz, "SIMON_TIMEZONE_OFFSET", "Simon — hora local",
           ["-03:00", "-04:00", "-05:00", "-06:00", "+00:00"],
           col=g_tz, idx=1, rh=0)

        # ── APIs — Lista de ingestores activos ────────────────────────────
        sep = ctk.CTkFrame(scroll, fg_color="transparent")
        sep.grid(row=fila[0], column=0, sticky="ew", padx=16, pady=(20, 0))
        fila[0] += 1
        ctk.CTkFrame(sep, height=1, fg_color=C_BORDE).pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(sep, text="APIS — Prestadores cuya API consultamos nosotros",
                     font=("Inter", 11, "bold"), text_color=C_APAGADO,
                     anchor="w").pack(fill="x")

        # Frame lista APIs activas
        frame_apis = ctk.CTkFrame(scroll, fg_color=C_SURF2, corner_radius=10)
        frame_apis.grid(row=fila[0], column=0, sticky="ew", padx=16, pady=(8, 4))
        frame_apis.grid_columnconfigure(0, weight=1)
        fila[0] += 1
        self._frame_lista_apis = frame_apis
        self._lista_apis_row = [0]

        ctk.CTkButton(frame_apis, text="＋  Agregar ingestor activo",
                      height=36, font=F_NORMAL,
                      fg_color="transparent", hover_color=C_SURF,
                      text_color=C_GRAD2, border_color=C_GRAD2,
                      border_width=1,
                      command=self._agregar_api).grid(
            row=99, column=0, sticky="ew", padx=16, pady=12)

        # ── Proveedores pasivos — Lista ───────────────────────────────────
        sep2 = ctk.CTkFrame(scroll, fg_color="transparent")
        sep2.grid(row=fila[0], column=0, sticky="ew", padx=16, pady=(16, 0))
        fila[0] += 1
        ctk.CTkFrame(sep2, height=1, fg_color=C_BORDE).pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(sep2, text="PROVEEDORES PASIVOS — Prestadores que nos envían datos",
                     font=("Inter", 11, "bold"), text_color=C_APAGADO,
                     anchor="w").pack(fill="x")

        # ── Endpoint info box ─────────────────────────────────────────────
        frame_ep = ctk.CTkFrame(scroll, fg_color=C_SURF2, corner_radius=10)
        frame_ep.grid(row=fila[0], column=0, sticky="ew", padx=16, pady=(8, 4))
        frame_ep.grid_columnconfigure(0, weight=1)
        fila[0] += 1
        ctk.CTkLabel(frame_ep, text="📌  Endpoint que le das al prestador AVL",
                     font=("Inter", 12, "bold"), text_color=C_TEXTO, anchor="w").grid(
            row=0, column=0, sticky="w", padx=16, pady=(12, 6))
        ctk.CTkLabel(frame_ep, text="Local (desarrollo):", font=F_PEQUENA,
                     text_color=C_APAGADO, anchor="w").grid(
            row=1, column=0, sticky="w", padx=16, pady=(0, 2))
        f_ep_loc = ctk.CTkFrame(frame_ep, fg_color=C_SURF, corner_radius=6)
        f_ep_loc.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
        f_ep_loc.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(f_ep_loc, text="POST  http://localhost:8000/ingresar/{nombre}",
                     font=F_MONO, text_color=C_GRAD3, anchor="w").grid(
            row=0, column=0, sticky="w", padx=10, pady=6)
        ctk.CTkButton(f_ep_loc, text="📋 Copiar", width=80, height=26,
                      font=F_PEQUENA, fg_color=C_SURF2, hover_color=C_BORDE,
                      text_color=C_GRAD3, corner_radius=6,
                      command=lambda: self._copiar_texto(
                          "http://localhost:8000/ingresar/{nombre}",
                          "URL local copiada")).grid(row=0, column=1, padx=(0, 8))
        ctk.CTkLabel(frame_ep, text="Publico via ngrok (cuando esta activo):",
                     font=F_PEQUENA, text_color=C_APAGADO, anchor="w").grid(
            row=3, column=0, sticky="w", padx=16, pady=(0, 2))
        f_ep_ng = ctk.CTkFrame(frame_ep, fg_color=C_SURF, corner_radius=6)
        f_ep_ng.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 8))
        f_ep_ng.grid_columnconfigure(0, weight=1)
        self._lbl_endpoint_ngrok = ctk.CTkLabel(
            f_ep_ng, text="POST  https://[inicia ngrok primero]/ingresar/{nombre}",
            font=F_MONO, text_color=C_APAGADO, anchor="w", wraplength=700)
        self._lbl_endpoint_ngrok.grid(row=0, column=0, sticky="w", padx=10, pady=6)
        self._btn_copiar_ngrok_ep = ctk.CTkButton(
            f_ep_ng, text="📋 Copiar", width=80, height=26,
            font=F_PEQUENA, fg_color=C_SURF2, hover_color=C_BORDE,
            text_color=C_APAGADO, corner_radius=6,
            command=lambda: self._copiar_endpoint_ngrok())
        self._btn_copiar_ngrok_ep.grid(row=0, column=1, padx=(0, 8))
        f_ep_token = ctk.CTkFrame(frame_ep, fg_color="transparent")
        f_ep_token.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 12))
        f_ep_token.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(f_ep_token,
                     text="Header:  Authorization: Bearer {HUB_INGEST_TOKEN}   (vacio = sin autenticacion)",
                     font=F_MONO, text_color=C_APAGADO, anchor="w").grid(
            row=0, column=0, sticky="w")
        ctk.CTkButton(f_ep_token, text="📋 Copiar token", width=110, height=26,
                      font=F_PEQUENA, fg_color=C_SURF2, hover_color=C_BORDE,
                      text_color=C_APAGADO, corner_radius=6,
                      command=lambda: self._copiar_token_ingest()).grid(row=0, column=1, padx=(8, 0))

        # ── Lista de proveedores pasivos ──────────────────────────────────
        frame_pasivos = ctk.CTkFrame(scroll, fg_color=C_SURF2, corner_radius=10)
        frame_pasivos.grid(row=fila[0], column=0, sticky="ew", padx=16, pady=(8, 4))
        frame_pasivos.grid_columnconfigure(0, weight=1)
        fila[0] += 1
        self._frame_lista_pasivos = frame_pasivos
        self._lista_pasivos_row = [0]

        ctk.CTkButton(frame_pasivos, text="＋  Agregar proveedor pasivo",
                      height=36, font=F_NORMAL,
                      fg_color="transparent", hover_color=C_SURF,
                      text_color=C_GRAD2, border_color=C_GRAD2,
                      border_width=1,
                      command=self._agregar_pasivo).grid(
            row=99, column=0, sticky="ew", padx=16, pady=12)

        # ── Routing global ────────────────────────────────────────────────
        s_rg = sec("🔀  Routing global",
                   "Destino por defecto para proveedores sin configuración específica")
        op(s_rg, "DESTINOS_DEFAULT", "Destino por defecto:",
           ["(ninguno)", "recurso_confiable", "simon", "recurso_confiable,simon"])

        # Aviso
        av = ctk.CTkFrame(scroll, fg_color=C_SURF2, corner_radius=8)
        av.grid(row=fila[0], column=0, sticky="ew", padx=16, pady=(4, 4))
        fila[0] += 1
        ctk.CTkLabel(av,
                     text="Importante: el Hub lee el .env al iniciar. "
                          "Guarda y luego DETENE y REINICIA para aplicar cambios.",
                     font=F_PEQUENA, text_color=C_AMARILLO,
                     wraplength=700, anchor="w", justify="left").pack(padx=12, pady=8, fill="x")

        # Botones
        fb = ctk.CTkFrame(scroll, fg_color="transparent")
        fb.grid(row=fila[0], column=0, sticky="ew", padx=16, pady=16)
        fila[0] += 1
        ctk.CTkButton(fb, text="💾  Guardar configuración",
                      font=("Inter", 14, "bold"), height=44,
                      fg_color=C_GRAD2, hover_color=C_GRAD3,
                      text_color=C_BG_TOP,
                      command=self._guardar).pack(side="left", expand=True, fill="x", padx=(0, 8))
        ctk.CTkButton(fb, text="↺  Recargar", font=F_NORMAL, height=44, width=120,
                      fg_color=C_SURF2, hover_color=C_BORDE, text_color=C_TEXTO,
                      command=self._cargar_todo).pack(side="right")

        self._lbl_ok = ctk.CTkLabel(scroll, text="", font=F_PEQUENA, text_color=C_VERDE)
        self._lbl_ok.grid(row=fila[0], column=0, pady=(0, 16))

    # ------------------------------------------------------------------ #
    # Listas de APIs y proveedores                                        #
    # ------------------------------------------------------------------ #

    def _fila_item(self, parent, row_list, datos: dict, tipo: str):
        """Renderiza una fila en la lista de APIs o proveedores pasivos."""
        r = row_list[0]
        row_list[0] += 1

        f = ctk.CTkFrame(parent, fg_color=C_SURF, corner_radius=8)
        f.grid(row=r, column=0, sticky="ew", padx=12, pady=(6, 0))
        f.grid_columnconfigure(1, weight=1)

        # Indicador activo/inactivo
        if tipo == "activo":
            activo = str(datos.get("activo", "false")).lower() == "true"
            dot_color = C_VERDE if activo else C_APAGADO
        else:
            dot_color = C_GRAD3

        ctk.CTkLabel(f, text="●", font=("Inter", 14),
                     text_color=dot_color, width=20).grid(row=0, column=0, padx=(12, 4), pady=10)

        # Info
        nombre = datos.get("nombre", "sin nombre")
        if tipo == "activo":
            destino = datos.get("destino", "—")
            intervalo = datos.get("intervalo", "60")
            subtexto = f"cada {intervalo}s  →  {destino}"
        else:
            destino = datos.get("destino", "—")
            ngrok_url = getattr(self, "_ngrok_url", "")
            base = ngrok_url if ngrok_url else "http://localhost:8000"
            subtexto = f"POST {base}/ingresar/{nombre}  →  {destino}"

        info_f = ctk.CTkFrame(f, fg_color="transparent")
        info_f.grid(row=0, column=1, sticky="w", padx=4, pady=8)
        ctk.CTkLabel(info_f, text=nombre, font=("Inter", 13, "bold"),
                     text_color=C_TEXTO).pack(anchor="w")
        ctk.CTkLabel(info_f, text=subtexto, font=F_PEQUENA,
                     text_color=C_APAGADO).pack(anchor="w")

        datos_edit = datos.copy()
        datos_edit["_puede_eliminar"] = True

        frame_btns_fila = ctk.CTkFrame(f, fg_color="transparent")
        frame_btns_fila.grid(row=0, column=2, padx=(4, 12), pady=8)

        if tipo == "pasivo":
            ngrok_url = getattr(self, "_ngrok_url", "")
            base_url = ngrok_url if ngrok_url else "http://localhost:8000"
            url_final = f"{base_url}/ingresar/{datos.get('nombre', 'proveedor')}"
            ctk.CTkButton(frame_btns_fila, text="📋", width=32, height=30,
                          font=F_PEQUENA, fg_color=C_SURF2, hover_color=C_BORDE,
                          text_color=C_GRAD3, corner_radius=6,
                          command=lambda u=url_final: self._copiar_texto(u, f"URL copiada: {u}")
                          ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(frame_btns_fila, text="✏  Editar", width=80, height=30,
                      font=F_PEQUENA, fg_color=C_SURF2, hover_color=C_BORDE,
                      text_color=C_TEXTO,
                      command=lambda d=datos_edit, t=tipo: self._editar_item(d, t)).pack(side="left")

    def _rebuild_lista_apis(self):
        """Reconstruye la lista de APIs desde _apis_data."""
        for w in self._frame_lista_apis.winfo_children():
            info = w.grid_info()
            if info and int(info.get("row", 99)) < 99:
                w.destroy()
        self._lista_apis_row[0] = 0
        for datos in self._apis_data:
            self._fila_item(self._frame_lista_apis,
                            self._lista_apis_row, datos, "activo")

    def _rebuild_lista_pasivos(self):
        """Reconstruye la lista de proveedores pasivos desde _pasivos_data."""
        for w in self._frame_lista_pasivos.winfo_children():
            info = w.grid_info()
            if info and int(info.get("row", 99)) < 99:
                w.destroy()
        self._lista_pasivos_row[0] = 0
        for datos in self._pasivos_data:
            self._fila_item(self._frame_lista_pasivos,
                            self._lista_pasivos_row, datos, "pasivo")

    def _agregar_api(self):
        ModalEdicion(self, "Nueva API — Ingestor activo",
                     {"activo": "false", "intervalo": "60", "destino": "recurso_confiable"},
                     self._cb_api, tipo="activo")

    def _agregar_pasivo(self):
        ModalEdicion(self, "Nuevo Proveedor Pasivo",
                     {"destino": "recurso_confiable"},
                     self._cb_pasivo, tipo="pasivo")

    def _editar_item(self, datos: dict, tipo: str):
        titulo = f"Editar — {datos.get('nombre', 'proveedor')}"
        if tipo == "activo":
            ModalEdicion(self, titulo, datos, self._cb_api, tipo="activo")
        else:
            ModalEdicion(self, titulo, datos, self._cb_pasivo, tipo="pasivo")

    def _cb_api(self, datos: dict, accion: str):
        nombre = datos.get("nombre", "").strip()
        if accion == "guardar" and nombre:
            self._apis_data = [d for d in self._apis_data
                               if d.get("nombre") != nombre]
            self._apis_data.append(datos)
        elif accion == "eliminar":
            self._apis_data = [d for d in self._apis_data
                               if d.get("nombre") != nombre]
        self._rebuild_lista_apis()

    def _cb_pasivo(self, datos: dict, accion: str):
        nombre = datos.get("nombre", "").strip()
        if accion == "guardar" and nombre:
            self._pasivos_data = [d for d in self._pasivos_data
                                  if d.get("nombre") != nombre]
            self._pasivos_data.append(datos)
        elif accion == "eliminar":
            self._pasivos_data = [d for d in self._pasivos_data
                                  if d.get("nombre") != nombre]
        self._rebuild_lista_pasivos()

    # ------------------------------------------------------------------ #
    # Carga y guardado de configuración                                   #
    # ------------------------------------------------------------------ #

    def _cargar_todo(self):
        datos = leer_env()
        self._cargar_campos_simples(datos)
        self._cargar_apis(datos)
        self._cargar_pasivos(datos)

    def _cargar_campos_simples(self, datos: dict):
        for key, (tipo, widget) in self._campos.items():
            valor = datos.get(key, "")
            if tipo == "switch":
                widget.set(valor.lower() == "true")
            elif tipo == "entry":
                widget.delete(0, "end")
                if valor:
                    widget.insert(0, valor)
            elif tipo == "pwd":
                widget.configure(show="")
                widget.delete(0, "end")
                if valor:
                    widget.insert(0, valor)
                widget.configure(show="●")
            elif tipo == "optionmenu":
                if valor and valor != "(ninguno)":
                    try:
                        widget.set(valor)
                    except Exception:
                        pass

    def _cargar_apis(self, datos: dict):
        """
        Carga los ingestores activos desde el .env.
        Hoy solo existe Control Group — en el futuro habrá más.
        Formato en .env: prefijo CONTROL_GROUP_* para el ingestor conocido.
        """
        self._apis_data = []

        # Control Group — el único ingestor activo implementado
        if datos.get("CONTROL_GROUP_USER") or datos.get("CONTROL_GROUP_ENABLED"):
            self._apis_data.append({
                "nombre":    "control_group",
                "activo":    datos.get("CONTROL_GROUP_ENABLED", "false"),
                "url":       datos.get("CONTROL_GROUP_URL", ""),
                "usuario":   datos.get("CONTROL_GROUP_USER", ""),
                "clave":     datos.get("CONTROL_GROUP_PASS", ""),
                "intervalo": datos.get("CONTROL_GROUP_INTERVAL", "60"),
                "destino":   datos.get("DESTINOS_CONTROL_GROUP", "recurso_confiable"),
                "_tipo_conocido": "control_group",
            })

        self._rebuild_lista_apis()

    def _cargar_pasivos(self, datos: dict):
        """
        Carga los proveedores pasivos desde el .env.
        Son los DESTINOS_* que no son CONTROL_GROUP ni DEFAULT.
        """
        self._pasivos_data = []
        excluir = {"DESTINOS_CONTROL_GROUP", "DESTINOS_DEFAULT"}
        for clave, valor in datos.items():
            if clave.startswith("DESTINOS_") and clave not in excluir:
                nombre = clave.replace("DESTINOS_", "").lower()
                self._pasivos_data.append({"nombre": nombre, "destino": valor})
        self._rebuild_lista_pasivos()

    def _guardar(self):
        datos = {}

        # Campos simples del formulario
        for key, (tipo, widget) in self._campos.items():
            if tipo == "switch":
                datos[key] = "true" if widget.get() else "false"
            elif tipo in ("entry", "pwd"):
                datos[key] = widget.get().strip()
            elif tipo == "optionmenu":
                v = widget.get()
                if v != "(ninguno)":
                    datos[key] = v

        # APIs activas → escribir variables en .env
        for api in self._apis_data:
            tipo_conocido = api.get("_tipo_conocido", "")
            nombre = api.get("nombre", "").lower()

            if tipo_conocido == "control_group" or nombre == "control_group":
                datos["CONTROL_GROUP_ENABLED"] = api.get("activo", "false")
                datos["CONTROL_GROUP_URL"]     = api.get("url", "")
                datos["CONTROL_GROUP_USER"]    = api.get("usuario", "")
                datos["CONTROL_GROUP_PASS"]    = api.get("clave", "")
                datos["CONTROL_GROUP_INTERVAL"]= api.get("intervalo", "60")
                datos["DESTINOS_CONTROL_GROUP"]= api.get("destino", "recurso_confiable")
            else:
                # API genérica futura — guardar como DESTINOS_{NOMBRE}
                if nombre:
                    datos[f"DESTINOS_{nombre.upper()}"] = api.get("destino", "")

        # Proveedores pasivos → DESTINOS_{NOMBRE}
        for prov in self._pasivos_data:
            nombre = prov.get("nombre", "").strip().upper().replace("-", "_").replace(" ", "_")
            destino = prov.get("destino", "")
            if nombre and destino and destino != "(ninguno)":
                datos[f"DESTINOS_{nombre}"] = destino

        if not datos.get("PORT"):
            datos["PORT"] = "8000"
        datos.pop("CONFIG_USUARIO", None)
        datos.pop("CONFIG_CLAVE", None)

        # limpiar_prefijos=["DESTINOS_"] elimina del .env todos los DESTINOS_*
        # antes de escribir, para que los proveedores eliminados no reaparezcan
        escribir_env(datos, limpiar_prefijos=["DESTINOS_"])
        self._lbl_ok.configure(
            text="✓ Guardado — Detené y Reiniciá el Hub para aplicar los cambios",
            text_color=C_VERDE)
        self.after(5000, lambda: self._lbl_ok.configure(text=""))
        self._log("SUCCESS", "Configuración guardada en .env")
        if _servidor.en_ejecucion:
            self._log("WARNING", "Detené y volvé a iniciar el Hub para aplicar los cambios.")

    # ------------------------------------------------------------------ #
    # Control Hub                                                         #
    # ------------------------------------------------------------------ #

    def _toggle(self):
        if _servidor.en_ejecucion:
            self._detener()
        else:
            self._iniciar()

    def _iniciar(self):
        self._log("INFO", "Iniciando HUB de datos HTTP — Traductor Rusertech ®...")
        self._btn.configure(state="disabled", text="Iniciando...")
        threading.Thread(target=self._run_iniciar, daemon=True).start()

    def _run_iniciar(self):
        ok = _servidor.iniciar()
        time.sleep(1.5)
        self.after(0, self._post_iniciar if ok else self._post_error)

    def _post_iniciar(self):
        self._btn.configure(state="normal")
        self._uptime_inicio = __import__("time").time()
        self._actualizar_boton()
        self._ciclo_uptime()

    def _post_error(self):
        self._btn.configure(state="normal", text="▶  INICIAR",
                            fg_color=C_GRAD2, hover_color=C_GRAD3, text_color=C_BG_TOP)
        self._circulo.configure(text_color=C_APAGADO)
        self._lbl_estado.configure(text="Error al iniciar", text_color=C_ROJO)

    def _detener(self):
        self._log("WARNING", "Deteniendo Hub...")
        self._btn.configure(state="disabled", text="Deteniendo...")
        threading.Thread(target=self._run_detener, daemon=True).start()

    def _run_detener(self):
        _servidor.detener()
        self.after(0, self._post_detener)

    def _post_detener(self):
        self._btn.configure(state="normal")
        self._actualizar_boton()
        self._log("INFO", "Hub detenido.")
        self._uptime_inicio = 0.0
        self._lbl_uptime.configure(text="")
        if hasattr(self, "_lbl_uptime_monitor"):
            self._lbl_uptime_monitor.configure(text="")
        for v in self._metricas.values():
            v.configure(text="0", text_color=C_TEXTO)

    def _actualizar_boton(self):
        if _servidor.en_ejecucion:
            self._btn.configure(text="⏹  DETENER",
                                fg_color=C_ROJO, hover_color="#c0003a",
                                text_color=C_TEXTO)
            self._circulo.configure(text_color=C_VERDE)
            self._lbl_estado.configure(text="Ejecutando", text_color=C_VERDE)
        else:
            self._btn.configure(text="▶  INICIAR",
                                fg_color=C_GRAD2, hover_color=C_GRAD3,
                                text_color=C_BG_TOP)
            self._circulo.configure(text_color=C_APAGADO)
            self._lbl_estado.configure(text="Detenido", text_color=C_APAGADO)

    # ------------------------------------------------------------------ #
    # Logs                                                                #
    # ------------------------------------------------------------------ #

    def _log(self, nivel: str, msg: str):
        ts = time.strftime("%H:%M:%S")
        self._txt.configure(state="normal")
        self._txt._textbox.insert("end", f"[{ts}] {msg}\n", nivel)
        self._txt._textbox.see("end")
        self._txt.configure(state="disabled")

    def _limpiar(self):
        self._txt.configure(state="normal")
        self._txt.delete("0.0", "end")
        self._txt.configure(state="disabled")

    def _actualizar_logs(self):
        try:
            while True:
                nivel, msg = cola_logs.get_nowait()
                if isinstance(nivel, int):
                    nivel = {10: "DEBUG", 20: "INFO",
                             30: "WARNING", 40: "ERROR"}.get(nivel, "INFO")
                if any(x in msg for x in ["✓", "exitoso", "Éxito"]):
                    nivel = "SUCCESS"
                self._log(nivel, msg)
        except queue.Empty:
            pass
        if (not _servidor.en_ejecucion and hasattr(self, "_btn") and
                "DETENER" in (self._btn.cget("text") or "")):
            self._actualizar_boton()
        self.after(150, self._actualizar_logs)

    # ------------------------------------------------------------------ #
    # Métricas                                                            #
    # ------------------------------------------------------------------ #

    def _buscar_ngrok_exe(self) -> str:
        """Busca ngrok.exe en el PATH y ubicaciones comunes de Windows."""
        import shutil
        from pathlib import Path

        en_path = shutil.which("ngrok")
        if en_path:
            return en_path

        candidatos = [
            BASE_DIR / "ngrok.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "ngrok.exe",
            Path(os.environ.get("USERPROFILE", "")) / "AppData" / "Local" / "ngrok" / "ngrok.exe",
            Path(os.environ.get("USERPROFILE", "")) / "scoop" / "shims" / "ngrok.exe",
        ]
        winget_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        if winget_base.exists():
            for p in winget_base.rglob("ngrok.exe"):
                candidatos.append(p)

        for c in candidatos:
            if c and Path(c).exists():
                return str(c)
        return ""

    def _toggle_ngrok(self):
        """Inicia o detiene ngrok."""
        import subprocess
        if self._proceso_ngrok and self._proceso_ngrok.poll() is None:
            self._proceso_ngrok.terminate()
            self._proceso_ngrok = None
            self._btn_ngrok.configure(text="▶ Iniciar", fg_color=C_GRAD2,
                                       hover_color=C_GRAD3, text_color=C_BG_TOP)
            self._lbl_ngrok.configure(text="No activo", text_color=C_APAGADO)
            self._lbl_ngrok_hint.configure(text="")
            self._ngrok_url = ""
        else:
            exe = self._buscar_ngrok_exe()
            if not exe:
                self._lbl_ngrok.configure(
                    text="ngrok.exe no encontrado", text_color=C_AMARILLO)
                self._lbl_ngrok_hint.configure(
                    text="Descargar en ngrok.com/download y poner en la carpeta del proyecto",
                    text_color=C_APAGADO)
                return
            try:
                self._proceso_ngrok = subprocess.Popen(
                    [exe, "http", "8000"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                self._btn_ngrok.configure(text="⏹ Detener", fg_color=C_ROJO,
                                           hover_color="#c0003a", text_color=C_TEXTO)
                self._lbl_ngrok.configure(text="Iniciando...", text_color=C_AMARILLO)
                self._lbl_ngrok_hint.configure(text="Esperando URL...", text_color=C_APAGADO)
            except Exception as e:
                self._lbl_ngrok.configure(text=f"Error: {e}", text_color=C_ROJO)

    def _copiar_url_ngrok(self, event=None):
        """Copia la URL de ngrok al portapapeles al hacer click."""
        if self._ngrok_url:
            self.clipboard_clear()
            self.clipboard_append(self._ngrok_url)
            self._lbl_ngrok_hint.configure(
                text="✓ Copiado al portapapeles", text_color=C_VERDE)
            self.after(2500, lambda: self._lbl_ngrok_hint.configure(
                text="Click para copiar", text_color=C_APAGADO))

    def _copiar_texto(self, texto: str, mensaje: str = "Copiado"):
        """Copia texto al portapapeles y confirma en el log."""
        self.clipboard_clear()
        self.clipboard_append(texto)
        self._log("SUCCESS", f"✓ {mensaje} al portapapeles")

    def _exportar_log(self):
        """
        Exporta el contenido del log en vivo a un archivo .txt
        y los archivos JSON de logs del día como resumen en .md.
        """
        import json as _json
        from datetime import datetime

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        carpeta = BASE_DIR / "logs"
        carpeta.mkdir(exist_ok=True)

        # 1. Exportar log en vivo de la GUI → .txt
        txt_path = carpeta / f"session_{ts}.txt"
        log_texto = self._txt.get("0.0", "end").strip()
        txt_path.write_text(log_texto, encoding="utf-8")

        # 2. Leer el JSON del día y generar resumen .md
        import time as _time
        hoy = _time.strftime("%Y-%m-%d")
        json_path = carpeta / f"hub_{hoy}.json"

        md_path = carpeta / f"resumen_{ts}.md"
        lineas_md = [
            f"# Resumen de actividad — {hoy}",
            f"Exportado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        if json_path.exists():
            lotes = {}
            despachos = []
            errores = []
            try:
                with open(json_path, encoding="utf-8") as f:
                    for linea in f:
                        linea = linea.strip()
                        if not linea:
                            continue
                        try:
                            ev = _json.loads(linea)
                            tipo = ev.get("tipo", "")
                            if tipo == "ingesta_lote":
                                prv = ev.get("proveedor", "?")
                                lotes[prv] = lotes.get(prv, 0) + ev.get("cantidad_total", 0)
                            elif tipo == "despacho":
                                despachos.append(ev)
                            elif tipo == "error":
                                errores.append(ev)
                        except Exception:
                            pass
            except Exception:
                pass

            # Sección ingesta
            lineas_md.append("## Registros ingestados por proveedor")
            if lotes:
                for prv, total in sorted(lotes.items()):
                    lineas_md.append(f"- **{prv}**: {total:,} registros")
            else:
                lineas_md.append("- Sin datos")
            lineas_md.append("")

            # Sección despacho
            lineas_md.append("## Despachos a destinos")
            if despachos:
                ok_rc = sum(1 for d in despachos if d.get("destino") == "recurso_confiable" and d.get("resultado") == "exitoso")
                fail_rc = sum(1 for d in despachos if d.get("destino") == "recurso_confiable" and d.get("resultado") != "exitoso")
                ok_si = sum(1 for d in despachos if d.get("destino") == "simon" and d.get("resultado") == "exitoso")
                fail_si = sum(1 for d in despachos if d.get("destino") == "simon" and d.get("resultado") != "exitoso")
                if ok_rc + fail_rc > 0:
                    lineas_md.append(f"- **Recurso Confiable**: {ok_rc} exitosos / {fail_rc} fallidos")
                if ok_si + fail_si > 0:
                    lineas_md.append(f"- **Simon 4.0**: {ok_si} exitosos / {fail_si} fallidos")
            else:
                lineas_md.append("- Sin despachos registrados")
            lineas_md.append("")

            # Sección errores
            if errores:
                lineas_md.append("## Errores")
                for e in errores[-10:]:  # últimos 10
                    lineas_md.append(f"- `{e.get('etapa', '?')}` — {e.get('mensaje', '?')[:80]}")
                lineas_md.append("")
        else:
            lineas_md.append("*Sin archivo de log JSON para hoy.*")
            lineas_md.append("")

        lineas_md.append("---")
        lineas_md.append(f"*Log de sesión exportado a: `{txt_path.name}`*")

        md_path.write_text("\n".join(lineas_md), encoding="utf-8")

        self._log("SUCCESS",
                  f"✓ Exportado → {txt_path.name} + {md_path.name} en logs/")

        # Abrir la carpeta
        try:
            import subprocess as _sp
            _sp.Popen(["explorer", str(carpeta)])
        except Exception:
            pass

    def _copiar_endpoint_ngrok(self):
        """Copia la URL pública ngrok completa al portapapeles."""
        url = getattr(self, "_ngrok_url", "")
        if url:
            texto = f"{url}/ingresar/{{nombre}}"
            self.clipboard_clear()
            self.clipboard_append(texto)
            self._log("SUCCESS", f"✓ URL ngrok copiada: {texto}")
            if hasattr(self, "_btn_copiar_ngrok_ep"):
                self._btn_copiar_ngrok_ep.configure(text="✓ Copiado", text_color=C_VERDE)
                self.after(2000, lambda: self._btn_copiar_ngrok_ep.configure(
                    text="📋 Copiar", text_color=C_GRAD3))
        else:
            self._log("WARNING", "ngrok no está activo — inicialo primero")

    def _copiar_token_ingest(self):
        """Copia HUB_INGEST_TOKEN del .env al portapapeles."""
        token = leer_env().get("HUB_INGEST_TOKEN", "").strip()
        if token:
            self.clipboard_clear()
            self.clipboard_append(token)
            self._log("SUCCESS", "✓ Token copiado al portapapeles")
        else:
            self._log("WARNING", "HUB_INGEST_TOKEN está vacío — sin autenticación configurada")

    def _abrir_logs(self):
        """
        Abre la carpeta de logs en el explorador de Windows.
        Si no existe, la crea primero. Si hay logs, abre el más reciente.
        """
        import subprocess as _sp
        carpeta_logs = BASE_DIR / "logs"
        carpeta_logs.mkdir(exist_ok=True)

        # Buscar el archivo de log más reciente
        logs = sorted(carpeta_logs.glob("hub_*.json"), reverse=True)
        if logs:
            # Abrir el archivo más reciente con el programa predeterminado
            # (Notepad, VS Code, etc.)
            try:
                os.startfile(str(logs[0]))
                return
            except Exception:
                pass

        # Si no hay logs o falla, abrir la carpeta
        try:
            _sp.Popen(["explorer", str(carpeta_logs)])
        except Exception:
            self._log("WARNING", f"Logs en: {carpeta_logs}")

    def _ciclo_ngrok(self):
        """
        Consulta la API local de ngrok (puerto 4040) para obtener la URL activa.
        ngrok expone http://localhost:4040/api/tunnels cuando está corriendo.
        Se ejecuta cada 5 segundos.
        """
        threading.Thread(target=self._fetch_ngrok, daemon=True).start()
        self.after(5000, self._ciclo_ngrok)

    def _fetch_ngrok(self):
        """Descarga el estado de ngrok en un hilo aparte."""
        try:
            r = httpx.get("http://localhost:4040/api/tunnels", timeout=2)
            tunnels = r.json().get("tunnels", [])
            # Buscar el túnel HTTPS
            url = ""
            for t in tunnels:
                if t.get("proto") == "https":
                    url = t.get("public_url", "")
                    break
            if not url and tunnels:
                url = tunnels[0].get("public_url", "")

            if url:
                self._ngrok_url = url
                endpoint = f"{url}/ingresar/{{proveedor}}"
                self.after(0, lambda u=url, e=endpoint: self._mostrar_ngrok(u, e))
            else:
                self._ngrok_url = ""
                self.after(0, self._ocultar_ngrok)

        except Exception:
            self._ngrok_url = ""
            self.after(0, self._ocultar_ngrok)

    def _mostrar_ngrok(self, url: str, endpoint: str):
        """Actualiza el panel ngrok con la URL activa y sincroniza el endpoint en Config."""
        host = url.replace("https://", "").replace("http://", "")
        self._lbl_ngrok.configure(text=host, text_color=C_VERDE)
        self._lbl_ngrok_hint.configure(
            text="Click para copiar  ·  /ingresar/{proveedor}",
            text_color=C_APAGADO)
        if hasattr(self, "_lbl_endpoint_ngrok"):
            self._lbl_endpoint_ngrok.configure(
                text=f"POST  {url}/ingresar/{{nombre}}",
                text_color=C_VERDE)
        if hasattr(self, "_btn_copiar_ngrok_ep"):
            self._btn_copiar_ngrok_ep.configure(text_color=C_VERDE)

    def _ocultar_ngrok(self):
        """
        Muestra 'No activo' cuando ngrok no está corriendo.
        Si el proceso terminó inesperadamente, resetea el botón a ▶ Iniciar.
        """
        self._lbl_ngrok.configure(text="No activo", text_color=C_APAGADO)
        self._lbl_ngrok_hint.configure(text="", text_color=C_APAGADO)
        if hasattr(self, "_lbl_endpoint_ngrok"):
            self._lbl_endpoint_ngrok.configure(
                text="POST  https://[ngrok-url]/ingresar/{nombre_proveedor}",
                text_color=C_APAGADO,
            )
        # Si el proceso no está corriendo (terminó o nunca se inició),
        # resetear el botón a ▶ Iniciar
        proceso_vivo = (
            self._proceso_ngrok is not None and
            self._proceso_ngrok.poll() is None
        )
        if not proceso_vivo:
            self._proceso_ngrok = None
            if hasattr(self, "_btn_ngrok"):
                self._btn_ngrok.configure(
                    text="▶ Iniciar",
                    fg_color=C_GRAD2,
                    hover_color=C_GRAD3,
                    text_color=C_BG_TOP,
                )

    def _ciclo_uptime(self):
        """Actualiza el label de uptime cada segundo mientras el Hub está corriendo."""
        if not _servidor.en_ejecucion or self._uptime_inicio == 0:
            return
        elapsed = int(time.time() - self._uptime_inicio)
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            texto = f"↑ {h}h {m:02d}m corriendo"
        elif m > 0:
            texto = f"↑ {m}m {s:02d}s corriendo"
        else:
            texto = f"↑ {s}s corriendo"
        self._lbl_uptime.configure(text=texto, text_color=C_VERDE)
        if hasattr(self, "_lbl_uptime_monitor"):
            self._lbl_uptime_monitor.configure(text=f"— {texto}")
        self.after(1000, self._ciclo_uptime)

    def _actualizar_metricas(self):
        if _servidor.en_ejecucion:
            threading.Thread(target=self._fetch, daemon=True).start()
        self.after(5000, self._actualizar_metricas)

    def _fetch(self):
        try:
            r = httpx.get("http://localhost:8000/metricas", timeout=3)
            d = r.json()
            hub = d.get("hub", {})
            cola = d.get("cola_pendientes", {})
            ing = hub.get("total_ingestados", 0)
            env = hub.get("total_despachados_ok", 0)
            fal = hub.get("total_despachados_fallidos", 0)
            enq = cola.get("recurso_confiable", 0) + cola.get("simon", 0)
            fmt = lambda n: f"{n:,}".replace(",", ".")
            _ing, _env, _fal, _enq = ing, env, fal, enq
            self.after(0, lambda: self._metricas["ingestados"].configure(text=fmt(_ing)))
            self.after(0, lambda: self._metricas["enviados"].configure(
                text=fmt(_env), text_color=C_VERDE if _env > 0 else C_TEXTO))
            self.after(0, lambda: self._metricas["fallidos"].configure(
                text=fmt(_fal), text_color=C_ROJO if _fal > 0 else C_TEXTO))
            self.after(0, lambda: self._metricas["cola"].configure(
                text=fmt(_enq), text_color=C_AMARILLO if _enq > 0 else C_TEXTO))
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Cierre                                                              #
    # ------------------------------------------------------------------ #

    def _al_cerrar(self):
        if self._proceso_ngrok and self._proceso_ngrok.poll() is None:
            self._proceso_ngrok.terminate()
        if _servidor.en_ejecucion:
            _servidor.detener()
        self.destroy()


# =========================================================================== #
# Punto de entrada                                                            #
# =========================================================================== #

if __name__ == "__main__":
    try:
        import customtkinter  # noqa
        import httpx           # noqa
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install",
                        "customtkinter", "httpx"], check=True)
        sys.exit(0)

    login = VentanaLogin()
    login.mainloop()

    if login.acceso_ok:
        app = HubApp()
        app.mainloop()
