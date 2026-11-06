"""Background jobs own their session; request sessions must never be reopened later."""
async def notify(tenant_id,user_id,title,message,kind,payload):
    from app.db.session import SessionLocal
    from app.services.push_notifications import dispatch_notification
    with SessionLocal(tenant_id=tenant_id) as db:
        await dispatch_notification(db,user_id,title,message,kind,payload)
