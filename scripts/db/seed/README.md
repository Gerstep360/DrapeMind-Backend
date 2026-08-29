# 📁 Directorio de Seeds de DrapeMind Atelier (`backend/scripts/db/seed/`)

¡Aquí puedes crear y guardar tus scripts seeders para poblar o restaurar la base de datos!

## ¿Cómo crear un nuevo script Seed fácilmente?

Crea un archivo Python en esta carpeta (ejemplo: `seed_promociones.py` o `seed_prendas_nuevas.py`) siguiendo esta plantilla básica:

```python
#!/usr/bin/env python3
from pathlib import Path
import sys

# Agregar el backend al path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.db.session import SessionLocal
from app.models.entities import Product, Category

def run_seed():
    db = SessionLocal()
    try:
        print("🌱 Ejecutando seed...")
        # Inserta tus datos aquí usando SQLAlchemy:
        # db.add(Category(nombre="Nueva Categoria", slug="nueva-categoria", activo=True))
        # db.commit()
        print("✓ Seed completado con éxito.")
    finally:
        db.close()

if __name__ == "__main__":
    run_seed()
```

Desde el **Orquestador** puedes ejecutar todos los seeds con 1 clic en el botón `🌱 Poblar Base de Datos`.
