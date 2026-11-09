#!/usr/bin/env python3
"""
DRAPEMIND - DESPACHADOR DE NOTIFICACIONES PERSONALIZADAS
Envia notificaciones en tiempo real simultaneamente a Web (WebSockets)
y Mobile (Google Firebase Cloud Messaging HTTP v1).
"""

import argparse
import asyncio
import os
import sys

# Agregar la raiz de backend al path
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import func, select
from app.db.session import SessionLocal
from app.models.entities import User, UserDevice
from app.services.push_notifications import dispatch_notification, _find_firebase_service_account_path
from app.core.tenancy import system_scope


def get_users_summary(db):
    """Consulta la lista de usuarios junto con el conteo de dispositivos activos."""
    with system_scope(db):
        stmt = (
            select(
                User.id,
                User.nombre,
                User.email,
                User.rol,
                User.tenant_id,
                func.count(UserDevice.id).filter(UserDevice.activo == True).label("devices_count"),  # noqa: E712
            )
            .outerjoin(UserDevice, User.id == UserDevice.usuario_id)
            .group_by(User.id, User.nombre, User.email, User.rol, User.tenant_id)
            .order_by(User.id)
        )
        return db.execute(stmt).all()


async def send_to_user(user_id, title, message, screen, notification_type, tenant_id=None):
    if not tenant_id:
        with SessionLocal() as lookup_db:
            with system_scope(lookup_db):
                u = lookup_db.get(User, user_id)
                if not u or not u.tenant_id:
                    raise ValueError('El destinatario debe pertenecer a una tienda')
                tenant_id = u.tenant_id

    payload = {
        "screen": screen,
        "enlace": screen,
        "url": screen,
        "action": "NAVIGATE",
    }
    with SessionLocal(tenant_id=tenant_id) as db:
        with system_scope(db):
            notif = await dispatch_notification(
                db=db,
                user_id=user_id,
                titulo=title,
                mensaje=message,
                tipo=notification_type,
                payload=payload,
            )
            return notif


async def main_async(args):
    db = SessionLocal()
    try:
        users = get_users_summary(db)
        if not users:
            print("[ERROR] No se encontraron usuarios registrados en la base de datos.")
            return

        sa_path = _find_firebase_service_account_path()
        print("\n========================================================")
        print("  DRAPEMIND - GESTOR DE NOTIFICACIONES MULTIPLATAFORMA")
        print("  Web (WebSockets) + Mobile (Firebase Cloud Messaging)")
        print("========================================================")
        if sa_path:
            print(f"[ESTADO FCM] Cuenta de servicio Firebase detectada: {os.path.basename(sa_path)}")
        else:
            print("[ESTADO FCM] Aviso: No se encontro archivo 'firebase_service_account.json'.")
            print("             Las notificaciones llegaran de inmediato a Web y Mobile activo via WebSocket.")
            print("             Para push en segundo plano Android, coloque firebase_service_account.json.")
        print("--------------------------------------------------------\n")

        target_user_id = args.user_id
        title = args.title
        message = args.message
        screen = args.screen
        notif_type = args.type or "PROMOTION"

        # Modo interactivo si faltan argumentos
        if target_user_id is None:
            print("USUARIOS REGISTRADOS:")
            print(f" {'ID':<5} | {'NOMBRE':<22} | {'EMAIL':<28} | {'ROL':<10} | {'DISP. MOBILE'}")
            print("-" * 80)
            for u in users:
                dev_text = f"{u.devices_count} activo(s)" if u.devices_count > 0 else "0 (sin registrar)"
                print(f" {u.id:<5} | {u.nombre[:20]:<22} | {u.email[:26]:<28} | {str(u.rol):<10} | {dev_text}")
            print(" [ 0 ] | [ ENVIAR A TODOS LOS USUARIOS ]")
            print("-" * 80)

            while True:
                choice = input("\nSeleccione el ID del destinatario [0 para todos]: ").strip()
                try:
                    target_user_id = int(choice)
                    if target_user_id == 0 or any(u.id == target_user_id for u in users):
                        break
                    print("ID no encontrado en la lista. Intente nuevamente.")
                except ValueError:
                    print("Por favor ingrese un numero valido.")

        if not title:
            title = input("Titulo de la notificacion: ").strip()
            if not title:
                title = "Notificacion DrapeMind"

        if not message:
            message = input("Mensaje / Contenido: ").strip()
            if not message:
                message = "Tienes una nueva actualizacion en DrapeMind Atelier."

        if not screen:
            print("\nPantalla de destino al pulsar:")
            print(" 1) Catalogo (/catalog)")
            print(" 2) Chat Inteligente (/chat)")
            print(" 3) Mis Pedidos (/orders)")
            print(" 4) Reservas (/reservations)")
            print(" 5) Notificaciones (/notifications)")
            scr_choice = input("Seleccione una opcion [1-5, por defecto 5]: ").strip()
            scr_map = {
                "1": "/catalog",
                "2": "/chat",
                "3": "/orders",
                "4": "/reservations",
                "5": "/notifications",
            }
            screen = scr_map.get(scr_choice, "/notifications")

        print("\n--------------------------------------------------------")
        print("DESPACHANDO NOTIFICACION...")
        print(f" Destino: {'TODOS LOS USUARIOS' if target_user_id == 0 else f'Usuario ID {target_user_id}'}")
        print(f" Titulo:  {title}")
        print(f" Mensaje: {message}")
        print(f" Ruta:    {screen}")
        print("--------------------------------------------------------")

        if target_user_id == 0:
            count = 0
            for u in users:
                await send_to_user(u.id, title, message, screen, notif_type, tenant_id=u.tenant_id)
                count += 1
            print(f"\n[EXITO] Notificacion despachada a {count} usuarios simultaneamente.")
        else:
            u_match = next((u for u in users if u.id == target_user_id), None)
            if not u_match or not u_match.tenant_id:
                raise ValueError('Selecciona un destinatario que pertenezca a una tienda')
            tid = u_match.tenant_id
            await send_to_user(target_user_id, title, message, screen, notif_type, tenant_id=tid)
            print(f"\n[EXITO] Notificacion enviada correctamente al usuario ID {target_user_id}.")

        print("[CANALES ACTIVADOS]")
        print(" - WebSockets: Enviado en tiempo real a navegadores Web y Mobile conectados.")
        print(" - Base de datos: Persistido en tabla de notificaciones para el badge.")
        print(" - FCM HTTP v1: Despachado a los dispositivos Android vinculados.")
        if sa_path:
            print(" - Nota FCM: Si la API de Google requiere habilitacion, visite:")
            print("   https://console.cloud.google.com/apis/library/fcm.googleapis.com?project=drapemind-5bd6e")
        print("========================================================\n")

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Despachador de notificaciones personalizadas DrapeMind")
    parser.add_argument("--notify", action="store_true", help="Bandera de despacho invocado desde config.sh")
    parser.add_argument("--notification", action="store_true", help="Alias de bandera notify")
    parser.add_argument("--user-id", type=int, default=None, help="ID del usuario destinatario (0 para todos)")
    parser.add_argument("--title", type=str, default=None, help="Titulo de la notificacion")
    parser.add_argument("--message", type=str, default=None, help="Contenido del mensaje")
    parser.add_argument("--screen", type=str, default=None, help="Ruta de pantalla (/catalog, /chat, etc.)")
    parser.add_argument("--type", type=str, default="PROMOTION", help="Tipo de notificacion (GENERAL, PROMOTION, ORDER, CHAT)")

    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
