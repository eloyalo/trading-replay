# 010 · Plan técnico

Referencia: [spec.md](spec.md)

## Enfoque

El Estudio es una página estática más (`frontend/estudio.html`) con su propio script. **No reutiliza `app.js`**, que está atado al estado global del replay, pero sí `calculos.js` (indicadores) y Lightweight Charts. El backend añade un paquete `estudio/` que valida la escena y resuelve sus datos. La página recibe la escena ya validada, con las velas dentro y los tiempos convertidos a segundos, y solo pinta.

```
escena.json ──► POST /api/estudio/preparar ──► {escena normalizada, velas}
                (valida y resuelve los datos)          │
                                                       ▼
                                   estudio.js: cargar() → ir(t) → pinta el instante t
                                                       ▲
trading-replay estudio capturar ── Chrome sin interfaz (CDP) ── ir(t) + captura por fotograma ──► ffmpeg ──► MP4
```

## Componentes afectados

| Módulo / archivo | Cambio |
|---|---|
| `backend/trading_replay/estudio/acciones.py` | Nuevo. Acciones y ETF de Dukascopy bajo demanda (RF-4): diario por año y 1m por día, caché en `datos/estudio/<SÍMBOLO>/`, splits, agregación a cualquier timeframe y hora ET. |
| `backend/trading_replay/estudio/escena.py` | Nuevo. Validación (RF-6) y resolución: tiempos ET → segundos, datos reales de NQ/ES/GC con `almacen.consultar` (sin recorte del replay), acciones, velas escritas a mano y aportadas. |
| `backend/trading_replay/estudio/captura.py` | Nuevo. Servidor propio en un puerto libre, Chrome sin interfaz, protocolo de DevTools con `websockets` (ya instalado con uvicorn) y ffmpeg por tubería. |
| `backend/trading_replay/app.py` | `POST /api/estudio/preparar`. |
| `backend/trading_replay/cli.py` | `trading-replay estudio validar|capturar`. |
| `frontend/estudio.html`, `estudio.css` | Nuevos. Página con la barra (cargar, play, línea de tiempo, pincel) y el lienzo de tamaño fijo. |
| `frontend/estudio_calculos.js` | Nuevo. Funciones puras: progreso de un paso, suavizado, vela en formación, cámara. Se prueban en Node. |
| `frontend/estudio.js` | Nuevo. Gráfico, primitiva que pinta los pasos, `window.estudio` (RF-7) y modo manual (RF-12 a RF-14). |
| `pyproject.toml` | `websockets` como dependencia explícita (ya venía con `uvicorn[standard]`). |

## Modelo de datos

### Escena (entrada, `formato: 1`)

```json
{
  "formato": 1,
  "lienzo": { "aspecto": "16:9", "tema": { "fondo": "#0b1630", "...": "..." },
              "logo_tradingview": false, "eje_tiempo": true, "ilustrativo": false },
  "datos": { "tipo": "real", "instrumento": "NQ", "tf": "15m", "desde": "2024-03-08 09:30", "hasta": "2024-03-08 16:00" },
  "vista": { "desde": "2024-03-08 09:30", "hasta": "2024-03-08 13:00", "precio": [18100, 18300] },
  "indicadores": [{ "tipo": "ema", "periodo": 20 }],
  "pasos": [ { "id": "r1", "t": 4.5, "accion": "horizontal", "precio": 18240, "etiqueta": "Resistance", "duracion": 0.8 } ]
}
```

- `datos.tipo`: `real` (NQ, ES, GC o una acción o ETF), `manual` (`velas: [[o, h, l, c], ...]` o `[[o, h, l, c, v], ...]`) o `aportadas` (`simbolo` + `velas: [[tiempo, o, h, l, c, v?], ...]`).
- Velas `manual`: tiempos ficticios de un día por vela, desde el lunes 2001-01-01 y sin fines de semana. Por defecto `eje_tiempo: false` e `ilustrativo: true`.
- Tiempos de la escena (`desde`, `hasta`, puntos de los dibujos): texto ET `AAAA-MM-DD HH:MM`, o un índice de vela entero (`5` = la sexta vela), que es lo cómodo con velas inventadas.
- `duracion` de la escena: el mayor `t + duracion` de los pasos más 1 s, o `escena.duracion` si viene.

### Escena normalizada (salida de `preparar`)

La misma estructura con todos los tiempos en segundos "ET como UTC" (como `time` de las velas), `velas` resueltas, `simbolo`, `duracion` calculada y los pasos ordenados por `t`.

### Caché de acciones

`datos/estudio/<SÍMBOLO>/<año>.dia.bi5` y `datos/estudio/<SÍMBOLO>/<año>/<AAAA-MM-DD>.bi5`. Un año en curso o un día de hace menos de 3 días se vuelve a pedir pasadas 12 horas. Splits en `estudio/acciones.py` (`SPLITS`), editables.

## Decisiones (decididas por Claude)

- **Dibujar en un `<canvas>` encima del gráfico**, no con una primitiva de Lightweight Charts. Así cada fotograma pinta todo a partir de `t` sin depender del ciclo de repintado de la librería. Las coordenadas salen de la API del gráfico (`timeToCoordinate`/`logicalToCoordinate`, `priceToCoordinate`).
- **La cámara mueve el rango lógico visible** (`setVisibleLogicalRange`) y, si la escena da precios, el rango de precio (`priceScale().setVisibleRange`). Si no, la escala de precio se ajusta sola.
- **Revelar velas** = `setData` con las velas hasta el instante. La vela en formación recorre apertura → extremo más cercano → otro extremo → cierre, en proporción al progreso.
- **Resaltar** = color por vela: las demás bajan a un 25 % de opacidad.
- **La captura usa `Page.captureScreenshot`** tras `await estudio.ir(t)`, que espera dos fotogramas del navegador. Tamaño fijo con `Emulation.setDeviceMetricsOverride` (1920×1080 o 1080×1920, escala 1). Los PNG van por tubería a ffmpeg (`-c:v libx264 -pix_fmt yuv420p -crf 16`).
- **Tipografía:** la del tema; por defecto, la del sistema. Sin descargas: el Estudio funciona sin internet.

## Riesgos

- **Velocidad de captura:** unos 50–100 ms por fotograma. El criterio pide 600 fotogramas en menos de 3 min. Se mide en T6.
- **Determinismo:** Lightweight Charts anima algunas cosas (desplazamiento cinético, cruz del cursor). Se desactivan. Se comprueba con dos capturas del mismo instante.
- **Dukascopy:** bloqueos 429 si se piden muchos días seguidos. Bajo demanda y con caché el volumen es pequeño, y se reutiliza la conexión keep-alive del descargador.

## Cómo se prueba

- `tests/test_estudio_acciones.py`: decodificación, splits, filtro de minutos sin volumen, agregación a 15m y diario con `.bi5` sintéticos (sin red).
- `tests/test_estudio_escena.py`: validación con mensajes por paso, tiempos ET y por índice, velas manuales, y datos reales iguales a `almacen.consultar` aunque haya un replay en marcha.
- `tests/js/estudio.test.mjs`: progreso, suavizado, vela en formación y cámara.
- `tests/test_estudio_captura.py` (se salta sin Chrome o sin ffmpeg): mismo instante dos veces → mismos bytes; `ir(8)` tras `ir(20)` → igual que `ir(8)`; MP4 con el número de fotogramas esperado.
- A mano: las tres escenas de prueba en 16:9 y 9:16, y el pincel.
