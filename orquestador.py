#!/usr/bin/env python3
"""
DRAPEMIND ATELIER - ORQUESTADOR MAESTRO MULTITERMINAL, BASE DE DATOS & IA
Centro de control integral con interfaz fluida y desacoplada:
- Terminal Backend (FastAPI :8000)
- Terminal Frontend (Angular Web :4200)
- Terminal Flutter Móvil (Debug Engine con Hot Reload y stdin interactivo)
- Centro de Depuración Inalámbrica ADB (Pairing, Connect y Reverse Port 8000/4200)
- ESTUDIO VISUAL COMPLETO DE BASE DE DATOS & MIGRACIONES:
  * Explorador de Tablas y Datos en Vivo (Estilo Supabase/TablePlus con Data Grid)
  * Diseñador Visual de Tablas y Columnas (Crea migraciones Alembic con cero código)
  * Asistente y Creador Visual de Seeds (scripts/db/seed/)
  * Consola SQL Interactiva y Logs Alembic
- Gestor y Descargador de Modelos de Inteligencia Artificial (Gemma 4 QAT, Streaming rápido, no bloqueante)
- Selector y persistencia inteligente de directorios (Backend, Web, Móvil, Modelos)
"""

import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

# Importar herramientas modulares
try:
    from scripts.ai.download_models import (
        DEFAULT_MODELS,
        check_models_status,
        download_file_fast,
        format_bytes,
        format_speed,
    )
    from scripts.db.db_tools import (
        check_postgres_status,
        create_database_if_not_exists,
        create_seed_template,
        delete_row_by_pk,
        execute_raw_sql,
        generate_add_column_migration,
        generate_create_table_migration,
        get_all_tables_info,
        get_table_data,
        get_table_schema,
        list_migration_files,
        list_seed_files,
        run_alembic_command,
    )
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from scripts.ai.download_models import (
        DEFAULT_MODELS,
        check_models_status,
        download_file_fast,
        format_bytes,
        format_speed,
    )
    from scripts.db.db_tools import (
        check_postgres_status,
        create_database_if_not_exists,
        create_seed_template,
        delete_row_by_pk,
        execute_raw_sql,
        generate_add_column_migration,
        generate_create_table_migration,
        get_all_tables_info,
        get_table_data,
        get_table_schema,
        list_migration_files,
        list_seed_files,
        run_alembic_command,
    )

# --- RUTAS BASE Y CONFIGURACIÓN ---
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent if CURRENT_DIR.name == "backend" else CURRENT_DIR
CONFIG_FILE = CURRENT_DIR / ".orquestador_config.json"

# --- PALETA ATELIER LUXURY DARK ---
COLOR_BG = "#0E1311"           # Fondo ultra oscuro atelier
COLOR_CARD = "#161D1A"         # Fondo tarjetas y paneles
COLOR_CARD_HEADER = "#1F2824"  # Cabeceras
COLOR_FOREST = "#294438"       # Verde bosque
COLOR_FOREST_LIGHT = "#3A5F4F" # Hover
COLOR_ACID = "#C7F653"         # Acid green acento
COLOR_TEXT = "#F3F1E9"         # Texto blanco papel
COLOR_MUTED = "#88988E"        # Texto secundario gris verdoso
COLOR_BORDER = "#25332D"       # Bordes
COLOR_SUCCESS = "#4ECA78"      # Verde online
COLOR_WARNING = "#E5A93C"      # Ámbar cargando
COLOR_DANGER = "#E05353"       # Rojo error/detenido
COLOR_CONSOLE_BG = "#080B0A"   # Fondo terminal
COLOR_CONSOLE_FG = "#E6ECE8"   # Texto terminal


class ConfigManager:
    """Administra la persistencia de rutas configurables por el usuario."""

    def __init__(self):
        self.backend_dir = str(CURRENT_DIR if CURRENT_DIR.name == "backend" else PROJECT_ROOT / "backend")
        self.web_dir = str(PROJECT_ROOT / "web")
        self.mobile_dir = str(PROJECT_ROOT / "mobile")
        self.ai_models_dir = str(Path(self.backend_dir) / "ai_models" / "gemma-4-e2b")
        self.load()

    def load(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.backend_dir = data.get("backend_dir", self.backend_dir)
                    self.web_dir = data.get("web_dir", self.web_dir)
                    self.mobile_dir = data.get("mobile_dir", self.mobile_dir)
                    self.ai_models_dir = data.get("ai_models_dir", self.ai_models_dir)
            except Exception:
                pass

    def save(self):
        data = {
            "backend_dir": self.backend_dir,
            "web_dir": self.web_dir,
            "mobile_dir": self.mobile_dir,
            "ai_models_dir": self.ai_models_dir,
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass


class ProcessManager:
    """Gestiona el ciclo de vida de un subproceso con lectura y escritura no bloqueante."""

    def __init__(self, name: str, get_cwd_func, on_log_callback):
        self.name = name
        self.get_cwd = get_cwd_func
        self.on_log = on_log_callback
        self.process: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, cmd: list[str] | str, shell: bool = False):
        if self.is_running:
            self.log(f"[WARN] {self.name} ya está en ejecución.")
            return

        cwd = self.get_cwd()
        self.log(f"[START] Iniciando {self.name} en {cwd}...")
        self.log(f"[CMD] {cmd if isinstance(cmd, str) else ' '.join(cmd)}")

        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                universal_newlines=True,
                shell=shell,
            )
            self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
            self._reader_thread.start()
        except Exception as e:
            self.log(f"[ERROR] Error al iniciar {self.name}: {e}")

    def send_input(self, text: str):
        if self.is_running and self.process and self.process.stdin:
            try:
                self.process.stdin.write(text if text.endswith("\n") else text + "\n")
                self.process.stdin.flush()
                self.log(f"[STDIN >] {text.strip()}")
            except Exception as e:
                self.log(f"[ERROR] Error enviando comando stdin: {e}")

    def stop(self):
        if not self.is_running or self.process is None:
            return

        self.log(f"[STOP] Deteniendo {self.name}...")
        try:
            if sys.platform == "win32":
                subprocess.call(["taskkill", "/F", "/T", "/PID", str(self.process.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                self.process.terminate()
        except Exception as e:
            self.log(f"[WARN] Forzando detención: {e}")
        finally:
            self.process = None
            self.log(f"[OFF] {self.name} detenido.")

    def _read_output(self):
        proc = self.process
        if not proc or not proc.stdout:
            return
        try:
            for line in iter(proc.stdout.readline, ""):
                if line:
                    self.on_log(self.name, line)
        except Exception:
            pass
        finally:
            try:
                if proc and proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass

    def log(self, text: str):
        self.on_log(self.name, text + "\n" if not text.endswith("\n") else text)


class TerminalCard(tk.Frame):
    """Componente reutilizable de Terminal individual con controles, logs y barra de comandos."""

    def __init__(self, parent, title: str, subtitle: str, on_start=None, on_stop=None, on_restart=None, extra_controls=None, on_send_input=None):
        super().__init__(parent, bg=COLOR_CARD, highlightbackground=COLOR_BORDER, highlightthickness=1)
        self.title = title
        self.on_send_input = on_send_input
        self.autoscroll = tk.BooleanVar(value=True)

        header = tk.Frame(self, bg=COLOR_CARD_HEADER, padx=10, pady=6)
        header.pack(fill=tk.X)

        lbl_title = tk.Label(header, text=title, font=("Segoe UI", 10, "bold"), fg=COLOR_ACID, bg=COLOR_CARD_HEADER)
        lbl_title.pack(side=tk.LEFT)

        self.lbl_status = tk.Label(header, text="DETENIDO", font=("Segoe UI", 8, "bold"), fg=COLOR_DANGER, bg=COLOR_CARD_HEADER, padx=6)
        self.lbl_status.pack(side=tk.LEFT, padx=6)

        lbl_sub = tk.Label(header, text=subtitle, font=("Segoe UI", 8), fg=COLOR_MUTED, bg=COLOR_CARD_HEADER)
        lbl_sub.pack(side=tk.LEFT)

        btn_box = tk.Frame(header, bg=COLOR_CARD_HEADER)
        btn_box.pack(side=tk.RIGHT)

        if extra_controls:
            extra_controls(btn_box)

        if on_restart:
            btn_restart = tk.Button(btn_box, text="↻", font=("Segoe UI", 8, "bold"), bg=COLOR_FOREST, fg=COLOR_TEXT,
                                    activebackground=COLOR_FOREST_LIGHT, activeforeground=COLOR_TEXT, relief=tk.FLAT,
                                    padx=6, pady=1, cursor="hand2", command=on_restart)
            btn_restart.pack(side=tk.LEFT, padx=2)

        if on_start:
            self.btn_start = tk.Button(btn_box, text="▶ Iniciar", font=("Segoe UI", 8, "bold"), bg=COLOR_FOREST, fg=COLOR_ACID,
                                       activebackground=COLOR_FOREST_LIGHT, activeforeground=COLOR_ACID, relief=tk.FLAT,
                                       padx=8, pady=1, cursor="hand2", command=on_start)
            self.btn_start.pack(side=tk.LEFT, padx=2)

        if on_stop:
            self.btn_stop = tk.Button(btn_box, text="■ Detener", font=("Segoe UI", 8, "bold"), bg="#381D1D", fg="#FF8B8B",
                                      activebackground="#542525", activeforeground="#FFA6A6", relief=tk.FLAT,
                                      padx=6, pady=1, cursor="hand2", command=on_stop)
            self.btn_stop.pack(side=tk.LEFT, padx=2)

        body = tk.Frame(self, bg=COLOR_CONSOLE_BG)
        body.pack(fill=tk.BOTH, expand=True)

        self.txt_console = tk.Text(
            body, bg=COLOR_CONSOLE_BG, fg=COLOR_CONSOLE_FG, insertbackground=COLOR_ACID,
            font=("Consolas", 9), wrap=tk.CHAR, relief=tk.FLAT, padx=6, pady=6
        )
        self.scrollbar = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.txt_console.yview)
        self.txt_console.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt_console.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        footer = tk.Frame(self, bg=COLOR_CARD, padx=6, pady=3)
        footer.pack(fill=tk.X)

        if on_send_input:
            self.var_cmd = tk.StringVar()
            entry_cmd = tk.Entry(footer, textvariable=self.var_cmd, bg="#0F1613", fg=COLOR_TEXT,
                                 insertbackground=COLOR_ACID, relief=tk.FLAT, font=("Consolas", 9))
            entry_cmd.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6), ipady=1)
            entry_cmd.bind("<Return>", lambda e: self._do_send_input())

            btn_send = tk.Button(footer, text="Enviar", font=("Segoe UI", 8, "bold"), bg=COLOR_FOREST, fg=COLOR_TEXT,
                                 relief=tk.FLAT, padx=6, pady=1, cursor="hand2", command=self._do_send_input)
            btn_send.pack(side=tk.LEFT, padx=2)

        btn_clear = tk.Button(footer, text="Limpiar", font=("Segoe UI", 8), bg=COLOR_CARD, fg=COLOR_MUTED,
                              activebackground=COLOR_CARD_HEADER, activeforeground=COLOR_TEXT, relief=tk.FLAT,
                              cursor="hand2", command=self.clear)
        btn_clear.pack(side=tk.RIGHT)

        chk_scroll = tk.Checkbutton(footer, text="Auto-scroll", variable=self.autoscroll, bg=COLOR_CARD,
                                    fg=COLOR_MUTED, selectcolor="#0F1613", activebackground=COLOR_CARD,
                                    activeforeground=COLOR_TEXT, font=("Segoe UI", 8))
        chk_scroll.pack(side=tk.RIGHT, padx=4)

    def _do_send_input(self):
        if not self.on_send_input:
            return
        val = self.var_cmd.get()
        if val.strip():
            self.on_send_input(val)
            self.var_cmd.set("")

    def append_text(self, text: str):
        self.txt_console.insert(tk.END, text)
        if self.autoscroll.get():
            self.txt_console.see(tk.END)

    def clear(self):
        self.txt_console.delete("1.0", tk.END)

    def set_status(self, text: str, color: str):
        self.lbl_status.config(text=text, fg=color)


class OrquestadorApp(tk.Tk):
    """Aplicación principal del Orquestador DrapeMind Atelier."""

    def __init__(self):
        super().__init__()
        self.title("DrapeMind Atelier - Orquestador Maestro, Base de Datos & IA")
        self.geometry("1380x900")
        self.minsize(1120, 760)
        self.configure(bg=COLOR_BG)

        self.cfg = ConfigManager()
        self.log_queue = queue.Queue()
        self.download_queue = queue.Queue(maxsize=200)
        self._download_cancel_flag = False
        self._is_downloading = False

        self._selected_table = "usuarios"
        self._mig_files_cache = []
        self._seed_files_cache = []

        # Procesos
        self.proc_backend = ProcessManager("BACKEND", lambda: self.cfg.backend_dir, self._enqueue_log)
        self.proc_web = ProcessManager("WEB", lambda: self.cfg.web_dir, self._enqueue_log)
        self.proc_mobile = ProcessManager("MOBILE", lambda: self.cfg.mobile_dir, self._enqueue_log)

        self._apply_theme()
        self._build_ui()
        self._start_status_checker()
        self._process_log_queue()
        self._process_download_queue()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_theme(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("TNotebook", background=COLOR_BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=COLOR_CARD, foreground=COLOR_MUTED,
                        padding=[12, 8], font=("Segoe UI", 9, "bold"), borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", COLOR_CARD_HEADER), ("active", COLOR_FOREST)],
                  foreground=[("selected", COLOR_ACID), ("active", COLOR_TEXT)])
        style.configure("TProgressbar", thickness=16, troughcolor=COLOR_CONSOLE_BG, background=COLOR_ACID)

        # Estilo para Treeview (Data Grid visual moderno)
        style.configure("Treeview",
                        background="#0B1310",
                        foreground=COLOR_TEXT,
                        fieldbackground="#0B1310",
                        rowheight=26,
                        font=("Consolas", 9),
                        borderwidth=0)
        style.configure("Treeview.Heading",
                        background=COLOR_CARD_HEADER,
                        foreground=COLOR_ACID,
                        font=("Segoe UI", 9, "bold"),
                        borderwidth=1,
                        relief=tk.FLAT)
        style.map("Treeview",
                  background=[("selected", COLOR_FOREST)],
                  foreground=[("selected", COLOR_ACID)])

    def _build_ui(self):
        header = tk.Frame(self, bg=COLOR_CARD, padx=16, pady=10, highlightbackground=COLOR_BORDER, highlightthickness=1)
        header.pack(fill=tk.X)

        title_box = tk.Frame(header, bg=COLOR_CARD)
        title_box.pack(side=tk.LEFT)

        lbl_app = tk.Label(title_box, text="DRAPEMIND ATELIER", font=("Segoe UI", 13, "bold"), fg=COLOR_ACID, bg=COLOR_CARD)
        lbl_app.pack(anchor=tk.W)

        lbl_desc = tk.Label(title_box, text="Orquestador Maestro · Backend, Frontend, Móvil, Estudio Visual de BD & Modelos IA",
                            font=("Segoe UI", 8), fg=COLOR_MUTED, bg=COLOR_CARD)
        lbl_desc.pack(anchor=tk.W)

        actions_box = tk.Frame(header, bg=COLOR_CARD)
        actions_box.pack(side=tk.RIGHT)

        btn_all_start = tk.Button(actions_box, text="⚡ Iniciar Todo", font=("Segoe UI", 10, "bold"),
                                  bg=COLOR_FOREST, fg=COLOR_ACID, activebackground=COLOR_FOREST_LIGHT,
                                  activeforeground=COLOR_ACID, relief=tk.FLAT, padx=14, pady=5,
                                  cursor="hand2", command=self.start_all)
        btn_all_start.pack(side=tk.LEFT, padx=4)

        btn_all_stop = tk.Button(actions_box, text="🛑 Detener Todo", font=("Segoe UI", 10, "bold"),
                                 bg="#381D1D", fg="#FF8B8B", activebackground="#542525",
                                 activeforeground="#FFA6A6", relief=tk.FLAT, padx=12, pady=5,
                                 cursor="hand2", command=self.stop_all)
        btn_all_stop.pack(side=tk.LEFT, padx=4)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # 1. Vista General
        self.tab_dashboard = tk.Frame(self.notebook, bg=COLOR_BG)
        self.notebook.add(self.tab_dashboard, text="  ✦ Vista General  ")
        self._build_dashboard_tab()

        # 2. Backend
        self.tab_backend = tk.Frame(self.notebook, bg=COLOR_BG)
        self.notebook.add(self.tab_backend, text="  ⚙ Backend (:8000)  ")
        self._build_single_term_tab(self.tab_backend, "BACKEND")

        # 3. Frontend Web
        self.tab_web = tk.Frame(self.notebook, bg=COLOR_BG)
        self.notebook.add(self.tab_web, text="  🌐 Web (:4200)  ")
        self._build_single_term_tab(self.tab_web, "WEB")

        # 4. Flutter Móvil
        self.tab_mobile = tk.Frame(self.notebook, bg=COLOR_BG)
        self.notebook.add(self.tab_mobile, text="  📱 Flutter Móvil  ")
        self._build_single_term_tab(self.tab_mobile, "MOBILE")

        # 5. ADB Inalámbrico
        self.tab_adb = tk.Frame(self.notebook, bg=COLOR_BG)
        self.notebook.add(self.tab_adb, text="  📶 ADB Inalámbrico  ")
        self._build_single_term_tab(self.tab_adb, "ADB")

        # 6. Estudio Visual de Base de Datos & Migraciones
        self.tab_db = tk.Frame(self.notebook, bg=COLOR_BG)
        self.notebook.add(self.tab_db, text="  🗄️ Estudio Visual de BD & Migraciones  ")
        self._build_db_studio_tab()

        # 7. Modelos de IA
        self.tab_ai = tk.Frame(self.notebook, bg=COLOR_BG)
        self.notebook.add(self.tab_ai, text="  🤖 Modelos de IA  ")
        self._build_ai_tab()

        # 8. Configuración de Rutas
        self.tab_config = tk.Frame(self.notebook, bg=COLOR_BG)
        self.notebook.add(self.tab_config, text="  📁 Directorios  ")
        self._build_config_tab()

    def _build_dashboard_tab(self):
        grid = tk.Frame(self.tab_dashboard, bg=COLOR_BG)
        grid.pack(fill=tk.BOTH, expand=True)

        grid.rowconfigure(0, weight=1)
        grid.rowconfigure(1, weight=1)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        self.term_backend = TerminalCard(
            grid, "BACKEND", "FastAPI :8000",
            on_start=self.start_backend, on_stop=self.stop_backend, on_restart=self.restart_backend
        )
        self.term_backend.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        self.term_web = TerminalCard(
            grid, "WEB FRONTEND", "Angular :4200",
            on_start=self.start_web, on_stop=self.stop_web, on_restart=self.restart_web
        )
        self.term_web.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)

        def _flutter_ctrls(box):
            btn_r = tk.Button(box, text="⚡ Hot Reload (r)", font=("Segoe UI", 8, "bold"),
                              bg=COLOR_FOREST, fg=COLOR_ACID, relief=tk.FLAT, padx=6, pady=2,
                              cursor="hand2", command=self.flutter_hot_reload)
            btn_r.pack(side=tk.LEFT, padx=2)
            btn_R = tk.Button(box, text="↻ Hot Restart (R)", font=("Segoe UI", 8, "bold"),
                              bg=COLOR_FOREST, fg=COLOR_TEXT, relief=tk.FLAT, padx=6, pady=2,
                              cursor="hand2", command=self.flutter_hot_restart)
            btn_R.pack(side=tk.LEFT, padx=2)

        self.term_mobile = TerminalCard(
            grid, "FLUTTER MÓVIL", "Motor de Depuración",
            on_start=self.start_mobile, on_stop=self.stop_mobile,
            extra_controls=_flutter_ctrls, on_send_input=self.send_mobile_input
        )
        self.term_mobile.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)

        def _adb_ctrls(box):
            btn_dev = tk.Button(box, text="⟳ Dispositivos", font=("Segoe UI", 8, "bold"),
                                bg=COLOR_FOREST, fg=COLOR_TEXT, relief=tk.FLAT, padx=6, pady=2,
                                cursor="hand2", command=self.refresh_devices)
            btn_dev.pack(side=tk.LEFT, padx=2)

        self.term_adb = TerminalCard(
            grid, "ADB INALÁMBRICO", "Túnel & Pareo de Dispositivos",
            on_start=self.adb_connect, on_stop=self.adb_disconnect,
            extra_controls=_adb_ctrls, on_send_input=self.send_adb_command
        )
        self.term_adb.grid(row=1, column=1, sticky="nsew", padx=4, pady=4)

    def _build_single_term_tab(self, parent, kind: str):
        if kind == "BACKEND":
            self.term_backend_full = TerminalCard(
                parent, "BACKEND", "FastAPI :8000 (Consola Completa)",
                on_start=self.start_backend, on_stop=self.stop_backend, on_restart=self.restart_backend
            )
            self.term_backend_full.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        elif kind == "WEB":
            self.term_web_full = TerminalCard(
                parent, "WEB FRONTEND", "Angular :4200 (Consola Completa)",
                on_start=self.start_web, on_stop=self.stop_web, on_restart=self.restart_web
            )
            self.term_web_full.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        elif kind == "MOBILE":
            def _flutter_ctrls(box):
                lbl = tk.Label(box, text="Dispositivo:", font=("Segoe UI", 8), fg=COLOR_MUTED, bg=COLOR_CARD_HEADER)
                lbl.pack(side=tk.LEFT, padx=4)

                self.var_flutter_device = tk.StringVar()
                self.combo_devices_full = ttk.Combobox(box, textvariable=self.var_flutter_device, width=18, state="readonly")
                self.combo_devices_full.pack(side=tk.LEFT, padx=4)

                btn_r = tk.Button(box, text="⚡ Hot Reload (r)", font=("Segoe UI", 9, "bold"),
                                  bg=COLOR_FOREST, fg=COLOR_ACID, relief=tk.FLAT, padx=8, pady=2,
                                  cursor="hand2", command=self.flutter_hot_reload)
                btn_r.pack(side=tk.LEFT, padx=3)

                btn_R = tk.Button(box, text="↻ Hot Restart (R)", font=("Segoe UI", 9, "bold"),
                                  bg=COLOR_FOREST, fg=COLOR_TEXT, relief=tk.FLAT, padx=8, pady=2,
                                  cursor="hand2", command=self.flutter_hot_restart)
                btn_R.pack(side=tk.LEFT, padx=3)

            self.term_mobile_full = TerminalCard(
                parent, "FLUTTER MÓVIL", "Consola Interactiva Completa",
                on_start=self.start_mobile, on_stop=self.stop_mobile,
                extra_controls=_flutter_ctrls, on_send_input=self.send_mobile_input
            )
            self.term_mobile_full.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        elif kind == "ADB":
            panel = tk.Frame(parent, bg=COLOR_CARD, padx=12, pady=10, highlightbackground=COLOR_BORDER, highlightthickness=1)
            panel.pack(fill=tk.X, padx=4, pady=4)

            f_pair = tk.Frame(panel, bg=COLOR_CARD)
            f_pair.pack(fill=tk.X, pady=3)

            tk.Label(f_pair, text="Vincular (Pair):", font=("Segoe UI", 9, "bold"), fg=COLOR_TEXT, bg=COLOR_CARD, width=14, anchor=tk.W).pack(side=tk.LEFT)
            tk.Label(f_pair, text="IP:Puerto", font=("Segoe UI", 8), fg=COLOR_MUTED, bg=COLOR_CARD).pack(side=tk.LEFT, padx=2)

            self.var_adb_pair_ip = tk.StringVar()
            tk.Entry(f_pair, textvariable=self.var_adb_pair_ip, width=22, bg="#0F1613", fg=COLOR_TEXT,
                     insertbackground=COLOR_ACID, relief=tk.FLAT).pack(side=tk.LEFT, padx=4)

            tk.Label(f_pair, text="Código:", font=("Segoe UI", 8), fg=COLOR_MUTED, bg=COLOR_CARD).pack(side=tk.LEFT, padx=2)
            self.var_adb_pair_code = tk.StringVar()
            tk.Entry(f_pair, textvariable=self.var_adb_pair_code, width=12, bg="#0F1613", fg=COLOR_TEXT,
                     insertbackground=COLOR_ACID, relief=tk.FLAT).pack(side=tk.LEFT, padx=4)

            tk.Button(f_pair, text="Vincular Dispositivo", font=("Segoe UI", 8, "bold"), bg=COLOR_FOREST, fg=COLOR_ACID,
                      relief=tk.FLAT, padx=10, pady=2, cursor="hand2", command=self.adb_pair).pack(side=tk.LEFT, padx=6)

            f_conn = tk.Frame(panel, bg=COLOR_CARD)
            f_conn.pack(fill=tk.X, pady=3)

            tk.Label(f_conn, text="Conectar (Connect):", font=("Segoe UI", 9, "bold"), fg=COLOR_TEXT, bg=COLOR_CARD, width=14, anchor=tk.W).pack(side=tk.LEFT)
            tk.Label(f_conn, text="IP:Puerto", font=("Segoe UI", 8), fg=COLOR_MUTED, bg=COLOR_CARD).pack(side=tk.LEFT, padx=2)

            self.var_adb_connect_ip = tk.StringVar()
            tk.Entry(f_conn, textvariable=self.var_adb_connect_ip, width=22, bg="#0F1613", fg=COLOR_TEXT,
                     insertbackground=COLOR_ACID, relief=tk.FLAT).pack(side=tk.LEFT, padx=4)

            tk.Button(f_conn, text="Conectar Inalámbrico", font=("Segoe UI", 8, "bold"), bg=COLOR_FOREST, fg=COLOR_ACID,
                      relief=tk.FLAT, padx=10, pady=2, cursor="hand2", command=self.adb_connect).pack(side=tk.LEFT, padx=6)
            tk.Button(f_conn, text="Desconectar Todo", font=("Segoe UI", 8), bg="#381D1D", fg="#FF8B8B",
                      relief=tk.FLAT, padx=8, pady=2, cursor="hand2", command=self.adb_disconnect).pack(side=tk.LEFT, padx=4)
            tk.Button(f_conn, text="Reiniciar Servidor ADB", font=("Segoe UI", 8), bg=COLOR_CARD_HEADER, fg=COLOR_TEXT,
                      relief=tk.FLAT, padx=8, pady=2, cursor="hand2", command=self.adb_restart_server).pack(side=tk.LEFT, padx=4)

            self.term_adb_full = TerminalCard(
                parent, "ADB INALÁMBRICO", "Registro de Comandos y Túneles Reverse",
                on_start=self.refresh_devices, on_stop=self.adb_disconnect,
                on_send_input=self.send_adb_command
            )
            self.term_adb_full.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    # =========================================================================
    # ESTUDIO VISUAL COMPLETO DE BASE DE DATOS & MIGRACIONES
    # =========================================================================
    def _build_db_studio_tab(self):
        """Construye el Estudio Visual Integral de Base de Datos."""
        container = tk.Frame(self.tab_db, bg=COLOR_BG, padx=8, pady=6)
        container.pack(fill=tk.BOTH, expand=True)

        # 1. HEADER DE CONTROL SUPERIOR
        header = tk.Frame(container, bg=COLOR_CARD, padx=12, pady=8, highlightbackground=COLOR_BORDER, highlightthickness=1)
        header.pack(fill=tk.X, pady=(0, 6))

        h_left = tk.Frame(header, bg=COLOR_CARD)
        h_left.pack(side=tk.LEFT)

        lbl_t = tk.Label(h_left, text="ESTUDIO VISUAL DE BASE DE DATOS POSTGRESQL & MIGRACIONES",
                         font=("Segoe UI", 11, "bold"), fg=COLOR_ACID, bg=COLOR_CARD)
        lbl_t.pack(anchor=tk.W)

        self.lbl_db_status = tk.Label(h_left, text="Verificando PostgreSQL...", font=("Segoe UI", 8), fg=COLOR_MUTED, bg=COLOR_CARD)
        self.lbl_db_status.pack(anchor=tk.W)

        h_right = tk.Frame(header, bg=COLOR_CARD)
        h_right.pack(side=tk.RIGHT)

        self.btn_create_db = tk.Button(
            h_right, text="➕ Crear Base de Datos (drapemind_db)", font=("Segoe UI", 8, "bold"),
            bg=COLOR_FOREST, fg=COLOR_ACID, relief=tk.FLAT, padx=10, pady=3, cursor="hand2",
            command=self.db_create_database
        )
        self.btn_create_db.pack(side=tk.LEFT, padx=3)

        btn_ref_db = tk.Button(
            h_right, text="⟳ Recargar Tablas & Estado", font=("Segoe UI", 8, "bold"),
            bg=COLOR_CARD_HEADER, fg=COLOR_TEXT, relief=tk.FLAT, padx=8, pady=3, cursor="hand2",
            command=self.refresh_db_studio
        )
        btn_ref_db.pack(side=tk.LEFT, padx=3)

        # 2. SUB-NOTEBOOK DEL ESTUDIO VISUAL
        self.db_notebook = ttk.Notebook(container)
        self.db_notebook.pack(fill=tk.BOTH, expand=True)

        # Sub-pestaña A: Explorador de Tablas y Datos en Vivo (Data Grid)
        self.tab_sub_explorer = tk.Frame(self.db_notebook, bg=COLOR_BG)
        self.db_notebook.add(self.tab_sub_explorer, text="  📊 Explorador de Tablas & Datos en Vivo  ")
        self._build_subtab_explorer()

        # Sub-pestaña B: Diseñador Visual de Migraciones (Cero Código)
        self.tab_sub_designer = tk.Frame(self.db_notebook, bg=COLOR_BG)
        self.db_notebook.add(self.tab_sub_designer, text="  ⚡ Diseñador Visual de Migraciones  ")
        self._build_subtab_designer()

        # Sub-pestaña C: Gestor & Creador Visual de Seeds
        self.tab_sub_seeds = tk.Frame(self.db_notebook, bg=COLOR_BG)
        self.db_notebook.add(self.tab_sub_seeds, text="  🌱 Gestor de Seeds (scripts/db/seed/)  ")
        self._build_subtab_seeds()

        # Sub-pestaña D: Consola SQL & Terminal de Logs
        self.tab_sub_console = tk.Frame(self.db_notebook, bg=COLOR_BG)
        self.db_notebook.add(self.tab_sub_console, text="  💻 Consola SQL & Logs Alembic  ")
        self._build_subtab_console()

        self.refresh_db_studio()

    # --- SUB-PESTAÑA 1: EXPLORADOR VISUAL DE TABLAS Y DATA GRID ---
    def _build_subtab_explorer(self):
        frame = tk.Frame(self.tab_sub_explorer, bg=COLOR_BG, padx=4, pady=4)
        frame.pack(fill=tk.BOTH, expand=True)

        # Panel Izquierdo: Lista de Tablas con búsqueda
        panel_left = tk.Frame(frame, bg=COLOR_CARD, width=280, padx=8, pady=8, highlightbackground=COLOR_BORDER, highlightthickness=1)
        panel_left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 6))
        panel_left.pack_propagate(False)

        lbl_tbl_t = tk.Label(panel_left, text="TABLAS EN POSTGRESQL", font=("Segoe UI", 9, "bold"), fg=COLOR_ACID, bg=COLOR_CARD)
        lbl_tbl_t.pack(anchor=tk.W, pady=(0, 4))

        self.var_table_filter = tk.StringVar()
        entry_filter = tk.Entry(panel_left, textvariable=self.var_table_filter, bg="#0B1310", fg=COLOR_TEXT,
                                insertbackground=COLOR_ACID, relief=tk.FLAT, font=("Segoe UI", 8))
        entry_filter.pack(fill=tk.X, pady=(0, 6), ipady=2)
        entry_filter.bind("<KeyRelease>", lambda e: self._filter_tables_list())

        self.list_tables_box = tk.Listbox(
            panel_left, bg="#080B0A", fg=COLOR_TEXT, font=("Segoe UI", 9),
            selectbackground=COLOR_FOREST, selectforeground=COLOR_ACID, relief=tk.FLAT
        )
        self.list_tables_box.pack(fill=tk.BOTH, expand=True)
        self.list_tables_box.bind("<<ListboxSelect>>", self._on_table_selected)

        # Panel Derecho: Visualizador de Datos y Estructura
        panel_right = tk.Frame(frame, bg=COLOR_CARD, padx=10, pady=8, highlightbackground=COLOR_BORDER, highlightthickness=1)
        panel_right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Toolbar sobre el Data Grid
        toolbar = tk.Frame(panel_right, bg=COLOR_CARD)
        toolbar.pack(fill=tk.X, pady=(0, 6))

        self.lbl_selected_table_info = tk.Label(toolbar, text="Selecciona una tabla para explorar registros",
                                                font=("Segoe UI", 10, "bold"), fg=COLOR_ACID, bg=COLOR_CARD)
        self.lbl_selected_table_info.pack(side=tk.LEFT)

        self.var_data_search = tk.StringVar()
        entry_data_search = tk.Entry(toolbar, textvariable=self.var_data_search, bg="#0B1310", fg=COLOR_TEXT,
                                     insertbackground=COLOR_ACID, relief=tk.FLAT, width=20, font=("Segoe UI", 8))
        entry_data_search.pack(side=tk.RIGHT, padx=4, ipady=2)
        entry_data_search.bind("<Return>", lambda e: self.load_selected_table_data())

        btn_search_data = tk.Button(toolbar, text="🔍 Buscar", font=("Segoe UI", 8, "bold"), bg=COLOR_FOREST, fg=COLOR_TEXT,
                                    relief=tk.FLAT, padx=8, pady=1, cursor="hand2", command=self.load_selected_table_data)
        btn_search_data.pack(side=tk.RIGHT, padx=2)

        self.var_view_mode = tk.StringVar(value="DATA")
        btn_toggle_mode = tk.Button(toolbar, text="📑 Ver Columnas / Esquema", font=("Segoe UI", 8),
                                    bg=COLOR_CARD_HEADER, fg=COLOR_TEXT, relief=tk.FLAT, padx=8, pady=1,
                                    cursor="hand2", command=self._toggle_table_view_mode)
        btn_toggle_mode.pack(side=tk.RIGHT, padx=4)

        btn_refresh_tbl = tk.Button(toolbar, text="⟳", font=("Segoe UI", 8, "bold"), bg=COLOR_FOREST, fg=COLOR_TEXT,
                                    relief=tk.FLAT, padx=6, pady=1, cursor="hand2", command=self.load_selected_table_data)
        btn_refresh_tbl.pack(side=tk.RIGHT, padx=2)

        # Contenedor del Data Grid con Scrollbars
        grid_box = tk.Frame(panel_right, bg="#080B0A")
        grid_box.pack(fill=tk.BOTH, expand=True)

        self.tree_data = ttk.Treeview(grid_box, show="headings", selectmode="browse")
        scroll_y = ttk.Scrollbar(grid_box, orient=tk.VERTICAL, command=self.tree_data.yview)
        scroll_x = ttk.Scrollbar(grid_box, orient=tk.HORIZONTAL, command=self.tree_data.xview)
        self.tree_data.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree_data.pack(fill=tk.BOTH, expand=True)

        # Footer del Data Grid con acciones de fila
        footer_grid = tk.Frame(panel_right, bg=COLOR_CARD, pady=4)
        footer_grid.pack(fill=tk.X)

        self.lbl_grid_stats = tk.Label(footer_grid, text="0 filas", font=("Segoe UI", 8), fg=COLOR_MUTED, bg=COLOR_CARD)
        self.lbl_grid_stats.pack(side=tk.LEFT)

        btn_del_row = tk.Button(footer_grid, text="🗑️ Eliminar Fila Seleccionada", font=("Segoe UI", 8),
                                bg="#381D1D", fg="#FF8B8B", relief=tk.FLAT, padx=8, pady=2,
                                cursor="hand2", command=self.delete_selected_row)
        btn_del_row.pack(side=tk.RIGHT, padx=4)

    # --- SUB-PESTAÑA 2: DISEÑADOR VISUAL DE MIGRACIONES (CERO CÓDIGO) ---
    def _build_subtab_designer(self):
        container = tk.Frame(self.tab_sub_designer, bg=COLOR_BG, padx=8, pady=8)
        container.pack(fill=tk.BOTH, expand=True)

        col_left = tk.Frame(container, bg=COLOR_CARD, padx=12, pady=10, highlightbackground=COLOR_BORDER, highlightthickness=1)
        col_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        lbl_d1 = tk.Label(col_left, text="⚡ CREADOR VISUAL DE TABLAS (SIN CÓDIGO)", font=("Segoe UI", 10, "bold"), fg=COLOR_ACID, bg=COLOR_CARD)
        lbl_d1.pack(anchor=tk.W)

        lbl_d1_sub = tk.Label(col_left, text="Define las columnas y genera la migración Alembic automáticamente.", font=("Segoe UI", 8), fg=COLOR_MUTED, bg=COLOR_CARD)
        lbl_d1_sub.pack(anchor=tk.W, pady=(1, 8))

        row_tbl_name = tk.Frame(col_left, bg=COLOR_CARD)
        row_tbl_name.pack(fill=tk.X, pady=2)
        tk.Label(row_tbl_name, text="Nombre de la Nueva Tabla:", font=("Segoe UI", 8, "bold"), fg=COLOR_TEXT, bg=COLOR_CARD).pack(side=tk.LEFT)
        self.var_new_table_name = tk.StringVar()
        tk.Entry(row_tbl_name, textvariable=self.var_new_table_name, bg="#0B1310", fg=COLOR_TEXT, insertbackground=COLOR_ACID, relief=tk.FLAT, font=("Consolas", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6, ipady=2)

        # Columnas dinámicas para la nueva tabla
        lbl_cols_title = tk.Label(col_left, text="Columnas de la Tabla (por defecto incluye 'id'):", font=("Segoe UI", 8, "bold"), fg=COLOR_TEXT, bg=COLOR_CARD)
        lbl_cols_title.pack(anchor=tk.W, pady=(8, 2))

        self.frame_columns_builder = tk.Frame(col_left, bg="#0B1310", padx=6, pady=6)
        self.frame_columns_builder.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        self._builder_columns_list = []
        self._add_builder_column_row("nombre", "String", is_pk=False, nullable=False)
        self._add_builder_column_row("descripcion", "Text", is_pk=False, nullable=True)

        btn_add_col_row = tk.Button(col_left, text="➕ Agregar Otra Columna", font=("Segoe UI", 8, "bold"),
                                    bg=COLOR_CARD_HEADER, fg=COLOR_ACID, relief=tk.FLAT, padx=8, pady=2,
                                    cursor="hand2", command=lambda: self._add_builder_column_row("nueva_columna", "String"))
        btn_add_col_row.pack(anchor=tk.W, pady=(0, 8))

        btn_generate_tbl = tk.Button(col_left, text="🚀 Generar y Aplicar Migración de Tabla", font=("Segoe UI", 9, "bold"),
                                     bg=COLOR_FOREST, fg=COLOR_ACID, activebackground=COLOR_FOREST_LIGHT, relief=tk.FLAT,
                                     padx=12, pady=4, cursor="hand2", command=self.designer_create_table_migration)
        btn_generate_tbl.pack(fill=tk.X)

        # Columna Derecha: Agregar Columna a Tabla Existente & Lista de Migraciones
        col_right = tk.Frame(container, bg=COLOR_CARD, padx=12, pady=10, highlightbackground=COLOR_BORDER, highlightthickness=1)
        col_right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0))

        lbl_d2 = tk.Label(col_right, text="⚡ AGREGAR COLUMNA A TABLA EXISTENTE", font=("Segoe UI", 10, "bold"), fg=COLOR_ACID, bg=COLOR_CARD)
        lbl_d2.pack(anchor=tk.W)

        f_add_col = tk.Frame(col_right, bg=COLOR_CARD)
        f_add_col.pack(fill=tk.X, pady=4)

        tk.Label(f_add_col, text="Tabla:", font=("Segoe UI", 8, "bold"), fg=COLOR_TEXT, bg=COLOR_CARD).pack(side=tk.LEFT)
        self.var_add_col_table = tk.StringVar()
        self.combo_add_col_tables = ttk.Combobox(f_add_col, textvariable=self.var_add_col_table, state="readonly", width=16)
        self.combo_add_col_tables.pack(side=tk.LEFT, padx=4)

        tk.Label(f_add_col, text="Columna:", font=("Segoe UI", 8, "bold"), fg=COLOR_TEXT, bg=COLOR_CARD).pack(side=tk.LEFT, padx=2)
        self.var_add_col_name = tk.StringVar()
        tk.Entry(f_add_col, textvariable=self.var_add_col_name, width=14, bg="#0B1310", fg=COLOR_TEXT, insertbackground=COLOR_ACID, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        self.var_add_col_type = tk.StringVar(value="String")
        ttk.Combobox(f_add_col, textvariable=self.var_add_col_type, values=["String", "Integer", "Text", "Boolean", "Float", "DateTime", "JSONB"], state="readonly", width=9).pack(side=tk.LEFT, padx=2)

        btn_do_add_col = tk.Button(col_right, text="🚀 Generar y Aplicar Columna", font=("Segoe UI", 8, "bold"),
                                   bg=COLOR_FOREST, fg=COLOR_ACID, relief=tk.FLAT, padx=10, pady=3,
                                   cursor="hand2", command=self.designer_add_column_migration)
        btn_do_add_col.pack(anchor=tk.W, pady=(2, 10))

        # Migraciones Alembic Historial
        lbl_mig_hist = tk.Label(col_right, text="ARCHIVOS DE MIGRACIÓN (alembic/versions/):", font=("Segoe UI", 9, "bold"), fg=COLOR_TEXT, bg=COLOR_CARD)
        lbl_mig_hist.pack(anchor=tk.W, pady=(6, 2))

        self.list_mig_box_full = tk.Listbox(
            col_right, bg="#080B0A", fg=COLOR_TEXT, font=("Consolas", 8),
            selectbackground=COLOR_FOREST, selectforeground=COLOR_ACID, relief=tk.FLAT, height=7
        )
        self.list_mig_box_full.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        row_mig_btns = tk.Frame(col_right, bg=COLOR_CARD)
        row_mig_btns.pack(fill=tk.X)

        btn_auto_detect = tk.Button(row_mig_btns, text="⚡ Detectar Modelos (Autogenerate)", font=("Segoe UI", 8, "bold"),
                                    bg=COLOR_FOREST, fg=COLOR_ACID, relief=tk.FLAT, padx=6, pady=2, cursor="hand2",
                                    command=self.db_create_autogenerate_migration)
        btn_auto_detect.pack(side=tk.LEFT, padx=2)

        btn_up_all = tk.Button(row_mig_btns, text="🚀 Upgrade Head", font=("Segoe UI", 8, "bold"),
                               bg=COLOR_FOREST, fg=COLOR_TEXT, relief=tk.FLAT, padx=6, pady=2, cursor="hand2",
                               command=self.db_run_upgrade)
        btn_up_all.pack(side=tk.LEFT, padx=2)

        btn_down = tk.Button(row_mig_btns, text="⏪ Revertir (-1)", font=("Segoe UI", 8),
                             bg="#381D1D", fg="#FF8B8B", relief=tk.FLAT, padx=6, pady=2, cursor="hand2",
                             command=self.db_run_downgrade)
        btn_down.pack(side=tk.LEFT, padx=2)

        btn_open_m_fol = tk.Button(row_mig_btns, text="📂 Abrir Carpeta", font=("Segoe UI", 8),
                                   bg=COLOR_CARD_HEADER, fg=COLOR_TEXT, relief=tk.FLAT, padx=6, pady=2, cursor="hand2",
                                   command=self.db_open_migrations_folder)
        btn_open_m_fol.pack(side=tk.RIGHT)

    def _add_builder_column_row(self, col_name: str, col_type: str = "String", is_pk: bool = False, nullable: bool = True):
        row = tk.Frame(self.frame_columns_builder, bg="#0B1310", pady=2)
        row.pack(fill=tk.X)

        var_n = tk.StringVar(value=col_name)
        var_t = tk.StringVar(value=col_type)
        var_pk = tk.BooleanVar(value=is_pk)
        var_null = tk.BooleanVar(value=nullable)

        tk.Entry(row, textvariable=var_n, width=18, bg="#161D1A", fg=COLOR_TEXT, insertbackground=COLOR_ACID, relief=tk.FLAT, font=("Consolas", 8)).pack(side=tk.LEFT, padx=2)
        ttk.Combobox(row, textvariable=var_t, values=["String", "Integer", "Text", "Boolean", "Float", "DateTime", "JSONB"], state="readonly", width=9).pack(side=tk.LEFT, padx=2)
        tk.Checkbutton(row, text="PK", variable=var_pk, bg="#0B1310", fg=COLOR_ACID, selectcolor="#161D1A", activebackground="#0B1310", font=("Segoe UI", 7)).pack(side=tk.LEFT, padx=2)
        tk.Checkbutton(row, text="Null?", variable=var_null, bg="#0B1310", fg=COLOR_MUTED, selectcolor="#161D1A", activebackground="#0B1310", font=("Segoe UI", 7)).pack(side=tk.LEFT, padx=2)

        btn_del = tk.Button(row, text="✖", font=("Segoe UI", 7), bg="#381D1D", fg="#FF8B8B", relief=tk.FLAT, padx=4, cursor="hand2",
                            command=lambda: self._remove_builder_column_row(row, col_dict))
        btn_del.pack(side=tk.RIGHT, padx=2)

        col_dict = {"frame": row, "var_name": var_n, "var_type": var_t, "var_pk": var_pk, "var_nullable": var_null}
        self._builder_columns_list.append(col_dict)

    def _remove_builder_column_row(self, frame_row, col_dict):
        if col_dict in self._builder_columns_list:
            self._builder_columns_list.remove(col_dict)
        frame_row.destroy()

    # --- SUB-PESTAÑA 3: GESTOR DE SEEDS ---
    def _build_subtab_seeds(self):
        container = tk.Frame(self.tab_sub_seeds, bg=COLOR_BG, padx=12, pady=10)
        container.pack(fill=tk.BOTH, expand=True)

        top_box = tk.Frame(container, bg=COLOR_CARD, padx=12, pady=10, highlightbackground=COLOR_BORDER, highlightthickness=1)
        top_box.pack(fill=tk.X, pady=(0, 8))

        lbl_st = tk.Label(top_box, text="GESTIÓN Y EJECUCIÓN DE SEEDERS DE BASE DE DATOS", font=("Segoe UI", 10, "bold"), fg=COLOR_ACID, bg=COLOR_CARD)
        lbl_st.pack(anchor=tk.W)

        lbl_s_desc = tk.Label(top_box, text="Carpeta: backend/scripts/db/seed/ · Crea datos de prueba y catálogo con 1 clic.", font=("Segoe UI", 8), fg=COLOR_MUTED, bg=COLOR_CARD)
        lbl_s_desc.pack(anchor=tk.W, pady=(1, 6))

        btn_box = tk.Frame(top_box, bg=COLOR_CARD)
        btn_box.pack(fill=tk.X)

        btn_run_all = tk.Button(btn_box, text="🌱 Ejecutar Población Completa (seed_data.py)", font=("Segoe UI", 9, "bold"),
                                bg="#1B382B", fg=COLOR_ACID, activebackground=COLOR_FOREST_LIGHT, relief=tk.FLAT,
                                padx=12, pady=3, cursor="hand2", command=self.db_run_seed)
        btn_run_all.pack(side=tk.LEFT, padx=(0, 4))

        btn_new_seed = tk.Button(btn_box, text="➕ Crear Nuevo Script Seed", font=("Segoe UI", 8, "bold"),
                                 bg=COLOR_FOREST, fg=COLOR_TEXT, relief=tk.FLAT, padx=10, pady=3, cursor="hand2",
                                 command=self.db_create_new_seed)
        btn_new_seed.pack(side=tk.LEFT, padx=4)

        btn_open_seed_f = tk.Button(btn_box, text="📂 Abrir Carpeta de Seeds", font=("Segoe UI", 8),
                                    bg=COLOR_CARD_HEADER, fg=COLOR_TEXT, relief=tk.FLAT, padx=8, pady=3, cursor="hand2",
                                    command=self.db_open_seed_folder)
        btn_open_seed_f.pack(side=tk.RIGHT)

        # Lista de Seeds
        lbl_s_list = tk.Label(container, text="Scripts Seeder Disponibles:", font=("Segoe UI", 9, "bold"), fg=COLOR_TEXT, bg=COLOR_BG)
        lbl_s_list.pack(anchor=tk.W, pady=(6, 2))

        self.list_seed_box_full = tk.Listbox(
            container, bg="#080B0A", fg=COLOR_TEXT, font=("Consolas", 9),
            selectbackground=COLOR_FOREST, selectforeground=COLOR_ACID, relief=tk.FLAT, height=10
        )
        self.list_seed_box_full.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        btn_actions_seed = tk.Frame(container, bg=COLOR_BG)
        btn_actions_seed.pack(fill=tk.X)

        btn_run_one = tk.Button(btn_actions_seed, text="▶ Ejecutar Seed Seleccionado", font=("Segoe UI", 8, "bold"),
                                bg=COLOR_FOREST, fg=COLOR_ACID, relief=tk.FLAT, padx=10, pady=3, cursor="hand2",
                                command=self.db_run_selected_seed_full)
        btn_run_one.pack(side=tk.LEFT, padx=(0, 4))

        btn_edit_one = tk.Button(btn_actions_seed, text="✏️ Editar Código en Editor", font=("Segoe UI", 8),
                                 bg=COLOR_CARD_HEADER, fg=COLOR_TEXT, relief=tk.FLAT, padx=10, pady=3, cursor="hand2",
                                 command=self.db_open_selected_seed_full)
        btn_edit_one.pack(side=tk.LEFT, padx=4)

    # --- SUB-PESTAÑA 4: CONSOLA SQL & LOGS ALEMBIC ---
    def _build_subtab_console(self):
        container = tk.Frame(self.tab_sub_console, bg=COLOR_BG, padx=8, pady=8)
        container.pack(fill=tk.BOTH, expand=True)

        # Editor SQL
        sql_box = tk.Frame(container, bg=COLOR_CARD, padx=10, pady=8, highlightbackground=COLOR_BORDER, highlightthickness=1)
        sql_box.pack(fill=tk.X, pady=(0, 6))

        lbl_sql = tk.Label(sql_box, text="CONSOLA SQL INTERACTIVA (POSTGRESQL):", font=("Segoe UI", 9, "bold"), fg=COLOR_ACID, bg=COLOR_CARD)
        lbl_sql.pack(anchor=tk.W)

        self.txt_sql_input = tk.Text(sql_box, bg="#080B0A", fg=COLOR_TEXT, font=("Consolas", 9), height=3, relief=tk.FLAT, padx=6, pady=4)
        self.txt_sql_input.insert(tk.END, "SELECT id, nombre, email, rol, estado FROM usuarios LIMIT 10;")
        self.txt_sql_input.pack(fill=tk.X, pady=4)

        btn_row_sql = tk.Frame(sql_box, bg=COLOR_CARD)
        btn_row_sql.pack(fill=tk.X)

        btn_exec_sql = tk.Button(btn_row_sql, text="▶ Ejecutar Consulta SQL", font=("Segoe UI", 8, "bold"),
                                 bg=COLOR_FOREST, fg=COLOR_ACID, relief=tk.FLAT, padx=12, pady=2, cursor="hand2",
                                 command=self.db_execute_custom_sql)
        btn_exec_sql.pack(side=tk.LEFT)

        self.lbl_sql_res_status = tk.Label(btn_row_sql, text="", font=("Segoe UI", 8), fg=COLOR_MUTED, bg=COLOR_CARD)
        self.lbl_sql_res_status.pack(side=tk.LEFT, padx=8)

        # Terminal de Logs en Vivo
        self.term_db = TerminalCard(
            container, "REGISTRO EN VIVO DE BASE DE DATOS & ALEMBIC", "Salida de migraciones, comandos y consultas"
        )
        self.term_db.pack(fill=tk.BOTH, expand=True)

    # --- LÓGICA Y CONTROL DEL ESTUDIO VISUAL ---
    def refresh_db_studio(self):
        """Actualiza todas las tablas, estado y listas del estudio visual."""
        def _worker():
            st = check_postgres_status()
            online = st.get("server_online", False)
            db_exists = st.get("db_exists", False)
            msg = st.get("message", "")

            tables_info = get_all_tables_info() if online and db_exists else []
            backend_p = Path(self.cfg.backend_dir)
            migs = list_migration_files(backend_p)
            seeds = list_seed_files(backend_p)

            def _update_ui():
                if not online:
                    self.lbl_db_status.config(text=f"❌ {msg}", fg=COLOR_DANGER)
                    self.btn_create_db.config(state=tk.DISABLED)
                elif not db_exists:
                    self.lbl_db_status.config(text=f"⚠️ {msg}", fg=COLOR_WARNING)
                    self.btn_create_db.config(state=tk.NORMAL)
                else:
                    self.lbl_db_status.config(text=f"✓ {msg}", fg=COLOR_SUCCESS)
                    self.btn_create_db.config(state=tk.DISABLED)

                # Actualizar lista de tablas
                self._cached_tables_info = tables_info
                self._filter_tables_list()

                # Actualizar comboboxes
                table_names = [t["name"] for t in tables_info]
                if hasattr(self, "combo_add_col_tables"):
                    self.combo_add_col_tables["values"] = table_names
                    if table_names and not self.var_add_col_table.get():
                        self.var_add_col_table.set(table_names[0])

                # Actualizar listas de migraciones y seeds
                self._mig_files_cache = migs
                self._seed_files_cache = seeds

                if hasattr(self, "list_mig_box_full"):
                    self.list_mig_box_full.delete(0, tk.END)
                    for m in migs:
                        self.list_mig_box_full.insert(tk.END, f"  {m['name']} ({m['size']}, {m['date']})")

                if hasattr(self, "list_seed_box_full"):
                    self.list_seed_box_full.delete(0, tk.END)
                    for s in seeds:
                        self.list_seed_box_full.insert(tk.END, f"  {s['name']} ({s['size']}, {s['date']})")

                # Cargar datos de la tabla actual
                if table_names:
                    if self._selected_table not in table_names:
                        self._selected_table = table_names[0]
                    self.load_selected_table_data()

            self.after(0, _update_ui)

        threading.Thread(target=_worker, daemon=True).start()

    def _filter_tables_list(self):
        query = self.var_table_filter.get().strip().lower()
        self.list_tables_box.delete(0, tk.END)
        for t in getattr(self, "_cached_tables_info", []):
            if not query or query in t["name"].lower():
                self.list_tables_box.insert(tk.END, f" 📁 {t['name']}  ({t['row_count']} filas)")

    def _on_table_selected(self, event):
        sel = self.list_tables_box.curselection()
        if not sel:
            return
        item_text = self.list_tables_box.get(sel[0])
        # Extraer nombre limpio de la tabla
        tbl_name = item_text.replace(" 📁 ", "").split()[0]
        self._selected_table = tbl_name
        self.load_selected_table_data()

    def _toggle_table_view_mode(self):
        cur = self.var_view_mode.get()
        new_mode = "SCHEMA" if cur == "DATA" else "DATA"
        self.var_view_mode.set(new_mode)
        self.load_selected_table_data()

    def load_selected_table_data(self):
        """Carga y renderiza los datos o esquema de la tabla seleccionada en el Data Grid."""
        tbl = self._selected_table
        if not tbl:
            return

        mode = self.var_view_mode.get()
        search_txt = self.var_data_search.get()

        def _worker():
            if mode == "SCHEMA":
                schema = get_table_schema(tbl)
                columns = ["COLUMNA", "TIPO DATO", "¿NULLABLE?", "¿CLAVE?", "DEFAULT"]
                rows = [[c["name"], c["type"], c["nullable"], c["primary_key"], c["default"]] for c in schema]
                total = len(rows)
            else:
                columns, rows, total = get_table_data(tbl, limit=100, search_text=search_txt)

            def _render():
                self.lbl_selected_table_info.config(text=f"Tabla: '{tbl}' ({'Estructura de Columnas' if mode == 'SCHEMA' else 'Datos en Vivo'})")
                self.lbl_grid_stats.config(text=f"Mostrando {len(rows)} de {total} fila(s) · Tabla: {tbl}")

                # Limpiar árbol
                self.tree_data.delete(*self.tree_data.get_children())
                self.tree_data["columns"] = columns

                for col in columns:
                    self.tree_data.heading(col, text=col.upper())
                    self.tree_data.column(col, width=max(100, min(240, len(col) * 14)), anchor=tk.W)

                for r in rows:
                    self.tree_data.insert("", tk.END, values=r)

            self.after(0, _render)

        threading.Thread(target=_worker, daemon=True).start()

    def delete_selected_row(self):
        """Elimina la fila seleccionada por su primer columna (id/pk)."""
        sel = self.tree_data.selection()
        if not sel:
            messagebox.showinfo("Selección", "Selecciona una fila en la cuadrícula para eliminar.")
            return

        values = self.tree_data.item(sel[0], "values")
        if not values or not self._selected_table:
            return

        pk_col = self.tree_data["columns"][0]
        pk_val = values[0]

        if not messagebox.askyesno("Confirmar Eliminación", f"¿Eliminar fila con {pk_col} = '{pk_val}' de la tabla '{self._selected_table}'?"):
            return

        def _worker():
            success = delete_row_by_pk(self._selected_table, pk_col, pk_val)
            if success:
                self._enqueue_log("DB", f"[DB] ✓ Fila eliminada en {self._selected_table} ({pk_col} = {pk_val}).\n")
                self.after(0, self.load_selected_table_data)
            else:
                self._enqueue_log("DB", f"[ERROR DB] No se pudo eliminar la fila.\n")

        threading.Thread(target=_worker, daemon=True).start()

    def designer_create_table_migration(self):
        """Genera y aplica la migración para crear una nueva tabla visualmente."""
        tbl_name = self.var_new_table_name.get().strip()
        if not tbl_name:
            messagebox.showwarning("Nombre Requerido", "Ingresa un nombre para la nueva tabla.")
            return

        cols = [{"name": "id", "type": "Integer", "pk": True, "nullable": False}]
        for row_dict in self._builder_columns_list:
            c_name = row_dict["var_name"].get().strip()
            c_type = row_dict["var_type"].get().strip()
            is_pk = row_dict["var_pk"].get()
            is_null = row_dict["var_nullable"].get()
            if c_name:
                cols.append({"name": c_name, "type": c_type, "pk": is_pk, "nullable": is_null})

        backend_p = Path(self.cfg.backend_dir)
        mig_path = generate_create_table_migration(tbl_name, cols, backend_p)
        self._enqueue_log("DB", f"[DISEÑADOR] ✓ Creada migración de tabla: {mig_path.name}\n")

        # Aplicar migración automáticamente
        self.db_run_upgrade()
        messagebox.showinfo("Migración Creada", f"Migración para crear la tabla '{tbl_name}' generada y aplicada con éxito.")

    def designer_add_column_migration(self):
        """Genera y aplica la migración para agregar una columna."""
        tbl = self.var_add_col_table.get().strip()
        col = self.var_add_col_name.get().strip()
        c_type = self.var_add_col_type.get().strip()

        if not tbl or not col:
            messagebox.showwarning("Campos Requeridos", "Selecciona una tabla e ingresa el nombre de la columna.")
            return

        backend_p = Path(self.cfg.backend_dir)
        mig_path = generate_add_column_migration(tbl, col, c_type, nullable=True, backend_dir=backend_p)
        self._enqueue_log("DB", f"[DISEÑADOR] ✓ Creada migración de columna: {mig_path.name}\n")
        self.db_run_upgrade()
        messagebox.showinfo("Columna Agregada", f"Columna '{col}' ({c_type}) agregada a la tabla '{tbl}' exitosamente.")

    def db_execute_custom_sql(self):
        """Ejecuta SQL personalizado y muestra el resultado en el grid y consola."""
        sql = self.txt_sql_input.get("1.0", tk.END).strip()
        if not sql:
            return

        def _worker():
            cols, rows, msg = execute_raw_sql(sql)
            self._enqueue_log("DB", f"[SQL RUN] {sql}\n[SQL OUT] {msg}\n")

            def _update():
                self.lbl_sql_res_status.config(text=msg)
                if cols and rows and cols != ["Resultado"]:
                    self.tree_data.delete(*self.tree_data.get_children())
                    self.tree_data["columns"] = cols
                    for col in cols:
                        self.tree_data.heading(col, text=col.upper())
                        self.tree_data.column(col, width=120)
                    for r in rows:
                        self.tree_data.insert("", tk.END, values=r)
                    self.lbl_selected_table_info.config(text="Resultado de Consulta SQL Personalizada")
                    self.lbl_grid_stats.config(text=f"{len(rows)} fila(s) retornada(s)")
                self.refresh_db_studio()

            self.after(0, _update)

        threading.Thread(target=_worker, daemon=True).start()

    def db_create_database(self):
        """Crea la base de datos drapemind_db."""
        def _worker():
            self._enqueue_log("DB", "[DB] Iniciando creación de base de datos drapemind_db...\n")
            success = create_database_if_not_exists(lambda msg: self._enqueue_log("DB", msg + "\n"))
            if success:
                self.after(0, self.refresh_db_studio)
                self.after(0, lambda: messagebox.showinfo("Base de Datos", "Base de datos drapemind_db creada exitosamente."))
        threading.Thread(target=_worker, daemon=True).start()

    def db_create_autogenerate_migration(self):
        """Crea una migración automática comparando modelos SQLAlchemy con PostgreSQL."""
        msg = simpledialog.askstring("Autogenerate Migración", "Ingresa una breve descripción del cambio en los modelos:\n(Ej: add_loyalty_points_to_user)", parent=self)
        if not msg or not msg.strip():
            return

        clean_slug = msg.strip().replace(" ", "_").lower()

        def _worker():
            cwd = Path(self.cfg.backend_dir)
            self._enqueue_log("DB", f"[MIGRACIÓN] Comparando modelos con PostgreSQL y generando '{clean_slug}'...\n")
            run_alembic_command(["revision", "--autogenerate", "-m", clean_slug], cwd, lambda line: self._enqueue_log("DB", line))
            self.after(0, self.refresh_db_studio)
        threading.Thread(target=_worker, daemon=True).start()

    def db_run_upgrade(self):
        """Aplica todas las migraciones pendientes con Alembic."""
        def _worker():
            cwd = Path(self.cfg.backend_dir)
            self._enqueue_log("DB", "[MIGRACIÓN] Aplicando migraciones pendientes (upgrade head)...\n")
            run_alembic_command(["upgrade", "head"], cwd, lambda msg: self._enqueue_log("DB", msg))
            self.after(0, self.refresh_db_studio)
        threading.Thread(target=_worker, daemon=True).start()

    def db_run_downgrade(self):
        """Rebaja 1 nivel de migración."""
        if not messagebox.askyesno("Revertir Migración", "¿Estás seguro de revertir la última migración aplicada (downgrade -1)?"):
            return

        def _worker():
            cwd = Path(self.cfg.backend_dir)
            self._enqueue_log("DB", "[MIGRACIÓN] Revirtiendo última migración (downgrade -1)...\n")
            run_alembic_command(["downgrade", "-1"], cwd, lambda msg: self._enqueue_log("DB", msg))
            self.after(0, self.refresh_db_studio)
        threading.Thread(target=_worker, daemon=True).start()

    def db_create_new_seed(self):
        """Crea una nueva plantilla de seed en scripts/db/seed/."""
        name = simpledialog.askstring("Nuevo Script Seed", "Nombre del nuevo seeder:\n(Ej: seed_nuevas_prendas)", parent=self)
        if not name or not name.strip():
            return

        target = create_seed_template(name.strip(), Path(self.cfg.backend_dir))
        self.refresh_db_studio()
        self._enqueue_log("DB", f"[SEED] ✓ Creada plantilla de seed: {target}\n")
        if sys.platform == "win32":
            os.startfile(target)

    def db_run_seed(self):
        """Ejecuta el script principal de seed de datos."""
        def _worker():
            self._enqueue_log("DB", "[SEED] Iniciando población completa de base de datos...\n")
            py_exec = self._get_python_exec()
            cwd = Path(self.cfg.backend_dir)
            try:
                proc = subprocess.Popen(
                    [py_exec, "-m", "scripts.db.seed.seed_data"],
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
                if proc.stdout:
                    for line in iter(proc.stdout.readline, ""):
                        if line:
                            self._enqueue_log("DB", line)
                proc.wait()
                self._enqueue_log("DB", f"\n[SEED] Finalizado con código {proc.returncode}.\n")
                self.after(0, self.refresh_db_studio)
            except Exception as e:
                self._enqueue_log("DB", f"[ERROR SEED] {e}\n")
        threading.Thread(target=_worker, daemon=True).start()

    def db_run_selected_seed_full(self):
        sel = self.list_seed_box_full.curselection()
        if not sel:
            messagebox.showinfo("Selección", "Selecciona un script seed de la lista.")
            return
        script_info = self._seed_files_cache[sel[0]]
        script_path = Path(script_info["path"])

        def _worker():
            self._enqueue_log("DB", f"[SEED] Ejecutando {script_path.name}...\n")
            py_exec = self._get_python_exec()
            cwd = Path(self.cfg.backend_dir)
            try:
                proc = subprocess.Popen(
                    [py_exec, str(script_path)],
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
                if proc.stdout:
                    for line in iter(proc.stdout.readline, ""):
                        if line:
                            self._enqueue_log("DB", line)
                proc.wait()
                self._enqueue_log("DB", f"\n[SEED] {script_path.name} finalizado con código {proc.returncode}.\n")
                self.after(0, self.refresh_db_studio)
            except Exception as e:
                self._enqueue_log("DB", f"[ERROR SEED] {e}\n")
        threading.Thread(target=_worker, daemon=True).start()

    def db_open_selected_seed_full(self):
        sel = self.list_seed_box_full.curselection()
        if not sel:
            return
        script_info = self._seed_files_cache[sel[0]]
        if sys.platform == "win32":
            os.startfile(script_info["path"])

    def db_open_migrations_folder(self):
        folder = Path(self.cfg.backend_dir) / "alembic" / "versions"
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def db_open_seed_folder(self):
        folder = Path(self.cfg.backend_dir) / "scripts" / "db" / "seed"
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    # =========================================================================
    # PESTAÑA MODELOS DE IA
    # =========================================================================
    def _build_ai_tab(self):
        """Pestaña de gestión y descarga rápida de modelos de IA."""
        container = tk.Frame(self.tab_ai, bg=COLOR_BG, padx=16, pady=12)
        container.pack(fill=tk.BOTH, expand=True)

        h_box = tk.Frame(container, bg=COLOR_CARD, padx=14, pady=10, highlightbackground=COLOR_BORDER, highlightthickness=1)
        h_box.pack(fill=tk.X, pady=(0, 10))

        lbl_t = tk.Label(h_box, text="GESTOR DE MODELOS DE INTELIGENCIA ARTIFICIAL (GEMMA 4 QAT)",
                         font=("Segoe UI", 11, "bold"), fg=COLOR_ACID, bg=COLOR_CARD)
        lbl_t.pack(anchor=tk.W)

        lbl_st = tk.Label(h_box, text="Descarga a máxima velocidad usando todo el ancho de banda del router (Mbps) en hilo no bloqueante.",
                          font=("Segoe UI", 8), fg=COLOR_MUTED, bg=COLOR_CARD)
        lbl_st.pack(anchor=tk.W, pady=(2, 0))

        self.frame_model_cards = tk.Frame(container, bg=COLOR_BG)
        self.frame_model_cards.pack(fill=tk.X, pady=(0, 10))

        self.panel_download = tk.Frame(container, bg=COLOR_CARD, padx=14, pady=12, highlightbackground=COLOR_BORDER, highlightthickness=1)
        self.panel_download.pack(fill=tk.X, pady=(0, 10))

        lbl_down_title = tk.Label(self.panel_download, text="Descarga Rápida de Modelos GGUF",
                                  font=("Segoe UI", 10, "bold"), fg=COLOR_TEXT, bg=COLOR_CARD)
        lbl_down_title.pack(anchor=tk.W)

        self.lbl_down_file = tk.Label(self.panel_download, text="Listo para verificar o iniciar descargas.",
                                      font=("Segoe UI", 9), fg=COLOR_MUTED, bg=COLOR_CARD)
        self.lbl_down_file.pack(anchor=tk.W, pady=(2, 4))

        self.pb_download = ttk.Progressbar(self.panel_download, style="TProgressbar", orient=tk.HORIZONTAL, mode="determinate")
        self.pb_download.pack(fill=tk.X, pady=(0, 4))

        self.lbl_down_stats = tk.Label(
            self.panel_download,
            text="Progreso: 0.0% | Velocidad: 0.00 MB/s (0.0 Mbps) | ETA: --:--",
            font=("Consolas", 9, "bold"), fg=COLOR_ACID, bg=COLOR_CARD
        )
        self.lbl_down_stats.pack(anchor=tk.W)

        btn_box = tk.Frame(self.panel_download, bg=COLOR_CARD)
        btn_box.pack(anchor=tk.W, pady=(8, 0))

        self.btn_download_start = tk.Button(
            btn_box, text="⚡ Descargar Faltantes a Máxima Velocidad", font=("Segoe UI", 9, "bold"),
            bg=COLOR_FOREST, fg=COLOR_ACID, activebackground=COLOR_FOREST_LIGHT,
            activeforeground=COLOR_ACID, relief=tk.FLAT, padx=12, pady=3,
            cursor="hand2", command=self.start_ai_download
        )
        self.btn_download_start.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_download_cancel = tk.Button(
            btn_box, text="✖ Cancelar Descarga", font=("Segoe UI", 9),
            bg="#381D1D", fg="#FF8B8B", activebackground="#542525",
            activeforeground="#FFA6A6", relief=tk.FLAT, padx=10, pady=3,
            cursor="hand2", state=tk.DISABLED, command=self.cancel_ai_download
        )
        self.btn_download_cancel.pack(side=tk.LEFT, padx=4)

        btn_refresh_models = tk.Button(
            btn_box, text="⟳ Actualizar Estado", font=("Segoe UI", 9),
            bg=COLOR_CARD_HEADER, fg=COLOR_TEXT, relief=tk.FLAT, padx=10, pady=3,
            cursor="hand2", command=self.refresh_ai_models_view
        )
        btn_refresh_models.pack(side=tk.LEFT, padx=4)

        btn_restore = tk.Button(
            btn_box, text="🔁 Restaurar Nombres (.gguf000 → .gguf)", font=("Segoe UI", 9),
            bg=COLOR_CARD_HEADER, fg=COLOR_ACID, relief=tk.FLAT, padx=10, pady=3,
            cursor="hand2", command=self.restore_original_models
        )
        btn_restore.pack(side=tk.LEFT, padx=4)

        btn_diagnose = tk.Button(
            btn_box, text="🔍 Diagnóstico Runtime Gemma", font=("Segoe UI", 9),
            bg=COLOR_CARD_HEADER, fg=COLOR_TEXT, relief=tk.FLAT, padx=10, pady=3,
            cursor="hand2", command=self.diagnose_ai_runtime
        )
        btn_diagnose.pack(side=tk.LEFT, padx=4)

        lbl_log = tk.Label(container, text="Registro de Eventos y Runtime IA:", font=("Segoe UI", 9, "bold"), fg=COLOR_MUTED, bg=COLOR_BG)
        lbl_log.pack(anchor=tk.W, pady=(6, 2))

        self.txt_ai_log = tk.Text(container, bg=COLOR_CONSOLE_BG, fg=COLOR_CONSOLE_FG,
                                  font=("Consolas", 9), height=8, relief=tk.FLAT, padx=8, pady=8)
        self.txt_ai_log.pack(fill=tk.BOTH, expand=True)

        self.refresh_ai_models_view()

    def restore_original_models(self):
        """Restaura los archivos con extensión .gguf000 de vuelta a .gguf."""
        target_dir = Path(self.cfg.ai_models_dir)
        renamed = 0
        for f in target_dir.glob("*.gguf000"):
            target_name = target_dir / f.name[:-3]
            if not target_name.exists():
                f.rename(target_name)
                renamed += 1
                self._log_ai(f"[RESTAURAR] ✓ Renombrado {f.name} → {target_name.name}")
        for p in target_dir.glob("*.part"):
            base_name = p.with_suffix("")
            if base_name.exists() and base_name.stat().st_size > 10 * 1024 * 1024:
                p.unlink()
                self._log_ai(f"[LIMPIEZA] Eliminado temporal {p.name} por existir el modelo completo.")

        self.refresh_ai_models_view()
        if renamed > 0:
            messagebox.showinfo("Modelos Restaurados", f"Se restauraron {renamed} archivo(s) de modelo a su nombre original .gguf.")
        else:
            messagebox.showinfo("Verificación", "Los modelos ya tienen su nombre oficial o no se encontraron archivos .gguf000.")

    def refresh_ai_models_view(self):
        """Actualiza las tarjetas de estado de los modelos."""
        for w in self.frame_model_cards.winfo_children():
            w.destroy()

        target_dir = Path(self.cfg.ai_models_dir)
        models_info = check_models_status(target_dir)

        for i, m in enumerate(models_info):
            card = tk.Frame(self.frame_model_cards, bg=COLOR_CARD, padx=12, pady=8,
                            highlightbackground=COLOR_BORDER, highlightthickness=1)
            card.pack(fill=tk.X, pady=2)

            status_color = COLOR_SUCCESS if m["exists"] else COLOR_DANGER
            status_text = "LISTO (PRESENTE)" if m["exists"] else "FALTA DESCARGAR"

            lbl_name = tk.Label(card, text=f"• {m['filename']}", font=("Segoe UI", 10, "bold"), fg=COLOR_TEXT, bg=COLOR_CARD)
            lbl_name.pack(side=tk.LEFT)

            lbl_desc = tk.Label(card, text=f"({m['description']})", font=("Segoe UI", 8), fg=COLOR_MUTED, bg=COLOR_CARD)
            lbl_desc.pack(side=tk.LEFT, padx=8)

            lbl_sz = tk.Label(card, text=f"Tamaño: {m['size_str']}", font=("Consolas", 9), fg=COLOR_ACID, bg=COLOR_CARD)
            lbl_sz.pack(side=tk.RIGHT, padx=10)

            lbl_st = tk.Label(card, text=status_text, font=("Segoe UI", 9, "bold"), fg=status_color, bg=COLOR_CARD)
            lbl_st.pack(side=tk.RIGHT, padx=8)

    def start_ai_download(self):
        """Inicia la descarga en un hilo en segundo plano desacoplado."""
        if self._is_downloading:
            return

        target_dir = Path(self.cfg.ai_models_dir)
        models_info = check_models_status(target_dir)
        missing = [m for m in models_info if not m["exists"]]

        if not missing:
            messagebox.showinfo("Modelos Completos", "Todos los modelos de IA ya se encuentran descargados y listos.")
            return

        self._is_downloading = True
        self._download_cancel_flag = False
        self.btn_download_start.config(state=tk.DISABLED)
        self.btn_download_cancel.config(state=tk.NORMAL)

        def _worker():
            self._log_ai(f"[DESCARGA] Iniciando descarga de {len(missing)} archivo(s) en {target_dir}...")
            for m in missing:
                if self._download_cancel_flag:
                    self._log_ai("[DESCARGA] Operación cancelada por el usuario.")
                    break

                dest = target_dir / m["filename"]
                self._log_ai(f"[DESCARGA] Conectando a {m['filename']}...")

                def _progress(info):
                    try:
                        self.download_queue.put_nowait(info)
                    except queue.Full:
                        pass

                success = download_file_fast(
                    m["url"], dest,
                    progress_callback=_progress,
                    stop_check=lambda: self._download_cancel_flag
                )
                if success:
                    self._log_ai(f"[DESCARGA] ✓ {m['filename']} descargado correctamente.")
                elif not self._download_cancel_flag:
                    self._log_ai(f"[ERROR] No se pudo descargar {m['filename']}.")

            self.after(0, self._finish_ai_download)

        threading.Thread(target=_worker, daemon=True).start()

    def _process_download_queue(self):
        """Lee periódicamente la telemetría de descarga a 10 FPS sin sobrecargar la interfaz."""
        try:
            latest_info = None
            while True:
                latest_info = self.download_queue.get_nowait()
        except queue.Empty:
            pass

        if latest_info:
            status = latest_info.get("status")
            if status == "downloading":
                fn = latest_info.get("filename", "")
                pct = latest_info.get("percent", 0.0)
                self.pb_download["value"] = pct
                self.lbl_down_file.config(text=f"Descargando: {fn}")
                self.lbl_down_stats.config(
                    text=f"Progreso: {pct:.1f}% ({latest_info.get('progress_str')}) | Velocidad: {latest_info.get('speed_str')} | ETA: {latest_info.get('eta_str')}"
                )
            elif status == "completed":
                self.pb_download["value"] = 100.0
                self.lbl_down_file.config(text=latest_info.get("message", "Descarga finalizada."))
            elif status == "error":
                self.lbl_down_file.config(text=f"Error: {latest_info.get('error')}")

        self.after(100, self._process_download_queue)

    def cancel_ai_download(self):
        self._download_cancel_flag = True
        self._log_ai("[DESCARGA] Solicitando cancelación...")

    def _finish_ai_download(self):
        self._is_downloading = False
        self.btn_download_start.config(state=tk.NORMAL)
        self.btn_download_cancel.config(state=tk.DISABLED)
        self.pb_download["value"] = 0.0
        self.lbl_down_file.config(text="Descargas finalizadas o en pausa.")
        self.refresh_ai_models_view()

    def _log_ai(self, msg: str):
        self.after(0, lambda: self.txt_ai_log.insert(tk.END, msg + "\n"))
        self.after(0, lambda: self.txt_ai_log.see(tk.END))

    def diagnose_ai_runtime(self):
        """Ejecuta diagnóstico del runtime de IA."""
        def _run():
            self._log_ai("[DIAGNÓSTICO] Verificando runtime de Gemma...")
            py_exec = self._get_python_exec()
            script = Path(self.cfg.backend_dir) / "scripts" / "ai" / "check_runtime.py"
            if not script.exists():
                self._log_ai(f"[DIAGNÓSTICO] Script no encontrado: {script}")
                return

            try:
                res = subprocess.run([py_exec, str(script)], cwd=self.cfg.backend_dir, capture_output=True, text=True, timeout=15)
                out = (res.stdout + "\n" + res.stderr).strip()
                self._log_ai(f"[RESULTADO DIAGNÓSTICO]\n{out}\n")
            except Exception as e:
                self._log_ai(f"[ERROR DIAGNÓSTICO] {e}")

        threading.Thread(target=_run, daemon=True).start()

    # =========================================================================
    # PESTAÑA CONFIGURACIÓN DE DIRECTORIOS
    # =========================================================================
    def _build_config_tab(self):
        """Pestaña para examinar y configurar los directorios del proyecto."""
        container = tk.Frame(self.tab_config, bg=COLOR_BG, padx=20, pady=20)
        container.pack(fill=tk.BOTH, expand=True)

        lbl_t = tk.Label(container, text="CONFIGURACIÓN DE DIRECTORIOS DEL PROYECTO",
                         font=("Segoe UI", 12, "bold"), fg=COLOR_ACID, bg=COLOR_BG)
        lbl_t.pack(anchor=tk.W, pady=(0, 4))

        lbl_desc = tk.Label(container, text="Selecciona o examina las carpetas locales. El orquestador recordará tus rutas automáticamente.",
                            font=("Segoe UI", 9), fg=COLOR_MUTED, bg=COLOR_BG)
        lbl_desc.pack(anchor=tk.W, pady=(0, 16))

        self.paths_entries = {}
        paths_def = [
            ("backend_dir", "Directorio Backend (FastAPI):", self.cfg.backend_dir),
            ("web_dir", "Directorio Web Frontend (Angular):", self.cfg.web_dir),
            ("mobile_dir", "Directorio Móvil (Flutter):", self.cfg.mobile_dir),
            ("ai_models_dir", "Directorio Modelos IA (Gemma GGUF):", self.cfg.ai_models_dir),
        ]

        for key, title, initial_val in paths_def:
            row = tk.Frame(container, bg=COLOR_CARD, padx=14, pady=10, highlightbackground=COLOR_BORDER, highlightthickness=1)
            row.pack(fill=tk.X, pady=5)

            tk.Label(row, text=title, font=("Segoe UI", 9, "bold"), fg=COLOR_TEXT, bg=COLOR_CARD, width=32, anchor=tk.W).pack(side=tk.LEFT)

            var = tk.StringVar(value=initial_val)
            self.paths_entries[key] = var

            entry = tk.Entry(row, textvariable=var, font=("Consolas", 9), bg="#0F1613", fg=COLOR_TEXT,
                             insertbackground=COLOR_ACID, relief=tk.FLAT)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, ipady=3)

            btn_browse = tk.Button(
                row, text="📁 Explorar...", font=("Segoe UI", 8, "bold"), bg=COLOR_FOREST, fg=COLOR_ACID,
                relief=tk.FLAT, padx=10, pady=2, cursor="hand2",
                command=lambda k=key, v=var: self._browse_directory(k, v)
            )
            btn_browse.pack(side=tk.RIGHT)

        btn_save = tk.Button(
            container, text="💾 Guardar Rutas Configuradas", font=("Segoe UI", 10, "bold"),
            bg=COLOR_FOREST, fg=COLOR_ACID, activebackground=COLOR_FOREST_LIGHT,
            activeforeground=COLOR_ACID, relief=tk.FLAT, padx=16, pady=6,
            cursor="hand2", command=self._save_paths
        )
        btn_save.pack(anchor=tk.W, pady=(16, 0))

    def _browse_directory(self, key: str, var: tk.StringVar):
        chosen = filedialog.askdirectory(initialdir=var.get(), title="Seleccionar Directorio")
        if chosen:
            var.set(chosen)

    def _save_paths(self):
        self.cfg.backend_dir = self.paths_entries["backend_dir"].get()
        self.cfg.web_dir = self.paths_entries["web_dir"].get()
        self.cfg.mobile_dir = self.paths_entries["mobile_dir"].get()
        self.cfg.ai_models_dir = self.paths_entries["ai_models_dir"].get()
        self.cfg.save()
        self.refresh_ai_models_view()
        self.refresh_db_studio()
        messagebox.showinfo("Configuración Guardada", "Las rutas del proyecto han sido guardadas y actualizadas correctamente.")

    # --- REGISTRO DE LOGS ---
    def _enqueue_log(self, target: str, text: str):
        self.log_queue.put((target, text))

    def _process_log_queue(self):
        try:
            while True:
                target, text = self.log_queue.get_nowait()
                if target == "BACKEND":
                    self.term_backend.append_text(text)
                    if hasattr(self, "term_backend_full"):
                        self.term_backend_full.append_text(text)
                elif target == "WEB":
                    self.term_web.append_text(text)
                    if hasattr(self, "term_web_full"):
                        self.term_web_full.append_text(text)
                elif target == "MOBILE":
                    self.term_mobile.append_text(text)
                    if hasattr(self, "term_mobile_full"):
                        self.term_mobile_full.append_text(text)
                elif target == "ADB":
                    self.term_adb.append_text(text)
                    if hasattr(self, "term_adb_full"):
                        self.term_adb_full.append_text(text)
                elif target == "DB":
                    if hasattr(self, "term_db"):
                        self.term_db.append_text(text)
        except queue.Empty:
            pass
        self.after(50, self._process_log_queue)

    def _get_python_exec(self) -> str:
        backend_p = Path(self.cfg.backend_dir)
        venv_py = backend_p / ".venv" / "Scripts" / "python.exe"
        if venv_py.exists():
            return str(venv_py)
        venv_py_posix = backend_p / ".venv" / "bin" / "python"
        if venv_py_posix.exists():
            return str(venv_py_posix)
        return sys.executable

    # --- VERIFICADOR DE ESTADO EN SEGUNDO PLANO ---
    def _start_status_checker(self):
        def _check():
            if self.proc_backend.is_running:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                res = s.connect_ex(("127.0.0.1", 8000))
                s.close()
                if res == 0:
                    self.term_backend.set_status("ONLINE (8000)", COLOR_SUCCESS)
                    if hasattr(self, "term_backend_full"):
                        self.term_backend_full.set_status("ONLINE (8000)", COLOR_SUCCESS)
                else:
                    self.term_backend.set_status("INICIANDO...", COLOR_WARNING)
                    if hasattr(self, "term_backend_full"):
                        self.term_backend_full.set_status("INICIANDO...", COLOR_WARNING)
            else:
                self.term_backend.set_status("DETENIDO", COLOR_DANGER)
                if hasattr(self, "term_backend_full"):
                    self.term_backend_full.set_status("DETENIDO", COLOR_DANGER)

            if self.proc_web.is_running:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                res = s.connect_ex(("127.0.0.1", 4200))
                s.close()
                if res == 0:
                    self.term_web.set_status("ONLINE (4200)", COLOR_SUCCESS)
                    if hasattr(self, "term_web_full"):
                        self.term_web_full.set_status("ONLINE (4200)", COLOR_SUCCESS)
                else:
                    self.term_web.set_status("COMPILANDO...", COLOR_WARNING)
                    if hasattr(self, "term_web_full"):
                        self.term_web_full.set_status("COMPILANDO...", COLOR_WARNING)
            else:
                self.term_web.set_status("DETENIDO", COLOR_DANGER)
                if hasattr(self, "term_web_full"):
                    self.term_web_full.set_status("DETENIDO", COLOR_DANGER)

            if self.proc_mobile.is_running:
                self.term_mobile.set_status("EJECUTANDO", COLOR_SUCCESS)
                if hasattr(self, "term_mobile_full"):
                    self.term_mobile_full.set_status("EJECUTANDO", COLOR_SUCCESS)
            else:
                self.term_mobile.set_status("DETENIDO", COLOR_DANGER)
                if hasattr(self, "term_mobile_full"):
                    self.term_mobile_full.set_status("DETENIDO", COLOR_DANGER)

            self.after(2000, _check)

        self.after(1000, _check)

    # --- ACCIONES BACKEND ---
    def start_backend(self):
        py_exec = self._get_python_exec()
        cmd = [py_exec, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
        self.proc_backend.start(cmd)

    def stop_backend(self):
        self.proc_backend.stop()

    def restart_backend(self):
        self.stop_backend()
        self.after(600, self.start_backend)

    # --- ACCIONES WEB FRONTEND ---
    def start_web(self):
        self.proc_web.start("npm start", shell=True)

    def stop_web(self):
        self.proc_web.stop()

    def restart_web(self):
        self.stop_web()
        self.after(600, self.start_web)

    # --- ACCIONES FLUTTER MÓVIL ---
    def start_mobile(self):
        dev = getattr(self, "var_flutter_device", None)
        dev_str = dev.get().strip() if dev else ""
        cmd = ["flutter", "run"]
        if dev_str and dev_str != "Ninguno detectado":
            cmd.extend(["-d", dev_str.split()[0]])
        self.proc_mobile.start(cmd, shell=True)

    def stop_mobile(self):
        self.proc_mobile.stop()

    def flutter_hot_reload(self):
        self.proc_mobile.send_input("r")

    def flutter_hot_restart(self):
        self.proc_mobile.send_input("R")

    def send_mobile_input(self, text: str):
        self.proc_mobile.send_input(text)

    # --- ACCIONES ADB ---
    def adb_pair(self):
        target = self.var_adb_pair_ip.get().strip()
        code = self.var_adb_pair_code.get().strip()
        if not target or not code:
            messagebox.showwarning("Campos Requeridos", "Ingresa tanto la IP:Puerto como el código de vinculación.")
            return

        def _run():
            self._enqueue_log("ADB", f"[ADB PAIR] Vinculando a {target} con código {code}...\n")
            try:
                res = subprocess.run(["adb", "pair", target, code], capture_output=True, text=True, timeout=15)
                out = (res.stdout + "\n" + res.stderr).strip()
                self._enqueue_log("ADB", f"{out}\n")
                self.refresh_devices()
            except Exception as e:
                self._enqueue_log("ADB", f"[ERROR] Error en adb pair: {e}\n")

        threading.Thread(target=_run, daemon=True).start()

    def adb_connect(self):
        target = getattr(self, "var_adb_connect_ip", None)
        target_str = target.get().strip() if target else ""
        if not target_str:
            self.refresh_devices()
            return

        def _run():
            self._enqueue_log("ADB", f"[ADB CONNECT] Conectando a {target_str}...\n")
            try:
                res = subprocess.run(["adb", "connect", target_str], capture_output=True, text=True, timeout=15)
                out = (res.stdout + "\n" + res.stderr).strip()
                self._enqueue_log("ADB", f"{out}\n")
                self.refresh_devices()
            except Exception as e:
                self._enqueue_log("ADB", f"[ERROR] Error en adb connect: {e}\n")

        threading.Thread(target=_run, daemon=True).start()

    def adb_disconnect(self):
        def _run():
            try:
                res = subprocess.run(["adb", "disconnect"], capture_output=True, text=True)
                self._enqueue_log("ADB", f"[ADB DISCONNECT] {res.stdout.strip()}\n")
                self.refresh_devices()
            except Exception as e:
                self._enqueue_log("ADB", f"[ERROR] {e}\n")

        threading.Thread(target=_run, daemon=True).start()

    def adb_restart_server(self):
        def _run():
            self._enqueue_log("ADB", "[ADB] Reiniciando servidor daemon ADB...\n")
            subprocess.run(["adb", "kill-server"], capture_output=True)
            subprocess.run(["adb", "start-server"], capture_output=True)
            self._enqueue_log("ADB", "[ADB] Servidor ADB reiniciado correctamente.\n")
            self.refresh_devices()

        threading.Thread(target=_run, daemon=True).start()

    def send_adb_command(self, cmd_text: str):
        def _run():
            parts = cmd_text.strip().split()
            if not parts:
                return
            if parts[0] != "adb":
                parts.insert(0, "adb")
            self._enqueue_log("ADB", f"[RUN] {' '.join(parts)}\n")
            try:
                res = subprocess.run(parts, capture_output=True, text=True, timeout=15)
                self._enqueue_log("ADB", (res.stdout + "\n" + res.stderr).strip() + "\n")
            except Exception as e:
                self._enqueue_log("ADB", f"[ERROR] {e}\n")

        threading.Thread(target=_run, daemon=True).start()

    def refresh_devices(self):
        def _run():
            try:
                res_adb = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True, timeout=10)
                adb_out = res_adb.stdout

                devices = []
                for line in adb_out.splitlines()[1:]:
                    line = line.strip()
                    if line and not line.startswith("*"):
                        parts = line.split()
                        if len(parts) >= 2 and parts[1] == "device":
                            dev_id = parts[0]
                            devices.append(dev_id)
                            try:
                                subprocess.run(["adb", "-s", dev_id, "reverse", "tcp:8000", "tcp:8000"], capture_output=True)
                                subprocess.run(["adb", "-s", dev_id, "reverse", "tcp:4200", "tcp:4200"], capture_output=True)
                                self._enqueue_log("ADB", f"[ADB REVERSE] Dispositivo {dev_id}: Puertos 8000 y 4200 redirigidos.\n")
                            except Exception:
                                pass

                self.after(0, lambda: self._update_devices_dropdown(devices, adb_out))
            except Exception as e:
                self._enqueue_log("ADB", f"[ERROR] No se pudo consultar dispositivos: {e}\n")

        threading.Thread(target=_run, daemon=True).start()

    def _update_devices_dropdown(self, devices: list[str], adb_out: str):
        if hasattr(self, "combo_devices_full"):
            if devices:
                self.combo_devices_full["values"] = devices
                if not self.var_flutter_device.get() or self.var_flutter_device.get() not in devices:
                    self.var_flutter_device.set(devices[0])
                self.term_adb.set_status(f"{len(devices)} CONECTADO(S)", COLOR_SUCCESS)
                if hasattr(self, "term_adb_full"):
                    self.term_adb_full.set_status(f"{len(devices)} CONECTADO(S)", COLOR_SUCCESS)
            else:
                self.combo_devices_full["values"] = ["Ninguno detectado"]
                self.term_adb.set_status("DESCONECTADO", COLOR_DANGER)
                if hasattr(self, "term_adb_full"):
                    self.term_adb_full.set_status("DESCONECTADO", COLOR_DANGER)

        self._enqueue_log("ADB", f"--- ESTADO DISPOSITIVOS ACTIVOS ---\n{adb_out.strip()}\n")

    # --- ACCIONES GLOBALES ---
    def start_all(self):
        self.start_backend()
        self.after(1200, self.start_web)
        self.after(2500, self.start_mobile)

    def stop_all(self):
        self.stop_mobile()
        self.stop_web()
        self.stop_backend()

    def _on_close(self):
        if self.proc_backend.is_running or self.proc_web.is_running or self.proc_mobile.is_running:
            if messagebox.askyesno("Cerrar Orquestador", "¿Deseas detener todos los procesos activos antes de salir?"):
                self.stop_all()
        self.destroy()


if __name__ == "__main__":
    app = OrquestadorApp()
    app.mainloop()
