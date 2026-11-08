"""Standards-based encrypted browser push; signing key remains on the server."""
import base64
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from app.core.config import BACKEND_DIR


def key_path():
    path = Path(os.environ.get('WEB_PUSH_PRIVATE_KEY_PATH', str(BACKEND_DIR / '.runtime' / 'webpush.pem')))
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        data = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
    return path


def public_key():
    key = serialization.load_pem_private_key(key_path().read_bytes(), password=None)
    raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def validate_subscription(subscription):
    # Push providers are an explicit allowlist: never POST credentials to arbitrary client URLs.
    raw = subscription.get('endpoint', '')
    if not isinstance(raw, str) or len(raw) > 4096:
        raise ValueError('Destino de notificaciones no válido')
    endpoint = urlparse(raw)
    allowed = {'fcm.googleapis.com', 'updates.push.services.mozilla.com', 'web.push.apple.com'}
    host = endpoint.hostname or ''
    if endpoint.scheme != 'https' or endpoint.username or endpoint.password or endpoint.port not in (None, 443) or not (host in allowed or host.endswith('.notify.windows.com')):
        raise ValueError('Proveedor de notificaciones no admitido')
    keys = subscription.get('keys', {})
    for name, length in [('p256dh', 65), ('auth', 16)]:
        value = keys.get(name, '')
        if not isinstance(value, str) or len(value) > 200:
            raise ValueError('Claves del navegador no válidas')
        try:
            decoded = base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
        except Exception as exc:
            raise ValueError('Claves del navegador no válidas') from exc
        if len(decoded) != length:
            raise ValueError('Claves del navegador no válidas')
    return {'endpoint': subscription['endpoint'], 'keys': {name: keys[name] for name in ('p256dh', 'auth')}}


def send(subscription, title, body, data):
    from pywebpush import webpush, WebPushException
    try:
        webpush(subscription_info=subscription, data=json.dumps({'title': title, 'body': body, 'data': data}),
                vapid_private_key=str(key_path()), vapid_claims={'sub': 'https://167.86.106.105/DrapeMind/'},
                timeout=10, ttl=86400)
        return {'sent': 1, 'failed': 0, 'invalid': False}
    except WebPushException as exc:
        return {'sent': 0, 'failed': 1, 'invalid': exc.response is not None and exc.response.status_code in (404, 410)}
