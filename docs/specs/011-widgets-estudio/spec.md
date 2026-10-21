# 011 · Widgets del Estudio: libro de órdenes y cotización

- **Estado:** Implementada (2026-10-18; aprobada por delegación). Falta la revisión visual del usuario
- **Fase:** 8
- **Creada:** 2026-10-18 · **Actualizada:** 2026-10-18

## Problema

Hay conceptos que un gráfico de velas no puede enseñar: cómo se ve la cotización (bid, ask, last), qué hay en el libro de órdenes y qué le pasa cuando llega una orden a mercado. El canal los necesita animados y con números exactos (en L1-01, 9 escenas del vídeo largo y 3 de los Shorts). Esta spec añade al Estudio de la 010 "widgets" con el mismo reloj, la misma captura y la misma sincronía con la voz.

## Alcance

**Incluye:**
- Escenas con `widget` en lugar de `datos`: `cotizacion`, `libro` y `comparar_libros`.
- Pasos de widget: `orden` (compra o venta a mercado que se come el libro nivel a nivel), `foco` (resaltar una parte) y `ocultar`.
- Textos fijos en inglés (`Price`, `Size`, `Spread`, `Last trade`, `Avg fill`...), sustituibles desde la escena.
- 16:9 y 9:16, tema y aviso *Illustrative example* como en la 010.

**No incluye:**
- Órdenes limitadas que entran en el libro, cancelaciones o libros con datos reales (no hay datos de nivel 2).
- Curva de capital y calculadora de tamaño de posición: otra spec cuando un guion las necesite.

## Requisitos

1. **RF-1 · Cotización.** `{"tipo": "cotizacion", "simbolo", "bid", "ask", "last"}`: tres cajas grandes (Bid, Ask, Last). `foco` con `zona` `bid`, `ask` o `last` la resalta.
2. **RF-2 · Libro.** `{"tipo": "libro", "simbolo", "asks": [[precio, cantidad], ...], "bids": [...]}`: escalera con las asks en rojo arriba (la mejor junto al centro), las bids en verde abajo, una barra por nivel proporcional a la cantidad y el spread entre las dos.
3. **RF-3 · Orden a mercado.** Paso `orden` con `lado` (`compra`/`venta`), `cantidad` y `duracion`: va consumiendo los niveles desde el mejor precio, en proporción a lo que hay en cada uno. Se ven las ejecuciones (`200 @ 50.01`), el último precio (*Last trade*) y el precio medio (*Avg fill*). Con `duracion: 0`, el libro empieza ya ejecutado (para seguir desde la escena anterior).
4. **RF-4 · Foco en el libro.** `zona`: `lados` (asks y bids), `spread`, `creador` (resalta la mejor bid y la mejor ask como cotización de un creador de mercado, con una etiqueta) o `bid`/`ask`/`last` en la cotización.
5. **RF-5 · Comparar libros.** `{"tipo": "comparar_libros", "izquierda": {titulo, asks, bids}, "derecha": {...}}`: dos libros lado a lado (por defecto *Deep book* y *Thin book*).
6. **RF-6 · Validación.** Precios positivos, asks por encima de las bids, cantidades enteras positivas, una orden no puede pedir más de lo que hay en el libro; errores con el paso.
7. **RF-7 · Determinista.** Como en la 010: el estado en `t` sale solo de la escena y de `t`.

## Criterios de aceptación

- [x] La compra de 900 en el libro de L1-01 ejecuta 200 @ 50,01, 500 @ 50,02 y 200 @ 50,03, con último 50,03 y medio 50,02 (test).
- [x] La venta de 700 ejecuta 400 @ 50,00 y 300 @ 49,99, con último 49,99 (test).
- [x] A mitad de una orden, el nivel en curso aparece parcialmente consumido y el estado no depende del orden en que se pidan los instantes (test).
- [x] Una orden mayor que el libro se rechaza con un mensaje que nombra el paso (test).
- [ ] Las escenas de libro y cotización de L1-01 se capturan en MP4 sincronizadas con la voz y se leen bien en 16:9 y 9:16 (revisión).
