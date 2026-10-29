"""Funciones comunes de los contratos idempotentes del incremento."""
from hashlib import sha256
import json


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
