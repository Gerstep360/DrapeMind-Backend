from sqlalchemy import text
from app.db.session import engine

with engine.begin() as conn:
    conn.execute(text("ALTER TABLE pedidos DROP CONSTRAINT IF EXISTS pedidos_direccion_entrega_snapshot_check;"))
    conn.execute(text("ALTER TABLE pedidos ADD CONSTRAINT pedidos_direccion_entrega_snapshot_check CHECK (direccion_entrega_snapshot IS NULL OR jsonb_typeof(direccion_entrega_snapshot) IN ('object', 'null'));"))

print("Constraint successfully updated!")
