from fastapi import APIRouter
from app.segundo_parcial.compartido.indicadores import (
    Date,
    Depends,
    Order,
    Query,
    ReportInput,
    Session,
    User,
    admin,
    cast,
    date,
    datetime,
    facts,
    forecast,
    func,
    get_db,
    require_active_subscription,
    select,
    timedelta,
    timezone,
)
from .cu28_entrenamiento import persisted_forecast

router = APIRouter(prefix="", tags=["CU-28 · machine_learning"])


@router.get("/business-predictions")
def predictions(
    sucursal_id: int | None = Query(None, gt=0),
    user: User = Depends(admin),
    db: Session = Depends(get_db),
    force: bool = False,
):
    require_active_subscription(db, user.tenant_id)
    # Validate branch ownership using the same server-side scope as dashboard.
    scope = facts(
        db, ReportInput(consulta="Predicción de pedidos", sucursal_id=sucursal_id), user
    )
    today = datetime.now(timezone.utc).date()
    filters = [
        Order.paid_at.is_not(None),
        Order.estado != "CANCELADO",
        Order.paid_at
        < datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
    ]
    if sucursal_id:
        filters.append(Order.sucursal_id == sucursal_id)
    first = db.scalar(select(func.min(Order.paid_at)).where(*filters))
    if first is None:
        return {
            **forecast([], today),
            "empresa": scope["empresa"],
            "sucursal": scope["sucursal"],
        }
    first_utc = (
        first.replace(tzinfo=timezone.utc)
        if first.tzinfo is None
        else first.astimezone(timezone.utc)
    )
    start = max(first_utc.date(), today - timedelta(days=180))
    filters.append(
        Order.paid_at
        >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    )
    day = (
        cast(func.timezone("UTC", Order.paid_at), Date)
        if db.bind.dialect.name == "postgresql"
        else func.date(Order.paid_at)
    )
    rows = db.execute(
        select(day, func.count(Order.id)).where(*filters).group_by(day)
    ).all()
    counts = {
        value if isinstance(value, date) else date.fromisoformat(value): count
        for value, count in rows
    }
    series = [
        counts.get(start + timedelta(days=i), 0) for i in range((today - start).days)
    ]
    return {
        **persisted_forecast(db, user, sucursal_id, series, start, force=force),
        "empresa": scope["empresa"],
        "sucursal": scope["sucursal"],
        "corte": str(today),
        "zona_horaria": "UTC",
    }


@router.post("/business-predictions/train")
def retrain(
    sucursal_id: int | None = Query(None, gt=0),
    user: User = Depends(admin),
    db: Session = Depends(get_db),
):
    return predictions(sucursal_id, user, db, force=True)
