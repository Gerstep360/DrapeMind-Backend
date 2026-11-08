# Implementación del segundo parcial

El código específico se encuentra en [app/segundo_parcial](../app/segundo_parcial/README.md), organizado por CU-01 a CU-30. Web usa `src/app/segundo_parcial`; Flutter usa `lib/segundo_parcial`. Cada implementación y contrato específico se identifica por CU. Los servicios técnicos generales y la caja en línea compartida se reutilizan; no se duplican por presentación.

La carpeta académica vigente es `segundo parcial/Documentacion`, con `casos_de_uso/CU-01` a `CU-30`, `modelos_generales` y `verificacion`. El paquete completo está en [Segundo_parcial_CU01_CU30.zip](entregas/Segundo_parcial_CU01_CU30.zip). Contiene PlantUML, SVG, PNG, fichas y diseño de base de datos sin secretos.

La aplicación móvil abre la tienda habitual con navegación de catálogo, Altair, carrito y pedidos, también para personal. La pestaña Negocio presenta gestión según permisos. Las operaciones sin conexión son una capacidad adicional. El checkout comprueba stock por sucursal, conserva su identificador idempotente y ofrece Stripe como pago electrónico. Los 409 legítimos por cambios de inventario siguen siendo validaciones del servidor y se presentan con acciones de recuperación.

Voz de CU-25/CU-29: el cliente graba PCM16 mono a 16 kHz, máximo 60 segundos; `POST /voice/transcribe` valida permisos, propósito y formato, transcribe por NVIDIA y devuelve texto para revisión. Se utiliza `NVIDIA_API_KEY` exclusivamente en el servidor. Valores ASR predeterminados: `NVIDIA_ASR_SERVER=grpc.nvcf.nvidia.com:443`, función `71203149-d3b7-4460-8231-1be2543a1fca`, idioma `multi`. No se requiere instalar un modelo en el teléfono ni almacenar grabaciones.

CU-28 incorpora scikit-learn: Random Forest de 96 árboles comparado con regresión y media móvil mediante validación temporal de siete días. El modelo con menor MAE genera el pronóstico; no se fuerza un algoritmo de mayor complejidad si rinde peor. Los artefactos, receta, huella y resultado se persisten por empresa y alcance en `modelos_demanda`. La consulta reutiliza el modelo vigente y `POST /business-predictions/train` permite volver a entrenar. La migración es `20261108_03`.

Verificación: 280 pruebas generales backend, 60 contratos PostgreSQL, 41 Angular y 70 Flutter; build web de producción y APK VPS correctos. Se verificaron por navegador real voz, checkout, conflicto de stock y persistencia PWA. NVIDIA ASR se probó con audio sintético en español. Las verificaciones de cobro usan sustitutos sin cargos financieros y no equivalen a una certificación de teléfono físico.
