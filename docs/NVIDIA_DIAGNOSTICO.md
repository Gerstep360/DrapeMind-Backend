# Diagnostico NVIDIA: modelo y credenciales

Comprobado el 6 de noviembre de 2026 desde el VPS contra el mismo endpoint de NVIDIA.

| Credencial | Nemotron 3 Super | Nemotron 3.5 Bolt E4B |
|---|---|---|
| Existente | HTTP 404 | HTTP 200 |
| Alternativa proporcionada | HTTP 404 | HTTP 200 |

El error del modelo anterior era `Not found for account`. El listado de modelos devolvia 200 y contenia el modelo, pero eso no acreditaba acceso a su ejecucion. Las pruebas cruzadas descartan un bloqueo general de la clave: la misma credencial ejecuta Bolt. No se afirma una causa interna del despliegue de NVIDIA que el proveedor no haya confirmado.

Se configura `nvidia/nemotron-3.5-bolt-e4b` tanto localmente como en el VPS. Se conserva la clave existente. El nuevo valor se incluye en la configuracion predeterminada y en las plantillas del instalador; las credenciales siguen fuera de Git.

Verificaciones reales: herramientas nativas con retorno de resultados, streaming de contenido publico y JSON para reportes. La comprobacion autenticada de la API devolvio estado saludable. En la tienda sin productos, Altair consulto search_products y no genero prendas ni precios ficticios. Pruebas automatizadas relacionadas: 19 aprobadas.

Referencia del protocolo: https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3_5-bolt-e4b-infer
