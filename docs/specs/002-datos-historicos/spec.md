# 002 · Datos históricos

- **Estado:** Hecha (2026-10-15)
- **Fase:** 1
- **Creada:** 2026-10-15 · **Actualizada:** 2026-10-15

## Problema

El replay, las órdenes y las estadísticas necesitan el histórico de los tres instrumentos guardado en local, limpio y rápido de consultar a cualquier timeframe.

## Alcance

**Incluye:**
- Descarga desde Dukascopy de velas de 1 minuto de los últimos 4 años (desde el 2022-10-15).
- Comando para actualizar después solo los días nuevos.
- Limpieza: quitar los periodos de mercado cerrado y detectar los huecos.
- Almacenamiento en Parquet.
- Consulta por instrumento, timeframe y rango de fechas.
- Endpoint de la API que devuelve velas, y el gráfico del frontend mostrándolas (sin replay todavía).

**No incluye:**
- Replay ni ocultar el futuro (spec de la fase 2).
- Datos tick.
- Futuros reales del CME.

## Instrumentos

| Nuestro símbolo | Dukascopy | Equivale a | Unidad de precio |
|---|---|---|---|
| `NQ` | `USATECHIDXUSD` | Nasdaq 100 | 0.001 |
| `ES` | `USA500IDXUSD` | S&P 500 | 0.001 |
| `GC` | `XAUUSD` | Oro | 0.001 |

En toda la app usamos los nombres de los futuros (NQ, ES, GC), aunque los datos sean de CFD.

## Requisitos

1. **RF-1 · Descarga.** El comando `uv run trading-replay datos descargar` baja los 4 años de los tres instrumentos. Si se corta, al relanzarlo continúa por donde iba y no repite lo que ya tiene. Muestra el progreso y no satura a Dukascopy: como mucho 8 peticiones a la vez y reintentos con espera si falla.
2. **RF-2 · Actualización.** Al relanzar el mismo comando más adelante, solo baja los días que falten hasta ayer.
3. **RF-3 · Precio BID.** Se descarga solo el precio BID. El spread se simulará en la fase 3 con un valor configurable parecido al de los futuros (por defecto 1 tick), porque el spread del CFD no se parece al del futuro.
4. **RF-4 · Mercado cerrado.** Dukascopy rellena los periodos cerrados con velas planas de volumen 0. Esas velas se descartan, para que en el gráfico no aparezcan tramos planos los fines de semana ni en la pausa diaria.
5. **RF-5 · Huecos.** Se genera un informe por instrumento con los huecos de más de 15 minutos dentro de horario de mercado (festivos, cortes, datos ausentes). *Cambiado de 5 a 15 minutos el 2026-10-15: los CFD tienen minutos sueltos sin cotizaciones, sobre todo justo después de la reapertura de las 18:00, que llenarían el informe de ruido.*
6. **RF-6 · Zona horaria.** Las horas se guardan en UTC. La API y el gráfico muestran la hora de Nueva York (ET), con el cambio de horario de verano bien aplicado.
7. **RF-7 · Timeframes.** Se puede consultar en 1m, 5m, 15m, 30m, 1h, 4h y 1D, siempre agregando a partir de 1m.
8. **RF-8 · Día de trading.** Las velas diarias y de 4h siguen la sesión de los futuros del CME, no el día natural: el día de trading empieza a las 18:00 ET de la víspera. Las de 4h se alinean a las 18:00 ET.
9. **RF-9 · Sesiones.** Cada vela de 1m se etiqueta con su sesión: Asia (18:00 a 03:00 ET), Londres (03:00 a 09:30 ET) o Nueva York (09:30 a 17:00 ET). Servirá para los filtros de estadísticas de la fase 5.
10. **RF-10 · API.** `GET /api/velas?simbolo=NQ&tf=15m&desde=...&hasta=...` devuelve las velas en el formato que usa Lightweight Charts.
11. **RF-11 · Gráfico.** El frontend permite elegir instrumento y timeframe y muestra el histórico (por defecto, el último mes), con zoom y desplazamiento.

## Criterios de aceptación

- [ ] Tras ejecutar la descarga hay 4 años de los tres instrumentos en `datos/`, y relanzarla no vuelve a descargar nada. *(falta 1 día, GC 2022-10-20, que da 503 de forma persistente; se reintenta en cada actualización)*
- [x] Si corto la descarga a mitad y la relanzo, termina sin duplicados.
- [x] Pedir `NQ`, `15m`, del 2023-03-01 al 2023-03-31 tarda menos de 1 s. *(44 ms)*
- [x] Una vela diaria de NQ coincide en apertura y cierre con la sesión que empieza a las 18:00 ET (comprobado a mano con un día concreto). El cierre es el de las 16:14 ET, porque el CFD deja de cotizar a las 16:15 (ver la nota del final). *(2024-03-12: O 17987.297, H 18228.389, L 17914.443, C 18204.831, iguales a mano y por la API)*
- [x] En el gráfico no aparecen tramos planos en fines de semana. *(0 velas en fin de semana en los tres instrumentos)*
- [x] Existe un informe de huecos por instrumento. *(los mayores son festivos: Navidad, 4 de julio, Viernes Santo, Año Nuevo)*
- [x] En el navegador se puede cambiar entre NQ, ES y GC y entre timeframes, y se ven las velas. *(confirmado por el usuario)*

## Dudas

- Ninguna abierta. Datos de una prueba real del 2026-10-15:
  - Cada día es un archivo LZMA con 1.440 velas de 24 bytes (tiempo, apertura, cierre, mínimo, máximo y volumen).
  - Los precios cuadran con los niveles reales del 2024-03-12 (NQ 18.030, ES 5.132, oro 2.183).
  - En la URL, los meses empiezan en 0.
  - Cada petición tarda de 1 a 3,5 s. Con 8 en paralelo, la descarga completa (unos 4.400 archivos) debería llevar entre 30 y 60 minutos.
  - Ocupará menos de 300 MB.

## Limitación descubierta al implementar

Los CFD de índices de Dukascopy (NQ y ES) dejan de cotizar a las **16:15 ET** y reabren a las 18:00. Los futuros reales cotizan hasta las 17:00, así que en NQ y ES falta el tramo de 16:15 a 17:00 ET. El oro (GC) sí cierra a las 17:00, igual que el futuro. El horario de cada instrumento está en `config.py` (`cierre_diario`) y lo usa el informe de huecos.
