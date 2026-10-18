"""Local maintenance commands, also used by iniciar_local.py. Never print secrets."""

import argparse
import asyncio
from pathlib import Path
import secrets

BACKEND = Path(__file__).resolve().parents[1]


def create_env() -> None:
    target = BACKEND / ".env"
    if target.exists():
        print(".env ya existe; se conserva su configuración.")
        return
    template = (BACKEND / ".env.example").read_text(encoding="utf-8")
    template = template.replace(
        "change-me-with-at-least-32-characters", secrets.token_urlsafe(48)
    )
    template = template.replace(
        "change-me-payment-webhook-secret", secrets.token_urlsafe(48)
    )
    with target.open("x", encoding="utf-8") as output:
        output.write(template)
    print(
        "Creado backend/.env con secretos locales nuevos. Configura PostgreSQL y NVIDIA_API_KEY."
    )


def database_task(create: bool = False) -> None:
    from sqlalchemy import create_engine, text, inspect
    from sqlalchemy.engine import make_url
    from app.core.config import settings

    url = make_url(settings.database_uri)
    if url.get_backend_name() != "postgresql" or not url.database:
        raise ValueError(
            "La base local requiere una URL PostgreSQL con nombre de base."
        )
    engine = create_engine(
        url.set(database="postgres") if create else url,
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.connect() as connection:
            if create:
                exists = connection.scalar(
                    text("SELECT 1 FROM pg_database WHERE datname=:name"),
                    {"name": url.database},
                )
                if not exists:
                    name = connection.dialect.identifier_preparer.quote_identifier(
                        url.database
                    )
                    connection.execute(text(f"CREATE DATABASE {name}"))
                print("Base PostgreSQL disponible. Aplica ahora las migraciones.")
            else:
                connection.execute(text("SELECT 1"))
                print("Conexión PostgreSQL correcta.")
                from app.models.entities import Base

                schema = inspect(connection)
                existing = set(schema.get_table_names())
                missing = []
                for name, table in Base.metadata.tables.items():
                    if name not in existing:
                        missing.append(f"tabla {name}")
                    else:
                        columns = {
                            column["name"] for column in schema.get_columns(name)
                        }
                        missing.extend(
                            f"columna {name}.{column}"
                            for column in set(table.columns.keys()) - columns
                        )
                if missing:
                    print("Faltan elementos del esquema: " + ", ".join(sorted(missing)))
                    print(
                        "Aplica las migraciones con el botón Migrar o python -m alembic upgrade head."
                    )
                    raise SystemExit(1)
                print("Tablas y columnas compatibles con el backend.")
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["env", "create-db", "check-db", "check-ai"])
    args = parser.parse_args()
    try:
        if args.action == "env":
            create_env()
        elif args.action in {"create-db", "check-db"}:
            database_task(create=args.action == "create-db")
        else:
            from app.core.config import settings

            if not settings.NVIDIA_API_KEY:
                print(
                    "Configura NVIDIA_API_KEY en backend/.env antes de comprobar la IA."
                )
                raise SystemExit(1)
            from app.services.llm_provider import check_provider

            result = asyncio.run(check_provider())
            print(f"NVIDIA: {result['model']} — herramientas y streaming comprobados.")
    except Exception:
        # Database errors can contain connection strings; keep credentials out of the GUI console.
        print(
            "La operación falló. Revisa backend/.env, dependencias y disponibilidad del servicio."
        )
        if args.action in {"create-db", "check-db"}:
            print(
                "PostgreSQL debe estar iniciado y accesible con las credenciales de .env. En Windows revisa el servicio PostgreSQL; si está detenido, inícialo desde Servicios con permisos de administrador."
            )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
