from app.models.entities import (
    AIInteraction, AIRecommendation, AISession, Address, Branch, BranchStaff,
    BranchStock, Cart, CartItem, Category, City, Favorite, Gender, InventoryMovement,
    Order, OrderItem, Payment, Product, ProductVariant, Promotion, Reservation,
    ReservationItem, Role, Season, Supplier, SupplierProduct, User, UserDevice,
    Notification, UserStatus, UserStyleProfile,
)

__all__ = [
    "User", "Role", "UserStatus", "Gender", "Address", "City", "Branch", "BranchStaff",
    "BranchStock", "Category", "Product", "ProductVariant", "Favorite", "Cart",
    "CartItem", "Reservation", "ReservationItem", "Order",
    "OrderItem", "Payment", "InventoryMovement", "AISession", "AIInteraction",
    "AIRecommendation", "UserStyleProfile", "Supplier", "Promotion", "Season",
    "SupplierProduct", "UserDevice", "Notification",
]


from app.models.saas import Tenant, SaaSPlan, TenantSubscription, BillingEvent, CheckoutAttempt, tenant_metadata_constraints
from sqlalchemy import UniqueConstraint
User.__table__.append_constraint(UniqueConstraint("tenant_id", "email", name="uq_usuarios_tenant_email"))
Branch.__table__.append_constraint(UniqueConstraint("tenant_id", "codigo", name="uq_sucursales_tenant_codigo"))
Category.__table__.append_constraint(UniqueConstraint("tenant_id", "slug", name="uq_categorias_tenant_slug"))
ProductVariant.__table__.append_constraint(UniqueConstraint("tenant_id", "sku", name="uq_variantes_tenant_sku"))
ProductVariant.__table__.append_constraint(UniqueConstraint("tenant_id", "codigo_barras", name="uq_variantes_tenant_barcode"))
from app.db.base import Base
from app.incrementos.incremento_ii.models import SupplyOrder, SupplyOrderItem, OfflineReservationReceipt
tenant_metadata_constraints(Base.metadata)

Promotion.__table__.append_constraint(UniqueConstraint("tenant_id", "codigo", name="uq_promociones_tenant_codigo"))

Season.__table__.append_constraint(UniqueConstraint("tenant_id", "codigo", name="uq_temporadas_tenant_codigo"))

from app.models.saas import SaaSPrice
from sqlalchemy import Index, CheckConstraint
Index("uq_platform_email",User.email,unique=True,postgresql_where=User.tenant_id.is_(None),sqlite_where=User.tenant_id.is_(None))
User.__table__.append_constraint(CheckConstraint("tenant_id IS NOT NULL OR is_platform_admin",name="ck_user_has_company"))
