# Fases del proyecto

Cada fase tiene una o varias specs en `specs/`. No se empieza una fase sin cerrar la anterior, salvo que se indique lo contrario.

| Fase | Nombre | Estado |
|------|--------|--------|
| 0 | Preparación y stack | Hecha |
| 1 | Datos históricos | Hecha |
| 2 | Gráfico y replay | Hecha |
| 3 | Órdenes y cuenta simulada | Hecha |
| 4 | Simulador de prop firm | Implementada, en revisión |
| 5 | Diario y estadísticas | Pendiente |
| 6 | Backtest automático de estrategias (opcional) | Pendiente |
| 7 | Pulido | Pendiente |

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
| 006 | Perfiles de reto, cuentas de reto, reglas, intentos y resumen de cuentas | Implementada, en revisión |

## Fase 5 · Diario y estadísticas

**Objetivo:** medir qué funciona y qué no.

- Cada trade se puede etiquetar con estrategia y setup, y se le pueden añadir notas y una captura del gráfico.
- Métricas: % de acierto, R medio, esperanza matemática, profit factor, drawdown máximo y rachas.
- Filtros por estrategia, instrumento, sesión, día de la semana y periodo.
- Curva de capital.

**Hecho cuando:** se puede responder "¿qué % de acierto tiene mi estrategia X en NQ durante la sesión de NY en 2024?".

## Fase 6 · Backtest automático (opcional)

**Objetivo:** probar estrategias definidas por reglas sin operar a mano.

- Estrategias escritas en Python que usan el mismo motor de órdenes de la fase 3.
- Se ejecutan sobre el histórico, pueden pasar por los perfiles de prop firm de la fase 4 y generan las estadísticas de la fase 5.
- Comparar los resultados del backtest con los del trading manual de la misma estrategia.

## Fase 7 · Pulido

- Atajos de teclado (avanzar vela, comprar/vender, cerrar posición).
- Exportar trades a CSV.
- Guardar y retomar sesiones de replay.
- Lo que haya salido por el camino.
