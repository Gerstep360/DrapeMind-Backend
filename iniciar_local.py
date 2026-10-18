#!/usr/bin/env python3
"""Panel local de FastAPI, PostgreSQL, Alembic y seeders. Solo requiere tkinter."""

import argparse
import os
from pathlib import Path
import queue
import signal
import socket
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import webbrowser

BACKEND = Path(__file__).resolve().parent


def python_path() -> str:
    candidate = BACKEND / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(candidate) if candidate.exists() else sys.executable


def child_env() -> dict:
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1",
               ENVIRONMENT="development", DEBUG="true", ROOT_PATH="")
    # A demo seed from this panel must never inherit destructive seed options.
    env.pop("SEED_RESET", None)
    env.pop("SEED_FORCE", None)
    return env


def spawn(command: list[str], env: dict) -> subprocess.Popen:
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    return subprocess.Popen(command, cwd=BACKEND, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", bufsize=1, **options)


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)


class LocalPanel:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.events = queue.Queue()
        self.server = None
        self.forwarder = None
        self.job = None
        self.job_busy = False
        self.closing = False
        root.title("DrapeMind · Backend local")
        root.geometry("960x700")
        root.minsize(760, 600)
        self.port = tk.StringVar(value="8000")
        self.lan = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Backend detenido")
        self.seed_mode = tk.StringVar(value="quick")
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="DrapeMind · Backend local", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(frame, text="FastAPI + PostgreSQL local · Asistente NVIDIA").pack(anchor="w", pady=(3, 16))
        config = ttk.Frame(frame)
        config.pack(fill="x")
        ttk.Label(config, text="Puerto:").pack(side="left")
        ttk.Entry(config, textvariable=self.port, width=8).pack(side="left", padx=8)
        ttk.Checkbutton(config, text="Acceso por red local (Flutter / teléfono)", variable=self.lan).pack(side="left", padx=8)
        server = ttk.LabelFrame(frame, text="Servidor", padding=10)
        server.pack(fill="x", pady=12)
        self.start_button = ttk.Button(server, text="Iniciar backend", command=self.start)
        self.start_button.pack(side="left", padx=4)
        ttk.Button(server, text="Detener backend", command=self.stop).pack(side="left", padx=4)
        ttk.Button(server, text="Abrir Swagger", command=lambda: self.open_url("/docs")).pack(side="left", padx=4)
        ttk.Button(server, text="Estado API / DB", command=self.check_api).pack(side="left", padx=4)
        ttk.Label(frame, textvariable=self.status).pack(anchor="w")
        setup = ttk.LabelFrame(frame, text="Preparación (en este orden la primera vez)", padding=10)
        setup.pack(fill="x", pady=10)
        self.job_buttons = []
        self.button(setup, "1. Instalar dependencias", self.install)
        self.button(setup, "2. Crear .env", lambda: self.task("env"))
        self.button(setup, "Editar .env", self.edit_env)
        self.button(setup, "3. Crear base", lambda: self.task("create-db"))
        self.button(setup, "4. Migrar", lambda: self.alembic("upgrade", "head"))
        database = ttk.LabelFrame(frame, text="Migraciones y datos de demostración (ficticios)", padding=10)
        database.pack(fill="x")
        self.button(database, "Revisión actual", lambda: self.alembic("current"))
        self.button(database, "Historial", lambda: self.alembic("history"))
        self.button(database, "Generar migración", self.revision)
        ttk.Combobox(database, textvariable=self.seed_mode, values=["quick", "standard", "full"],
                     state="readonly", width=10).pack(side="left", padx=4)
        self.button(database, "5. Ejecutar seeder", self.seed)
        saas = ttk.LabelFrame(frame, text="Empresas y suscripciones SaaS", padding=10)
        saas.pack(fill="x", pady=8)
        company_tools=ttk.Frame(saas);company_tools.pack(fill="x")
        billing_tools=ttk.Frame(saas);billing_tools.pack(fill="x",pady=(8,0))
        self.button(company_tools, "Respaldar base", lambda: self.saas_task("backup"))
        self.button(company_tools, "Configurar rol seguro", lambda: self.saas_task("runtime-role"))
        self.button(company_tools, "Crear empresas demo", lambda: self.saas_task("demo"))
        self.button(company_tools, "Probar aislamiento", lambda: self.run_job([[python_path(), "-m", "scripts.diagnostics.check_saas"]]))
        self.button(billing_tools, "Publicar precios Stripe", lambda: self.saas_task("stripe-prices"))
        self.button(billing_tools, "Configurar Stripe local", lambda: self.run_job([[python_path(), "-m", "scripts.stripe_local", "configure"]]))
        self.button(billing_tools, "Iniciar webhooks locales", self.start_stripe)
        self.button(billing_tools, "Detener webhooks", self.stop_stripe)
        checks = ttk.Frame(frame)
        checks.pack(fill="x", pady=10)
        self.button(checks, "Comprobar PostgreSQL", lambda: self.task("check-db"))
        self.button(checks, "Probar IA (usa cuota)", lambda: self.task("check-ai"))
        ttk.Label(checks, text="El backend funciona sin una clave IA; el chat sí la necesita.").pack(side="left", padx=12)
        log_frame = ttk.Frame(frame)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(log_frame, wrap="word", state="disabled", font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)
        self.write("Configura PostgreSQL y NVIDIA_API_KEY en backend/.env.\n")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.drain)

    def button(self, parent, label, command):
        button = ttk.Button(parent, text=label, command=command)
        button.pack(side="left", padx=3)
        self.job_buttons.append(button)

    def write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def drain(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.write(value)
            elif kind == "server_done":
                self.server = None
                self.start_button.configure(state="normal")
                self.status.set(f"Backend detenido (código {value})")
            elif kind == "job_done":
                self.job = None
                self.job_busy = False
                for button in self.job_buttons:
                    button.configure(state="normal")
        if not self.closing:
            self.root.after(100, self.drain)

    def run_job(self, commands):
        if self.job_busy:
            return
        self.job_busy = True
        env = child_env()
        for button in self.job_buttons:
            button.configure(state="disabled")

        def worker():
            try:
                for command in commands:
                    if self.closing:
                        break
                    self.events.put(("log", f"\n> {subprocess.list2cmdline(command)}\n"))
                    self.job = spawn(command, env)
                    for line in self.job.stdout:
                        self.events.put(("log", line))
                    code = self.job.wait()
                    self.events.put(("log", f"Finalizado con código {code}.\n"))
                    if code:
                        break
            except Exception as exc:
                self.events.put(("log", f"No se pudo ejecutar la tarea: {type(exc).__name__}.\n"))
            finally:
                self.events.put(("job_done", None))
        threading.Thread(target=worker, daemon=True).start()

    def task(self, name):
        self.run_job([[python_path(), "-m", "scripts.local_tasks", name]])

    def saas_task(self, name):
        self.run_job([[python_path(), "-m", "scripts.saas_setup", name]])

    def start_stripe(self):
        if self.forwarder is not None and self.forwarder.poll() is None:
            return
        try:
            port=self.server_port()
            self.forwarder=spawn([python_path(),"-m","scripts.stripe_local","listen","--port",str(port)],child_env())
        except (ValueError,OSError) as exc:
            messagebox.showerror("Stripe local",str(exc));return
        process=self.forwarder
        def read():
            for line in process.stdout:self.events.put(("log",line))
            self.events.put(("log",f"Reenvío Stripe finalizado ({process.wait()}).\n"))
        threading.Thread(target=read,daemon=True).start()

    def stop_stripe(self):
        if self.forwarder is not None:
            threading.Thread(target=stop_process,args=(self.forwarder,),daemon=True).start()

    def alembic(self, *args):
        self.run_job([[python_path(), "-m", "alembic", *args]])

    def install(self):
        venv = BACKEND / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        commands = []
        if not venv.exists():
            commands.append([sys.executable, "-m", "venv", str(BACKEND / ".venv")])
        commands.append([str(venv), "-m", "pip", "install", "-r", "requirements.txt"])
        self.run_job(commands)

    def edit_env(self):
        path = BACKEND / ".env"
        if not path.exists():
            messagebox.showinfo("Configuración", "Primero pulsa Crear .env.")
            return
        if os.name == "nt":
            subprocess.Popen(["notepad.exe", str(path)])
        else:
            webbrowser.open(path.as_uri())

    def revision(self):
        name = simpledialog.askstring("Nueva migración", "Descripción del cambio:", parent=self.root)
        if name and name.strip():
            self.alembic("revision", "--autogenerate", "-m", name.strip())

    def seed(self):
        self.write("\nSeed ficticio: no se usa --reset ni --force. Una base con productos se conserva.\n")
        self.run_job([[python_path(), "-m", "scripts.db.seed.seed_data", f"--{self.seed_mode.get()}"]])

    def server_port(self):
        try:
            port = int(self.port.get())
            if 1024 <= port <= 65535:
                return port
        except ValueError:
            pass
        raise ValueError("El puerto debe estar entre 1024 y 65535.")

    def start(self):
        if self.server is not None:
            return
        try:
            port = self.server_port()
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    raise ValueError(f"El puerto {port} ya está ocupado. Detén el otro servidor o usa otro puerto.")
            self.server = spawn([python_path(), "-m", "uvicorn", "app.main:app", "--host",
                                 "0.0.0.0" if self.lan.get() else "127.0.0.1", "--port", str(port)],
                                child_env())
        except (ValueError, OSError) as exc:
            messagebox.showerror("Inicio del backend", str(exc))
            return
        process = self.server
        self.active_port = port
        self.start_button.configure(state="disabled")
        self.status.set(f"Proceso iniciado · http://127.0.0.1:{port} · NVIDIA")

        def read():
            for line in process.stdout:
                self.events.put(("log", line))
            self.events.put(("server_done", process.wait()))
        threading.Thread(target=read, daemon=True).start()

    def stop(self):
        if self.server is not None:
            process = self.server
            threading.Thread(target=stop_process, args=(process,), daemon=True).start()

    def open_url(self, suffix):
        try:
            webbrowser.open(f"http://127.0.0.1:{getattr(self, 'active_port', self.server_port())}{suffix}")
        except ValueError as exc:
            messagebox.showerror("Puerto", str(exc))

    def check_api(self):
        try:
            port = getattr(self, "active_port", self.server_port())
        except ValueError as exc:
            messagebox.showerror("Puerto", str(exc))
            return

        def check():
            from urllib.request import urlopen
            for endpoint in ("/health/live", "/health/ready"):
                try:
                    with urlopen(f"http://127.0.0.1:{port}{endpoint}", timeout=5) as result:
                        self.events.put(("log", f"{endpoint}: {result.status} {result.read().decode()}\n"))
                except Exception:
                    self.events.put(("log", f"{endpoint}: no disponible.\n"))
        threading.Thread(target=check, daemon=True).start()

    def close(self):
        if self.job_busy:
            messagebox.showinfo("Tarea en curso", "Espera a que termine la tarea de mantenimiento antes de cerrar.")
            return
        self.closing = True
        self.stop_stripe()
        if self.server is not None:
            process = self.server
            def finish():
                stop_process(process)
                self.events.put(("closed", None))
            threading.Thread(target=finish, daemon=True).start()
            self.wait_close()
        else:
            self.root.destroy()

    def wait_close(self):
        if self.server is not None and self.server.poll() is None:
            self.root.after(100, self.wait_close)
        else:
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    root = tk.Tk()
    LocalPanel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
