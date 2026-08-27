"""
DrapeMind - Gestor Visual Completo de Base de Datos y Datos
Permite:
- Gestionar usuarios (Crear, Listar, Cambiar Rol/Estado, Resetear Clave, Eliminar).
- Ejecutar Seeders (Catálogo de Moda, Variantes con Stock, Categorías, Cuentas Demo).
- Gestionar Migraciones y Esquema (Alembic upgrade head, autogenerate revision, schema.sql).
- Explorar datos de todas las tablas en tiempo real.
- Consola SQL interactiva y configuración de conexión PostgreSQL (.env).
"""

import os
import re
import secrets
import string
import subprocess
import sys
import threading
from decimal import Decimal
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

# Soporte para Windows High-DPI
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from urllib.parse import quote_plus
from sqlalchemy import create_engine, delete, func, inspect, select, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import hash_password
from app.models.entities import (
    Address, Category, Gender, Product, ProductVariant, Role, User, UserStatus,
)
from scripts.seed_data import run_full_seed, seed_categories, seed_products, seed_users


class DrapeMindDBManager(tk.Tk):
    # Palette Modern Dark Slate
    BG_DARK = "#0f172a"        # Fondo principal
    BG_CARD = "#1e293b"        # Fondo tarjetas
    BG_CARD_LIGHT = "#334155"  # Fondo hover/borde
    BG_INPUT = "#0b132b"       # Inputs
    FG_TEXT = "#f8fafc"        # Texto blanco
    FG_MUTED = "#94a3b8"       # Texto secundario
    PRIMARY = "#6366f1"        # Indigo
    PRIMARY_HOVER = "#4f46e5"
    SUCCESS = "#10b981"        # Emerald
    WARNING = "#f59e0b"        # Amber
    DANGER = "#ef4444"         # Red
    ACCENT = "#38bdf8"         # Sky

    def __init__(self):
        super().__init__()
        self.title("DrapeMind — Database & Data Manager")
        self.geometry("1060x760")
        self.minsize(920, 650)
        # Variables de conexion
        self.db_host = tk.StringVar()
        self.db_port = tk.StringVar()
        self.db_user = tk.StringVar()
        self.db_pass = tk.StringVar()
        self.db_name = tk.StringVar()
        self.show_cfg_pass = tk.BooleanVar(value=False)

        self.load_credentials_from_env()

        self.current_engine = None
        self.current_sessionmaker = None
        self.is_connected = False

        self.setup_styles()
        self.build_header()
        self.build_notebook()
        self.build_statusbar()

        # Probar conexion y cargar datos iniciales de inmediato
        self.init_db_connection()

    def load_credentials_from_env(self):
        """Lee directamente el archivo .env de disco para asegurar las credenciales mas recientes."""
        env_path = BACKEND_DIR / ".env"
        host, port, user, password, dbname = "localhost", "5432", "postgres", "63014529", "drapemind_db"
        if env_path.exists():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k == "POSTGRES_HOST": host = v
                        elif k == "POSTGRES_PORT": port = v
                        elif k == "POSTGRES_USER": user = v
                        elif k == "POSTGRES_PASSWORD": password = v
                        elif k == "POSTGRES_DB": dbname = v
            except Exception:
                pass
        self.db_host.set(host)
        self.db_port.set(port)
        self.db_user.set(user)
        self.db_pass.set(password)
        self.db_name.set(dbname)

    def setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        # Notebook Tabs
        style.configure("TNotebook", background=self.BG_DARK, borderwidth=0)
        style.configure("TNotebook.Tab", background=self.BG_CARD, foreground=self.FG_MUTED,
                        padding=[14, 7], font=("Segoe UI", 9, "bold"), borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", self.PRIMARY), ("active", self.BG_CARD_LIGHT)],
                  foreground=[("selected", "#ffffff"), ("active", "#ffffff")])

        # Frames
        style.configure("TFrame", background=self.BG_DARK)
        style.configure("Card.TFrame", background=self.BG_CARD)

        # Combobox
        style.configure("TCombobox", fieldbackground=self.BG_CARD, background=self.PRIMARY,
                        foreground="#ffffff", bordercolor=self.BG_CARD_LIGHT, arrowcolor="#ffffff",
                        padding=5, font=("Segoe UI", 9))
        style.map("TCombobox",
                  fieldbackground=[("readonly", self.BG_CARD)],
                  selectbackground=[("readonly", self.PRIMARY)])

        # Treeview (Tablas)
        style.configure("Treeview", background=self.BG_CARD, foreground=self.FG_TEXT,
                        fieldbackground=self.BG_CARD, rowheight=28, font=("Segoe UI", 9),
                        bordercolor=self.BG_CARD_LIGHT, borderwidth=0)
        style.configure("Treeview.Heading", background=self.BG_CARD_LIGHT, foreground="#ffffff",
                        font=("Segoe UI", 9, "bold"), padding=5)
        style.map("Treeview",
                  background=[("selected", self.PRIMARY)],
                  foreground=[("selected", "#ffffff")])

        # Scrollbars
        style.configure("Vertical.TScrollbar", background=self.BG_CARD, troughcolor=self.BG_DARK,
                        bordercolor=self.BG_DARK, arrowcolor=self.FG_MUTED)
        style.configure("Horizontal.TScrollbar", background=self.BG_CARD, troughcolor=self.BG_DARK,
                        bordercolor=self.BG_DARK, arrowcolor=self.FG_MUTED)

    def build_header(self):
        header = tk.Frame(self, bg=self.BG_CARD, padx=20, pady=10, highlightthickness=1,
                          highlightbackground=self.BG_CARD_LIGHT)
        header.pack(fill=tk.X, side=tk.TOP)

        left = tk.Frame(header, bg=self.BG_CARD)
        left.pack(side=tk.LEFT, fill=tk.Y)

        title = tk.Label(left, text="👗 DrapeMind — DB & Data Manager",
                         font=("Segoe UI", 13, "bold"), bg=self.BG_CARD, fg=self.FG_TEXT)
        title.pack(anchor="w")

        sub = tk.Label(left, text="Gestión Integral de Base de Datos PostgreSQL, Usuarios, Seeders y Migraciones",
                       font=("Segoe UI", 8), bg=self.BG_CARD, fg=self.FG_MUTED)
        sub.pack(anchor="w")

        right = tk.Frame(header, bg=self.BG_CARD)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        self.db_badge = tk.Label(right, text="🟡 Conectando a PostgreSQL...",
                                 font=("Segoe UI", 9, "bold"), bg="#3b82f6", fg="#ffffff",
                                 padx=10, pady=4, cursor="hand2")
        self.db_badge.pack(side=tk.RIGHT)
        self.db_badge.bind("<Button-1>", lambda e: self.notebook.select(self.tab_config))

    def build_notebook(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

        # Tabs
        self.tab_users = tk.Frame(self.notebook, bg=self.BG_DARK)
        self.tab_seed = tk.Frame(self.notebook, bg=self.BG_DARK)
        self.tab_migrations = tk.Frame(self.notebook, bg=self.BG_DARK)
        self.tab_explorer = tk.Frame(self.notebook, bg=self.BG_DARK)
        self.tab_config = tk.Frame(self.notebook, bg=self.BG_DARK)

        self.notebook.add(self.tab_users, text="  👥 Usuarios & Roles  ")
        self.notebook.add(self.tab_seed, text="  🌱 Seeders & Catálogo  ")
        self.notebook.add(self.tab_migrations, text="  🚀 Migraciones & Esquema  ")
        self.notebook.add(self.tab_explorer, text="  📊 Explorador de Tablas  ")
        self.notebook.add(self.tab_config, text="  ⚡ Consola SQL & Conexión  ")

        self.build_users_tab()
        self.build_seed_tab()
        self.build_migrations_tab()
        self.build_explorer_tab()
        self.build_config_tab()

    # =========================================================================
    # TAB 1: GESTIÓN DE USUARIOS
    # =========================================================================
    def build_users_tab(self):
        paned = tk.PanedWindow(self.tab_users, orient=tk.HORIZONTAL, bg=self.BG_DARK, sashwidth=4)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Panel Izquierdo: Formulario de Creación
        form_card = tk.Frame(paned, bg=self.BG_CARD, padx=15, pady=15, highlightthickness=1,
                             highlightbackground=self.BG_CARD_LIGHT)
        paned.add(form_card, minsize=320, width=350)

        form_title = tk.Label(form_card, text="➕ Crear / Registrar Usuario",
                              font=("Segoe UI", 11, "bold"), bg=self.BG_CARD, fg=self.ACCENT)
        form_title.pack(anchor="w", pady=(0, 10))

        # Nombre
        tk.Label(form_card, text="Nombre Completo *", font=("Segoe UI", 8, "bold"),
                 bg=self.BG_CARD, fg=self.FG_TEXT).pack(anchor="w")
        self.u_name = tk.Entry(form_card, font=("Segoe UI", 9), bg=self.BG_INPUT, fg=self.FG_TEXT,
                               insertbackground=self.FG_TEXT, relief="flat", highlightthickness=1,
                               highlightbackground=self.BG_CARD_LIGHT, highlightcolor=self.PRIMARY)
        self.u_name.pack(fill=tk.X, pady=(2, 8), ipady=4)

        # Email
        tk.Label(form_card, text="Correo Electrónico *", font=("Segoe UI", 8, "bold"),
                 bg=self.BG_CARD, fg=self.FG_TEXT).pack(anchor="w")
        self.u_email = tk.Entry(form_card, font=("Segoe UI", 9), bg=self.BG_INPUT, fg=self.FG_TEXT,
                                insertbackground=self.FG_TEXT, relief="flat", highlightthickness=1,
                                highlightbackground=self.BG_CARD_LIGHT, highlightcolor=self.PRIMARY)
        self.u_email.pack(fill=tk.X, pady=(2, 8), ipady=4)

        # Telefono
        tk.Label(form_card, text="Teléfono (Opcional)", font=("Segoe UI", 8, "bold"),
                 bg=self.BG_CARD, fg=self.FG_TEXT).pack(anchor="w")
        self.u_phone = tk.Entry(form_card, font=("Segoe UI", 9), bg=self.BG_INPUT, fg=self.FG_TEXT,
                                insertbackground=self.FG_TEXT, relief="flat", highlightthickness=1,
                                highlightbackground=self.BG_CARD_LIGHT, highlightcolor=self.PRIMARY)
        self.u_phone.pack(fill=tk.X, pady=(2, 8), ipady=4)

        # Rol & Estado en 2 columnas
        row_re = tk.Frame(form_card, bg=self.BG_CARD)
        row_re.pack(fill=tk.X, pady=(0, 8))
        row_re.columnconfigure(0, weight=1)
        row_re.columnconfigure(1, weight=1)

        tk.Label(row_re, text="Rol *", font=("Segoe UI", 8, "bold"), bg=self.BG_CARD, fg=self.FG_TEXT).grid(row=0, column=0, sticky="w")
        self.u_role = ttk.Combobox(row_re, state="readonly", values=["ADMIN", "VENDEDOR", "CLIENTE"], width=12)
        self.u_role.set("ADMIN")
        self.u_role.grid(row=1, column=0, sticky="ew", padx=(0, 5), pady=(2, 0))

        tk.Label(row_re, text="Estado *", font=("Segoe UI", 8, "bold"), bg=self.BG_CARD, fg=self.FG_TEXT).grid(row=0, column=1, sticky="w")
        self.u_status = ttk.Combobox(row_re, state="readonly", values=["ACTIVO", "INACTIVO", "BLOQUEADO"], width=12)
        self.u_status.set("ACTIVO")
        self.u_status.grid(row=1, column=1, sticky="ew", padx=(5, 0), pady=(2, 0))

        # Contraseña
        pass_top = tk.Frame(form_card, bg=self.BG_CARD)
        pass_top.pack(fill=tk.X, pady=(4, 2))
        tk.Label(pass_top, text="Contraseña (mín 8 chars) *", font=("Segoe UI", 8, "bold"),
                 bg=self.BG_CARD, fg=self.FG_TEXT).pack(side=tk.LEFT)
        btn_gen = tk.Button(pass_top, text="🎲 Generar", font=("Segoe UI", 7, "bold"),
                            bg=self.BG_CARD_LIGHT, fg=self.ACCENT, relief="flat", padx=4, cursor="hand2",
                            command=self.generate_user_password)
        btn_gen.pack(side=tk.RIGHT)

        pass_box = tk.Frame(form_card, bg=self.BG_CARD)
        pass_box.pack(fill=tk.X, pady=(0, 8))
        self.u_pass = tk.Entry(pass_box, show="•", font=("Segoe UI", 9), bg=self.BG_INPUT,
                               fg=self.FG_TEXT, insertbackground=self.FG_TEXT, relief="flat",
                               highlightthickness=1, highlightbackground=self.BG_CARD_LIGHT,
                               highlightcolor=self.PRIMARY)
        self.u_pass.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        self.btn_u_eye = tk.Button(pass_box, text="👁", font=("Segoe UI", 8), bg=self.BG_CARD_LIGHT,
                                   fg=self.FG_TEXT, relief="flat", padx=6, cursor="hand2",
                                   command=self.toggle_user_pass)
        self.btn_u_eye.pack(side=tk.RIGHT, padx=(3, 0))

        # Boton Submit
        btn_create = tk.Button(form_card, text="✨ Registrar Usuario", font=("Segoe UI", 9, "bold"),
                               bg=self.PRIMARY, fg="#ffffff", activebackground=self.PRIMARY_HOVER,
                               relief="flat", pady=7, cursor="hand2", command=self.handle_create_user)
        btn_create.pack(fill=tk.X, pady=(8, 4))

        self.u_alert = tk.Label(form_card, text="", font=("Segoe UI", 8), bg=self.BG_CARD, fg=self.FG_MUTED, wraplength=300)
        self.u_alert.pack(fill=tk.X, pady=(4, 0))

        # Panel Derecho: Tabla de Usuarios
        table_card = tk.Frame(paned, bg=self.BG_CARD, padx=12, pady=12, highlightthickness=1,
                              highlightbackground=self.BG_CARD_LIGHT)
        paned.add(table_card, minsize=450, stretch="always")

        top_bar = tk.Frame(table_card, bg=self.BG_CARD)
        top_bar.pack(fill=tk.X, pady=(0, 8))

        self.u_stats = tk.Label(top_bar, text="Cargando usuarios...", font=("Segoe UI", 9, "bold"),
                                bg=self.BG_CARD, fg=self.ACCENT)
        self.u_stats.pack(side=tk.LEFT)

        btn_ref_u = tk.Button(top_bar, text="🔄 Refrescar", font=("Segoe UI", 8, "bold"),
                              bg=self.PRIMARY, fg="#ffffff", relief="flat", padx=10, pady=2,
                              cursor="hand2", command=self.load_users)
        btn_ref_u.pack(side=tk.RIGHT)

        # Buscador y Acciones rapidas
        act_bar = tk.Frame(table_card, bg=self.BG_CARD)
        act_bar.pack(fill=tk.X, pady=(0, 6))

        tk.Label(act_bar, text="🔍", bg=self.BG_CARD, fg=self.FG_MUTED).pack(side=tk.LEFT)
        self.u_search = tk.Entry(act_bar, font=("Segoe UI", 9), bg=self.BG_INPUT, fg=self.FG_TEXT,
                                 insertbackground=self.FG_TEXT, relief="flat", highlightthickness=1,
                                 highlightbackground=self.BG_CARD_LIGHT)
        self.u_search.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 10), ipady=3)
        self.u_search.bind("<KeyRelease>", self.filter_users_table)

        btn_ch_role = tk.Button(act_bar, text="✏️ Cambiar Rol/Estado", font=("Segoe UI", 8),
                                bg=self.BG_CARD_LIGHT, fg=self.FG_TEXT, relief="flat", padx=6, pady=2,
                                cursor="hand2", command=self.action_edit_selected_user)
        btn_ch_role.pack(side=tk.RIGHT, padx=2)

        btn_reset_p = tk.Button(act_bar, text="🔑 Resetear Clave", font=("Segoe UI", 8),
                                bg=self.BG_CARD_LIGHT, fg=self.WARNING, relief="flat", padx=6, pady=2,
                                cursor="hand2", command=self.action_reset_password)
        btn_reset_p.pack(side=tk.RIGHT, padx=2)

        btn_del_u = tk.Button(act_bar, text="🗑️ Eliminar", font=("Segoe UI", 8),
                              bg=self.BG_CARD_LIGHT, fg=self.DANGER, relief="flat", padx=6, pady=2,
                              cursor="hand2", command=self.action_delete_user)
        btn_del_u.pack(side=tk.RIGHT, padx=2)

        # Tabla TreeView
        cols = ("id", "nombre", "email", "rol", "estado", "telefono", "created_at")
        self.users_table = ttk.Treeview(table_card, columns=cols, show="headings", selectmode="browse")

        self.users_table.heading("id", text="ID")
        self.users_table.heading("nombre", text="Nombre")
        self.users_table.heading("email", text="Email")
        self.users_table.heading("rol", text="Rol")
        self.users_table.heading("estado", text="Estado")
        self.users_table.heading("telefono", text="Teléfono")
        self.users_table.heading("created_at", text="Registrado")

        self.users_table.column("id", width=40, anchor="center")
        self.users_table.column("nombre", width=140, anchor="w")
        self.users_table.column("email", width=180, anchor="w")
        self.users_table.column("rol", width=80, anchor="center")
        self.users_table.column("estado", width=75, anchor="center")
        self.users_table.column("telefono", width=95, anchor="w")
        self.users_table.column("created_at", width=110, anchor="center")

        sb_u = ttk.Scrollbar(table_card, orient=tk.VERTICAL, command=self.users_table.yview)
        self.users_table.configure(yscroll=sb_u.set)

        self.users_table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_u.pack(side=tk.RIGHT, fill=tk.Y)

        self.raw_users = []

    # =========================================================================
    # TAB 2: SEEDERS & CATÁLOGO
    # =========================================================================
    def build_seed_tab(self):
        container = tk.Frame(self.tab_seed, bg=self.BG_DARK, padx=10, pady=10)
        container.pack(fill=tk.BOTH, expand=True)

        # Card de Acciones de Seeding
        actions_card = tk.Frame(container, bg=self.BG_CARD, padx=20, pady=15,
                                highlightthickness=1, highlightbackground=self.BG_CARD_LIGHT)
        actions_card.pack(fill=tk.X, pady=(0, 10))

        tk.Label(actions_card, text="🌱 Generador & Seeder de Datos DrapeMind",
                 font=("Segoe UI", 12, "bold"), bg=self.BG_CARD, fg=self.FG_TEXT).pack(anchor="w")
        tk.Label(actions_card, text="Puebla la base de datos con categorías de moda, prendas reales, tallas, colores, stock y usuarios de prueba.",
                 font=("Segoe UI", 8), bg=self.BG_CARD, fg=self.FG_MUTED).pack(anchor="w", pady=(2, 12))

        btn_row = tk.Frame(actions_card, bg=self.BG_CARD)
        btn_row.pack(fill=tk.X)

        btn_seed_all = tk.Button(btn_row, text="🌟 Seed Completo (Catálogo + Usuarios)",
                                 font=("Segoe UI", 9, "bold"), bg=self.SUCCESS, fg="#ffffff",
                                 relief="flat", padx=14, pady=7, cursor="hand2",
                                 command=lambda: self.run_async_task(self.task_seed_all, "Ejecutando Seed Completo..."))
        btn_seed_all.pack(side=tk.LEFT, padx=(0, 8))

        btn_seed_cat = tk.Button(btn_row, text="👔 Solo Catálogo (Prendas & Stock)",
                                 font=("Segoe UI", 9), bg=self.PRIMARY, fg="#ffffff",
                                 relief="flat", padx=12, pady=7, cursor="hand2",
                                 command=lambda: self.run_async_task(self.task_seed_catalog, "Sembrando Catálogo..."))
        btn_seed_cat.pack(side=tk.LEFT, padx=(0, 8))

        btn_seed_u = tk.Button(btn_row, text="👥 Solo Usuarios Base",
                               font=("Segoe UI", 9), bg=self.BG_CARD_LIGHT, fg=self.FG_TEXT,
                               relief="flat", padx=12, pady=7, cursor="hand2",
                               command=lambda: self.run_async_task(self.task_seed_users_only, "Sembrando Usuarios..."))
        btn_seed_u.pack(side=tk.LEFT, padx=(0, 8))

        btn_clean = tk.Button(btn_row, text="🧹 Vaciar / Resetear Tablas",
                              font=("Segoe UI", 9, "bold"), bg=self.DANGER, fg="#ffffff",
                              relief="flat", padx=12, pady=7, cursor="hand2",
                              command=self.action_truncate_data)
        btn_clean.pack(side=tk.RIGHT)

        # Consola de Log de Seeding
        log_card = tk.Frame(container, bg=self.BG_CARD, padx=15, pady=12,
                            highlightthickness=1, highlightbackground=self.BG_CARD_LIGHT)
        log_card.pack(fill=tk.BOTH, expand=True)

        tk.Label(log_card, text="📜 Registro de Actividad en Tiempo Real:",
                 font=("Segoe UI", 9, "bold"), bg=self.BG_CARD, fg=self.ACCENT).pack(anchor="w", pady=(0, 6))

        self.txt_seed_log = tk.Text(log_card, bg=self.BG_INPUT, fg=self.FG_TEXT,
                                    font=("Consolas", 9), relief="flat", highlightthickness=1,
                                    highlightbackground=self.BG_CARD_LIGHT)
        sb_sl = ttk.Scrollbar(log_card, orient=tk.VERTICAL, command=self.txt_seed_log.yview)
        self.txt_seed_log.configure(yscroll=sb_sl.set)

        self.txt_seed_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_sl.pack(side=tk.RIGHT, fill=tk.Y)

    # =========================================================================
    # TAB 3: MIGRACIONES & ESQUEMA (ALEMBIC / SQL)
    # =========================================================================
    def build_migrations_tab(self):
        container = tk.Frame(self.tab_migrations, bg=self.BG_DARK, padx=10, pady=10)
        container.pack(fill=tk.BOTH, expand=True)

        top_card = tk.Frame(container, bg=self.BG_CARD, padx=20, pady=15,
                            highlightthickness=1, highlightbackground=self.BG_CARD_LIGHT)
        top_card.pack(fill=tk.X, pady=(0, 10))

        tk.Label(top_card, text="🚀 Control de Esquema & Migraciones Alembic",
                 font=("Segoe UI", 12, "bold"), bg=self.BG_CARD, fg=self.FG_TEXT).pack(anchor="w")

        btn_row = tk.Frame(top_card, bg=self.BG_CARD)
        btn_row.pack(fill=tk.X, pady=(10, 0))

        btn_mig = tk.Button(btn_row, text="🚀 Ejecutar Alembic Upgrade Head",
                            font=("Segoe UI", 9, "bold"), bg=self.PRIMARY, fg="#ffffff",
                            relief="flat", padx=14, pady=6, cursor="hand2",
                            command=lambda: self.run_async_task(self.task_alembic_upgrade, "Ejecutando alembic upgrade head..."))
        btn_mig.pack(side=tk.LEFT, padx=(0, 8))

        btn_apply_sql = tk.Button(btn_row, text="📄 Aplicar database/schema.sql",
                                  font=("Segoe UI", 9), bg=self.SUCCESS, fg="#ffffff",
                                  relief="flat", padx=12, pady=6, cursor="hand2",
                                  command=lambda: self.run_async_task(self.task_apply_schema_sql, "Aplicando schema.sql..."))
        btn_apply_sql.pack(side=tk.LEFT, padx=(0, 8))

        btn_rev = tk.Button(btn_row, text="📝 Crear Nueva Revisión Alembic",
                            font=("Segoe UI", 9), bg=self.BG_CARD_LIGHT, fg=self.ACCENT,
                            relief="flat", padx=12, pady=6, cursor="hand2",
                            command=self.action_create_alembic_revision)
        btn_rev.pack(side=tk.LEFT)

        # Vista de Tablas Existentes y Log
        bot_frame = tk.Frame(container, bg=self.BG_DARK)
        bot_frame.pack(fill=tk.BOTH, expand=True)
        bot_frame.columnconfigure(0, weight=1)
        bot_frame.columnconfigure(1, weight=2)

        # Tablas y Conteo
        tables_card = tk.Frame(bot_frame, bg=self.BG_CARD, padx=12, pady=10,
                               highlightthickness=1, highlightbackground=self.BG_CARD_LIGHT)
        tables_card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        tk.Label(tables_card, text="📊 Tablas en PostgreSQL:", font=("Segoe UI", 9, "bold"),
                 bg=self.BG_CARD, fg=self.ACCENT).pack(anchor="w", pady=(0, 4))

        self.table_list_box = tk.Listbox(tables_card, bg=self.BG_INPUT, fg=self.FG_TEXT,
                                         font=("Consolas", 9), relief="flat", highlightthickness=0)
        self.table_list_box.pack(fill=tk.BOTH, expand=True)

        # Log de Migraciones
        mig_log_card = tk.Frame(bot_frame, bg=self.BG_CARD, padx=12, pady=10,
                                highlightthickness=1, highlightbackground=self.BG_CARD_LIGHT)
        mig_log_card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

        tk.Label(mig_log_card, text="📜 Salida de Comandos / Alembic:", font=("Segoe UI", 9, "bold"),
                 bg=self.BG_CARD, fg=self.FG_TEXT).pack(anchor="w", pady=(0, 4))

        self.txt_mig_log = tk.Text(mig_log_card, bg=self.BG_INPUT, fg=self.FG_TEXT,
                                   font=("Consolas", 9), relief="flat", highlightthickness=1,
                                   highlightbackground=self.BG_CARD_LIGHT)
        self.txt_mig_log.pack(fill=tk.BOTH, expand=True)

    # =========================================================================
    # TAB 4: EXPLORADOR DE TABLAS & DATOS
    # =========================================================================
    def build_explorer_tab(self):
        container = tk.Frame(self.tab_explorer, bg=self.BG_DARK, padx=10, pady=10)
        container.pack(fill=tk.BOTH, expand=True)

        card = tk.Frame(container, bg=self.BG_CARD, padx=15, pady=12,
                        highlightthickness=1, highlightbackground=self.BG_CARD_LIGHT)
        card.pack(fill=tk.BOTH, expand=True)

        # Selector de tabla
        sel_bar = tk.Frame(card, bg=self.BG_CARD)
        sel_bar.pack(fill=tk.X, pady=(0, 10))

        tk.Label(sel_bar, text="📁 Seleccionar Tabla:", font=("Segoe UI", 9, "bold"),
                 bg=self.BG_CARD, fg=self.FG_TEXT).pack(side=tk.LEFT, padx=(0, 8))

        self.cb_explorer_tables = ttk.Combobox(sel_bar, state="readonly", width=26)
        self.cb_explorer_tables.pack(side=tk.LEFT, padx=(0, 12))
        self.cb_explorer_tables.bind("<<ComboboxSelected>>", lambda e: self.load_table_data())

        btn_load_t = tk.Button(sel_bar, text="🔄 Cargar Datos", font=("Segoe UI", 8, "bold"),
                               bg=self.PRIMARY, fg="#ffffff", relief="flat", padx=10, pady=2,
                               cursor="hand2", command=self.load_table_data)
        btn_load_t.pack(side=tk.LEFT)

        self.lbl_table_info = tk.Label(sel_bar, text="", font=("Segoe UI", 8),
                                       bg=self.BG_CARD, fg=self.ACCENT)
        self.lbl_table_info.pack(side=tk.RIGHT)

        # Tabla de visualizacion con doble scrollbar
        tbl_frame = tk.Frame(card, bg=self.BG_CARD)
        tbl_frame.pack(fill=tk.BOTH, expand=True)

        self.explorer_tree = ttk.Treeview(tbl_frame, show="headings", selectmode="browse")
        sb_y = ttk.Scrollbar(tbl_frame, orient=tk.VERTICAL, command=self.explorer_tree.yview)
        sb_x = ttk.Scrollbar(tbl_frame, orient=tk.HORIZONTAL, command=self.explorer_tree.xview)
        self.explorer_tree.configure(yscroll=sb_y.set, xscroll=sb_x.set)

        self.explorer_tree.grid(row=0, column=0, sticky="nsew")
        sb_y.grid(row=0, column=1, sticky="ns")
        sb_x.grid(row=1, column=0, sticky="ew")

        tbl_frame.columnconfigure(0, weight=1)
        tbl_frame.rowconfigure(0, weight=1)

    # =========================================================================
    # TAB 5: CONSOLA SQL & CONEXIÓN
    # =========================================================================
    def build_config_tab(self):
        container = tk.Frame(self.tab_config, bg=self.BG_DARK, padx=10, pady=10)
        container.pack(fill=tk.BOTH, expand=True)

        paned = tk.PanedWindow(container, orient=tk.HORIZONTAL, bg=self.BG_DARK, sashwidth=4)
        paned.pack(fill=tk.BOTH, expand=True)

        # Panel Izquierdo: Ajustes de PostgreSQL
        cfg_card = tk.Frame(paned, bg=self.BG_CARD, padx=15, pady=15,
                            highlightthickness=1, highlightbackground=self.BG_CARD_LIGHT)
        paned.add(cfg_card, minsize=320, width=360)

        tk.Label(cfg_card, text="⚙️ Parámetros PostgreSQL", font=("Segoe UI", 11, "bold"),
                 bg=self.BG_CARD, fg=self.FG_TEXT).pack(anchor="w", pady=(0, 8))

        fields = [
            ("Host:", self.db_host, False),
            ("Puerto:", self.db_port, False),
            ("Usuario:", self.db_user, False),
            ("Contraseña:", self.db_pass, True),
            ("Base de Datos:", self.db_name, False),
        ]

        for label_text, var, is_secret in fields:
            tk.Label(cfg_card, text=label_text, font=("Segoe UI", 8, "bold"),
                     bg=self.BG_CARD, fg=self.FG_TEXT).pack(anchor="w", pady=(2, 0))
            if is_secret:
                p_frame = tk.Frame(cfg_card, bg=self.BG_CARD)
                p_frame.pack(fill=tk.X, pady=(0, 6))
                self.ent_cfg_pass = tk.Entry(p_frame, textvariable=var, font=("Segoe UI", 9), bg=self.BG_INPUT,
                                             fg=self.FG_TEXT, insertbackground=self.FG_TEXT, relief="flat",
                                             highlightthickness=1, highlightbackground=self.BG_CARD_LIGHT,
                                             highlightcolor=self.PRIMARY, show="•")
                self.ent_cfg_pass.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
                self.btn_cfg_eye = tk.Button(p_frame, text="👁", font=("Segoe UI", 8), bg=self.BG_CARD_LIGHT,
                                             fg=self.FG_TEXT, relief="flat", padx=6, cursor="hand2",
                                             command=self.toggle_cfg_pass)
                self.btn_cfg_eye.pack(side=tk.RIGHT, padx=(3, 0))
            else:
                ent = tk.Entry(cfg_card, textvariable=var, font=("Segoe UI", 9), bg=self.BG_INPUT,
                               fg=self.FG_TEXT, insertbackground=self.FG_TEXT, relief="flat",
                               highlightthickness=1, highlightbackground=self.BG_CARD_LIGHT,
                               highlightcolor=self.PRIMARY)
                ent.pack(fill=tk.X, pady=(0, 6), ipady=4)

        btn_box = tk.Frame(cfg_card, bg=self.BG_CARD)
        btn_box.pack(fill=tk.X, pady=(10, 0))

        btn_test = tk.Button(btn_box, text="🔍 Probar Conexión", font=("Segoe UI", 8, "bold"),
                             bg=self.PRIMARY, fg="#ffffff", relief="flat", padx=10, pady=6,
                             cursor="hand2", command=self.init_db_connection)
        btn_test.pack(side=tk.LEFT, padx=(0, 6))

        btn_save = tk.Button(btn_box, text="💾 Guardar en .env", font=("Segoe UI", 8, "bold"),
                             bg=self.SUCCESS, fg="#ffffff", relief="flat", padx=10, pady=6,
                             cursor="hand2", command=self.save_env_credentials)
        btn_save.pack(side=tk.LEFT)

        # Panel Derecho: Consola SQL
        sql_card = tk.Frame(paned, bg=self.BG_CARD, padx=15, pady=15,
                            highlightthickness=1, highlightbackground=self.BG_CARD_LIGHT)
        paned.add(sql_card, minsize=450, stretch="always")

        sql_top = tk.Frame(sql_card, bg=self.BG_CARD)
        sql_top.pack(fill=tk.X, pady=(0, 6))

        tk.Label(sql_top, text="⚡ Consola SQL Directa", font=("Segoe UI", 11, "bold"),
                 bg=self.BG_CARD, fg=self.ACCENT).pack(side=tk.LEFT)

        btn_run_sql = tk.Button(sql_top, text="▶️ Ejecutar Consulta (F5)", font=("Segoe UI", 8, "bold"),
                                bg=self.SUCCESS, fg="#ffffff", relief="flat", padx=12, pady=3,
                                cursor="hand2", command=self.execute_sql_query)
        btn_run_sql.pack(side=tk.RIGHT)

        self.txt_sql = tk.Text(sql_card, height=5, bg=self.BG_INPUT, fg=self.FG_TEXT,
                               font=("Consolas", 10), relief="flat", highlightthickness=1,
                               highlightbackground=self.BG_CARD_LIGHT, insertbackground=self.FG_TEXT)
        self.txt_sql.insert(tk.END, "SELECT id, nombre, email, rol, estado FROM usuarios ORDER BY id ASC;")
        self.txt_sql.pack(fill=tk.X, pady=(0, 10))
        self.txt_sql.bind("<F5>", lambda e: self.execute_sql_query())

        # Tabla de resultados SQL
        tk.Label(sql_card, text="Resultados:", font=("Segoe UI", 8, "bold"),
                 bg=self.BG_CARD, fg=self.FG_MUTED).pack(anchor="w", pady=(0, 2))

        sql_res_frame = tk.Frame(sql_card, bg=self.BG_CARD)
        sql_res_frame.pack(fill=tk.BOTH, expand=True)

        self.sql_tree = ttk.Treeview(sql_res_frame, show="headings", selectmode="browse")
        sb_sql_y = ttk.Scrollbar(sql_res_frame, orient=tk.VERTICAL, command=self.sql_tree.yview)
        sb_sql_x = ttk.Scrollbar(sql_res_frame, orient=tk.HORIZONTAL, command=self.sql_tree.xview)
        self.sql_tree.configure(yscroll=sb_sql_y.set, xscroll=sb_sql_x.set)

        self.sql_tree.grid(row=0, column=0, sticky="nsew")
        sb_sql_y.grid(row=0, column=1, sticky="ns")
        sb_sql_x.grid(row=1, column=0, sticky="ew")

        sql_res_frame.columnconfigure(0, weight=1)
        sql_res_frame.rowconfigure(0, weight=1)

    def build_statusbar(self):
        statusbar = tk.Frame(self, bg=self.BG_CARD, padx=15, pady=4, highlightthickness=1,
                             highlightbackground=self.BG_CARD_LIGHT)
        statusbar.pack(fill=tk.X, side=tk.BOTTOM)

        self.status_msg = tk.Label(statusbar, text="Listo", font=("Segoe UI", 8),
                                   bg=self.BG_CARD, fg=self.FG_MUTED)
        self.status_msg.pack(side=tk.LEFT)

        version_lbl = tk.Label(statusbar, text="DrapeMind Backend • Python 3.11",
                               font=("Segoe UI", 8), bg=self.BG_CARD, fg=self.FG_MUTED)
        version_lbl.pack(side=tk.RIGHT)

    # =========================================================================
    # LÓGICA DE BASE DE DATOS Y CONEXIÓN ROBUSTA
    # =========================================================================
    def get_uri(self) -> str:
        host = self.db_host.get().strip()
        port = self.db_port.get().strip()
        user = self.db_user.get().strip()
        password = self.db_pass.get()
        dbname = self.db_name.get().strip()
        return f"postgresql+psycopg://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{dbname}"

    def get_active_engine(self):
        """Devuelve un engine activo y conectado a PostgreSQL."""
        if self.current_engine is not None:
            try:
                with self.current_engine.connect() as conn:
                    return self.current_engine
            except Exception:
                pass

        uri = self.get_uri()
        engine = create_engine(uri, pool_pre_ping=True)
        with engine.connect() as conn:
            self.current_engine = engine
            self.current_sessionmaker = sessionmaker(bind=engine, expire_on_commit=False)
            self.is_connected = True
            return engine

    def get_active_sessionmaker(self):
        """Devuelve un sessionmaker activo."""
        self.get_active_engine()
        return self.current_sessionmaker

    def init_db_connection(self):
        self.db_badge.config(text="🟡 Conectando...", bg="#f59e0b")
        try:
            engine = self.get_active_engine()
            with engine.connect() as conn:
                v = conn.execute(text("SELECT version()")).scalar()
                dbname = self.db_name.get().strip()
                self.db_badge.config(text=f"🟢 Conectado: {dbname}", bg=self.SUCCESS)
                self.status_msg.config(text=f"Conectado a PostgreSQL ({dbname})")

                # Cargar lista de tablas y datos
                self.refresh_database_overview()
                self.load_users()
                return True
        except Exception as ex:
            self.is_connected = False
            self.db_badge.config(text="🔴 Error de Conexión", bg=self.DANGER)
            err = str(ex)
            if "autentificaci" in err.lower() or "password authentication failed" in err.lower():
                msg = "Contraseña incorrecta de PostgreSQL. Verifica tus credenciales."
            elif "does not exist" in err.lower():
                msg = f"La base de datos '{self.db_name.get()}' no existe en PostgreSQL."
            else:
                msg = f"Error: {err[:100]}"
            self.status_msg.config(text=msg)
            return False

    def refresh_database_overview(self):
        """Actualiza la lista de tablas y llena los selectores."""
        try:
            engine = self.get_active_engine()
            insp = inspect(engine)
            tables = insp.get_table_names()

            # Llenar listbox en migraciones
            self.table_list_box.delete(0, tk.END)
            with engine.connect() as conn:
                for t in tables:
                    try:
                        cnt = conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar()
                        self.table_list_box.insert(tk.END, f"• {t.ljust(25)} : {cnt} filas")
                    except Exception:
                        self.table_list_box.insert(tk.END, f"• {t}")

            # Llenar combobox de explorador
            self.cb_explorer_tables["values"] = tables
            if tables and not self.cb_explorer_tables.get():
                self.cb_explorer_tables.set(tables[0])
                self.load_table_data()

        except Exception as e:
            self.log_seed(f"Error inspeccionando tablas: {e}")

    def toggle_cfg_pass(self):
        if self.show_cfg_pass.get():
            self.ent_cfg_pass.config(show="•")
            self.btn_cfg_eye.config(text="👁")
            self.show_cfg_pass.set(False)
        else:
            self.ent_cfg_pass.config(show="")
            self.btn_cfg_eye.config(text="🔒")
            self.show_cfg_pass.set(True)

    def save_env_credentials(self):
        env_path = BACKEND_DIR / ".env"
        if not env_path.exists():
            messagebox.showerror("Error", f"No se encontró .env en {env_path}")
            return
        try:
            content = env_path.read_text(encoding="utf-8")
            host = self.db_host.get().strip()
            port = self.db_port.get().strip()
            user = self.db_user.get().strip()
            password = self.db_pass.get()
            dbname = self.db_name.get().strip()
            db_url = f"postgresql+psycopg://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{dbname}"

            updates = {
                "DATABASE_URL": db_url,
                "POSTGRES_HOST": host,
                "POSTGRES_PORT": port,
                "POSTGRES_USER": user,
                "POSTGRES_PASSWORD": password,
                "POSTGRES_DB": dbname,
            }
            for k, val in updates.items():
                pat = rf'^{k}=.*$'
                rep = f'{k}="{val}"' if not val.isdigit() else f'{k}={val}'
                if re.search(pat, content, flags=re.MULTILINE):
                    content = re.sub(pat, rep, content, flags=re.MULTILINE)
                else:
                    content += f"\n{rep}"

            env_path.write_text(content, encoding="utf-8")
            messagebox.showinfo("Guardado", "Credenciales actualizadas en .env con éxito.")
            self.current_engine = None  # Forzar reconexion con nuevos datos
            self.init_db_connection()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # =========================================================================
    # OPERACIONES ASÍNCRONAS Y LOGS
    # =========================================================================
    def run_async_task(self, target_fn, label: str):
        """Ejecuta una función en un hilo separado para no congelar la UI."""
        self.status_msg.config(text=f"⏳ {label}")
        t = threading.Thread(target=target_fn, daemon=True)
        t.start()

    def log_seed(self, msg: str):
        self.txt_seed_log.insert(tk.END, f"{msg}\n")
        self.txt_seed_log.see(tk.END)

    def log_mig(self, msg: str):
        self.txt_mig_log.insert(tk.END, f"{msg}\n")
        self.txt_mig_log.see(tk.END)

    # =========================================================================
    # TAREAS DE SEEDING
    # =========================================================================
    def task_seed_all(self):
        try:
            self.log_seed("=" * 60)
            self.log_seed("Iniciando Seed Completo...")
            run_full_seed(log_fn=self.log_seed)
            self.after(0, self.refresh_database_overview)
            self.after(0, self.load_users)
            self.after(0, lambda: messagebox.showinfo("Seeding Exitoso", "¡Seeding completo finalizado con éxito!"))
        except Exception as e:
            self.log_seed(f"❌ Error en Seeding: {e}")
            self.after(0, lambda: messagebox.showerror("Error de Seeding", str(e)))

    def task_seed_catalog(self):
        try:
            self.log_seed("=" * 60)
            self.log_seed("Sembrando Catálogo de Moda & Variantes...")
            sm = self.get_active_sessionmaker()
            with sm() as db:
                cat_map = seed_categories(db, self.log_seed)
                seed_products(db, cat_map, self.log_seed)
                db.commit()
            self.after(0, self.refresh_database_overview)
            self.after(0, lambda: messagebox.showinfo("Catálogo Creado", "¡Prendas y variantes sembradas con éxito!"))
        except Exception as e:
            self.log_seed(f"❌ Error: {e}")

    def task_seed_users_only(self):
        try:
            self.log_seed("=" * 60)
            self.log_seed("Sembrando Usuarios Base (Admin, Vendedor, Cliente)...")
            sm = self.get_active_sessionmaker()
            with sm() as db:
                seed_users(db, self.log_seed)
                db.commit()
            self.after(0, self.load_users)
            self.after(0, lambda: messagebox.showinfo("Usuarios Creados", "¡Usuarios base sembrados con éxito!"))
        except Exception as e:
            self.log_seed(f"❌ Error: {e}")

    def action_truncate_data(self):
        if not messagebox.askyesno("Confirmar Reseteo", "¿Estás seguro de vaciar los datos de prueba? (Las tablas no se eliminarán, solo su contenido)"):
            return

        def truncate_task():
            try:
                self.log_seed("🧹 Vaciando tablas...")
                engine = self.get_active_engine()
                with engine.connect() as conn:
                    tables = [
                        "items_pedido", "pagos", "pedidos", "items_reserva", "reservas",
                        "items_carrito", "carritos", "favoritos", "movimientos_inventario",
                        "variantes_producto", "productos", "categorias", "direcciones",
                        "ai_recomendaciones", "ai_interacciones", "ai_sesiones", "usuarios"
                    ]
                    for t in tables:
                        try:
                            conn.execute(text(f'TRUNCATE TABLE "{t}" CASCADE'))
                            self.log_seed(f"  - Tabla vaciada: {t}")
                        except Exception:
                            pass
                    conn.commit()
                self.log_seed("✨ Tablas vaciadas correctamente.")
                self.after(0, self.refresh_database_overview)
                self.after(0, self.load_users)
            except Exception as e:
                self.log_seed(f"❌ Error: {e}")

        self.run_async_task(truncate_task, "Vaciando datos...")

    # =========================================================================
    # TAREAS DE MIGRACIONES & ESQUEMA
    # =========================================================================
    def task_alembic_upgrade(self):
        try:
            self.log_mig("=" * 60)
            self.log_mig("Ejecutando: alembic upgrade head")
            res = subprocess.run(["alembic", "upgrade", "head"], cwd=str(BACKEND_DIR),
                                 capture_output=True, text=True)
            self.log_mig(res.stdout)
            if res.stderr:
                self.log_mig(res.stderr)
            self.after(0, self.refresh_database_overview)
        except Exception as e:
            self.log_mig(f"❌ Error ejecutando Alembic: {e}")

    def task_apply_schema_sql(self):
        try:
            sql_file = BACKEND_DIR / "database" / "schema.sql"
            if not sql_file.exists():
                self.log_mig(f"❌ No se encontró {sql_file}")
                return
            self.log_mig("=" * 60)
            self.log_mig("Ejecutando database/schema.sql...")
            sql_content = sql_file.read_text(encoding="utf-8")
            engine = self.get_active_engine()
            with engine.connect() as conn:
                conn.execute(text(sql_content))
                conn.commit()
            self.log_mig("✅ Schema SQL aplicado exitosamente.")
            self.after(0, self.refresh_database_overview)
            self.after(0, lambda: messagebox.showinfo("Schema Aplicado", "Tablas y vistas de PostgreSQL inicializadas correctamente."))
        except Exception as e:
            self.log_mig(f"❌ Error aplicando SQL: {e}")

    def action_create_alembic_revision(self):
        msg = simpledialog.askstring("Nueva Migración", "Ingresa una descripción para la migración (ej: 'add_user_fields'):")
        if not msg:
            return

        def rev_task():
            try:
                self.log_mig("=" * 60)
                self.log_mig(f"Creando migración: alembic revision --autogenerate -m '{msg}'")
                res = subprocess.run(["alembic", "revision", "--autogenerate", "-m", msg],
                                     cwd=str(BACKEND_DIR), capture_output=True, text=True)
                self.log_mig(res.stdout)
                if res.stderr:
                    self.log_mig(res.stderr)
            except Exception as e:
                self.log_mig(f"❌ Error: {e}")

        self.run_async_task(rev_task, "Creando revisión Alembic...")

    # =========================================================================
    # LÓGICA DE USUARIOS
    # =========================================================================
    def generate_user_password(self):
        chars = string.ascii_letters + string.digits + "!@#$"
        pwd = "".join(secrets.choice(chars) for _ in range(12))
        self.u_pass.delete(0, tk.END)
        self.u_pass.insert(0, pwd)
        self.u_alert.config(text="Contraseña aleatoria generada (12 caracteres).", fg=self.ACCENT)

    def toggle_user_pass(self):
        if self.u_pass.cget("show") == "•":
            self.u_pass.config(show="")
            self.btn_u_eye.config(text="🔒")
        else:
            self.u_pass.config(show="•")
            self.btn_u_eye.config(text="👁")

    def handle_create_user(self):
        name = self.u_name.get().strip()
        email = self.u_email.get().strip().lower()
        phone = self.u_phone.get().strip() or None
        role_val = self.u_role.get()
        status_val = self.u_status.get()
        password = self.u_pass.get()

        if not name or not email or not password:
            self.u_alert.config(text="Completa todos los campos obligatorios (*).", fg=self.WARNING)
            return

        if len(password) < 8:
            self.u_alert.config(text="La contraseña debe tener mínimo 8 caracteres.", fg=self.WARNING)
            return

        try:
            sm = self.get_active_sessionmaker()
            with sm() as db:
                existing = db.scalar(select(User).where(func.lower(User.email) == email))
                if existing:
                    self.u_alert.config(text=f"El email '{email}' ya existe.", fg=self.DANGER)
                    return

                u = User(
                    nombre=name, email=email, password_hash=hash_password(password),
                    telefono=phone, rol=Role(role_val), estado=UserStatus(status_val),
                )
                db.add(u)
                db.commit()

            self.u_alert.config(text=f"¡Usuario '{name}' ({role_val}) creado con éxito!", fg=self.SUCCESS)
            self.u_name.delete(0, tk.END)
            self.u_email.delete(0, tk.END)
            self.u_phone.delete(0, tk.END)
            self.u_pass.delete(0, tk.END)
            self.load_users()
            messagebox.showinfo("Usuario Creado", f"Usuario '{name}' creado correctamente con rol {role_val}.")

        except Exception as e:
            self.u_alert.config(text=f"Error: {e}", fg=self.DANGER)

    def load_users(self):
        for item in self.users_table.get_children():
            self.users_table.delete(item)

        try:
            sm = self.get_active_sessionmaker()
            with sm() as db:
                users = db.scalars(select(User).order_by(User.id.asc())).all()
                self.raw_users = []
                admins = sum(1 for u in users if u.rol == Role.ADMIN)
                vendedores = sum(1 for u in users if u.rol == Role.VENDEDOR)
                clientes = sum(1 for u in users if u.rol == Role.CLIENTE)

                for u in users:
                    c_str = u.created_at.strftime("%Y-%m-%d %H:%M") if u.created_at else "-"
                    row = (
                        u.id, u.nombre, u.email,
                        u.rol.value if hasattr(u.rol, "value") else str(u.rol),
                        u.estado.value if hasattr(u.estado, "value") else str(u.estado),
                        u.telefono or "-", c_str
                    )
                    self.raw_users.append(row)
                    self.users_table.insert("", tk.END, values=row)

                self.u_stats.config(
                    text=f"Total: {len(users)}  |  👑 Admins: {admins}  |  💼 Vendedores: {vendedores}  |  🛍️ Clientes: {clientes}",
                    fg=self.ACCENT
                )
        except Exception as e:
            self.u_stats.config(text=f"Error: {e}", fg=self.DANGER)

    def filter_users_table(self, event=None):
        q = self.u_search.get().strip().lower()
        for item in self.users_table.get_children():
            self.users_table.delete(item)
        for r in self.raw_users:
            if not q or q in str(r[1]).lower() or q in str(r[2]).lower() or q in str(r[3]).lower():
                self.users_table.insert("", tk.END, values=r)

    def action_edit_selected_user(self):
        sel = self.users_table.selection()
        if not sel:
            messagebox.showwarning("Seleccionar", "Selecciona un usuario de la tabla.")
            return
        item = self.users_table.item(sel[0])
        uid = item["values"][0]
        uname = item["values"][1]
        cur_role = item["values"][3]
        cur_status = item["values"][4]

        diag = tk.Toplevel(self)
        diag.title(f"Editar Usuario: {uname}")
        diag.geometry("340x220")
        diag.configure(bg=self.BG_CARD)

        tk.Label(diag, text=f"Editar: {uname}", font=("Segoe UI", 10, "bold"), bg=self.BG_CARD, fg=self.FG_TEXT).pack(pady=8)

        tk.Label(diag, text="Rol:", bg=self.BG_CARD, fg=self.FG_MUTED).pack(anchor="w", padx=20)
        cb_r = ttk.Combobox(diag, state="readonly", values=["ADMIN", "VENDEDOR", "CLIENTE"])
        cb_r.set(cur_role)
        cb_r.pack(fill=tk.X, padx=20, pady=2)

        tk.Label(diag, text="Estado:", bg=self.BG_CARD, fg=self.FG_MUTED).pack(anchor="w", padx=20, pady=(6, 0))
        cb_s = ttk.Combobox(diag, state="readonly", values=["ACTIVO", "INACTIVO", "BLOQUEADO"])
        cb_s.set(cur_status)
        cb_s.pack(fill=tk.X, padx=20, pady=2)

        def save_edit():
            try:
                sm = self.get_active_sessionmaker()
                with sm() as db:
                    u = db.get(User, uid)
                    if u:
                        u.rol = Role(cb_r.get())
                        u.estado = UserStatus(cb_s.get())
                        db.commit()
                diag.destroy()
                self.load_users()
                messagebox.showinfo("Actualizado", "Usuario actualizado correctamente.")
            except Exception as e:
                messagebox.showerror("Error", str(e))

        tk.Button(diag, text="💾 Guardar Cambios", font=("Segoe UI", 9, "bold"), bg=self.PRIMARY,
                  fg="#ffffff", relief="flat", pady=4, cursor="hand2", command=save_edit).pack(pady=15)

    def action_reset_password(self):
        sel = self.users_table.selection()
        if not sel:
            messagebox.showwarning("Seleccionar", "Selecciona un usuario de la tabla.")
            return
        item = self.users_table.item(sel[0])
        uid = item["values"][0]
        uname = item["values"][1]

        new_p = simpledialog.askstring("Resetear Contraseña", f"Ingresa nueva contraseña para {uname} (mínimo 8 caracteres):")
        if not new_p or len(new_p) < 8:
            if new_p:
                messagebox.showerror("Error", "La contraseña debe tener al menos 8 caracteres.")
            return

        try:
            sm = self.get_active_sessionmaker()
            with sm() as db:
                u = db.get(User, uid)
                if u:
                    u.password_hash = hash_password(new_p)
                    db.commit()
            messagebox.showinfo("Contraseña Actualizada", f"Contraseña actualizada para {uname}.")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def action_delete_user(self):
        sel = self.users_table.selection()
        if not sel:
            messagebox.showwarning("Seleccionar", "Selecciona un usuario de la tabla.")
            return
        item = self.users_table.item(sel[0])
        uid = item["values"][0]
        uname = item["values"][1]

        if not messagebox.askyesno("Eliminar Usuario", f"¿Estás seguro de eliminar el usuario '{uname}' (ID {uid})?"):
            return

        try:
            sm = self.get_active_sessionmaker()
            with sm() as db:
                u = db.get(User, uid)
                if u:
                    db.delete(u)
                    db.commit()
            self.load_users()
            messagebox.showinfo("Eliminado", f"Usuario {uname} eliminado.")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # =========================================================================
    # EXPLORADOR DE TABLAS
    # =========================================================================
    def load_table_data(self):
        table_name = self.cb_explorer_tables.get()
        if not table_name:
            return

        for item in self.explorer_tree.get_children():
            self.explorer_tree.delete(item)

        try:
            engine = self.get_active_engine()
            with engine.connect() as conn:
                res = conn.execute(text(f'SELECT * FROM "{table_name}" LIMIT 100'))
                cols = list(res.keys())
                rows = res.fetchall()

                self.explorer_tree["columns"] = cols
                for c in cols:
                    self.explorer_tree.heading(c, text=c)
                    self.explorer_tree.column(c, width=120, anchor="w")

                for r in rows:
                    row_vals = [str(v) if v is not None else "NULL" for v in r]
                    self.explorer_tree.insert("", tk.END, values=row_vals)

                total = conn.execute(text(f'SELECT count(*) FROM "{table_name}"')).scalar()
                self.lbl_table_info.config(text=f"Mostrando {len(rows)} de {total} registros en '{table_name}'")

        except Exception as e:
            self.lbl_table_info.config(text=f"Error: {e}")

    # =========================================================================
    # CONSOLA SQL
    # =========================================================================
    def execute_sql_query(self):
        query = self.txt_sql.get("1.0", tk.END).strip()
        if not query:
            return

        for item in self.sql_tree.get_children():
            self.sql_tree.delete(item)

        try:
            engine = self.get_active_engine()
            with engine.connect() as conn:
                res = conn.execute(text(query))
                if res.returns_rows:
                    cols = list(res.keys())
                    rows = res.fetchall()
                    self.sql_tree["columns"] = cols
                    for c in cols:
                        self.sql_tree.heading(c, text=c)
                        self.sql_tree.column(c, width=120, anchor="w")
                    for r in rows:
                        self.sql_tree.insert("", tk.END, values=[str(v) if v is not None else "NULL" for v in r])
                    self.status_msg.config(text=f"Consulta exitosa: {len(rows)} filas devueltas.")
                else:
                    conn.commit()
                    self.status_msg.config(text=f"Sentencia ejecutada: {res.rowcount} filas afectadas.")
                    self.refresh_database_overview()
                    self.load_users()
        except Exception as e:
            messagebox.showerror("Error SQL", str(e))


def main():
    app = DrapeMindDBManager()
    app.mainloop()


if __name__ == "__main__":
    main()
