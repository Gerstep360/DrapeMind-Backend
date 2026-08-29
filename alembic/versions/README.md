# 📁 Directorio de Migraciones Alembic (`backend/alembic/versions/`)

Aquí es donde se almacenan y versionan las migraciones de la base de datos PostgreSQL.

## ¿Cómo crear una migración fácilmente desde el Orquestador?

1. Modifica o crea tus modelos en `backend/app/models/entities.py`.
2. En el **Orquestador**, ve a la pestaña **🗄️ Base de Datos & Migraciones**.
3. Haz clic en **⚡ Detectar y Generar Migración (Autogenerate)**.
4. El sistema comparará tus modelos de SQLAlchemy con la base de datos PostgreSQL y creará automáticamente el script de migración aquí.
5. Haz clic en **⚡ Aplicar Migraciones (Upgrade Head)** para aplicar los cambios a la base de datos.
