from app.models import Branch, City, User
from app.models.saas import Tenant

def receipt_identity(db,order):
    tenant=db.get(Tenant,order.tenant_id)
    branch=db.get(Branch,order.sucursal_id) if order.sucursal_id else None
    city=db.get(City,branch.ciudad_id) if branch else None
    attendant=db.get(User,order.atendido_por_id) if order.atendido_por_id else None
    return {
        'empresa':{'id':tenant.id,'nombre':tenant.name,'slug':tenant.slug,'direccion':tenant.address or '', 'telefono':tenant.phone or '', 'email':tenant.contact_email or ''},
        'sucursal':{'id':branch.id if branch else None,'nombre':branch.nombre if branch else 'Sucursal no registrada','ciudad':city.nombre if city else '', 'direccion':branch.direccion if branch else tenant.address or '', 'telefono':branch.telefono if branch else tenant.phone or ''},
        'atendido_por':{'id':attendant.id,'nombre':attendant.nombre} if attendant else None,
        'comprador_registrado':bool(order.comprador_registrado and order.usuario_id),
    }
