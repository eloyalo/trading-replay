# 011 · Plan técnico

Referencia: [spec.md](spec.md)

## Enfoque

Mismo Estudio y misma captura. Si la escena trae `widget`, el backend la valida por su lado (sin velas) y el frontend oculta el gráfico y pinta el widget en la capa de dibujo. El cálculo de la orden (qué se ejecuta y qué queda en cada nivel en el instante t) es una función pura en `estudio_calculos.js`, con tests en Node; el backend repite solo la comprobación de que la orden cabe en el libro.

| Archivo | Cambio |
|---|---|
| `estudio/escena.py` | `preparar()` acepta `widget`: valida tipo, niveles, pasos `orden`/`foco`/`ocultar` |
| `frontend/estudio_calculos.js` | `ejecutar(libro, lado, cantidad)` y `libroEn(widget, pasos, t)` |
| `frontend/estudio.js` | Sin gráfico cuando hay widget; dibujo de cotización, libro y comparación |
| `tests/` | Validación en Python, cálculo de órdenes en Node |

**Decidido por Claude:** con varias órdenes, cada una parte del libro que dejó la anterior; las asks se pintan de mayor a menor precio (la mejor abajo, junto al spread), como en cualquier plataforma; la cantidad de cada nivel se muestra como número y como barra; la barra de los niveles consumidos se vacía de izquierda a derecha.
