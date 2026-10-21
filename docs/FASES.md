# Fases del proyecto

Cada fase tiene una o varias specs en `specs/`. No se empieza una fase sin cerrar la anterior, salvo que se indique lo contrario.

| Fase | Nombre | Estado |
|------|--------|--------|
| 0 | Preparación y stack | Hecha |
| 1 | Datos históricos | Hecha |
| 2 | Gráfico y replay | Hecha |
| 3 | Órdenes y cuenta simulada | Hecha |
| 4 | Simulador de prop firm | Hecha |
| 5 | Backtest de estrategias | Hecha |
| 6 | Diario de operaciones manuales | Pendiente |
| 7 | Pulido | Pendiente |
| 8 | Estudio para vídeos | En curso (spec 010 implementada; falta que la pruebe el usuario) |

---

## Fase 0 · Preparación y stack

**Objetivo:** tener el proyecto montado y el stack decidido.

- Estructura de carpetas y documentación SDD. ✔
- Decidir y registrar el stack (ADR 0001). ✔
- Entorno de desarrollo: Python con entorno virtual, Node si hace falta para el frontend. ✔
- Esqueleto mínimo: un backend que arranca y una página que muestra un gráfico vacío. ✔ (spec 001)

**Hecho cuando:** el esqueleto arranca en local con un solo comando y el ADR del stack está aceptado.

## Fase 1 · Datos históricos

**Objetivo:** tener en disco el histórico de los tres instrumentos, limpio y listo para consultar rápido.

- Descarga desde Dukascopy: `USATECHIDXUSD` (Nasdaq 100), `USA500IDXUSD` (S&P 500) y `XAUUSD` (oro). Últimos 4 años.
- Resolución base de 1 minuto. Valorar ticks más adelante si hace falta precisión intrabar.
- Normalizar zona horaria (UTC al guardar, hora de Nueva York al mostrar) y marcar las sesiones (Asia, Londres, Nueva York).
- Detectar huecos: fines de semana, festivos y datos que falten.
- Almacenamiento en Parquet con consultas mediante DuckDB.
- Agregación a timeframes superiores (5m, 15m, 1h, 4h, 1D) a partir de 1m.

**Hecho cuando:** se puede pedir "NQ, 15m, del 2023-03-01 al 2023-03-31" y se devuelve en menos de un segundo, con huecos documentados.

**Limitación conocida:** Dukascopy da CFDs, no futuros. El precio difiere algo (base) y el volumen es de ticks, no volumen real del CME.

## Fase 2 · Gráfico y replay

**Objetivo:** ver el gráfico y reproducir el mercado como si fuera en vivo.

- Gráfico con TradingView Lightweight Charts.
- Elegir instrumento y fecha de inicio concreta.
- **Botón "Momento aleatorio":** salta a un instante al azar dentro del histórico, solo en horas de mercado abierto. Se carga el contexto previo (las velas anteriores) y el futuro queda oculto. Opción de ocultar la fecha para no condicionarse con lo que se sabe que pasó.
- Avanzar vela a vela, play/pausa y velocidad ajustable.
- **Modo tiempo real:** el replay avanza a velocidad 1x, minuto a minuto como en vivo, para practicar la toma de decisiones con presión de tiempo.
- Cambiar de timeframe durante el replay **sin ver el futuro**: la vela en formación se construye a partir de 1m hasta el instante actual.
- Movimiento dentro del minuto a elegir: real (saltos de 1m) o simulado (spec 003, RF-9).
- Herramientas de dibujo (líneas horizontales, de tendencia y rectángulos) e **indicadores** (EMA/SMA, VWAP, volumen, RSI, ATR, niveles del día anterior y overnight), en la spec 004.

**Hecho cuando:** se puede hacer replay de una sesión completa cambiando entre 1m y 1h sin que aparezca ningún dato posterior al instante del replay, y se puede dibujar y añadir indicadores.

| Spec | Contenido | Estado |
|---|---|---|
| 003 | Replay (reloj, momento aleatorio, velocidades, real/simulado, modo a ciegas) | Hecha |
| 004 | Herramientas de dibujo e indicadores | Hecha |

## Fase 3 · Órdenes y cuenta simulada

**Objetivo:** operar dentro del replay con una cuenta demo realista.

- Órdenes market, limit y stop, con SL/TP y OCO.
- Tamaño en contratos, con los multiplicadores de los futuros reales:
  - NQ $20/punto, MNQ $2/punto
  - ES $50/punto, MES $5/punto
  - GC $100/punto, MGC $10/punto
- Comisiones y slippage configurables.
- Ejecución con datos de 1m. Si SL y TP caen dentro de la misma vela, se resuelve de forma conservadora (cuenta el SL) hasta tener ticks.
- PnL abierto y cerrado y balance de la cuenta.
- **Cartera persistente:** la cuenta conserva su balance y su historial entre sesiones y entre saltos a momentos aleatorios. Así se ve cómo evoluciona la cartera trade tras trade aunque cada trade sea en una fecha distinta.

**Hecho cuando:** un trade manual con SL/TP se ejecuta y liquida igual que lo calcularíamos a mano, comisiones incluidas, y el resultado se refleja en el balance de la cartera.

| Spec | Contenido | Estado |
|---|---|---|
| 005 | Órdenes y cuenta simulada | Hecha |

## Fase 4 · Simulador de prop firm

**Objetivo:** comprobar si se pasaría un reto de prop firm real.

- Perfiles configurables (YAML o JSON) con:
  - Tamaño de cuenta y objetivo de beneficio.
  - Pérdida máxima: estática, trailing intradía o trailing al cierre del día.
  - Límite de pérdida diaria.
  - Regla de consistencia (ningún día puede superar un % del beneficio total).
  - Días mínimos de trading, contratos máximos y hora de cierre obligatoria.
- Primeros perfiles: **Topstep** y **DayTraders**. Se revisarán sus reglas vigentes al empezar la fase, porque cambian a menudo.
- Estado del reto en tiempo real: en curso, aprobado o suspendido, con el motivo.
- Varias cuentas o retos en paralelo e historial de intentos.
- **Decidido (2026-10-16):** cada salto a un momento aleatorio (o a una fecha) es un día del reto.

**Hecho cuando:** un reto se marca como suspendido justo en el momento en que se rompe una regla, con el motivo correcto.

| Spec | Contenido | Estado |
|---|---|---|
| 006 | Perfiles de reto, cuentas de reto, reglas, intentos y resumen de cuentas | Hecha |

## Fase 5 · Backtest de estrategias

**Objetivo:** saber si una estrategia funciona antes de usarla. El usuario la explica, Claude la escribe en Python, se pasa por el histórico y se ve el resultado en números y en el gráfico, operación por operación.

- Estrategias en Python en `estrategias/`, con parámetros que se cambian desde la interfaz.
- Usan el mismo motor de órdenes de la fase 3, con las mismas reglas de ejecución y costes, y nunca ven velas futuras.
- Resultados: % de acierto, beneficio, profit factor, esperanza, R, drawdown, rachas, curva de capital y desglose por año, sesión, día de la semana y lado, con filtros.
- Modo backtest en el gráfico: recorrer las operaciones con su entrada, salida, SL, TP y lo que dibuje la estrategia para explicarse.
- Historial de ejecuciones para comparar parámetros e instrumentos.

**Hecho cuando:** se puede responder "¿qué % de acierto tiene la estrategia X en NQ durante la sesión de NY en 2024?" y ver esas operaciones en el gráfico.

**Cambio de plan (2026-10-16):** era la fase 6 opcional. El usuario aclaró que esto es lo que buscaba con "estrategias", así que pasa a la fase 5 y el diario manual va a la fase 6. Las estrategias las escribe Claude a partir de la explicación del usuario, y el usuario las retoca a mano.

| Spec | Contenido | Estado |
|---|---|---|
| 008 | Backtest de estrategias escritas en Python, resultados y modo backtest en el gráfico | Hecha |
| 009 | Backtest con las reglas de un reto de prop firm: intentos encadenados y % de aprobados | Implementada; falta que la pruebe el usuario |
| 012 | Estrategias EMA pullback y Fibonacci muy parametrizables, y herramienta Fibonacci del gráfico | Implementada; falta que la pruebe el usuario |

## Fase 6 · Diario de operaciones manuales

**Objetivo:** medir el trading manual del replay: etiquetas, notas y capturas en cada operación, y estadísticas con filtros. Se parte del borrador de la spec 007, revisado para que una operación manual pueda llevar una estrategia de `estrategias/` y compararse con su backtest.

| Spec | Contenido | Estado |
|---|---|---|
| 007 | Diario manual: estrategia, etiquetas, notas, capturas y estadísticas | Borrador, por revisar |

- Pasar el backtest por las reglas de un reto de prop firm (fase 4) y comparar el backtest con el trading manual de la misma estrategia también encajan aquí o después de la fase 5.

**Ampliaciones del backtest** (le gustan al usuario, 2026-10-17; sin spec todavía):

- ~~Pasar un backtest por las reglas de un reto de prop firm~~: hecho en la spec 009.
- Optimizar parámetros probando combinaciones, con un periodo de prueba aparte para no engañarse.

## Fase 7 · Pulido

- Atajos de teclado (avanzar vela, comprar/vender, cerrar posición).
- Exportar trades a CSV.
- Guardar y retomar sesiones de replay.
- Lo que haya salido por el camino.

## Fase 8 · Estudio para vídeos

**Objetivo:** que el canal de YouTube del usuario (proyecto `Canal Trading`) pueda generar gráficos didácticos exactos y anotados, reales o inventados, y capturarlos en vídeo sin intervención. Va **en paralelo** a las fases 6 y 7: no depende de ellas.

- Página `/estudio`, separada del replay, que reproduce una escena descrita en JSON con un reloj determinista.
- Captura en PNG y MP4, 16:9 y 9:16, en modo limpio y en inglés.
- Pincel y grabación de trazos para dibujar a mano.
- Después (spec 011): widgets didácticos que no son velas (libro de órdenes, tamaño de posición, curva de capital).

**Hecho cuando:** una escena escrita desde un guion del canal se captura en MP4 sin tocar nada a mano y el usuario la da por buena para un vídeo.

| Spec | Contenido | Estado |
|---|---|---|
| 010 | Estudio: escenas en JSON, datos reales (también acciones y ETF de Dukascopy) o inventados, pasos animados, captura y pincel | Implementada; falta que la pruebe el usuario |
| 011 | Widgets del Estudio: cotización, libro de órdenes con órdenes a mercado y comparación de libros | Implementada; falta que la pruebe el usuario |
