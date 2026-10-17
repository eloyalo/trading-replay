# trading-replay

Simulador local de trading para practicar sobre datos históricos de NQ (Nasdaq 100), ES (S&P 500) y GC (oro).

- Replay vela a vela desde cualquier fecha o desde un momento aleatorio, sin ver el futuro.
- Herramientas de dibujo e indicadores (medias, VWAP, volumen, RSI, ATR y niveles del día anterior y overnight).
- Cuentas demo propias con órdenes, SL/TP, comisiones y slippage, que conservan el balance entre replays.
- Simulación de retos de prop firm (Topstep y DayTraders): pérdida máxima, límite diario, consistencia, objetivo y días mínimos, aplicados en el momento.
- Backtest de estrategias escritas en Python: se pasan por el histórico con el mismo motor de órdenes, con % de acierto, profit factor, drawdown, desglose por año, sesión y día, y las operaciones una a una en el gráfico. También con las reglas de un reto de prop firm, para ver qué % de intentos aprobaría.

Todo corre en local. Está en desarrollo: el estado de cada fase está en [`docs/FASES.md`](docs/FASES.md).

## Requisitos

- [uv](https://docs.astral.sh/uv/), que instala Python y las dependencias.
- Linux. Debería funcionar también en Windows y macOS, pero todavía no se ha probado.

## Uso

```
uv run trading-replay datos descargar   # descarga ~4 años de histórico (unos 30-40 min la primera vez)
./iniciar.sh                            # Linux/macOS
.\iniciar.ps1                           # Windows (PowerShell)
```

Después, abre http://127.0.0.1:8000.

Las cuentas, órdenes y operaciones se guardan en `datos/cuentas.sqlite`. Para empezar de cero, borra ese archivo con el servidor parado.

Las reglas de los retos están en `perfiles/` (un JSON por empresa). Las prop firms cambian sus reglas a menudo: si alguna ya no cuadra, se corrige ese archivo sin tocar el código.

Las estrategias del backtest están en `estrategias/`, un archivo Python cada una. Cómo se escriben: [`estrategias/LEEME.md`](estrategias/LEEME.md). El historial de backtests se guarda en `datos/backtests.sqlite`, aparte de las cuentas.

## Documentación

El proyecto se desarrolla con specs (SDD). Está todo en [`docs/`](docs/README.md); el estado actual, en [`docs/CONTEXTO.md`](docs/CONTEXTO.md).

## Datos

Los precios proceden de [Dukascopy](https://www.dukascopy.com/) y son de CFD, no de futuros del CME (las diferencias están documentadas en `docs/`). Este repositorio **no incluye ni redistribuye datos**: cada usuario los descarga por su cuenta con el comando anterior y es responsable de cumplir las condiciones de uso de Dukascopy.

## Avisos

- **No es asesoramiento financiero.** Es una herramienta de práctica y estudio. Los resultados obtenidos sobre datos históricos no garantizan resultados futuros.
- Los nombres de prop firms (por ejemplo Topstep o DayTraders) se usan solo para describir los perfiles de reglas que se simulan. Este proyecto no tiene relación con ellas ni con su respaldo, y sus reglas reales pueden cambiar.

## Licencia y atribuciones

Código bajo licencia [MIT](LICENSE).

Incluye [TradingView Lightweight Charts™](https://www.tradingview.com/lightweight-charts/) 5.2.1, bajo licencia Apache 2.0 ([licencia](frontend/vendor/LICENSE-lightweight-charts) y [aviso](frontend/vendor/NOTICE-lightweight-charts)):

> TradingView Lightweight Charts™
> Copyright (c) 2025 TradingView, Inc. https://www.tradingview.com/

El gráfico muestra el logotipo de TradingView con enlace a su web, tal como pide su licencia.
