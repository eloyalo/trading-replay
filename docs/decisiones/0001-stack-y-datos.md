# 0001 · Stack tecnológico y fuente de datos

- **Estado:** Aceptada (2026-10-15)
- **Fecha:** 2026-10-15

## Contexto

Queremos un simulador de trading local, en Linux, con replay de gráficos, órdenes simuladas, retos de prop firm y estadísticas. Sin coste y sin depender de Windows.

## Opciones consideradas

**Plataformas existentes**
- **NinjaTrader (Playback):** tiene datos de futuros reales y es gratis en simulación. Descartada porque solo funciona en Windows.
- **FX Replay, Forex Tester:** de pago y cerradas. No permiten modelar prop firms a medida.

**Fuente de datos**
- **Dukascopy:** gratis, años de histórico en tick y 1m. Son CFDs, no futuros.
- **yfinance:** tiene los futuros (`NQ=F`, `ES=F`, `GC=F`), pero en intradía guarda muy poco histórico.
- **Proveedores de pago** (FirstRate Data, Databento…): futuros reales del CME. Se dejan como opción futura.

## Decisión

- **Backend:** Python con FastAPI. Contiene el motor de replay, las órdenes, las reglas de prop firm y las estadísticas.
- **Datos:** Dukascopy, en resolución de 1m y con los últimos 4 años de histórico, guardados en Parquet y consultados con DuckDB.
- **Frontend:** app web local con TradingView Lightweight Charts (licencia Apache 2.0).
- **Persistencia de trades, cuentas y retos:** SQLite.
- **Configuración de prop firms:** archivos YAML.

## Consecuencias

- Precios de CFD en lugar de futuros: hay una pequeña diferencia de base y el volumen no es real. Para practicar price action es suficiente. Si más adelante hace falta precisión de futuros, se cambia de proveedor sin tocar el resto, porque la capa de datos queda aislada.
- Con datos de 1m no se sabe el orden de los precios dentro de la vela. Se asume el peor caso hasta que se añadan ticks.
- Todo en Python facilita reutilizar el motor para el backtest automático de la fase 6.
