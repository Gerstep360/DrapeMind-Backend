from fastapi import APIRouter

router = APIRouter()
from app.segundo_parcial.compartido.voz import router as voz_router

router.include_router(voz_router)
from app.segundo_parcial.cu11_proveedores.cu11_api import router as proveedores_router
from app.segundo_parcial.cu20_cambios.cu20_api import router as cambios_router

router.include_router(proveedores_router)
router.include_router(cambios_router)
from app.segundo_parcial.cu01_empresas.cu01_api import router as r0

router.include_router(r0)
from app.segundo_parcial.cu02_planes.cu02_api import router as r1

router.include_router(r1)
from app.segundo_parcial.cu03_suscripciones.cu03_api import router as r2

router.include_router(r2)
from app.segundo_parcial.cu04_plan_empresa.cu04_api import router as r3

router.include_router(r3)
from app.segundo_parcial.cu05_acceso.cu05_api import router as r4

router.include_router(r4)
from app.segundo_parcial.cu12_descarga_offline.cu12_api import router as r5

router.include_router(r5)
from app.segundo_parcial.cu14_reservas_offline.cu14_api import router as r6

router.include_router(r6)
from app.segundo_parcial.cu16_operaciones_pendientes.cu16_api import router as r7

router.include_router(r7)
from app.segundo_parcial.cu17_sincronizacion.cu17_api import router as r8

router.include_router(r8)
from app.segundo_parcial.cu18_conflictos.cu18_api import router as r9

router.include_router(r9)
from app.segundo_parcial.cu19_atencion_reservas.cu19_api import router as r10

router.include_router(r10)
from app.segundo_parcial.cu21_comprobantes.cu21_api import router as r11

router.include_router(r11)
from app.segundo_parcial.cu22_carrito_checkout.cu22_api import router as r12

router.include_router(r12)
from app.segundo_parcial.cu25_reportes_voz.cu25_api import router as r13

router.include_router(r13)
from app.segundo_parcial.cu26_exportar_reportes.cu26_pdf import router as r14

router.include_router(r14)
from app.segundo_parcial.cu26_exportar_reportes.cu26_api import router as r15

router.include_router(r15)
from app.segundo_parcial.cu27_dashboard.cu27_api import router as r16

router.include_router(r16)
from app.segundo_parcial.cu28_machine_learning.cu28_api import router as r17

router.include_router(r17)
from app.segundo_parcial.cu30_vestidor.cu30_api import router as r18

router.include_router(r18)
