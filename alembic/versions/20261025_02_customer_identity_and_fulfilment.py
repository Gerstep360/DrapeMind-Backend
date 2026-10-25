"""Personal customer identity, merchant contact and branch fulfilment."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision='20261025_02'
down_revision='20261025_01'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('customer_accounts',sa.Column('id',sa.BigInteger(),primary_key=True),sa.Column('email',pg.CITEXT(),nullable=False,unique=True),sa.Column('password_hash',sa.String(255),nullable=False),sa.Column('name',sa.String(120),nullable=False),sa.Column('phone',sa.String(30)),sa.Column('active',sa.Boolean(),nullable=False,server_default=sa.true()),sa.Column('personal_data',pg.JSONB(),nullable=False,server_default='{}'))
    op.add_column('usuarios',sa.Column('customer_account_id',sa.BigInteger(),sa.ForeignKey('customer_accounts.id')))
    op.create_index('ix_usuarios_customer_account_id','usuarios',['customer_account_id'])
    op.create_unique_constraint('uq_customer_store_membership','usuarios',['tenant_id','customer_account_id'])
    for name,length in [('address',250),('phone',30),('contact_email',150)]:
        op.add_column('saas_tenants',sa.Column(name,sa.String(length)))
    op.alter_column('pedidos','usuario_id',nullable=True)
    op.add_column('pedidos',sa.Column('atendido_por_id',sa.BigInteger()))
    op.create_foreign_key('fk_pedidos_atendido_por_id_tenant','pedidos','usuarios',['atendido_por_id','tenant_id'],['id','tenant_id'])
    op.add_column('pedidos',sa.Column('comprador_registrado',sa.Boolean(),nullable=False,server_default=sa.true()))
    # An old POS ticket identifies the employee in usuario_id. Never label them
    # a buyer; preserve that employee as the attendant and mark an anonymous sale.
    op.execute("SELECT set_config('app.saas_system','true',true)")
    op.execute("UPDATE pedidos p SET atendido_por_id=p.usuario_id, usuario_id=NULL, comprador_registrado=false FROM usuarios u WHERE p.usuario_id=u.id AND p.canal='TIENDA' AND p.reserva_id IS NULL AND u.rol<>'CLIENTE' AND p.observacion LIKE 'Venta en mostrador / POS%'")

def downgrade():
    raise RuntimeError('La identidad de clientes y los compradores no registrados requieren restaurar un respaldo para volver atrás sin perder datos.')
