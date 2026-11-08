"""Paquete 01: Acceso y gestión de usuarios (PK-01).
Casos de uso:
- CU-01: Registrar cliente
- CU-02: Iniciar sesión y mantener sesión segura
- CU-03: Gestionar perfil y direcciones
- CU-27: Gestionar usuarios, roles y empleados
"""
from fastapi import APIRouter

from app.modules.acceso_y_gestion_de_usuarios.cu01_registrar_cliente import router as cu01_router
from app.segundo_parcial.cu05_acceso.cu05_autenticacion import router as cu02_router
from app.modules.acceso_y_gestion_de_usuarios.cu03_gestionar_perfil_y_direcciones import router as cu03_router
from app.segundo_parcial.cu06_usuarios_roles.cu06_empleados import router as cu27_router

auth_router = cu02_router
auth_router.include_router(cu01_router)

users_router = cu03_router

admin_users_router = cu27_router

__all__ = ["auth_router", "users_router", "admin_users_router"]

