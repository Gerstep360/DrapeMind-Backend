"""
DrapeMind - Acceso directo a DB & User Manager GUI
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

try:
    from scripts.db.db_manager_gui import DrapeMindDBManager, main
except ImportError:
    from .db_manager_gui import DrapeMindDBManager, main

if __name__ == "__main__":
    main()

