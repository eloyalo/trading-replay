# 002 · Plan técnico

Referencia: [spec.md](spec.md)

## Enfoque

El proceso tiene dos etapas separadas:

1. **Descarga.** Cada día se guarda tal cual llega de Dukascopy en `datos/crudo/{SIMBOLO}/{AAAA}/{AAAA-MM-DD}.bi5`. Que el archivo exista significa que ese día ya está descargado, y así la descarga se puede reanudar sin más. Se escribe a un temporal y luego se renombra, para que un corte nunca deje un archivo a medias.
2. **Construcción.** A partir de los crudos se genera `datos/velas/{SIMBOLO}.parquet`, con las velas de 1m limpias. Es rápido y se puede rehacer en cualquier momento sin volver a descargar.

Las consultas por timeframe se hacen con DuckDB sobre ese Parquet, agregando al vuelo. No se guardan timeframes precalculados.

## Componentes

| Módulo / archivo | Cambio |
|---|---|
| `trading_replay/config.py` | Rutas (con `TRADING_REPLAY_DATOS` para poder cambiarla en los tests), instrumentos, fecha de inicio y zona horaria |
| `trading_replay/historico/dukascopy.py` | URL de cada día, descarga con reintentos, 8 hilos en paralelo y decodificación de los `.bi5` |
| `trading_replay/historico/almacen.py` | Construcción del Parquet, consulta de velas por timeframe y rango disponible |
| `trading_replay/historico/huecos.py` | Informe de huecos |
| `trading_replay/cli.py` | `trading-replay datos descargar`, `datos construir` y `datos huecos` |
| `trading_replay/app.py` | `GET /api/instrumentos` y `GET /api/velas` |
| `frontend/app.js`, `index.html` | Selector de instrumento y timeframe, y carga de más historia al desplazarse a la izquierda |

## Modelo de datos

`datos/velas/{SIMBOLO}.parquet`, una fila por minuto con mercado abierto:

| Columna | Tipo | Nota |
|---|---|---|
| `ts` | timestamp (UTC) | inicio del minuto |
| `open`, `high`, `low`, `close` | double | ya multiplicados por 0.001 |
| `volume` | double | volumen de ticks de Dukascopy, solo orientativo |
| `sesion` | varchar | `asia`, `londres` o `nueva_york` |

## Decisiones de detalle

- **Días a descargar:** desde el 2022-10-15 hasta ayer (UTC), saltando los sábados, que siempre están cerrados. Si un día de los 3 últimos llega vacío, no se marca como descargado y se reintenta en la próxima actualización.
- **Mercado cerrado:** se descartan las velas con volumen 0 (RF-4).
- **Hora para el gráfico:** Lightweight Charts siempre muestra los timestamps como UTC. La API devuelve `time` como la hora de Nueva York escrita como si fuera UTC, que es el truco habitual con esta librería. No da problemas con los cambios de horario porque ocurren de madrugada en domingo, con el mercado cerrado.
- **Día de trading y 4h (RF-8):** en hora ET se suman 6 horas, se redondea hacia abajo al día o a las 4 horas y se restan las 6 horas. Así los días empiezan a las 18:00 ET y los bloques de 4h caen a las 18, 22, 02, 06, 10 y 14 ET. La vela diaria se etiqueta con la fecha del día de trading.
- **Huecos (RF-5):** se buscan saltos entre velas seguidas y solo se informan si contienen más de 15 minutos de horario abierto del instrumento: de domingo 18:00 a viernes al cierre, sin contar la pausa diaria, que va de `cierre_diario` a 18:00 (16:15 en los índices y 17:00 en el oro). Se guardan en `datos/huecos/{SIMBOLO}.csv`.
- **Rango por defecto en el gráfico:** depende del timeframe para que la carga sea ágil: 1m 3 días, 5m 2 semanas, 15m 1 mes, 30m 2 meses, 1h 3 meses, 4h 1 año y 1D todo. Al desplazarse a la izquierda se carga más.

## Dependencias nuevas

`duckdb`, `pyarrow` y `numpy`. La descarga usa `http.client` de la biblioteca estándar, con una conexión keep-alive por hilo, y un `ThreadPoolExecutor`. Con `urllib` se abría una conexión TLS nueva en cada petición y Dukascopy tardaba más de 10 s en aceptarla: unos 4 s por día de media.

## Riesgos

- Dukascopy puede limitar o cortar las conexiones si recibe muchas peticiones. Se mitiga con 8 hilos como máximo y reintentos con espera creciente.
- El horario de los CFD puede no coincidir exactamente con el del CME. El informe de huecos lo dejará a la vista.

## Cómo se prueba

- Tests unitarios: decodificar un `.bi5` sintético, agregar a 1D con el corte de las 18:00 ET (también en semanas con cambio de horario), etiquetar sesiones, informe de huecos y endpoints de la API con datos sintéticos.
- Prueba real: descarga completa, medir el tiempo de consulta, comprobar a mano una vela diaria y revisar en el navegador.
