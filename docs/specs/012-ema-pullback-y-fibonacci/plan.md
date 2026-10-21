# 012 · Plan técnico

Referencia: [spec.md](spec.md)

## Enfoque

Tres bloques que se pueden probar por separado, en este orden:

1. **Herramienta Fibonacci del gráfico** (RF-20 a RF-23). Cálculo puro en `calculos.js` (con tests en Node) y figura nueva en `dibujo.js`, como las tres que ya hay.
2. **Piezas comunes del backtest** (RF-1 a RF-5): timeframe elegible, sesiones, lados, límites, y la detección de pivotes. Las dos estrategias las usan.
3. **Las estrategias** (RF-6 a RF-19) y la figura de Fibonacci en el modo backtest (RF-24), que reutiliza el dibujo del bloque 1.

Cada estrategia se hace en dos pasadas: primero lo marcado como "por defecto" en la spec, y después las variantes (decidido con el usuario: base primero para que pruebe pronto).

### Decisiones técnicas

- **Timeframe como parámetro (RF-1).** Un parámetro llamado `timeframe` con `opciones` se trata como especial: el cargador lo valida y el ejecutor lo lee de los valores elegidos en vez de `clase.timeframe`. Si no existe, se usa `clase.timeframe` como hasta ahora. No cambia la API de las estrategias que ya hay.
- **Piezas comunes en `backtest/comunes.py`.** No en `estrategias/`, porque ahí cada `.py` es una estrategia. Dentro: `parametros_sesion()`, `parametros_salida()` (diccionarios de `Parametro` que se mezclan con los de cada estrategia), `PuertaDeSesion` (decide si se puede abrir ahora), `ControlDeOperaciones` (límites al día y por sentido) y `GestorDeSalidas` (parcial, break-even, trailing, cierre forzoso). Las estrategias lo usan por composición, no por herencia.
- **Pivotes en `backtest/swings.py`.** Función pura sobre las columnas de velas: un pivote en la posición `i` se devuelve cuando ya han cerrado `n` velas más, nunca antes (RF-12). Con test de no mirar al futuro.
- **Figura de Fibonacci compartida.** El cálculo de niveles (`fibonacciNiveles`) y el pintado de la figura viven en el frontend y los usan la herramienta manual y el modo backtest. En Python la estrategia solo guarda `origen`, `final` y los niveles que usó; no calcula nada para pintar.
- **Marca nueva `fibonacci`.** La clase `Marca` gana un campo opcional `datos` (diccionario) para esta marca: `{origen: {t, precio}, final: {t, precio}, retrocesos: [...], extensiones: [...]}`. La estrategia la crea con `self.fibonacci(...)`. El campo se guarda en `backtests.sqlite` dentro de las marcas ya existentes (JSON); las ejecuciones antiguas no lo tienen y se leen igual.
- **"Copiar como dibujo" (RF-24).** Crea un dibujo `fibonacci` normal en `dibujo.lista` del instrumento a partir de la marca. Pasa por `guardarDibujos()`, así que sigue la regla de la 004 de borrarse al empezar un replay.
- **Un dibujo de Fibonacci en `dibujo.js`.** Tipo `fibonacci` con 2 puntos (`PUNTOS_POR_TIPO`), atajo `f`. Sus 2 puntos son las 2 esquinas de control. La configuración (niveles, extensiones, etiquetas) es global y se recuerda en `preferencias` (`fibonacci.config`), no por figura.

## Componentes afectados

| Módulo / archivo | Cambio |
|------------------|--------|
| `frontend/calculos.js` | `fibonacciNiveles(origen, final, niveles)`: precio de cada nivel, en cualquier sentido |
| `frontend/dibujo.js` | Herramienta `fibonacci`: crear, pintar, seleccionar, arrastrar, borrar, atajo `f` y panel de configuración |
| `frontend/index.html`, `frontend/estilos.css` | Botón de la herramienta y panel de configuración |
| `frontend/backtest.js` | Pintar la marca `fibonacci` con la misma figura; botón "Copiar como dibujo"; campo `timeframe` en el formulario de lanzar si la estrategia lo trae como parámetro |
| `backend/trading_replay/backtest/cargador.py` | Aceptar `timeframe` como `Parametro` con opciones; validación |
| `backend/trading_replay/backtest/ejecutor.py` | Leer el timeframe de los valores elegidos; `Marca.datos`; método `marcar` ampliado |
| `backend/trading_replay/backtest/estrategia.py` | `self.fibonacci(...)`; el timeframe de la instancia sale del valor elegido |
| `backend/trading_replay/backtest/comunes.py` | Nuevo: parámetros y ayudas comunes (sesión, lados, límites, salidas) |
| `backend/trading_replay/backtest/swings.py` | Nuevo: pivotes sin mirar al futuro |
| `backend/trading_replay/backtest/almacen_bt.py` | Guardar y leer `datos` de las marcas |
| `estrategias/ema_pullback.py`, `estrategias/fibonacci.py` | Nuevas |
| `estrategias/LEEME.md` | Estrategias nuevas, timeframe como parámetro y aviso sobre probar muchas combinaciones |
| `tests/` | `test_backtest_comunes.py`, `test_backtest_swings.py`, `test_estrategia_ema_pullback.py`, `test_estrategia_fibonacci.py`, y tests en Node de `fibonacciNiveles` |

## Modelo de datos

- `Marca.datos`: `dict | None`. Solo lo usa la marca `fibonacci`.
- Parámetros de las estrategias: los de la spec. Los booleanos y opciones ya los admite `Parametro`; las sesiones son tres `bool` y la ventana horaria, dos textos `HH:MM` (vacíos = desactivada).
- Sin tablas nuevas.

## Riesgos

- **Muchos parámetros.** La ventana Backtest dibuja un formulario con todos. Con 40 o más, tiene que agruparse. Si no, el formulario se vuelve inmanejable. Mitigación: `Parametro` gana un campo `grupo` opcional (texto) y el formulario los agrupa en secciones plegables. Se hace en la T4.
- **Combinaciones sin sentido.** Muchas opciones se pueden combinar mal (entrada límite en la media con filtro de vela de confirmación, por ejemplo). Cada estrategia valida al empezar y falla con un mensaje claro en vez de operar raro.
- **Rendimiento.** Pivotes y filtros sobre 4 años de 5m se calculan por vela. Se hace incremental (solo las últimas `n` velas) y se mide en la T11; el criterio es menos de 30 s.
- **Mirada al futuro.** El riesgo más serio de Fibonacci. Los pivotes se confirman `n` velas después, y el máximo "reanclado" solo se mueve con velas ya cerradas. Test específico.
- **Marcas pesadas.** Fibonacci dibuja una figura por swing; con 4 años pueden ser miles. Se guardan solo las de swings que llegaron a operarse o a ordenarse, no todos los detectados.
- **NTFS.** Los tests de Node se lanzan desde pytest, como ya se hace; sin problema nuevo.

## Cómo se prueba

- `fibonacciNiveles` con tests en Node (100 → 200 y 200 → 100).
- Piezas comunes y pivotes con tests de pytest sobre velas sintéticas.
- Cada estrategia con velas sintéticas hechas a mano: un caso de entrada, uno por cada filtro que lo anula y uno por variante.
- Mirada al futuro: test de pivotes y de reanclaje.
- Rendimiento y datos reales: 4 años de NQ con los valores por defecto.
- Chrome headless con datos reales (herramienta manual, modo backtest y "Copiar como dibujo"); la revisión final es del usuario.
