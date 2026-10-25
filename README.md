# DrapeMind API

FastAPI + SQLAlchemy + PostgreSQL; NVIDIA API es el único proveedor de IA.

Plataforma SaaS de base compartida: [empresas, planes, Stripe y preparación local](docs/SAAS_MULTITENANT.md). El proceso HTTP requiere `RUNTIME_DATABASE_URL` con un rol sin bypass RLS; se configura desde el panel o `python -m scripts.saas_setup runtime-role`.

## Local

`python iniciar_local.py` abre el panel con instalación de dependencias, DB, migraciones, seeder y arranque/parada. Configura `.env` a partir de `.env.example`: conexión PostgreSQL, secretos y `NVIDIA_API_KEY`.

También puedes usar `.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000` en Windows o `.venv/bin/python -m uvicorn app.main:app --port 8000` en Linux. Para migrar: `python -m alembic upgrade head`. Datos de ejemplo: `python -m scripts.db.seed_data --quick`.

`python -m scripts.local_tasks check-ai` valida streaming y herramientas con el modelo NVIDIA configurado. Sin credencial, los flujos comerciales siguen disponibles y la IA comunica que falta configuración.

## Verificación

`python -m pytest -q`. Las pruebas del transporte, herramientas, concurrencia, permisos y guardado del perfil usan dobles herméticos y no consumen la API real.

[Arquitectura](docs/ARQUITECTURA_AI.md) · [Instalación nativa y mantenimiento del VPS](docs/INSTALACION_VPS.md)
