# 008 · Plan técnico

Referencia: [spec.md](spec.md)

## Enfoque

El backtest es un bucle en Python que recorre los minutos del histórico, arma las velas del timeframe de la estrategia, le avisa al cerrar cada una y pasa sus órdenes al **mismo `Motor`** del trading manual (`operativa/motor.py`), que no depende del replay ni de la base de datos. Así las reglas de ejecución son las mismas por construcción.

Todo lo nuevo del backend va en un paquete aparte, `backtest/`, para no mezclarlo con la operativa de las cuentas:

1. **`estrategias/`** (raíz del proyecto): los archivos de estrategia, `LEEME.md` y las dos de ejemplo.
2. **`backtest/estrategia.py`**: la clase base `Estrategia` y `Parametro`: lo único que necesita conocer quien escribe una estrategia.
3. **`backtest/indicadores.py`**: los indicadores de `frontend/calculos.js` pasados a Python, con el mismo cálculo paso a paso.
4. **`backtest/cargador.py`**: busca, carga, recarga y duplica estrategias, y traduce los errores a archivo, línea y mensaje.
5. **`backtest/ejecutor.py`**: el bucle de minutos, las velas del timeframe, las órdenes y el registro de operaciones y marcas.
6. **`backtest/metricas.py`**: métricas, desglose, curva y filtros. Funciones puras sobre la lista de operaciones.
7. **`backtest/almacen_bt.py`**: SQLite propio (`datos/backtests.sqlite`) con las ejecuciones, sus operaciones y sus marcas.
8. **`backtest/trabajos.py`**: lanza el backtest en un hilo, con progreso y cancelación.
9. **`app.py`**: endpoints `/api/estrategias` y `/api/backtests`.
10. **`frontend/backtest.js`**: ventana "Backtest" y modo backtest del gráfico.

## Cómo se escribe una estrategia

Lo que verá el usuario al abrir un archivo. Todo en español y sin nada que no sea la regla:

```python
"""Ruptura del rango de apertura.

Rango: máximo y mínimo de los primeros `minutos_rango` minutos desde las 9:30 ET.
Entrada: una vela de 5m que cierra por encima del máximo compra; por debajo del mínimo, vende.
Stop al otro lado del rango; objetivo a `objetivo_r` veces el riesgo. Una operación al día.
Si a las 16:00 sigue abierta, se cierra.
"""

from trading_replay.backtest import Estrategia, Parametro


class RupturaRango(Estrategia):
    nombre = "Ruptura del rango de apertura"
    timeframe = "5m"
    parametros = {
        "minutos_rango": Parametro(15, "Minutos del rango desde las 9:30", minimo=5, maximo=120, paso=5),
        "objetivo_r": Parametro(2.0, "Objetivo en R", minimo=0.5, maximo=10, paso=0.5),
        "contratos": Parametro(1, "Contratos", minimo=1, maximo=10),
    }

    def al_empezar_dia(self):
        self.alto = self.bajo = None
        self.operado_hoy = False

    def al_cerrar_vela(self, vela):
        fin_rango = self.hora_mas("09:30", self.p.minutos_rango)
        # Mientras dura el rango, se van guardando el máximo y el mínimo.
        if self.entre("09:30", fin_rango):
            self.alto = vela.high if self.alto is None else max(self.alto, vela.high)
            self.bajo = vela.low if self.bajo is None else min(self.bajo, vela.low)
            if self.hora == fin_rango:
                self.rango("09:30", fin_rango, self.alto, self.bajo, "Rango de apertura")
            return
        if self.alto is None:
            return
        # A las 16:00, fuera.
        if self.hora >= "16:00":
            self.cerrar()
            return
        if self.operado_hoy or self.posicion:
            return
        if vela.close > self.alto:
            self.comprar(self.p.contratos, sl=self.bajo, tp_r=self.p.objetivo_r, motivo="Cierra por encima del rango")
            self.operado_hoy = True
        elif vela.close < self.bajo:
            self.vender(self.p.contratos, sl=self.alto, tp_r=self.p.objetivo_r, motivo="Cierra por debajo del rango")
            self.operado_hoy = True
```

API de `Estrategia` (se documenta entera en `estrategias/LEEME.md`):

| Qué | Cómo |
|---|---|
| Datos | `nombre`, `timeframe` (1m, 5m, 15m, 30m, 1h, 4h), `parametros`, docstring del módulo como descripción |
| Avisos | `al_empezar()`, `al_empezar_dia()` (día de trading, 18:00 ET), `al_cerrar_vela(vela)` |
| Velas | `self.velas`: solo las cerradas (`self.velas[-1]` es la que acaba de cerrar; `vela.inicio`, `open`, `high`, `low`, `close`, `volume`) |
| Tiempo | `self.hora` ("HH:MM" ET del cierre de la vela, comparable como texto), `self.entre(a, b)` (la vela cierra después de `a` y como tarde a `b`), `self.hora_mas(h, minutos)`, `self.fecha`, `self.dia_semana`, `self.sesion` |
| Indicadores | `self.ema(n)`, `self.sma(n)`, `self.rsi(n)`, `self.atr(n)`, `self.vwap()`, `self.dia_anterior()` (high, low, close), `self.overnight()` (high, low). Valor en la vela que acaba de cerrar, o `None` si aún no hay datos |
| Parámetros | `self.p.minutos_rango`... con los valores elegidos al lanzar |
| Posición | `self.posicion` (contratos con signo, 0 si no hay), `self.precio_entrada`, `self.ordenes` |
| Órdenes | `self.comprar(contratos, tipo="mercado", precio=None, sl=None, sl_puntos=None, tp=None, tp_puntos=None, tp_r=None, micro=False, motivo="")`, `self.vender(...)` igual, `self.cerrar()`, `self.cancelar()`, `self.mover_sl(precio)` |
| Marcas | `self.nivel(precio, texto)`, `self.rango(desde, hasta, alto, bajo, texto)`, `self.texto(texto)` |

Detalles:

- **Sin futuro:** `self.velas` es una secuencia de solo lectura que crece al cerrar cada vela. Pedir una posición que no existe da `IndexError`; no hay ninguna referencia a los minutos siguientes al alcance de la estrategia.
- **SL y TP en precio o en R:** el motor trabaja con distancias en puntos desde el precio de ejecución (spec 005, RF-8). Cuando la estrategia da un precio (`sl=17990`) o un TP en R, el ejecutor espera a que se ejecute la entrada y entonces coloca el SL y el TP en el precio pedido con `Motor.modificar`, y deja `sl_inicial` de la operación en ese precio para calcular la R. Si el precio ya está rebasado al ejecutarse la entrada (el SL por encima del precio de un largo), la operación se cierra a mercado en el acto, con el motivo "SL rebasado al entrar".
- **Marcas:** se guardan con su instante. En el gráfico, cada operación enseña las marcas de su día de trading hasta su cierre.
- Una estrategia opera un solo instrumento, el que se elige al lanzar.

## Ejecución

```
cargar minutos 1m del periodo (DuckDB → listas de Python)
calcular el número de vela del timeframe de cada minuto (vectorizado, misma alineación que almacen.consultar)
para cada minuto:
    si hay órdenes pendientes o posición: motor.procesar(minuto) → ejecuciones
        → completar SL/TP pedidos en precio o R, cerrar operaciones, anotar motivo y dudosas
    sumar el minuto a la vela en curso
    si es el último minuto de su vela:
        cerrar la vela: añadirla a self.velas, avanzar indicadores
        si empieza día de trading: al_empezar_dia()
        motor.ultimo = este minuto; al_cerrar_vela(vela) con el reloj en el fin de la vela
    cada 20.000 minutos: progreso y ¿cancelado?
al final: motor.liquidar() con el motivo "Fin de los datos"
```

- **Orden a mercado al cierre:** se envía con el reloj en el fin de la vela. Si el último minuto de la vela existe, `Motor.enviar` la ejecuta al cierre de ese minuto, como en el replay. Si falta (hueco), espera a la apertura del siguiente minuto con datos, también como en el replay.
- **El último minuto de una vela** se sabe mirando el número de vela del minuto siguiente. Esto solo dice *cuándo* termina la vela, nunca precios futuros.
- **SL y TP en el mismo minuto:** `Motor._elegir_en_oco` ya decide (gana el SL). Se le añade un registro aparte, `motor.dudosas` (ids de ejecuciones), en vez de un campo nuevo en `Ejecucion`, para no tocar el esquema de `cuentas.sqlite`.
- **Motivo de salida:** del `papel` de la ejecución que cierra: `sl`, `tp`, `cierre` (la estrategia) o `fin` (fin de los datos).
- **Rapidez:** se evita crear objetos por minuto cuando no hay nada abierto: sin órdenes ni posición no se llama al motor. `Minuto` y `datetime` solo se crean cuando hacen falta. Estimación: 1,4 millones de minutos (4 años) en 5–15 s con la estrategia de ejemplo. Si no llega a RF-9, la siguiente palanca es saltar en bloque los minutos sin órdenes que no cierran vela.
- **Alineación de velas:** igual que `cubeta()` y `almacen.consultar` (4h y 1D desde las 18:00 ET). Un test compara las velas armadas por el ejecutor con las de `almacen.consultar` en todos los timeframes.

## Indicadores

`backtest/indicadores.py` replica cada indicador de `INDICADORES` de `calculos.js` con la misma función `paso(velas, i, previo)`, para que los valores sean los mismos que en el gráfico. Test de paridad: Node calcula con `calculos.js` sobre una serie sintética (con cambio de día y huecos), Python con `indicadores.py`, y se comparan con tolerancia de 1e-9. Como en la spec 004, si se toca uno hay que tocar el otro (anotado en `CONTEXTO.md`).

## Carga de estrategias

- Cada `estrategias/*.py` (salvo los que empiezan por `_`) se importa con `importlib.util.spec_from_file_location` y un nombre de módulo único, y se busca la única subclase de `Estrategia` que define. Se recarga si cambia la fecha de modificación del archivo.
- El id de una estrategia es el nombre del archivo sin `.py`.
- **Errores:** de carga (sintaxis, import) y de ejecución (en `al_cerrar_vela`). Del traceback se toma el último marco que está dentro de `estrategias/` para dar archivo y línea, y en los de ejecución también la vela en la que falló. Una estrategia con error de carga sale en la lista marcada, con el mensaje, y no se puede lanzar.
- **Duplicar:** copia el archivo a `<id>_2.py` (o el primer número libre) y cambia la línea `nombre = "..."` por `nombre = "... (copia 2)"`. Si no encuentra esa línea, copia el archivo tal cual.
- **Huella:** SHA-256 del código. Cada ejecución guarda la huella y una copia del código, así que se puede ver qué código dio cada resultado y si el archivo ha cambiado después.
- Las estrategias son código del usuario que corre en su propio servidor local, como cualquier script suyo. No hay sandbox; el servidor solo escucha en 127.0.0.1.

## Métricas

`metricas.py` recibe la lista de operaciones (ya filtrada) y devuelve:

- Conteos, % de acierto, neto, bruto, comisiones, ganancia y pérdida media y su proporción, profit factor (`null` si no hay pérdidas: la interfaz pone "∞"), esperanza en $ y en R, R medio de ganadoras y perdedoras, drawdown máximo en $ y en R, rachas, duración media, operaciones por mes y cuántas fueron dudosas.
- **Curva:** neto acumulado por fecha de cierre.
- **Desglose:** por año, sesión, día de la semana y lado, con las mismas métricas reducidas.
- **Sesión** según la hora ET de entrada, con los límites de `almacen.SESION_SQL` (se saca a constantes compartidas para no repetirlos). **Día de la semana** del día de trading de la entrada (domingo 19:00 ET cuenta como lunes).
- **Filtros:** periodo (desde, hasta), años, sesiones, días de la semana y lado. Se calculan en el servidor sobre las operaciones guardadas: unos pocos miles de operaciones, milisegundos.

## Modelo de datos

`datos/backtests.sqlite` (modo WAL, como `cuentas.sqlite`), aparte de las cuentas para que borrar o rehacer los backtests no las toque:

```sql
CREATE TABLE ejecuciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    estrategia TEXT NOT NULL,         -- id (nombre del archivo)
    nombre TEXT NOT NULL,
    huella TEXT NOT NULL,             -- SHA-256 del código
    codigo TEXT NOT NULL,             -- copia del código ejecutado
    parametros TEXT NOT NULL,         -- JSON
    simbolo TEXT NOT NULL,
    desde TEXT NOT NULL, hasta TEXT NOT NULL,
    costes TEXT NOT NULL,             -- JSON
    creada TEXT NOT NULL,             -- hora real
    segundos REAL NOT NULL,
    resumen TEXT NOT NULL             -- JSON con las métricas principales, para el historial
);
CREATE TABLE operaciones (
    ejecucion INTEGER NOT NULL REFERENCES ejecuciones(id) ON DELETE CASCADE,
    numero INTEGER NOT NULL,
    contrato TEXT NOT NULL, lado INTEGER NOT NULL, cantidad INTEGER NOT NULL,
    apertura TEXT NOT NULL, cierre TEXT NOT NULL,
    entrada REAL NOT NULL, salida REAL NOT NULL,
    sl_inicial REAL, sl_final REAL, tp_final REAL,
    motivo_entrada TEXT, motivo_salida TEXT NOT NULL,
    pnl_bruto REAL NOT NULL, comisiones REAL NOT NULL, riesgo REAL,
    dudosa INTEGER NOT NULL,
    PRIMARY KEY (ejecucion, numero)
);
CREATE TABLE marcas (
    ejecucion INTEGER NOT NULL REFERENCES ejecuciones(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL,               -- nivel | rango | texto
    instante TEXT NOT NULL, fin TEXT,
    precio REAL, precio2 REAL, texto TEXT
);
```

Una ejecución cancelada no se guarda. Una que falla por un error de la estrategia tampoco: se devuelve el error.

## API

| Ruta | Qué hace |
|---|---|
| `GET /api/estrategias` | Lista: id, nombre, descripción, timeframe, parámetros, ruta, huella y error si lo hay |
| `GET /api/estrategias/{id}/codigo` | Código fuente |
| `POST /api/estrategias/{id}/duplicar` | Crea la copia y la devuelve |
| `POST /api/backtests` | Lanza: estrategia, símbolo, desde y hasta (días de trading, `hasta` incluido), parámetros, costes. 409 si ya hay uno en marcha o hay un replay activo |
| `GET /api/backtests/en-marcha` | Progreso (0–1), o el resultado (id de la ejecución) o el error al terminar |
| `POST /api/backtests/en-marcha/cancelar` | Cancela |
| `GET /api/backtests` | Historial con el resumen de cada ejecución y si el código ha cambiado desde entonces |
| `GET /api/backtests/{id}?desde&hasta&anios&sesiones&dias&lado&inicio&limite` | Métricas, curva, desglose y operaciones filtradas (la lista, por páginas) |
| `GET /api/backtests/{id}/tramo?desde&hasta` | Operaciones y marcas de la estrategia en un tramo, para el gráfico |
| `GET /api/backtests/{id}/codigo` | El código que se ejecutó |
| `DELETE /api/backtests/{id}` | Borra la ejecución |

`POST /api/replay` devuelve 409 mientras corre un backtest, y `POST /api/backtests` mientras hay replay (RF-16).

El backtest corre en un `threading.Thread`. Con el GIL, la API sigue respondiendo (Python cambia de hilo cada 5 ms) aunque algo más lenta mientras dura. Si molesta, se pasa a un proceso aparte.

## Frontend

**Ventana "Backtest"** (`backtest.js`, botón en la barra de arriba, desactivado durante un replay), con tres pestañas:

1. **Lanzar:** estrategia (con su descripción, ruta del archivo, "Ver código" desplegable y "Duplicar"), parámetros generados desde su declaración, instrumento, periodo, costes y "Lanzar". Barra de progreso y "Cancelar". Si la estrategia tiene un error, el error en lugar del botón.
2. **Resultados:** filtros arriba; cifras; curva de capital (un gráfico de línea de Lightweight Charts dentro de la ventana); desglose; lista de operaciones (de 200 en 200, con "ver más"). Botón "Ver en el gráfico" y clic en una fila.
3. **Historial:** tabla de ejecuciones con estrategia, parámetros, instrumento, periodo, operaciones, % de acierto, profit factor, esperanza en R, drawdown y neto, con una marca si el código cambió después. Abrir y borrar (con segundo clic).

**Modo backtest del gráfico** (`estado.backtest`):

- `body.modo-backtest` oculta la barra de replay y el panel de operar, y enseña una barra con "Operación 37 de 412 · Largo 1 NQ · +450,00 $ · 1,8 R · TP", anterior y siguiente, "Resultados" y "Salir".
- Ir a una operación: cambia al instrumento de la ejecución, carga velas con `hasta` = cierre de la operación + un tercio de la ventana del timeframe, y centra la operación. Se añade la carga hacia la derecha al desplazarse (`cargarPosteriores`, solo en este modo, porque fuera del replay hasta ahora siempre se cargaba hasta el final).
- Dibujo: marcas de entrada y salida de todas las operaciones del tramo cargado (las de la cuenta se ocultan en este modo); para la operación actual, zonas de SL y TP entre la entrada y el cierre, al estilo de la herramienta de posición de TradingView; y las marcas de la estrategia. Las zonas y las marcas van en una primitiva propia, con la misma conversión tiempo ↔ coordenada que `dibujo.js`.
- Atajos: ← y → (libres fuera del replay) para anterior y siguiente, Esc para salir. Indicadores, dibujos y timeframes funcionan como siempre.

## Riesgos

- **Rapidez en Python.** Es el mayor. Se mide en cuanto esté el ejecutor (T3), antes de construir la interfaz. Plan B en "Ejecución".
- **Paridad de indicadores y de velas** entre Python y JavaScript: cubierta por tests que lanzan Node.
- **El GIL** mientras corre un backtest: aceptable para un uso local; si se nota, proceso aparte.
- **Estrategias con bucles infinitos:** "Cancelar" no puede cortar un bucle dentro de `al_cerrar_vela`. Se documenta; si pasa, hay que reiniciar el servidor.

## Cómo se prueba

- **Indicadores:** paridad con `calculos.js` vía Node.
- **Velas del ejecutor:** iguales a `almacen.consultar` en todos los timeframes, con días de cambio de horario y huecos.
- **Sin futuro:** una estrategia que lee `self.velas[len(self.velas)]` falla con `IndexError`; una límite enviada al cerrar una vela no se ejecuta con su precio aunque lo toque.
- **Igual que a mano:** la misma entrada con SL y TP por el `servicio` del replay y por el ejecutor da el mismo resultado neto.
- **Ruptura con velas sintéticas:** días diseñados a mano (ruptura al alza que llega al TP, ruptura a la baja que toca el SL, día sin ruptura, día con SL y TP en el mismo minuto, cierre a las 16:00) → operaciones, precios y métricas esperadas.
- **Métricas y filtros** con una lista de operaciones hecha a mano.
- **Cargador:** error de sintaxis con su línea, error de ejecución con su línea y su vela, recarga al cambiar el archivo, huella distinta, duplicar.
- **API:** lanzar, progreso, cancelar, resultado, historial, borrar, y los 409 con replay.
- **Rapidez (RF-9):** a mano, con los datos reales de NQ.
- **Chrome:** el último criterio de aceptación.
