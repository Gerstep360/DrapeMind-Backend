from fastapi import APIRouter
from app.segundo_parcial.compartido.indicadores import (
    Depends,
    Query,
    ReportInput,
    Session,
    User,
    admin,
    datetime,
    facts,
    get_db,
    require_active_subscription,
    timedelta,
    timezone,
)

router = APIRouter(prefix="", tags=["CU-27 · dashboard"])


@router.get("/business-dashboard")
def dashboard(
    days: int = Query(30, ge=1, le=366),
    sucursal_id: int | None = Query(None, gt=0),
    user: User = Depends(admin),
    db: Session = Depends(get_db),
):
    require_active_subscription(db, user.tenant_id)
    today = datetime.now(timezone.utc).date()
    return facts(
        db,
        ReportInput(
            consulta="Indicadores comerciales",
            desde=today - timedelta(days=days - 1),
            hasta=today,
            sucursal_id=sucursal_id,
        ),
        user,
    )
