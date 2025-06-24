import os
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime
import pytz

# 🔐 Credenciales Alpaca desde entorno
API_KEY = os.getenv("APCA_API_KEY_ID")
API_SECRET = os.getenv("APCA_API_SECRET_KEY")
BASE_URL = os.getenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")
EODHD_KEY = os.getenv("EODHD_API_KEY")

# 📊 Parámetros
SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "INTC"]
CAPITAL_POR_ORDEN = 10
RSI_PERIOD = 14
EMA_FAST = 9
EMA_SLOW = 21
VOL_PERIOD = 20
PRICE_PERIOD = 50

# 🕓 Zona horaria
zona = pytz.timezone("US/Eastern")
hoy = datetime.now(zona)
fecha_str = hoy.strftime("%Y-%m-%d")

# 🛑 Feriados y fines de semana
if hoy.weekday() >= 5 or fecha_str in {
    "2025-01-01","2025-01-20","2025-02-17","2025-04-18",
    "2025-05-26","2025-06-19","2025-07-04","2025-09-01",
    "2025-11-27","2025-12-25"
}:
    print("Día inhábil. No se opera:", fecha_str)
    exit()

# ⏰ Validar mercado abierto
clock = requests.get(f"{BASE_URL}/v2/clock", headers={
    "APCA-API-KEY-ID": API_KEY,
    "APCA-API-SECRET-KEY": API_SECRET
}).json()
if not clock.get("is_open", False):
    print("Mercado cerrado. Próxima apertura:", clock.get("next_open"))
    exit()

# 📈 Funciones de análisis técnico
def get_history(sym):
    r = requests.get(f"https://eodhd.com/api/eod/{sym}.US", params={
        "api_token": EODHD_KEY, "fmt": "json", "period": "d"
    })
    r.raise_for_status()
    df = pd.DataFrame(r.json())[["date", "close", "high", "low", "volume"]]
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()

def calc_rsi(c): delta = c.diff(); g = delta.clip(lower=0).ewm(alpha=1/RSI_PERIOD).mean(); l = -delta.clip(upper=0).ewm(alpha=1/RSI_PERIOD).mean(); rs = g/l; return 100 - (100 / (1 + rs))
def calc_ema(s, p): return s.ewm(span=p, adjust=False).mean()
def avwap(df): return (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
def squeeze(df):
    bb_u = df["close"].rolling(20).mean() + 2 * df["close"].rolling(20).std()
    kc_u = df["close"].rolling(20).mean() + 1.5 * (df["high"] - df["low"]).rolling(20).mean()
    return bb_u < kc_u

def breakout_squeeze(latest, df):
    prev = df.iloc[-2]["close"]
    return latest["close"] > prev * 1.01 and latest["volume"] > df["volume"].rolling(VOL_PERIOD).mean().iloc[-1]

# 🔍 Evaluación y ejecución
candidatos = {}
for sym in SYMBOLS:
    try:
        df = get_history(sym)
        df["RSI"] = calc_rsi(df["close"])
        df["EMA9"] = calc_ema(df["close"], EMA_FAST)
        df["EMA21"] = calc_ema(df["close"], EMA_SLOW)
        df["VolAvg"] = df["volume"].rolling(VOL_PERIOD).mean()
        df["AVWAP"] = avwap(df)
        df["SqueezeBand"] = squeeze(df)

        latest = df.iloc[-1]
        trend = latest["close"] > df["close"][-PRICE_PERIOD:].mean()
        ema_cross = latest["EMA9"] > latest["EMA21"]
        vol_ok = latest["volume"] > latest["VolAvg"]
        avwap_ok = latest["close"] > latest["AVWAP"]
        fired = breakout_squeeze(latest, df)
        rsi_ok = latest["RSI"] > 50
        cumple = all([rsi_ok, trend, ema_cross, vol_ok, avwap_ok, fired])

        if cumple:
            candidatos[sym] = round(latest["close"], 2)

    except Exception as e:
        print(f"{sym} ERROR: {e}")

# 🛒 Órdenes
for sym, precio in candidatos.items():
    qty = round(CAPITAL_POR_ORDEN / precio, 2)
    orden = {
        "symbol": sym,
        "qty": qty,
        "side": "buy",
        "type": "market",
        "time_in_force": "day"
    }
    r = requests.post(f"{BASE_URL}/v2/orders", headers={
        "APCA-API-KEY-ID": API_KEY,
        "APCA-API-SECRET-KEY": API_SECRET,
        "Content-Type": "application/json"
    }, json=orden)

    if r.status_code in [200, 201]:
        print(f"✅ Orden enviada: {sym} qty={qty} a ${precio}")
    else:
        print(f"❌ Error orden {sym}: {r.status_code} - {r.text}")