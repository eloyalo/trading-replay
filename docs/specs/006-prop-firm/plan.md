# 006 · Plan técnico

Referencia: [spec.md](spec.md)

## Enfoque

Las reglas del reto se aplican en el backend, en el mismo sitio y en el mismo orden en que el motor de órdenes ve los minutos (spec 005). Igual que el motor, la lógica de las reglas es un módulo puro que se testea a fondo, y el servicio lo conecta con el motor, el reloj y la base de datos.

Módulos nuevos:

1. **`perfiles/*.json`** (raíz del proyecto): un archivo por empresa con la lista de cuentas.
2. **`operativa/perfiles.py`**: carga y valida los perfiles (`Perfil`, `PerdidaMaxima`, `LimiteDiario`).
3. **`operativa/reto.py`**: lógica pura: estado del reto, nivel de liquidación, precio de ruptura, cierre de día, objetivo efectivo, días válidos, contratos y el resumen que se enseña.
4. Cambios en **`bd.py`** (tablas `retos` e `intentos`), **`servicio.py`** (vigilancia en cada minuto, días, eventos, estadísticas) y **`app.py`** (endpoints).
5. **`frontend/retos.js`**: panel del reto, línea de liquidación, ventana de aprobado/suspendido con confeti y ventana de resumen de cuentas.

## Perfiles

```json
{
  "empresa": "Topstep",
  "revisado": "2026-10-16",
  "fuentes": ["https://help.topstep.com/..."],
  "cuentas": [
    {
      "id": "topstep-50k",
      "nombre": "Trading Combine 50K",
      "balance_inicial": 50000,
      "objetivo": 3000,
      "perdida_maxima": {"importe": 2000, "tipo": "trailing_cierre", "tope": "balance_inicial"},
      "limite_diario": {"importe": 1000, "efecto": "pausa"},
      "consistencia": 0.55,
      "dias_minimos": 2,
      "beneficio_minimo_dia": null,
      "contratos_maximos": 5,
      "hora_cierre": "16:10"
    }
  ]
}
```

- `tipo`: `estatica`, `trailing_cierre` o `trailing_intradia`. `tope`: `null`, `balance_inicial` (Topstep) u `objetivo` (DayTraders: el umbral no pasa de balance inicial + objetivo).
- `limite_diario`, `consistencia`, `beneficio_minimo_dia`, `contratos_maximos` y `hora_cierre` pueden ser `null`.
- El nombre que se enseña es "Empresa nombre" ("Topstep Trading Combine 50K"). Se cargan al arrancar y se cachean por fecha de modificación, como `almacen.rango()`.

## Estado del reto

Tabla `retos` (una fila por cuenta de reto, clave `cuenta`):

| Campo | Qué es |
|---|---|
| `perfil` | id del perfil |
| `intento` | número de intento (empieza en 1) |
| `estado`, `motivo`, `fin` | `en_curso` / `aprobado` / `suspendido`, el motivo y el instante de mercado |
| `umbral` | nivel de la pérdida máxima en $ de balance |
| `pico` | balance en vivo más alto (trailing intradía) |
| `sesion_dia` | id de la sesión de replay del día en curso |
| `balance_inicio_dia` | para el límite diario |
| `operado` | si el día en curso tiene alguna ejecución |
| `bloqueo`, `bloqueo_hasta` | `limite_diario` (hasta el siguiente salto) u `hora_cierre` (hasta el instante de reapertura) |

Tabla `intentos`: cuenta, perfil, número, resultado (`aprobado`, `suspendido`, `abandonado`), motivo, días, beneficio, mejor día y fecha real de fin.

Los días del reto no se guardan aparte: salen de `operaciones`, agrupadas por `sesion` (cada salto es un día, RF-4). El beneficio de un día es la suma de `pnl_bruto − comisiones` de sus operaciones cerradas. Al saltar se liquida todo (spec 005, RF-17), así que cada operación empieza y acaba en el mismo día.

## Días

`sincronizar(sesion)` se llama antes de cualquier cosa que toque el reto (orden, avance, resumen). Si la sesión de replay actual no es `sesion_dia`:

1. Si el día anterior tuvo operaciones, se **cierra**: con trailing al cierre, `umbral = max(umbral, balance − importe)` limitado por el tope. Después se comprueba si se aprueba (RF-13).
2. Empieza el día nuevo: `sesion_dia = sesión actual`, `balance_inicio_dia = balance`, `operado = False` y se quita el bloqueo.

Al saltar o salir, después de liquidar, se llama a `sincronizar` con la sesión nueva (o ninguna). Una cuenta que no está activa cierra su día la próxima vez que se mira (al activarla o en el resumen de cuentas).

## Vigilancia en cada minuto

En `servicio.procesar_avance`, para cada minuto `m` del símbolo `s`, en orden cronológico como ahora:

1. **Hora de cierre** (si el perfil la tiene): si `m` empieza en [hora_cierre, 18:00) y hay algo abierto, se liquida todo a la apertura de `m` y se bloquean las órdenes hasta las 18:00 de ese día.
2. `motor.procesar(s, m)`: órdenes, SL y TP, igual que ahora.
3. **Ruptura.** Nivel `L = max(umbral, balance_inicio_dia − límite diario)`: la regla que manda es la del nivel más alto (si empatan, la pérdida máxima). Balance en vivo en el peor caso: posiciones de `s` al peor precio del minuto (largos al BID mínimo, cortos al ASK máximo) y las de otros símbolos a su último cierre. Si llega a `L`:
   - El balance en vivo es lineal en el BID de `s`: `equity(b) = C + K·b`, con `K = Σ cantidad × valor_tick` de las posiciones de `s`. El precio de ruptura es `b* = (L − C) / K`, redondeado al primer tick en que se rompe de verdad (hacia abajo en un largo, hacia arriba en un corto).
   - Si la apertura de `m` ya está más allá de `b*`, se liquida a la apertura (hueco). Si no, a `b*`.
   - Para liquidar a ese precio, se pone en `motor.ultimo[s]` un minuto con `close = precio`, se llama a `motor.liquidar(m.inicio)` y se vuelve a poner el minuto real.
   - Pérdida máxima → `suspendido`. Límite diario → `pausa` (bloqueo hasta el siguiente salto) o `suspendido`, según el perfil.
   - Si solo queda balance (sin posiciones) y ya está en `L` o por debajo (por ejemplo, un SL más allá del umbral), se suspende igual. **Simplificación conservadora:** en ese caso la cuenta pierde lo del SL, aunque en la realidad la liquidación habría saltado antes, en el umbral.
4. **Pico** (trailing intradía): balance en vivo con el mejor precio del minuto; `pico = max(pico, eso)` y `umbral = max(umbral, pico − importe)`, con el tope.

Al enviar una orden a mercado que se ejecuta en el acto se hace la misma comprobación con el precio actual (sin peor caso).

Con varias posiciones en instrumentos distintos, el precio de ruptura se calcula sobre el instrumento del minuto, con los demás quietos en su último cierre. Es una aproximación aceptable: lo normal es operar uno a la vez.

## Órdenes en una cuenta de reto

Al enviar una orden (`servicio.enviar`) se rechaza (422) si:

- el reto no está en curso,
- hay bloqueo por límite diario en este salto o por hora de cierre (instante antes de `bloqueo_hasta`), o el instante está en [hora_cierre, 18:00),
- contratos (RF-11): se suman a las posiciones las órdenes de entrada pendientes y la nueva, como si se ejecutaran, por contrato; el total de `|posición|` en minis (micro = 0,1) no puede pasar del máximo.

## Eventos para el frontend

El servicio acumula eventos de la cuenta activa (`aprobado`, `suspendido`, `pausa`, `hora_cierre`) y se entregan dentro del resumen de la cuenta (`cuenta.eventos`), que el frontend ya recibe en cada avance, cada orden y cada refresco. El frontend los atiende en `actualizarCuenta`: para el play y enseña la ventana o el aviso.

## API

- `GET /api/perfiles`: perfiles para el selector de cuenta nueva.
- `POST /api/cuentas`: acepta `perfil` (opcional). Con perfil, el balance inicial sale del perfil y el nombre por defecto también.
- `GET /api/cuenta`: añade `reto` (estado, umbral, distancia, límite diario, día, objetivo efectivo, falta, días válidos, mejor día, contratos en uso, bloqueo y precio de liquidación por símbolo con posición) y `eventos`.
- `GET /api/cuentas/resumen`: tarjeta de cada cuenta para RF-21 (estadísticas, reto, días e intentos).
- Reiniciar (`POST /api/cuentas/{id}/reiniciar`): en una cuenta de reto guarda el intento, borra el historial y deja el reto como nuevo con el intento siguiente.

## Frontend

- **`retos.js`**, cargado después de `operativa.js`:
  - panel del reto en el panel de operar,
  - línea de liquidación (una `createPriceLine` discontinua roja en la serie),
  - ventana modal propia (un `<dialog>` con `showModal()`, que no bloquea como `alert()`),
  - confeti en un `<canvas>` a pantalla completa con `requestAnimationFrame`: unas 200 piezas de colores con gravedad y giro durante unos 4 s, sin librerías,
  - ventana de resumen de cuentas.
- **Botón "Cuentas"** en la barra superior.
- **Cuenta nueva:** en los ajustes, un selector "Tipo" con "Libre" y los perfiles agrupados por empresa.
- **Modo a ciegas:** los días se numeran y el historial de intentos solo tiene número y resultado.

## Tests

- `tests/test_reto.py`: lógica pura (umbral de cada tipo, tope, precio de ruptura, objetivo efectivo, días válidos, contratos, cierre de día).
- `tests/test_retos_api.py`: con datos sintéticos (el precio sube 1 punto por minuto) y los perfiles reales: suspensión por pérdida máxima con cortos, límite diario con pausa, hora de cierre, aprobado al saltar, contratos máximos, reiniciar y resumen de cuentas.
