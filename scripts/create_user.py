import argparse
import getpass
import sys
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import Role, User, UserStatus  # noqa: E402


def main() -> None:
    if len(sys.argv) == 1 or "--gui" in sys.argv:
        try:
            from scripts.user_manager_gui import main as run_gui
        except ImportError:
            from user_manager_gui import main as run_gui
        run_gui()
        return

    parser = argparse.ArgumentParser(description="Crea un usuario interno DrapeMind")
    parser.add_argument("--gui", action="store_true", help="Abrir la interfaz grafica interactiva")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", required=True, choices=[Role.ADMIN.value, Role.VENDEDOR.value, Role.CLIENTE.value])
    parser.add_argument("--phone")
    args = parser.parse_args()
    password = getpass.getpass("Contrasena (8-72 caracteres): ")
    confirmation = getpass.getpass("Repetir contrasena: ")
    if password != confirmation or not 8 <= len(password) <= 72:
        raise SystemExit("Las contrasenas no coinciden o no cumplen la longitud")
    with SessionLocal() as db:
        if db.scalar(select(User).where(func.lower(User.email) == args.email.lower())):
            raise SystemExit("El email ya existe")
        db.add(User(
            nombre=args.name, email=args.email.lower(), password_hash=hash_password(password),
            telefono=args.phone, rol=Role(args.role), estado=UserStatus.ACTIVO,
        ))
        db.commit()
    print(f"Usuario {args.role} creado correctamente")


if __name__ == "__main__":
    main()

