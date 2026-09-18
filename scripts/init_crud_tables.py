"""Script de inicialización para las tablas de CU-32, CU-36 y CU-31."""
import sys
from pathlib import Path

# Añadir raíz de backend al PYTHONPATH
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.db.base import Base
from app.db.session import engine
from app.models import Promotion, Season, Supplier, SupplierProduct


def create_tables():
    try:
        Base.metadata.create_all(
            bind=engine,
            tables=[
                Supplier.__table__,
                Promotion.__table__,
                Season.__table__,
                SupplierProduct.__table__,
            ],
        )
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE promociones ADD COLUMN IF NOT EXISTS producto_id BIGINT REFERENCES productos(id) ON DELETE SET NULL;"))
        print("Tablas 'proveedores', 'promociones', 'temporadas_colecciones' y 'proveedor_suministros' verificadas/creadas correctamente.")
    except Exception as exc:
        print(f"Aviso: No se pudo conectar a PostgreSQL ({exc}). Las tablas se crearán al correr migraciones o conectar la base de datos.")


if __name__ == "__main__":
    create_tables()
