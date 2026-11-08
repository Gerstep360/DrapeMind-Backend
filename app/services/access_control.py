"""Tenant-scoped capabilities layered over branch rules and subscription limits."""
from sqlalchemy import select
from app.models.entities import Role

# Stable capability identifiers shared by API, UI and tool execution.
PERMISSIONS = {
    'catalog.read': ('Catálogo', 'Consultar prendas y disponibilidad'),
    'catalog.manage': ('Catálogo', 'Crear y editar prendas, variantes y categorías'),
    'inventory.manage': ('Inventario', 'Registrar y ajustar existencias'),
    'branches.manage': ('Sucursales', 'Administrar ciudades y sucursales'),
    'pricing.manage': ('Precios', 'Administrar precios y promociones'),
    'suppliers.manage': ('Abastecimiento', 'Administrar proveedores y abastecimiento'),
    'sales.manage': ('Caja', 'Registrar ventas de contado'),
    'orders.manage': ('Pedidos', 'Atender pedidos y entregas'),
    'reservations.manage': ('Reservas', 'Preparar y cobrar reservas'),
    'exchanges.manage': ('Cambios', 'Gestionar cambios de prendas'),
    'sync.review': ('Sincronización', 'Resolver conflictos y rechazos'),
    'offline.use': ('Sin conexión', 'Descargar y sincronizar operaciones permitidas'),
    'reports.view': ('Reportes', 'Consultar indicadores y reportes'),
    'reports.ai': ('Reportes', 'Generar reportes con IA'),
    'notifications.manage': ('Notificaciones', 'Enviar avisos a clientes de la tienda'),
    'team.manage': ('Equipo', 'Gestionar usuarios, roles y permisos'),
}
CLIENT = {'catalog.read', 'offline.use'}
STAFF = CLIENT | {'sales.manage', 'orders.manage', 'reservations.manage', 'exchanges.manage'}
DEFAULTS = {
    Role.ADMIN: set(PERMISSIONS), Role.CLIENTE: CLIENT,
    Role.CAJERO: STAFF, Role.VENDEDOR: STAFF | {'catalog.manage', 'inventory.manage', 'pricing.manage'},
    Role.ENCARGADO: STAFF | {'inventory.manage', 'sync.review'},
    Role.PROVEEDOR: {'catalog.read', 'suppliers.manage'},
}


def permission_for(path, method, user=None):
    path = path.removeprefix('/api/v1')
    if user is not None and user.rol != Role.CLIENTE:
        if path.startswith('/orders'):
            return 'orders.manage'
        if path.startswith('/reservations'):
            return 'reservations.manage'
    if path == '/team/me':
        return None
    if path.startswith(('/team', '/admin/users')):
        return 'team.manage'
    if path.startswith('/admin/customers'):
        return 'sales.manage'
    if path.startswith(('/admin/products', '/admin/categories', '/admin/variants', '/admin/seasons', '/admin/collections', '/ar/products')):
        return 'catalog.manage' if method != 'GET' or path.startswith('/admin/') else 'catalog.read'
    if path.startswith(('/admin/cities', '/admin/branches')):
        return 'branches.manage'
    if path.startswith(('/admin/inventory', '/admin/stock', '/admin/movements', '/admin/branch-stock')):
        return 'inventory.manage'
    if path.startswith(('/admin/promotions', '/admin/prices')):
        return 'pricing.manage'
    if path.startswith(('/supply', '/admin/suppliers')):
        return 'suppliers.manage'
    if path.startswith('/branches/') and path.endswith('/staff'):
        return 'team.manage'
    if path.startswith('/branches/') and path.endswith(('/stock', '/movements')):
        return 'inventory.manage'
    if path.startswith('/branches') and method != 'GET':
        return 'branches.manage'
    if path.startswith('/branches/cities'):
        return 'branches.manage'
    if path.startswith('/admin/ai/'):
        return 'reports.view'
    if path.startswith(('/ai/product', '/ai/studio/product')):
        return 'catalog.manage'
    if path.startswith('/ai/reports'):
        return 'reports.ai'
    if path.startswith('/retail/exchanges'):
        return 'exchanges.manage'
    if path.startswith('/retail/orders/find'):
        return 'exchanges.manage'
    if path.startswith('/retail/reservations') or path.startswith('/admin/reservations'):
        return 'reservations.manage'
    if path.startswith(('/retail/conflicts', '/retail/operations')):
        return 'sync.review'
    if path.startswith('/admin/sales/history'):
        return 'reports.view'
    if path.startswith(('/admin/sales', '/admin/pos')):
        return 'sales.manage'
    if path.startswith('/admin/orders') or (path.startswith('/orders/') and path.endswith('/status')):
        return 'orders.manage'
    if path.startswith('/offline'):
        return 'offline.use'
    if path.startswith(('/business-dashboard', '/business-predictions', '/admin/dashboard', '/admin/metrics', '/admin/sales/history')):
        return 'reports.view'
    if path.startswith('/business-reports'):
        return 'reports.ai' if method == 'POST' else 'reports.view'
    if path.startswith(('/notifications/send', '/notifications/broadcast')):
        return 'notifications.manage'
    if path.startswith(('/catalog', '/branches')):
        return 'catalog.read'
    return None


TOOL_PERMISSIONS = {
    'get_business_indicators': 'reports.view', 'get_demand_predictions': 'reports.view',
    'get_saved_business_reports': 'reports.view', 'get_suppliers': 'suppliers.manage',
    'get_supply_orders': 'suppliers.manage',
}


def tool_allowed(tool, user, db=None):
    if user is None:
        return not tool.allowed_roles
    from sqlalchemy.orm import object_session
    from app.models import User
    if isinstance(user, User):
        access = effective_access(db or object_session(user), user)
        permission = TOOL_PERMISSIONS.get(tool.name, 'catalog.read')
        if access['configured'] and permission not in access['permissions']:
            return False
    return not tool.allowed_roles or getattr(user, 'rol', None) in tool.allowed_roles


def effective_access(db, user):
    from app.models.access import UserAccess, TenantRole
    baseline = set(DEFAULTS.get(user.rol, ()))
    if user.rol == Role.ADMIN:
        return {'permissions': sorted(baseline), 'configured': False, 'role': None, 'overrides': {}}
    if db is None:
        return {'permissions': sorted(baseline), 'configured': False, 'role': None, 'overrides': {}}
    cache = db.info.setdefault('effective_access', {})
    if user.id in cache:
        return cache[user.id]
    row = db.scalar(select(UserAccess).where(UserAccess.usuario_id == user.id))
    role = db.get(TenantRole, row.rol_empresa_id) if row and row.rol_empresa_id else None
    if role:
        baseline = set(role.permisos) if role.activo else set()
    overrides = row.overrides if row else {}
    if not role or role.activo:
        baseline.update(key for key, value in overrides.items() if value is True)
        baseline.difference_update(key for key, value in overrides.items() if value is False)
    baseline.discard('team.manage')
    result = {'permissions': sorted(baseline & PERMISSIONS.keys()), 'configured': row is not None,
              'role': {'id': role.id, 'nombre': role.nombre, 'activo': role.activo} if role else None,
              'overrides': overrides}
    cache[user.id] = result
    return result
