"""
DRAPEMIND ATELIER - HERRAMIENTAS Y MOTOR DEL ESTUDIO VISUAL DE BASE DE DATOS
Funciones completas para:
- Diagnosticar conexión a PostgreSQL.
- Explorar tablas, conteo de filas y esquemas en tiempo real.
- Consultar, filtrar, paginar e insertar datos visualmente en cualquier tabla.
- Diseñador visual de migraciones (Crear Tabla, Agregar Columnas) generando archivos Alembic.
- Ejecutar consultas SQL arbitrarias con formateo de resultados.
- Administrar y crear scripts Seed en 'scripts/db/seed/'.
"""

import datetime
import decimal
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy import create_engine, inspect, text
from app.core.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


def get_engine():
    """Retorna una instancia del motor SQLAlchemy apuntando a PostgreSQL."""
    return create_engine(settings.database_uri)


def check_postgres_status() -> dict:
    """Verifica el estado del servidor PostgreSQL y la base de datos 'drapemind_db'."""
    import socket

    host = settings.POSTGRES_HOST
    port = settings.POSTGRES_PORT
    user = settings.POSTGRES_USER
    password = settings.POSTGRES_PASSWORD
    db_name = settings.POSTGRES_DB

    # 1. Comprobar socket TCP
    server_online = False
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        res = s.connect_ex((host, port))
        s.close()
        server_online = (res == 0)
    except Exception:
        server_online = False

    if not server_online:
        return {
            "server_online": False,
            "db_exists": False,
            "message": f"Servidor PostgreSQL detenido o inaccesible en {host}:{port}.",
        }

    # 2. Comprobar si existe la base de datos drapemind_db
    db_exists = False
    try:
        admin_uri = f"postgresql+psycopg://{user}:{password}@{host}:{port}/postgres"
        engine = create_engine(admin_uri, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
            ).scalar()
            db_exists = bool(result)
        engine.dispose()
    except Exception:
        try:
            target_uri = settings.database_uri
            engine = create_engine(target_uri)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                db_exists = True
            engine.dispose()
        except Exception as e:
            return {
                "server_online": True,
                "db_exists": False,
                "message": f"PostgreSQL online, pero error de autenticación: {e}",
            }

    return {
        "server_online": True,
        "db_exists": db_exists,
        "db_name": db_name,
        "message": f"PostgreSQL activo en {host}:{port} · Base de datos '{db_name}': {'DETECTADA Y LISTA' if db_exists else 'NO EXISTE'}",
    }


def create_database_if_not_exists(log_callback: Optional[Callable[[str], None]] = None) -> bool:
    """Crea la base de datos 'drapemind_db' si no existe."""
    host = settings.POSTGRES_HOST
    port = settings.POSTGRES_PORT
    user = settings.POSTGRES_USER
    password = settings.POSTGRES_PASSWORD
    db_name = settings.POSTGRES_DB

    def _log(msg: str):
        if log_callback:
            log_callback(msg)

    _log(f"[DB] Conectando a PostgreSQL ({host}:{port}) para crear '{db_name}'...")
    try:
        admin_uri = f"postgresql+psycopg://{user}:{password}@{host}:{port}/postgres"
        engine = create_engine(admin_uri, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            exists = conn.execute(
                text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
            ).scalar()
            if exists:
                _log(f"[DB] La base de datos '{db_name}' ya existe.")
                return True

            conn.execute(text(f'CREATE DATABASE "{db_name}" ENCODING "UTF8"'))
            _log(f"[DB] ✓ Base de datos '{db_name}' creada exitosamente.")
        engine.dispose()
        return True
    except Exception as e:
        _log(f"[ERROR DB] No se pudo crear la base de datos: {e}")
        return False


def get_all_tables_info() -> list[dict]:
    """Obtiene la lista de todas las tablas con su conteo de filas y columnas."""
    try:
        engine = get_engine()
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        result = []
        with engine.connect() as conn:
            for t in sorted(tables):
                try:
                    count = conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() or 0
                except Exception:
                    count = 0
                cols = inspector.get_columns(t)
                result.append({
                    "name": t,
                    "row_count": count,
                    "columns_count": len(cols),
                })
        engine.dispose()
        return result
    except Exception:
        return []


def get_table_schema(table_name: str) -> list[dict]:
    """Obtiene la estructura detallada de columnas de una tabla."""
    try:
        engine = get_engine()
        inspector = inspect(engine)
        cols = inspector.get_columns(table_name)
        pk_info = inspector.get_pk_constraint(table_name)
        pks = set(pk_info.get("constrained_columns", [])) if pk_info else set()

        result = []
        for c in cols:
            result.append({
                "name": c["name"],
                "type": str(c["type"]),
                "nullable": "SÍ" if c.get("nullable") else "NO",
                "primary_key": "PK" if c["name"] in pks else "",
                "default": str(c.get("default", "")) if c.get("default") is not None else "",
            })
        engine.dispose()
        return result
    except Exception:
        return []


def get_table_data(table_name: str, limit: int = 100, search_text: str = "") -> tuple[list[str], list[list[Any]], int]:
    """Obtiene los registros reales de una tabla con soporte para búsqueda rápida."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            # Obtener conteo total
            total_count = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar() or 0

            # Consulta de datos
            query = f'SELECT * FROM "{table_name}"'
            if search_text.strip():
                inspector = inspect(engine)
                cols = inspector.get_columns(table_name)
                # Filtrar columnas de texto para el LIKE
                text_cols = [c["name"] for c in cols if "CHAR" in str(c["type"]).upper() or "TEXT" in str(c["type"]).upper()]
                if text_cols:
                    conditions = [f'"{col}"::text ILIKE :st' for col in text_cols]
                    query += " WHERE " + " OR ".join(conditions)

            query += f" LIMIT {limit}"
            stmt = text(query)
            params = {"st": f"%{search_text.strip()}%"} if search_text.strip() else {}
            res = conn.execute(stmt, params)

            columns = list(res.keys())
            rows = []
            for row in res.fetchall():
                formatted_row = []
                for val in row:
                    if val is None:
                        formatted_row.append("<NULL>")
                    elif isinstance(val, (datetime.datetime, datetime.date)):
                        formatted_row.append(val.strftime("%Y-%m-%d %H:%M"))
                    elif isinstance(val, decimal.Decimal):
                        formatted_row.append(str(val))
                    elif isinstance(val, (dict, list)):
                        import json
                        formatted_row.append(json.dumps(val, ensure_ascii=False))
                    else:
                        formatted_row.append(str(val))
                rows.append(formatted_row)

        engine.dispose()
        return columns, rows, total_count
    except Exception as e:
        return ["Error"], [[str(e)]], 0


def delete_row_by_pk(table_name: str, pk_col: str, pk_val: Any) -> bool:
    """Elimina una fila por su clave primaria."""
    try:
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(text(f'DELETE FROM "{table_name}" WHERE "{pk_col}" = :val'), {"val": pk_val})
        engine.dispose()
        return True
    except Exception:
        return False


def execute_raw_sql(sql_query: str) -> tuple[list[str], list[list[Any]], str]:
    """Ejecuta una consulta SQL arbitraria y devuelve columnas, filas y posible mensaje."""
    sql = sql_query.strip()
    if not sql:
        return [], [], "Consulta vacía."

    try:
        engine = get_engine()
        is_select = sql.lower().startswith("select") or sql.lower().startswith("with") or sql.lower().startswith("show")
        with engine.begin() as conn:
            res = conn.execute(text(sql))
            if is_select and res.returns_rows:
                columns = list(res.keys())
                rows = []
                for row in res.fetchall()[:200]:
                    rows.append([str(v) if v is not None else "<NULL>" for v in row])
                msg = f"✓ Consulta ejecutada con éxito. {len(rows)} fila(s) retornada(s)."
                engine.dispose()
                return columns, rows, msg
            else:
                affected = res.rowcount if hasattr(res, "rowcount") else 0
                msg = f"✓ Comando SQL ejecutado correctamente. Filas afectadas: {affected}"
                engine.dispose()
                return ["Resultado"], [[msg]], msg
    except Exception as e:
        return ["Error"], [[str(e)]], f"✗ Error SQL: {e}"


def generate_create_table_migration(table_name: str, columns_list: list[dict], backend_dir: Path) -> Path:
    """
    Genera un archivo de migración Alembic para crear una nueva tabla visualmente.
    columns_list es una lista de dicts: [{'name': '...', 'type': 'Integer/String/Boolean/Float/DateTime/JSONB', 'pk': True/False, 'nullable': True/False, 'default': '...'}]
    """
    versions_dir = backend_dir / "alembic" / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    clean_table = table_name.strip().lower().replace(" ", "_")
    rev_id = f"{timestamp}_create_{clean_table}"
    filename = f"{rev_id}.py"
    target_path = versions_dir / filename

    cols_code = []
    for c in columns_list:
        c_name = c["name"].strip().lower().replace(" ", "_")
        c_type = c["type"]
        is_pk = c.get("pk", False)
        nullable = c.get("nullable", True)

        # Mapeo de tipos SQLAlchemy
        type_str = "sa.Integer()"
        if c_type == "String":
            length = c.get("length", 255)
            type_str = f"sa.String(length={length})"
        elif c_type == "Text":
            type_str = "sa.Text()"
        elif c_type == "Boolean":
            type_str = "sa.Boolean()"
        elif c_type == "Float":
            type_str = "sa.Numeric(10, 2)"
        elif c_type == "DateTime":
            type_str = "sa.DateTime(timezone=True)"
        elif c_type == "JSONB":
            type_str = "postgresql.JSONB()"

        pk_arg = ", primary_key=True" if is_pk else ""
        null_arg = f", nullable={nullable}"
        cols_code.append(f"        sa.Column('{c_name}', {type_str}{pk_arg}{null_arg}),")

    cols_str = "\n".join(cols_code)

    content = f'''"""create table {clean_table}

Revision ID: {rev_id}
Revises: 
Create Date: {time.strftime('%Y-%m-%d %H:%M:%S')}

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '{rev_id}'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        '{clean_table}',
{cols_str}
    )


def downgrade() -> None:
    op.drop_table('{clean_table}')
'''
    target_path.write_text(content, encoding="utf-8")
    return target_path


def generate_add_column_migration(table_name: str, col_name: str, col_type: str, nullable: bool, backend_dir: Path) -> Path:
    """Genera una migración Alembic para agregar una columna a una tabla existente."""
    versions_dir = backend_dir / "alembic" / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    clean_table = table_name.strip().lower()
    clean_col = col_name.strip().lower().replace(" ", "_")
    rev_id = f"{timestamp}_add_{clean_col}_to_{clean_table}"
    target_path = versions_dir / f"{rev_id}.py"

    type_str = "sa.String(255)"
    if col_type == "Integer":
        type_str = "sa.Integer()"
    elif col_type == "Text":
        type_str = "sa.Text()"
    elif col_type == "Boolean":
        type_str = "sa.Boolean()"
    elif col_type == "Float":
        type_str = "sa.Numeric(10, 2)"
    elif col_type == "DateTime":
        type_str = "sa.DateTime(timezone=True)"
    elif col_type == "JSONB":
        type_str = "postgresql.JSONB()"

    content = f'''"""add {clean_col} to {clean_table}

Revision ID: {rev_id}
Revises: 
Create Date: {time.strftime('%Y-%m-%d %H:%M:%S')}

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '{rev_id}'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('{clean_table}', sa.Column('{clean_col}', {type_str}, nullable={nullable}))


def downgrade() -> None:
    op.drop_column('{clean_table}', '{clean_col}')
'''
    target_path.write_text(content, encoding="utf-8")
    return target_path


def list_migration_files(backend_dir: Path) -> list[dict]:
    """Lista todos los archivos de migración en alembic/versions."""
    versions_dir = backend_dir / "alembic" / "versions"
    if not versions_dir.exists():
        return []

    files = []
    for p in sorted(versions_dir.glob("*.py"), reverse=True):
        if p.name.startswith("__"):
            continue
        try:
            mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))
        except Exception:
            mtime = "--"
        files.append({
            "name": p.name,
            "path": str(p),
            "date": mtime,
            "size": f"{p.stat().st_size / 1024:.1f} KB",
        })
    return files


def list_seed_files(backend_dir: Path) -> list[dict]:
    """Lista todos los scripts seeder en scripts/db/seed/."""
    seed_dir = backend_dir / "scripts" / "db" / "seed"
    if not seed_dir.exists():
        return []

    files = []
    for p in sorted(seed_dir.glob("*.py")):
        if p.name.startswith("__"):
            continue
        try:
            mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))
        except Exception:
            mtime = "--"
        files.append({
            "name": p.name,
            "path": str(p),
            "date": mtime,
            "size": f"{p.stat().st_size / 1024:.1f} KB",
        })
    return files


def create_seed_template(name: str, backend_dir: Path) -> Path:
    """Crea una nueva plantilla de script Seed lista para usar."""
    seed_dir = backend_dir / "scripts" / "db" / "seed"
    seed_dir.mkdir(parents=True, exist_ok=True)

    clean_name = name.strip().lower().replace(" ", "_")
    if not clean_name.startswith("seed_"):
        clean_name = f"seed_{clean_name}"
    if not clean_name.endswith(".py"):
        clean_name = f"{clean_name}.py"

    target_file = seed_dir / clean_name
    template_content = f'''#!/usr/bin/env python3
"""
DRAPEMIND ATELIER - SEED: {clean_name}
Script para sembrar o poblar datos específicos en PostgreSQL.
"""

import sys
from pathlib import Path

# Configurar ruta al backend
BACKEND_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.entities import Category, Product, ProductVariant, User, Role, UserStatus


def run():
    db = SessionLocal()
    try:
        print("🌱 Ejecutando seed: {clean_name}...")
        
        # --- ESCRIBE TU LÓGICA DE SIEMBRA AQUÍ ---
        # Ejemplo:
        # cat = db.scalar(select(Category).where(Category.slug == "mi-categoria"))
        # if not cat:
        #     db.add(Category(nombre="Mi Categoría", slug="mi-categoria", activo=True))
        #     db.commit()
        #     print("✓ Categoría creada.")

        print("✓ Seed {clean_name} finalizado con éxito.")
    except Exception as e:
        db.rollback()
        print(f"✗ Error durante el seed: {{e}}")
    finally:
        db.close()


if __name__ == "__main__":
    run()
'''
    target_file.write_text(template_content, encoding="utf-8")
    return target_file


def run_alembic_command(args: list[str], cwd: Path, log_callback: Callable[[str], None]) -> bool:
    """Ejecuta un comando de alembic capturando su salida en tiempo real."""
    venv_py = cwd / ".venv" / "Scripts" / "python.exe"
    py_exec = str(venv_py) if venv_py.exists() else sys.executable

    cmd = [py_exec, "-m", "alembic"] + args
    log_callback(f"[ALEMBIC] Ejecutando: {' '.join(cmd)}\n")

    try:
        proc = subprocess.Popen(
            cmd,
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
                    log_callback(line)
        proc.wait()
        success = (proc.returncode == 0)
        log_callback(f"\n[ALEMBIC] Finalizado con código {proc.returncode}.\n")
        return success
    except Exception as e:
        log_callback(f"[ERROR ALEMBIC] {e}\n")
        return False
