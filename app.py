import streamlit as st
from groq import Groq
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
import json
import re
import sqlite3
import pywencai 
import akshare as ak
import tushare as ts
import baostock as bs
import random
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List
from collections import Counter
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import warnings

warnings.filterwarnings('ignore')

# ================= 页面与终端 UI 配置 =================
st.set_page_config(
    page_title="AI 智能投研终端 Pro Max",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded"
)
st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
        flex-wrap: wrap;
    }
    .stTabs [data-baseweb="tab"] {
        height: auto;
        min-height: 40px;
        white-space: normal;
        background-color: transparent;
        border-radius: 4px 4px 0 0;
        padding: 8px 12px;
        font-weight: bold;
    }
    .terminal-header {
        font-family: 'Courier New', Courier, monospace;
        color: #888;
        font-size: 0.8em;
        margin-bottom: 20px;
        word-wrap: break-word;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.5rem;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🏦 AI 智能量化投研终端")
st.markdown(
    f"<div class='terminal-header'>TERMINAL BUILD v6.4.0 | SYS_TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | MULTI-TF HOTFIX + MANUAL OVERRIDE</div>",
    unsafe_allow_html=True
)

api_key = st.secrets.get("GROQ_API_KEY", "")

# ================= 侧边栏与参数调优 =================
with st.sidebar:
    st.header("⚙️ 终端控制台")

    # 新增：手动选择 LLM 模型
    st.markdown("### 🧠 核心推理引擎")
    selected_model = st.selectbox(
        "选择大模型",
        ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"],
        index=0,
        help="手动指定底层计算模型，精准控制分析逻辑"
    )

    # 新增：手动干预技术参数
    st.markdown("### 🎛️ 策略参数微调")
    with st.expander("自定义均线周期 (手动输入)", expanded=False):
        ema_short = st.number_input("短期 EMA", min_value=5, max_value=50, value=20, step=1)
        ema_mid = st.number_input("中期 EMA", min_value=10, max_value=100, value=60, step=1)
        ema_long = st.number_input("长期 EMA", min_value=20, max_value=250, value=120, step=1)

    ts_token = st.text_input("🔑 Tushare Token", type="password", help="仅作极致容灾兜底")
    DEBUG_MODE = st.checkbox("🛠️ 开启底层日志嗅探")

    st.markdown("---")
    st.markdown("### 📡 数据连通性")
    st.success("行情引流 : ACTIVE")
    st.success("7x24快讯 : ACTIVE")
    st.success("板块扫描 : ACTIVE (带熔断保护)")
    st.success("技术结构引擎 : ACTIVE")
    st.success("多周期分析 : ACTIVE (15m / 60m / 120m)")
    st.success("智瞰龙虎榜 : ACTIVE")

if ts_token:
    ts.set_token(ts_token)

# ================= 网络底座 =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:115.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
]

@st.cache_resource
def get_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[403, 429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

SESSION = get_session()

def safe_float(val, default=0.0):
    if val is None or val == "-" or str(val).strip() == "":
        return default
    try:
        return float(val)
    except Exception:
        return default

def fetch_json(url, timeout=5, extra_headers=None):
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    if extra_headers:
        headers.update(extra_headers)
    try:
        res = SESSION.get(url, headers=headers, timeout=timeout)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        if DEBUG_MODE:
            st.error(f"Feed Error: {e}")
        return None

# ================= 价格归一化修复 =================
def normalize_em_price(raw_price, prev_close=None):
    raw_price = safe_float(raw_price)
    prev_close = safe_float(prev_close)
    if raw_price <= 0:
        return 0.0
    candidates = [raw_price, raw_price / 10, raw_price / 100, raw_price / 1000]
    candidates = [x for x in candidates if 0.01 <= x <= 100000]
    if not candidates:
        return raw_price
    if prev_close > 0:
        best = min(candidates, key=lambda x: abs(x - prev_close))
        return best
    if raw_price > 100000:
        return raw_price / 1000
    if raw_price > 10000:
        return raw_price / 100
    if raw_price > 1000:
        return raw_price / 10
    return raw_price

# ================= 技术面核心函数 =================
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema_short"] = df["close"].ewm(span=ema_short, adjust=False).mean()
    df["ema_mid"] = df["close"].ewm(span=ema_mid, adjust=False).mean()
    df["ema_long"] = df["close"].ewm(span=ema_long, adjust=False).mean()

    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    df["rsi14"] = 100 - (100 / (1 + rs))

    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    df["tr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr14"] = df["tr"].rolling(14).mean()

    ma20 = df["close"].rolling(20).mean()
    std20 = df["close"].rolling(20).std()
    df["bb_mid"] = ma20
    df["bb_up"] = ma20 + 2 * std20
    df["bb_low"] = ma20 - 2 * std20

    df["vol_ma20"] = df["volume"].rolling(20).mean()
    return df

def detect_swings(df: pd.DataFrame, left=2, right=2):
    swing_highs = []
    swing_lows = []
    if len(df) < left + right + 1:
        return swing_highs, swing_lows
    for i in range(left, len(df) - right):
        high = df["high"].iloc[i]
        low = df["low"].iloc[i]
        if high == df["high"].iloc[i-left: i+right+1].max():
            swing_highs.append((i, high))
        if low == df["low"].iloc[i-left: i+right+1].min():
            swing_lows.append((i, low))
    return swing_highs, swing_lows

def detect_fvg(df: pd.DataFrame, max_zones=5):
    zones = []
    if len(df) < 3:
        return zones
    for i in range(2, len(df)):
        c1 = df.iloc[i - 2]
        c3 = df.iloc[i]
        if c3["low"] > c1["high"]:
            zones.append({
                "type": "bullish",
                "start_idx": i - 2,
                "end_idx": i,
                "top": c3["low"],
                "bottom": c1["high"],
                "date": str(pd.to_datetime(c3["date"]).date())
            })
        if c3["high"] < c1["low"]:
            zones.append({
                "type": "bearish",
                "start_idx": i - 2,
                "end_idx": i,
                "top": c1["low"],
                "bottom": c3["high"],
                "date": str(pd.to_datetime(c3["date"]).date())
            })
    return zones[-max_zones:]

def detect_liquidity_sweep(df: pd.DataFrame):
    if len(df) < 25:
        return "样本不足"
    recent = df.tail(20).copy()
    latest = recent.iloc[-1]
    prev_high = recent.iloc[:-1]["high"].max()
    prev_low = recent.iloc[:-1]["low"].min()
    if latest["high"] > prev_high and latest["close"] < prev_high:
        return "向上扫流动性后回落"
    if latest["low"] < prev_low and latest["close"] > prev_low:
        return "向下扫流动性后收回"
    return "未见明显扫流动性"

def detect_bos(df: pd.DataFrame):
    swing_highs, swing_lows = detect_swings(df)
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "结构样本不足"
    latest_close = df.iloc[-1]["close"]
    last_swing_high = swing_highs[-1][1]
    last_swing_low = swing_lows[-1][1]
    if latest_close > last_swing_high:
        return "向上 BOS (结构突破)"
    if latest_close < last_swing_low:
        return "向下 BOS (结构破坏)"
    return "结构未突破"

def detect_order_blocks(df: pd.DataFrame, lookback=30, max_zones=4):
    zones = []
    recent = df.tail(lookback).reset_index(drop=True)
    if len(recent) < 3 or "atr14" not in recent.columns:
        return zones
    for i in range(1, len(recent) - 1):
        curr = recent.iloc[i]
        nxt = recent.iloc[i + 1]
        body_curr = abs(curr["close"] - curr["open"])
        atr = recent["atr14"].iloc[i]
        if pd.isna(atr):
            continue
        if curr["close"] < curr["open"] and nxt["close"] > curr["high"] and body_curr < atr * 1.2:
            zones.append({
                "type": "bullish_ob",
                "date": str(pd.to_datetime(curr["date"]).date()),
                "top": max(curr["open"], curr["close"]),
                "bottom": min(curr["open"], curr["close"])
            })
        if curr["close"] > curr["open"] and nxt["close"] < curr["low"] and body_curr < atr * 1.2:
            zones.append({
                "type": "bearish_ob",
                "date": str(pd.to_datetime(curr["date"]).date()),
                "top": max(curr["open"], curr["close"]),
                "bottom": min(curr["open"], curr["close"])
            })
    return zones[-max_zones:]

def detect_equal_high_low(df: pd.DataFrame, tolerance=0.003):
    swing_highs, swing_lows = detect_swings(df)
    eqh = []
    eql = []
    for i in range(len(swing_highs) - 1):
        h1 = swing_highs[i][1]
        h2 = swing_highs[i + 1][1]
        if h1 > 0 and abs(h1 - h2) / h1 <= tolerance:
            eqh.append((swing_highs[i], swing_highs[i + 1]))
    for i in range(len(swing_lows) - 1):
        l1 = swing_lows[i][1]
        l2 = swing_lows[i + 1][1]
        if l1 > 0 and abs(l1 - l2) / l1 <= tolerance:
            eql.append((swing_lows[i], swing_lows[i + 1]))
    return eqh[-3:], eql[-3:]

def detect_mss(df: pd.DataFrame):
    swing_highs, swing_lows = detect_swings(df)
    if len(swing_highs) < 2 or len(swing_lows) < 2 or len(df) < 2:
        return "样本不足"
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    last_high = swing_highs[-1][1]
    last_low = swing_lows[-1][1]
    if prev["close"] < last_high and latest["close"] > last_high:
        return "Bullish MSS (多头结构转换)"
    if prev["close"] > last_low and latest["close"] < last_low:
        return "Bearish MSS (空头结构转换)"
    return "暂无明显 MSS"

def get_premium_discount_zone(df: pd.DataFrame, lookback=60):
    recent = df.tail(lookback)
    if recent.empty:
        return None
    range_high = recent["high"].max()
    range_low = recent["low"].min()
    eq = (range_high + range_low) / 2
    latest_close = recent.iloc[-1]["close"]
    zone = "Equilibrium"
    if latest_close > eq:
        zone = "Premium Zone"
    elif latest_close < eq:
        zone = "Discount Zone"
    return {
        "range_high": range_high,
        "range_low": range_low,
        "equilibrium": eq,
        "zone": zone
    }

def build_smc_summary(df: pd.DataFrame):
    obs = detect_order_blocks(df)
    eqh, eql = detect_equal_high_low(df)
    mss = detect_mss(df)
    pd_zone = get_premium_discount_zone(df)
    latest_bull_ob = next((z for z in reversed(obs) if z["type"] == "bullish_ob"), None)
    latest_bear_ob = next((z for z in reversed(obs) if z["type"] == "bearish_ob"), None)
    return {
        "latest_bull_ob": latest_bull_ob,
        "latest_bear_ob": latest_bear_ob,
        "eqh": eqh,
        "eql": eql,
        "mss": mss,
        "pd_zone": pd_zone
    }

def summarize_technicals(df: pd.DataFrame):
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest
    trend = "震荡"
    if latest["close"] > latest["ema_short"] > latest["ema_mid"]:
        trend = "多头趋势"
    elif latest["close"] < latest["ema_short"] < latest["ema_mid"]:
        trend = "空头趋势"
    momentum = "中性"
    rsi = latest["rsi14"]
    if pd.notna(rsi):
        if rsi >= 70:
            momentum = "超买"
        elif rsi <= 30:
            momentum = "超卖"
        elif rsi > 55:
            momentum = "偏强"
        elif rsi < 45:
            momentum = "偏弱"
    macd_state = "中性"
    if latest["macd"] > latest["macd_signal"] and latest["macd_hist"] > prev["macd_hist"]:
        macd_state = "金叉后增强"
    elif latest["macd"] < latest["macd_signal"] and latest["macd_hist"] < prev["macd_hist"]:
        macd_state = "死叉后走弱"
    bb_state = "带内运行"
    if latest["close"] > latest["bb_up"]:
        bb_state = "突破布林上轨"
    elif latest["close"] < latest["bb_low"]:
        bb_state = "跌破布林下轨"
    vol_state = "量能平稳"
    if pd.notna(latest["vol_ma20"]) and latest["vol_ma20"] > 0:
        if latest["volume"] > latest["vol_ma20"] * 1.8:
            vol_state = "显著放量"
        elif latest["volume"] < latest["vol_ma20"] * 0.7:
            vol_state = "明显缩量"
    fvg_zones = detect_fvg(df)
    bos_state = detect_bos(df)
    sweep_state = detect_liquidity_sweep(df)
    nearest_bull_fvg = next((z for z in reversed(fvg_zones) if z["type"] == "bullish"), None)
    nearest_bear_fvg = next((z for z in reversed(fvg_zones) if z["type"] == "bearish"), None)
    smc = build_smc_summary(df)
    return {
        "trend": trend,
        "momentum": momentum,
        "macd_state": macd_state,
        "bb_state": bb_state,
        "vol_state": vol_state,
        "atr14": latest["atr14"],
        "rsi14": latest["rsi14"],
        "bos_state": bos_state,
        "sweep_state": sweep_state,
        "nearest_bull_fvg": nearest_bull_fvg,
        "nearest_bear_fvg": nearest_bear_fvg,
        "latest_close": latest["close"],
        "ema_short": latest["ema_short"],
        "ema_mid": latest["ema_mid"],
        "ema_long": latest["ema_long"],
        "smc": smc
    }

def build_price_figure(df: pd.DataFrame):
    plot_df = df.copy()
    plot_df["date_str"] = plot_df["date"].dt.strftime("%Y-%m-%d")

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.03, subplot_titles=('K 线与结构', '成交量'),
                        row_width=[0.2, 0.7])

    fig.add_trace(go.Candlestick(
        x=plot_df["date_str"],
        open=plot_df["open"],
        high=plot_df["high"],
        low=plot_df["low"],
        close=plot_df["close"],
        name="K线"
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["ema_short"], mode="lines", name=f"EMA{ema_short}", line=dict(width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["ema_mid"], mode="lines", name=f"EMA{ema_mid}", line=dict(width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=plot_df["date_str"], y=plot_df["ema_long"], mode="lines", name=f"EMA{ema_long}", line=dict(width=1)), row=1, col=1)

    colors = ['red' if row['open'] - row['close'] >= 0 else 'green' for index, row in plot_df.iterrows()]
    fig.add_trace(go.Bar(
        x=plot_df['date_str'],
        y=plot_df['volume'],
        marker_color=colors,
        name='成交量'
    ), row=2, col=1)

    for zone in detect_fvg(plot_df, max_zones=4):
        start_idx = zone["start_idx"]
        end_idx = min(len(plot_df) - 1, start_idx + 12)
        x0 = plot_df.iloc[start_idx]["date_str"]
        x1 = plot_df.iloc[end_idx]["date_str"]
        fillcolor = "rgba(0, 200, 0, 0.15)" if zone["type"] == "bullish" else "rgba(200, 0, 0, 0.15)"
        fig.add_shape(
            type="rect",
            x0=x0, x1=x1,
            y0=zone["bottom"], y1=zone["top"],
            line=dict(width=0),
            fillcolor=fillcolor,
            row=1, col=1
        )

    fig.update_layout(
        height=650,
        xaxis_rangeslider_visible=False,
        legend_title="图层",
        margin=dict(l=20, r=20, t=30, b=20),
        showlegend=False
    )
    return fig

# ================= 多周期数据与分析 =================
def normalize_min_df(df: pd.DataFrame):
    if df is None or df.empty:
        return None
    rename_map = {}
    for col in df.columns:
        if col in ["时间", "日期", "datetime", "date"]:
            rename_map[col] = "date"
        elif col == "开盘":
            rename_map[col] = "open"
        elif col == "收盘":
            rename_map[col] = "close"
        elif col == "最高":
            rename_map[col] = "high"
        elif col == "最低":
            rename_map[col] = "low"
        elif col in ["成交量", "volume"]:
            rename_map[col] = "volume"
    df = df.rename(columns=rename_map).copy()
    need_cols = ["date", "open", "high", "low", "close", "volume"]
    if not all(col in df.columns for col in need_cols):
        return None
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna().sort_values("date").reset_index(drop=True)
    return df[need_cols]

def get_intraday_15m(symbol, max_rows=320):
    try:
        df = ak.stock_zh_a_hist_min_em(symbol=str(symbol), period="15", adjust="")
        df = normalize_min_df(df)
        if df is not None and not df.empty:
            return df.tail(max_rows).reset_index(drop=True)
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"15分钟数据获取失败: {e}")
    return None

def aggregate_minutes(df_15m: pd.DataFrame, bars_per_group: int):
    if df_15m is None or df_15m.empty:
        return None
    all_parts = []
    df_15m = df_15m.copy()
    df_15m["trade_day"] = df_15m["date"].dt.date
    for _, day_df in df_15m.groupby("trade_day"):
        day_df = day_df.sort_values("date").reset_index(drop=True)
        grp = pd.Series(range(len(day_df))) // bars_per_group
        g = day_df.groupby(grp)
        part = pd.DataFrame({
            "date": g["date"].last(),
            "open": g["open"].first(),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(),
            "volume": g["volume"].sum()
        })
        all_parts.append(part)
    if not all_parts:
        return None
    out = pd.concat(all_parts, ignore_index=True)
    out = out.dropna().reset_index(drop=True)
    return out

def summarize_intraday_tf(df: pd.DataFrame, label: str):
    if df is None or df.empty:
        return {
            "label": label,
            "status": "无数据",
            "trend": "N/A",
            "rsi": None,
            "macd_state": "N/A",
            "support": None,
            "pressure": None,
            "close": None,
            "bias": "无法判断"
        }
    df = df.copy()
    if len(df) >= 12:
        df = add_indicators(df)
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        trend = "震荡"
        if pd.notna(latest["ema_short"]) and latest["close"] > latest["ema_short"]:
            trend = "偏强"
        if pd.notna(latest["ema_short"]) and pd.notna(latest["ema_mid"]) and latest["close"] > latest["ema_short"] > latest["ema_mid"]:
            trend = "多头"
        elif pd.notna(latest["ema_short"]) and pd.notna(latest["ema_mid"]) and latest["close"] < latest["ema_short"] < latest["ema_mid"]:
            trend = "空头"
        macd_state = "中性"
        if pd.notna(latest["macd"]) and pd.notna(latest["macd_signal"]):
            if latest["macd"] > latest["macd_signal"] and latest["macd_hist"] >= prev["macd_hist"]:
                macd_state = "偏多"
            elif latest["macd"] < latest["macd_signal"] and latest["macd_hist"] <= prev["macd_hist"]:
                macd_state = "偏空"
        support = df.tail(min(12, len(df)))["low"].min()
        pressure = df.tail(min(12, len(df)))["high"].max()
        bias_score = 0
        if trend in ["多头", "偏强"]:
            bias_score += 1
        if macd_state == "偏多":
            bias_score += 1
        if pd.notna(latest["rsi14"]) and latest["rsi14"] > 55:
            bias_score += 1
        if pd.notna(latest["rsi14"]) and latest["rsi14"] < 45:
            bias_score -= 1
        if macd_state == "偏空":
            bias_score -= 1
        if trend == "空头":
            bias_score -= 1
        if bias_score >= 2:
            bias = "多头占优"
        elif bias_score <= -2:
            bias = "空头占优"
        else:
            bias = "震荡分歧"
        return {
            "label": label,
            "status": "有效",
            "trend": trend,
            "rsi": latest["rsi14"] if pd.notna(latest["rsi14"]) else None,
            "macd_state": macd_state,
            "support": support,
            "pressure": pressure,
            "close": latest["close"],
            "bias": bias
        }
    latest = df.iloc[-1]
    support = df["low"].min()
    pressure = df["high"].max()
    return {
        "label": label,
        "status": "样本较少",
        "trend": "简化观察",
        "rsi": None,
        "macd_state": "N/A",
        "support": support,
        "pressure": pressure,
        "close": latest["close"],
        "bias": "轻量判断"
    }

def get_multi_timeframe_analysis(symbol: str):
    df15 = get_intraday_15m(symbol)
    df60 = aggregate_minutes(df15, 4) if df15 is not None else None
    df120 = aggregate_minutes(df15, 8) if df15 is not None else None
    tf15 = summarize_intraday_tf(df15, "15分钟")
    tf60 = summarize_intraday_tf(df60, "60分钟")
    tf120 = summarize_intraday_tf(df120, "120分钟")
    score = 0
    mapping = {"多头占优": 2, "轻量判断": 0, "震荡分歧": 0, "空头占优": -2}
    score += mapping.get(tf15["bias"], 0)
    score += mapping.get(tf60["bias"], 0)
    score += mapping.get(tf120["bias"], 0)
    if score >= 3:
        final_view = "多周期共振偏多"
    elif score <= -3:
        final_view = "多周期共振偏空"
    else:
        final_view = "多周期分歧，偏观察"
    return {
        "15m": tf15,
        "60m": tf60,
        "120m": tf120,
        "final_view": final_view
    }

# ================= 核心数据流 =================
@st.cache_data(ttl=60)
def get_global_news():
    url = "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=60&zhibo_id=152&tag_id=0&dire=f&dpc=1"
    res = fetch_json(url, extra_headers={"Referer": "https://finance.sina.com.cn/"})
    news = []
    if res and res.get("result", {}).get("data", {}).get("feed", {}).get("list"):
        for item in res["result"]["data"]["feed"]["list"]:
            text = re.sub(r'<[^>]+>', '', str(item.get("rich_text", "")).strip())
            if len(text) > 15:
                news.append(f"[{item.get('create_time', '')}] {text}")
    return news

@st.cache_data(ttl=60)
def get_market_pulse():
    pulse = {}
    indices = {"上证指数": "1.000001", "深证成指": "0.399001", "创业板指": "0.399006"}
    for name, code in indices.items():
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={code}&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f43,f170"
        res = fetch_json(url)
        if res and res.get("data"):
            pulse[name] = {"price": safe_float(res["data"].get("f43")), "pct": safe_float(res["data"].get("f170"))}
    cnh_url = "https://push2.eastmoney.com/api/qt/stock/get?secid=133.USDCNH&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f43,f170"
    cnh_res = fetch_json(cnh_url)
    if cnh_res and cnh_res.get("data"):
        pulse["USD/CNH(离岸)"] = {"price": safe_float(cnh_res["data"].get("f43")), "pct": safe_float(cnh_res["data"].get("f170"))}
    return pulse

@st.cache_data(ttl=300)
def get_hot_blocks():
    try:
        df = ak.stock_board_industry_name_em()
        if df is not None and not df.empty:
            top_blocks = df.sort_values(by="涨跌幅", ascending=False).head(10)
            return top_blocks[["板块名称", "涨跌幅", "上涨家数", "下跌家数", "领涨股票"]].to_dict('records')
    except Exception:
        pass
    time.sleep(1)
    try:
        df = ak.stock_board_concept_name_em()
        if df is not None and not df.empty:
            top_blocks = df.sort_values(by="涨跌幅", ascending=False).head(10)
            return top_blocks[["板块名称", "涨跌幅", "上涨家数", "下跌家数", "领涨股票"]].to_dict('records')
    except Exception:
        pass
    return None

def get_stock_quote(symbol):
    try:
        spot_df = ak.stock_zh_a_spot_em()
        if spot_df is not None and not spot_df.empty:
            row = spot_df[spot_df["代码"].astype(str) == str(symbol)]
            if not row.empty:
                row = row.iloc[0]
                return {
                    "name": row.get("名称", "未知"),
                    "price": safe_float(row.get("最新价")),
                    "pct": safe_float(row.get("涨跌幅")),
                    "market_cap": safe_float(row.get("总市值")) / 100000000,
                    "pe": row.get("市盈率-动态", "-"),
                    "pb": row.get("市净率", "-"),
                    "turnover": safe_float(row.get("换手率"))
                }
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"AKShare 实时行情失败，回退东财: {e}")
    market = "1" if str(symbol).startswith(("6", "9", "5", "7")) else "0"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={market}.{symbol}&ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&fields=f58,f43,f60,f170,f116,f162,f168,f167"
    res = fetch_json(url)
    if res and res.get("data"):
        d = res["data"]
        prev_close = safe_float(d.get("f60"))
        price = normalize_em_price(d.get("f43"), prev_close)
        return {
            "name": d.get("f58", "未知"),
            "price": price,
            "pct": safe_float(d.get("f170")),
            "market_cap": safe_float(d.get("f116")) / 100000000,
            "pe": d.get("f162", "-"),
            "pb": d.get("f167", "-"),
            "turnover": safe_float(d.get("f168"))
        }
    return None

def get_kline(symbol, days=220):
    end_date = datetime.now()
    start_date = end_date - pd.Timedelta(days=days + 150)
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    start_str_bs = start_date.strftime("%Y-%m-%d")
    end_str_bs = end_date.strftime("%Y-%m-%d")
    try:
        df = ak.stock_zh_a_hist(symbol=str(symbol), period="daily", start_date=start_str, end_date=end_str, adjust="qfq")
        if df is not None and not df.empty:
            df = df.rename(columns={
                "日期": "date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume",
                "成交额": "amount", "换手率": "turnover_rate"
            })
            keep_cols = ["date", "open", "high", "low", "close", "volume", "turnover_rate"]
            if all(col in df.columns for col in keep_cols):
                df = df[keep_cols].copy()
                df["date"] = pd.to_datetime(df["date"])
                for col in ["open", "high", "low", "close", "volume", "turnover_rate"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna().reset_index(drop=True)
                if len(df) > 0:
                    return df.tail(days).reset_index(drop=True)
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"AKShare qfq 降级失败: {e}")
    try:
        df = ak.stock_zh_a_hist(symbol=str(symbol), period="daily", start_date=start_str, end_date=end_str, adjust="")
        if df is not None and not df.empty:
            df = df.rename(columns={
                "日期": "date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume"
            })
            keep_cols = ["date", "open", "high", "low", "close", "volume"]
            if all(col in df.columns for col in keep_cols):
                df = df[keep_cols].copy()
                df["date"] = pd.to_datetime(df["date"])
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna().reset_index(drop=True)
                if len(df) > 0:
                    return df.tail(days).reset_index(drop=True)
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"AKShare raw 降级失败: {e}")
    try:
        bs.login()
        bs_code = f"sh.{symbol}" if str(symbol).startswith(("6", "9", "5", "7")) else f"sz.{symbol}"
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume",
            start_date=start_str_bs, end_date=end_str_bs,
            frequency="d", adjustflag="2"
        )
        data_list = []
        while (rs.error_code == '0') & rs.next():
            data_list.append(rs.get_row_data())
        bs.logout()
        if data_list:
            df = pd.DataFrame(data_list, columns=rs.fields)
            df["date"] = pd.to_datetime(df["date"])
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna().sort_values("date").reset_index(drop=True)
            if len(df) > 0:
                return df.tail(days).reset_index(drop=True)
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"Baostock 降级失败: {e}")
        try:
            bs.logout()
        except Exception:
            pass
    try:
        if ts_token:
            pro = ts.pro_api()
            market = ".SH" if str(symbol).startswith(("6", "9", "5", "7")) else ".SZ"
            ts_code = f"{symbol}{market}"
            df = pro.daily(ts_code=ts_code, start_date=start_str, end_date=end_str)
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "trade_date": "date", "open": "open",
                    "high": "high", "low": "low",
                    "close": "close", "vol": "volume"
                })
                keep_cols = ["date", "open", "high", "low", "close", "volume"]
                if all(col in df.columns for col in keep_cols):
                    df = df[keep_cols].copy()
                    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
                    for col in ["open", "high", "low", "close", "volume"]:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                    df = df.dropna().sort_values("date").reset_index(drop=True)
                    if len(df) > 0:
                        return df.tail(days).reset_index(drop=True)
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"Tushare 兜底失败: {e}")
    return None

# ================= AI 计算核心 =================
def call_ai(prompt, model=None, temperature=0.3):
    try:
        exec_model = model if model else selected_model
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=exec_model,
            temperature=temperature
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"❌ AI 计算节点故障: {e}"
# ================= 宏观分析与数据采集模块 (整合版) =================
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class MacroAnalysisDataFetcher:
    """宏观分析板块数据获取器"""
    NBS_URL = "https://data.stats.gov.cn/easyquery.htm"
    NBS_SERIES_CONFIG = {
        "gdp_yoy": {"dbcode": "hgjd", "group_code": "A0103", "series_code": "A010301", "label": "GDP当季同比", "unit": "%", "period": "LAST8", "transform": "index_minus_100"},
        "industrial_yoy": {"dbcode": "hgyd", "group_code": "A0201", "series_code": "A020101", "label": "规上工业增加值同比", "unit": "%", "period": "LAST8"},
        "cpi_yoy": {"dbcode": "hgyd", "group_code": "A01010J", "series_code": "A01010J01", "label": "CPI同比", "unit": "%", "period": "LAST8", "transform": "index_minus_100"},
        "ppi_yoy": {"dbcode": "hgyd", "group_code": "A010801", "series_code": "A01080101", "label": "PPI同比", "unit": "%", "period": "LAST8", "transform": "index_minus_100"},
        "manufacturing_pmi": {"dbcode": "hgyd", "group_code": "A0B01", "series_code": "A0B0101", "label": "制造业PMI", "unit": "", "period": "LAST8"},
        "non_manufacturing_pmi": {"dbcode": "hgyd", "group_code": "A0B02", "series_code": "A0B0201", "label": "非制造业商务活动指数", "unit": "", "period": "LAST8"},
        "m2_yoy": {"dbcode": "hgyd", "group_code": "A0D01", "series_code": "A0D0102", "label": "M2同比", "unit": "%", "period": "LAST8"},
        "retail_sales_yoy": {"dbcode": "hgyd", "group_code": "A0701", "series_code": "A070104", "label": "社零累计同比", "unit": "%", "period": "LAST8"},
        "fixed_asset_yoy": {"dbcode": "hgyd", "group_code": "A0401", "series_code": "A040102", "label": "固定资产投资累计同比", "unit": "%", "period": "LAST8"},
        "real_estate_invest_yoy": {"dbcode": "hgyd", "group_code": "A0601", "series_code": "A060102", "label": "房地产开发投资累计同比", "unit": "%", "period": "LAST8"},
        "urban_unemployment": {"dbcode": "hgyd", "group_code": "A0E01", "series_code": "A0E0101", "label": "全国城镇调查失业率", "unit": "%", "period": "LAST8"},
    }
    A_SHARE_INDEX_CONFIG = {"上证指数": "sh000001", "深证成指": "sz399001", "创业板指": "sz399006", "沪深300": "sh000300"}
    SECTOR_STOCK_POOLS = {
        "银行": [{"code": "600036", "name": "招商银行"}, {"code": "601166", "name": "兴业银行"}],
        "券商": [{"code": "300059", "name": "东方财富"}, {"code": "600030", "name": "中信证券"}],
        "半导体": [{"code": "002371", "name": "北方华创"}, {"code": "688981", "name": "中芯国际"}],
        "算力AI": [{"code": "300308", "name": "中际旭创"}, {"code": "601138", "name": "工业富联"}],
        "消费电子": [{"code": "002475", "name": "立讯精密"}, {"code": "300433", "name": "蓝思科技"}],
        "房地产": [{"code": "600048", "name": "保利发展"}, {"code": "000002", "name": "万科A"}],
        "医药": [{"code": "600276", "name": "恒瑞医药"}, {"code": "688235", "name": "百济神州"}]
    }
    SECTOR_ALIASES = {"AI": ["算力AI"], "红利": ["银行", "煤炭"]}

    def fetch_all_data(self) -> Dict[str, Any]:
        result = {"success": False, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "macro_series": {}, "macro_snapshot": {}, "macro_tables": {}, "market_indices": {}, "news": [], "candidate_pools": self.SECTOR_STOCK_POOLS, "rule_based_sector_view": {}, "errors": []}
        for key, config in self.NBS_SERIES_CONFIG.items():
            try:
                result["macro_series"][key] = self._fetch_nbs_series(config)
            except Exception as exc:
                result["errors"].append(f"{config['label']}: {exc}")
        result["macro_snapshot"] = self._build_macro_snapshot(result["macro_series"])
        result["macro_tables"] = self._build_macro_tables(result["macro_series"])
        result["rule_based_sector_view"] = self.build_rule_based_sector_view(result["macro_snapshot"])
        try: result["market_indices"] = self._fetch_market_indices()
        except Exception as exc: result["errors"].append(f"市场指数: {exc}")
        try: result["news"] = self._fetch_macro_news()
        except Exception as exc: result["errors"].append(f"宏观新闻: {exc}")
        result["success"] = bool(result["macro_snapshot"])
        return result

    def _fetch_nbs_series(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        params = {"m": "QueryData", "dbcode": config["dbcode"], "rowcode": "zb", "colcode": "sj", "wds": "[]", "dfwds": json.dumps([{"wdcode": "zb", "valuecode": config["group_code"]}, {"wdcode": "sj", "valuecode": config["period"]}], ensure_ascii=False), "k1": str(int(time.time() * 1000))}
        res = requests.post(self.NBS_URL, params=params, verify=False, timeout=15)
        data = res.json()["returndata"]
        indicator_nodes = {item["code"]: item for item in data["wdnodes"][0]["nodes"]}
        time_nodes = {item["code"]: item for item in data["wdnodes"][1]["nodes"]}
        rows = []
        for node in data["datanodes"]:
            match = re.search(r"zb\.([^_]+)_sj\.([^_]+)", node["code"])
            if not match or match.group(1) != config["series_code"]: continue
            val = node.get("data", {}).get("data")
            if val in ("", None) or node.get("data", {}).get("strdata") == "": continue
            v_raw = float(val)
            v_trans = round(v_raw - 100, 2) if config.get("transform") == "index_minus_100" else round(v_raw, 2)
            rows.append({"series_code": match.group(1), "series_label": config["label"], "period_code": match.group(2), "period_label": time_nodes.get(match.group(2), {}).get("cname", ""), "value_raw": v_raw, "value": v_trans, "unit": config.get("unit", "")})
        return sorted(rows, key=lambda x: x["period_code"], reverse=True)

    def _build_macro_snapshot(self, macro_series):
        snapshot = {}
        for k, s in macro_series.items():
            if not s: continue
            latest, prev = s[0], s[1] if len(s) > 1 else None
            snapshot[k] = {"label": latest["series_label"], "value": latest["value"], "value_raw": latest["value_raw"], "unit": latest["unit"], "period_label": latest["period_label"], "change": round(latest["value"] - prev["value"], 2) if prev else None}
        return snapshot

    def _build_macro_tables(self, macro_series):
        return {k: pd.DataFrame([{"期间": i["period_label"], "数值": i["value"], "原始值": i["value_raw"], "单位": i["unit"] or "-"} for i in s]) for k, s in macro_series.items() if s}

    def _fetch_market_indices(self):
        res = {}
        for label, symbol in self.A_SHARE_INDEX_CONFIG.items():
            df = ak.stock_zh_index_daily(symbol=symbol)
            if df is None or df.empty: continue
            latest, prev = df.iloc[-1], df.iloc[-2] if len(df) > 1 else df.iloc[-1]
            res[label] = {"close": round(float(latest["close"]), 2), "date": str(latest["date"]), "daily_change_pct": round(((float(latest["close"]) - float(prev["close"])) / float(prev["close"])) * 100, 2) if float(prev["close"]) != 0 else 0.0, "pct_20d": self._calc_return(df, 20), "pct_60d": self._calc_return(df, 60)}
        return res

    def _fetch_macro_news(self):
        df = ak.stock_info_global_em()
        if df is None or df.empty: return []
        kw = ["财政", "货币", "央行", "地产", "消费", "PMI", "CPI"]
        return [{"title": r["标题"], "summary": str(r.get("摘要", ""))[:180], "publish_time": str(r.get("发布时间", ""))} for _, r in df.iterrows() if any(k in str(r.get("标题")) or k in str(r.get("摘要")) for k in kw)][:12]

    def _calc_return(self, df, days):
        if len(df) <= days: return 0.0
        base = float(df.iloc[-days - 1]["close"])
        return round((float(df.iloc[-1]["close"]) - base) / base * 100, 2) if base != 0 else 0.0

    def build_rule_based_sector_view(self, snapshot):
        return {"market_view": "结构性机会为主", "bullish_sectors": [], "bearish_sectors": [], "watch_signals": []}

    def build_stock_candidates_for_sectors(self, sectors):
        return [s for sec in sectors for s in self.SECTOR_STOCK_POOLS.get(sec, [])][:10]

    def build_prompt_context(self, data):
        lines = ["===== 当前国内宏观数据快照 ====="]
        for k, v in data.get("macro_snapshot", {}).items():
            lines.append(f"- {v['label']}: {v['value']}{v['unit']} ({v['period_label']})")
        lines.append("\n===== A股指数快照 =====")
        for k, v in data.get("market_indices", {}).items():
            lines.append(f"- {k}: {v['close']}, 日涨跌 {v['daily_change_pct']}%")
        lines.append("\n===== 可选板块池 =====\n" + "、".join(self.SECTOR_STOCK_POOLS.keys()))
        return "\n".join(lines)


class MacroAnalysisAgents:
    """基于主程序 call_ai 接口的宏观智能体集群"""
    def macro_analyst_agent(self, context_text: str) -> Dict:
        prompt = f"你是一位资深中国宏观经济研究员。请严格基于下面的数据，分析当前国内宏观经济形势。\n\n{context_text}\n重点回答：1.当前经济所处阶段。2.核心矛盾。3.关键跟踪变量。4.对A股投资的影响。"
        return self._call_text("你是中国宏观经济分析师", prompt, "宏观总量分析师", ["增长", "通胀", "信用"])

    def policy_analyst_agent(self, context_text: str) -> Dict:
        prompt = f"你是一位资深的政策与流动性分析师。请基于以下数据评估中国政策环境与流动性。\n\n{context_text}\n重点回答：1.当前政策组合倾向。2.流动性对A股估值的支撑。3.A股风格与板块轮动含义。"
        return self._call_text("你是政策流动性分析师", prompt, "政策流动性分析师", ["货币", "财政", "风格"])

    def sector_mapper_agent(self, context_text: str, sector_pool: List[str]) -> Dict:
        prompt = f"你是行业配置分析师。请结合数据，从以下板块池选择未来1季度受益和承压板块。\n板块池：{', '.join(sector_pool)}\n\n数据：\n{context_text}\n请只返回JSON：{{\"market_view\": \"...\", \"bullish_sectors\": [{{\"sector\":\"银行\", \"logic\":\"...\"}}], \"bearish_sectors\": []}}"
        structured = self._call_json("只输出合法JSON", prompt, {"market_view": "结构性震荡", "bullish_sectors": [], "bearish_sectors": []})
        analysis_prompt = f"请基于以下JSON写一份A股行业配置报告：\n{json.dumps(structured, ensure_ascii=False)}\n包含市场主线、看多/看空逻辑及传导链。"
        analysis = call_ai(f"你是A股行业配置专家\n\n{analysis_prompt}")
        return {"agent_name": "行业映射分析师", "analysis": analysis, "structured": structured}

    def stock_selector_agent(self, context_text: str, sector_view: Dict, stock_candidates: List[Dict]) -> Dict:
        cand_str = json.dumps(stock_candidates, ensure_ascii=False)
        prompt = f"你是选股分析师。结合行业视图从候选池中选股。\n行业视图：\n{json.dumps(sector_view, ensure_ascii=False)}\n候选池：\n{cand_str}\n请只返回JSON格式包含 'recommended_stocks' 和 'watchlist'。"
        structured = self._call_json("只输出合法JSON", prompt, {"recommended_stocks": stock_candidates[:2], "watchlist": []})
        analysis_prompt = f"请基于结构化结果写一份选股说明：\n{json.dumps(structured, ensure_ascii=False)}\n解释适配逻辑，指出催化剂与风险。"
        analysis = call_ai(f"你是A股选股专家\n\n{analysis_prompt}")
        return {"agent_name": "优质标的分析师", "analysis": analysis, "structured": structured}

    def chief_strategist_agent(self, context_text: str, macro_report: str, policy_report: str, sector_view: Dict) -> Dict:
        prompt = f"你是首席策略官，请给出A股后市综合报告。\n\n宏观数据：\n{context_text}\n\n【宏观研判】\n{macro_report}\n\n【政策研判】\n{policy_report}\n\n【行业映射】\n{json.dumps(sector_view, ensure_ascii=False)}\n\n要求输出：宏观判断、后市展望、利多利空板块及风险跟踪。"
        return self._call_text("你是首席策略官", prompt, "首席策略官", ["总策略", "配置"])

    def _call_text(self, sys_prompt, user_prompt, agent_name, focus_areas):
        res = call_ai(f"{sys_prompt}\n\n{user_prompt}")
        return {"agent_name": agent_name, "analysis": res, "focus_areas": focus_areas}

    def _call_json(self, sys_prompt, user_prompt, fallback):
        res = call_ai(f"{sys_prompt}\n\n{user_prompt}")
        if not res: return fallback
        match = re.search(r"(\{.*\})", res.strip(), re.S)
        if match:
            try: return json.loads(match.group(1))
            except: pass
        return fallback

class MacroAnalysisEngine:
    def run_full_analysis(self, progress_callback=None):
        results = {"success": False, "raw_data": {}, "agents_analysis": {}, "sector_view": {}, "candidate_stocks": [], "errors": []}
        try:
            fetcher = MacroAnalysisDataFetcher()
            agents = MacroAnalysisAgents()
            if progress_callback: progress_callback(10, "正在获取国家统计局宏观数据...")
            raw_data = fetcher.fetch_all_data()
            results["raw_data"] = raw_data
            ctx = fetcher.build_prompt_context(raw_data)
            
            if progress_callback: progress_callback(30, "宏观与政策分析师正在研判...")
            macro_res = agents.macro_analyst_agent(ctx)
            policy_res = agents.policy_analyst_agent(ctx)
            
            if progress_callback: progress_callback(60, "行业分析师生成映射...")
            sector_res = agents.sector_mapper_agent(ctx, list(fetcher.SECTOR_STOCK_POOLS.keys()))
            sector_view = sector_res.get("structured", {})
            
            bullish_sectors = [s.get("sector") for s in sector_view.get("bullish_sectors", []) if s.get("sector")]
            cands = fetcher.build_stock_candidates_for_sectors(bullish_sectors)
            results["candidate_stocks"] = cands
            
            if progress_callback: progress_callback(80, "筛选标的与生成最终策略...")
            stock_res = agents.stock_selector_agent(ctx, sector_view, cands)
            chief_res = agents.chief_strategist_agent(ctx, macro_res["analysis"], policy_res["analysis"], sector_view)
            
            results["agents_analysis"] = {"macro": macro_res, "policy": policy_res, "sector": sector_res, "stock": stock_res, "chief": chief_res}
            results["sector_view"] = sector_view
            results["stock_view"] = stock_res.get("structured", {})
            results["success"] = True
            if progress_callback: progress_callback(100, "分析完成")
        except Exception as e:
            results["error"] = str(e)
        return results

# ====== 宏观 UI 渲染函数 ======
def display_macro_analysis_ui():
    st.info("本板块通过国家统计局官方接口抓取最新宏观经济数据，并联动 AI 多智能体进行 A 股大势研判与行业映射。")
    if st.button("🚀 启动全局宏观深度推演", type="primary", use_container_width=True):
        if not api_key:
            st.error("配置缺失: GROQ_API_KEY")
            return
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        def p_call(pct, txt):
            progress_bar.progress(pct)
            status_text.text(txt)
            
        engine = MacroAnalysisEngine()
        res = engine.run_full_analysis(progress_callback=p_call)
        progress_bar.empty()
        status_text.empty()
        
        if res.get("success"):
            st.success("推演完成！")
            mt1, mt2, mt3, mt4 = st.tabs(["📌 首席综合结论", "📊 宏观核心数据", "🏭 行业多空映射", "🧠 智能体推演过程"])
            with mt1:
                st.markdown(res["agents_analysis"]["chief"]["analysis"])
            with mt2:
                st.write("##### 国家统计局最新宏观快照")
                snap = res["raw_data"].get("macro_snapshot", {})
                if snap:
                    df_snap = pd.DataFrame([{"指标": v["label"], "最新值": f"{v['value']}{v['unit']}", "发布期": v["period_label"], "环比/同比变动": f"{v['change']:+.2f}{v['unit']}" if v.get("change") else "-"} for k,v in snap.items()])
                    st.dataframe(df_snap, use_container_width=True, hide_index=True)
            with mt3:
                st.markdown(res["agents_analysis"]["sector"]["analysis"])
            with mt4:
                with st.expander("宏观总量分析师报告"): st.markdown(res["agents_analysis"]["macro"]["analysis"])
                with st.expander("政策流动性分析师报告"): st.markdown(res["agents_analysis"]["policy"]["analysis"])
                with st.expander("优质标的筛选报告"): st.markdown(res["agents_analysis"]["stock"]["analysis"])
        else:
            st.error(f"推演失败: {res.get('error')}")
# ================= 宏观分析板块结束 =================
# ================= 智瞰龙虎榜数据与分析模块 =================
class LonghubangDataFetcher:
    """龙虎榜数据获取类"""
    def __init__(self, api_key=None):
        self.base_url = "http://lhb-api.ws4.cn/v1"
        self.api_key = api_key
        self.max_retries = 3
        self.retry_delay = 2
        self.request_delay = 0.025

    def _safe_request(self, url, params=None):
        for attempt in range(self.max_retries):
            try:
                response = requests.get(url, params=params, timeout=10)
                time.sleep(self.request_delay)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('code') == 20000:
                        return data
                    else:
                        if DEBUG_MODE: st.warning(f"API返回错误: {data.get('msg', '未知错误')}")
                        return None
                else:
                    if DEBUG_MODE: st.warning(f"HTTP错误: {response.status_code}")
            except Exception as e:
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    return None
        return None

    def get_longhubang_data(self, date):
        url = f"{self.base_url}/youzi/all"
        params = {'date': date}
        return self._safe_request(url, params)

    def parse_to_dataframe(self, data_list):
        if not data_list:
            return pd.DataFrame()
        df = pd.DataFrame(data_list)
        column_mapping = {
            'yzmc': '游资名称', 'yyb': '营业部', 'sblx': '榜单类型',
            'gpdm': '股票代码', 'gpmc': '股票名称', 'mrje': '买入金额',
            'mcje': '卖出金额', 'jlrje': '净流入金额', 'rq': '日期', 'gl': '概念'
        }
        df = df.rename(columns=column_mapping)
        numeric_columns = ['买入金额', '卖出金额', '净流入金额']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        if '净流入金额' in df.columns:
            df = df.sort_values('净流入金额', ascending=False)
        return df

    def analyze_data_summary(self, data_list):
        if not data_list:
            return {}
        df = self.parse_to_dataframe(data_list)
        summary = {
            'total_records': len(df),
            'total_stocks': df['股票代码'].nunique() if '股票代码' in df.columns else 0,
            'total_youzi': df['游资名称'].nunique() if '游资名称' in df.columns else 0,
            'total_buy_amount': df['买入金额'].sum() if '买入金额' in df.columns else 0,
            'total_sell_amount': df['卖出金额'].sum() if '卖出金额' in df.columns else 0,
            'total_net_inflow': df['净流入金额'].sum() if '净流入金额' in df.columns else 0,
        }
        if '游资名称' in df.columns and '净流入金额' in df.columns:
            top_youzi = df.groupby('游资名称')['净流入金额'].sum().sort_values(ascending=False)
            summary['top_youzi'] = top_youzi.head(10).to_dict()
        if '股票代码' in df.columns and '净流入金额' in df.columns:
            top_stocks = df.groupby(['股票代码', '股票名称'])['净流入金额'].sum().sort_values(ascending=False)
            summary['top_stocks'] = [
                {'code': code, 'name': name, 'net_inflow': amount}
                for (code, name), amount in top_stocks.head(20).items()
            ]
        if '概念' in df.columns:
            all_concepts = []
            for concepts in df['概念'].dropna():
                all_concepts.extend([c.strip() for c in str(concepts).split(',')])
            concept_counter = Counter(all_concepts)
            summary['hot_concepts'] = dict(concept_counter.most_common(20))
        return summary

    def format_data_for_ai(self, data_list, summary=None):
        if not data_list:
            return "暂无龙虎榜数据"
        df = self.parse_to_dataframe(data_list)
        if summary is None:
            summary = self.analyze_data_summary(data_list)
        text_parts = []
        text_parts.append(f"""
【龙虎榜总体概况】
数据时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
记录总数: {summary.get('total_records', 0)}
涉及股票: {summary.get('total_stocks', 0)} 只
涉及游资: {summary.get('total_youzi', 0)} 个
总买入金额: {summary.get('total_buy_amount', 0):,.2f} 元
总卖出金额: {summary.get('total_sell_amount', 0):,.2f} 元
净流入金额: {summary.get('total_net_inflow', 0):,.2f} 元
""")
        if summary.get('top_youzi'):
            text_parts.append("\n【活跃游资 TOP10】")
            for idx, (name, amount) in enumerate(summary['top_youzi'].items(), 1):
                text_parts.append(f"{idx}. {name}: {amount:,.2f} 元")
        if summary.get('top_stocks'):
            text_parts.append("\n【资金净流入 TOP20股票】")
            for idx, stock in enumerate(summary['top_stocks'], 1):
                text_parts.append(f"{idx}. {stock['name']}({stock['code']}): {stock['net_inflow']:,.2f} 元")
        if summary.get('hot_concepts'):
            text_parts.append("\n【热门概念 TOP20】")
            for idx, (concept, count) in enumerate(list(summary['hot_concepts'].items())[:20], 1):
                text_parts.append(f"{idx}. {concept}: {count} 次")
        text_parts.append("\n【详细交易记录 TOP50】")
        for idx, row in df.head(50).iterrows():
            text_parts.append(
                f"{row.get('游资名称', 'N/A')} | "
                f"{row.get('股票名称', 'N/A')}({row.get('股票代码', 'N/A')}) | "
                f"买入:{row.get('买入金额', 0):,.0f} "
                f"卖出:{row.get('卖出金额', 0):,.0f} "
                f"净流入:{row.get('净流入金额', 0):,.0f} | "
                f"日期:{row.get('日期', 'N/A')}"
            )
        return "\n".join(text_parts)

class LonghubangAgents:
    """龙虎榜AI分析师集合 (整合主干引擎)"""
    def __init__(self):
        pass # 已复用主程序 call_ai 接口，无需初始化 DeepSeek 客户端

    def youzi_behavior_analyst(self, longhubang_data: str, summary: Dict) -> Dict[str, Any]:
        youzi_info = ""
        if summary.get('top_youzi'):
            youzi_info = "\n【活跃游资统计】\n"
            for idx, (name, amount) in enumerate(list(summary['top_youzi'].items())[:15], 1):
                youzi_info += f"{idx}. {name}: 净流入 {amount:,.2f} 元\n"

        prompt = f"""
你是一名资深的游资研究专家，擅长从龙虎榜数据中洞察游资意图和操作手法。拥有10年以上的龙虎榜数据分析经验，深谙各路游资的操作风格和盈利模式。

【龙虎榜数据概况】
记录总数: {summary.get('total_records', 0)}
涉及股票: {summary.get('total_stocks', 0)} 只
涉及游资: {summary.get('total_youzi', 0)} 个
总买入金额: {summary.get('total_buy_amount', 0):,.2f} 元
总卖出金额: {summary.get('total_sell_amount', 0):,.2f} 元
净流入金额: {summary.get('total_net_inflow', 0):,.2f} 元

{youzi_info}

{longhubang_data[:8000]}

请基于以上龙虎榜数据，进行深入的游资行为分析：
1. **活跃游资识别与画像** ⭐ 核心
   - 识别当前最活跃的5-8个游资席位
   - 分析每个游资的操作风格（激进型/稳健型/超短型/波段型）
   - 评估游资的胜率和成功案例
   - 识别知名"牛散"和"游资大佬"
2. **游资操作特征分析**
   - 分析游资的买入特征（追高/低吸/打板/潜伏）
   - 分析游资的卖出特征（一日游/持有周期/止盈止损）
   - 识别游资的联合操作和接力特征
   - 判断游资是否存在抱团现象
3. **游资目标股票分析**
   - 分析游资重点关注的股票（前10只）
   - 识别游资集体看好的股票（多席位介入）
   - 分析游资选股的共性特征（题材/概念/技术形态）
   - 评估游资介入股票的后续爆发力
4. **游资进出节奏**
   - 判断游资整体是进攻还是防守状态
   - 分析游资对热点的跟随速度
   - 识别游资撤退的信号和板块
   - 评估游资的持续作战能力
5. **游资与题材的匹配**
   - 分析游资偏好的题材和概念
   - 识别游资正在炒作的热点
   - 判断题材的炒作周期位置
   - 预判下一个游资可能关注的题材
6. **风险与机会提示**
   - 识别游资可能设置的"陷阱"股票
   - 提示游资一致性过高的风险（容易崩盘）
   - 发现游资刚开始介入的潜力股
   - 评估跟随游资的风险收益比
7. **投资策略建议**
   - 推荐3-5只游资看好的潜力股票
   - 提示2-3只游资可能出货的风险股票
   - 给出跟随游资的操作建议
   - 提供仓位和止损建议

请给出专业、实战性强的游资行为分析报告。
"""
        analysis = call_ai(prompt)
        return {
            "agent_name": "游资行为分析师",
            "agent_role": "分析游资操作特征、意图和目标股票",
            "analysis": analysis,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    def stock_potential_analyst(self, longhubang_data: str, summary: Dict) -> Dict[str, Any]:
        stock_info = ""
        if summary.get('top_stocks'):
            stock_info = "\n【热门股票统计】\n"
            for idx, stock in enumerate(summary['top_stocks'][:20], 1):
                stock_info += f"{idx}. {stock['name']}({stock['code']}): 净流入 {stock['net_inflow']:,.2f} 元\n"

        prompt = f"""
你是一名资深的个股研究专家和短线交易高手，精通技术分析和资金分析，擅长从龙虎榜中挖掘短期爆发股。

【龙虎榜数据概况】
记录总数: {summary.get('total_records', 0)}
涉及股票: {summary.get('total_stocks', 0)} 只
涉及游资: {summary.get('total_youzi', 0)} 个

{stock_info}

{longhubang_data[:8000]}

请基于以上龙虎榜数据，进行深入的个股潜力分析：
1. **次日大概率上涨股票挖掘** ⭐⭐⭐ 最核心
   - 识别5-8只次日大概率上涨的股票
   - 详细分析每只股票的上涨逻辑（资金面、技术面、题材面）
   - 评估每只股票的上涨空间和确定性（高/中/低）
   - 给出具体的买入价位和止损位
2. **资金流向强度分析**
   - 识别主力资金大幅流入的股票（净买入前10）
   - 分析资金流入的集中度和持续性
   - 识别多席位联合买入的股票（强烈看好信号）
   - 判断资金流入是真实买入还是诱多
3. **技术形态评估**
   - 分析上榜股票的技术位置（突破/回调/整理）
   - 识别处于启动阶段的股票
   - 评估股票的技术支撑和阻力
   - 判断股票的短期走势方向
4. **题材与概念分析**
   - 识别当前最热门的题材和概念
   - 分析题材的持续性和爆发力
   - 找出题材龙头和低位补涨股
   - 预判题材的炒作周期
5. **游资持仓分析**
   - 识别游资重仓持有的股票
   - 分析游资的一致性程度
   - 判断游资是建仓、加仓还是出货
   - 评估游资持仓的稳定性
6. **上榜类型分析**
   - 分析日榜和三日榜的差异
   - 识别连续上榜的股票（关注度高）
   - 判断上榜的性质（放量突破/涨停板/异常波动）
   - 评估不同上榜类型的后续表现概率
7. **风险股票识别**
   - 识别3-5只高风险股票（游资可能出货）
   - 分析卖出金额大于买入金额的股票
   - 提示游资一日游后撤离的股票
   - 警示技术面走坏的股票
8. **操作策略建议**
   - 推荐5-8只次日重点关注的股票（按优先级排序）
   - 给出每只股票的买入逻辑、买入价位、目标价位、止损价位
   - 提供仓位分配建议
   - 给出持有周期建议（超短/短线/波段）

务必重点分析次日大概率上涨的股票！
"""
        analysis = call_ai(prompt)
        return {
            "agent_name": "个股潜力分析师",
            "agent_role": "挖掘次日大概率上涨的潜力股票",
            "analysis": analysis,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    def theme_tracker_analyst(self, longhubang_data: str, summary: Dict) -> Dict[str, Any]:
        concept_info = ""
        if summary.get('hot_concepts'):
            concept_info = "\n【热门概念统计】\n"
            for idx, (concept, count) in enumerate(list(summary['hot_concepts'].items())[:20], 1):
                concept_info += f"{idx}. {concept}: 出现 {count} 次\n"

        prompt = f"""
你是一名资深的题材研究专家，拥有敏锐的市场嗅觉，擅长从龙虎榜数据中捕捉题材热点和板块轮动机会。

【龙虎榜数据概况】
记录总数: {summary.get('total_records', 0)}
涉及股票: {summary.get('total_stocks', 0)} 只

{concept_info}

{longhubang_data[:8000]}

请基于以上龙虎榜数据，进行深入的题材追踪分析：
1. **热点题材识别** ⭐ 核心
   - 识别当前最热门的5-8个题材/概念
   - 分析每个题材的核心逻辑和催化剂
   - 评估题材的市场关注度和参与度
   - 判断题材是主流还是伪题材
2. **题材炒作周期分析**
   - 判断每个题材所处的炒作周期（萌芽期/爆发期/高潮期/退潮期）
   - 分析题材的爆发力和持续性
   - 识别即将启动的新题材（萌芽期）
   - 提示即将退潮的老题材（高潮期）
3. **题材龙头与梯队**
   - 识别每个题材的龙头股（1-2只）
   - 找出题材的跟风股和补涨股
   - 分析龙头的地位是否稳固
   - 判断是否存在龙头切换
4. **游资对题材的态度**
   - 分析游资重点炒作的题材
   - 判断游资对题材的认同度（一致/分歧）
   - 识别游资集体进攻的题材（强势题材）
   - 发现游资开始撤离的题材（弱势题材）
5. **题材轮动特征**
   - 分析题材之间的轮动关系
   - 识别强势题材和弱势题材
   - 判断资金从哪个题材流向哪个题材
   - 预判下一个可能启动的题材
6. **题材与市场环境匹配度**
   - 分析题材是否符合当前市场风格
   - 评估题材的政策支持度
   - 判断题材的基本面支撑
   - 识别纯粹炒作的题材
7. **题材风险评估**
   - 识别过度炒作的题材（泡沫风险）
   - 提示游资分歧加大的题材
   - 警示题材逻辑破裂的风险
   - 评估题材的回调风险
8. **投资策略建议**
   - 推荐3-5个值得关注的强势题材
   - 每个题材推荐1-2只最优标的
   - 提供题材投资的时机选择
   - 给出题材仓位和持有周期建议
"""
        analysis = call_ai(prompt)
        return {
            "agent_name": "题材追踪分析师",
            "agent_role": "识别热点题材，分析炒作周期，预判轮动方向",
            "analysis": analysis,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    def risk_control_specialist(self, longhubang_data: str, summary: Dict) -> Dict[str, Any]:
        prompt = f"""
你是一名资深的风险控制专家和反向思维大师，拥有20年的市场风险管理经验，擅长识别龙虎榜中的风险信号和资金陷阱。

【龙虎榜数据概况】
记录总数: {summary.get('total_records', 0)}
涉及股票: {summary.get('total_stocks', 0)} 只
涉及游资: {summary.get('total_youzi', 0)} 个
总买入金额: {summary.get('total_buy_amount', 0):,.2f} 元
总卖出金额: {summary.get('total_sell_amount', 0):,.2f} 元
净流入金额: {summary.get('total_net_inflow', 0):,.2f} 元

{longhubang_data[:8000]}

请基于以上龙虎榜数据，进行全面的风险分析：
1. **高风险股票识别** ⭐ 核心
   - 识别5-8只高风险股票（次日大概率下跌）
   - 分析每只股票的风险点（游资出货/技术破位/题材退潮）
   - 评估每只股票的风险等级（高/中/低）
   - 给出规避建议和止损位
2. **游资出货信号识别**
   - 识别卖出金额远大于买入金额的股票
   - 分析游资"一日游"后撤离的股票
   - 识别游资集体出货的股票（多席位卖出）
   - 判断游资出货是正常获利了结还是预期恶化
3. **资金陷阱识别**
   - 识别"虚假放量"的股票（实为对倒出货）
   - 分析"高位放量滞涨"的股票
   - 识别"拉高出货"的经典手法
   - 提示"击鼓传花"的末期信号
4. **题材风险评估**
   - 识别过度炒作的题材（泡沫严重）
   - 分析题材逻辑破裂的风险
   - 提示题材退潮的信号
   - 评估题材的持续性风险
5. **技术面风险提示**
   - 识别技术面走坏的股票（破位/跌破支撑）
   - 分析高位震荡的股票（出货迹象）
   - 提示连续上涨后的回调风险
   - 评估短期超买的股票
6. **情绪风险评估**
   - 识别市场情绪过热的信号
   - 分析游资一致性过高的风险（易崩盘）
   - 提示跟风盘过多的股票（接盘侠风险）
   - 评估短期投机氛围的风险
7. **系统性风险提示**
   - 分析整体龙虎榜数据反映的市场风险
   - 评估游资整体是进攻还是防守
   - 判断市场风险偏好的变化
   - 提示可能的系统性调整风险
8. **风险管理建议**
   - 提供仓位控制建议（重仓/轻仓/空仓）
   - 给出止损止盈的纪律要求
   - 建议规避的板块和题材
   - 提供风险对冲策略
"""
        analysis = call_ai(prompt)
        return {
            "agent_name": "风险控制专家",
            "agent_role": "识别高风险股票、游资出货信号和市场陷阱",
            "analysis": analysis,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    def chief_strategist(self, all_analyses: List[Dict]) -> Dict[str, Any]:
        analyses_text = ""
        for analysis in all_analyses:
            analyses_text += f"\n{'='*60}\n"
            analyses_text += f"【{analysis['agent_name']}】分析报告\n"
            analyses_text += f"职责: {analysis['agent_role']}\n"
            analyses_text += f"{'='*60}\n"
            analyses_text += analysis['analysis'] + "\n"

        prompt = f"""
你是一名资深的首席投资策略师，拥有CFA、FRM等专业资格，具有25年的市场实战经验和卓越的综合分析能力。
你的团队包含4位专业分析师，他们已经从不同维度完成了龙虎榜数据分析：
以下是各位分析师的详细分析报告：

{analyses_text[:15000]}

请作为首席策略师，综合以上所有分析，给出最终的投资策略报告：
1. **市场总体研判**
   - 综合评估当前龙虎榜反映的市场状态
   - 判断游资整体的进攻或防守态度
   - 评估短期市场的机会和风险
   - 给出市场情绪和热度评分（0-100分）
2. **次日重点推荐股票（TOP5-8）** ⭐⭐⭐ 最核心
   - 综合4位分析师的意见，筛选出5-8只次日最有潜力的股票
   - 每只股票必须包含：股票名称和代码、推荐理由、确定性评级、买入价位区间、目标价位、止损价位、持有周期建议
   - 按推荐优先级排序
3. **高风险警示股票（TOP3-5）**
   - 综合识别3-5只高风险股票
   - 说明风险原因并给出规避建议
4. **热点题材总结**
   - 总结当前2-3个最强势题材
   - 每个题材推荐1-2只最优标的
5. **操作策略建议**
   - 仓位管理建议（进攻/平衡/防守）
   - 选股思路和方向
   - 买卖时机选择
   - 风险控制要求
6. **注意事项**
   - 提示关键风险点
   - 强调纪律执行
   - 给出应对预案
"""
        analysis = call_ai(prompt)
        return {
            "agent_name": "首席策略师",
            "agent_role": "综合多维度分析，给出最终投资建议",
            "analysis": analysis,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
# ==========================================
# ===================== 新增：主力资金选股整合模块 =====================
# =====================================================================
# 版本说明：
# 1. 彻底移除“启动后长期卡住”的高耗时路径：默认不再调用 pywencai，也不再调用 AKShare 的分页资金流接口。
# 2. 主数据源改为东方财富轻量 clist 接口，一次请求拉取候选池，通常数秒内返回。
# 3. 即使外部接口失败，也会立刻进入内置观察池，不让页面长时间转圈。
# 4. AI 分析从原来的三次串行调用压缩为一次调用；先展示量化结果，再生成 AI 解读。
# 5. JSON 解析失败也不再报错，直接使用量化打分结果兜底。

import sqlite3
import json
import re

class MainForceBatchDatabase:
    """主力选股分析历史数据库管理类"""
    def __init__(self, db_path="main_force_batch.db"):
        self.db_path = db_path
        self._init_database()

    def _init_database(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS batch_analysis_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_date TEXT NOT NULL,
                    batch_count INTEGER NOT NULL,
                    success_count INTEGER NOT NULL,
                    results_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
            conn.close()
        except Exception:
            pass

    def save_analysis(self, batch_count, success_count, results_json):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            analysis_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute('''
                INSERT INTO batch_analysis_history 
                (analysis_date, batch_count, success_count, results_json)
                VALUES (?, ?, ?, ?)
            ''', (analysis_date, batch_count, success_count, results_json))
            conn.commit()
            conn.close()
        except Exception:
            pass

class MainForceStockSelector:
    """主力资金快速选股器。

    设计目标：宁愿少抓一点数据，也不要让 Streamlit Cloud 一直卡住。
    数据优先级：
    1. 东方财富轻量 clist 接口：快，单次请求，适合云端。
    2. 内置核心观察池：外部接口不稳定时兜底。
    """

    DEFAULT_POOL = [
        {"股票代码": "600519", "股票简称": "贵州茅台", "所属行业": "食品饮料", "区间涨跌幅": 0, "最新价": 0, "主力净流入": 0, "成交额": 0, "换手率": 0, "总市值": 0, "市盈率": "-"},
        {"股票代码": "300750", "股票简称": "宁德时代", "所属行业": "电池", "区间涨跌幅": 0, "最新价": 0, "主力净流入": 0, "成交额": 0, "换手率": 0, "总市值": 0, "市盈率": "-"},
        {"股票代码": "601318", "股票简称": "中国平安", "所属行业": "保险", "区间涨跌幅": 0, "最新价": 0, "主力净流入": 0, "成交额": 0, "换手率": 0, "总市值": 0, "市盈率": "-"},
        {"股票代码": "600036", "股票简称": "招商银行", "所属行业": "银行", "区间涨跌幅": 0, "最新价": 0, "主力净流入": 0, "成交额": 0, "换手率": 0, "总市值": 0, "市盈率": "-"},
        {"股票代码": "300059", "股票简称": "东方财富", "所属行业": "证券", "区间涨跌幅": 0, "最新价": 0, "主力净流入": 0, "成交额": 0, "换手率": 0, "总市值": 0, "市盈率": "-"},
        {"股票代码": "002475", "股票简称": "立讯精密", "所属行业": "消费电子", "区间涨跌幅": 0, "最新价": 0, "主力净流入": 0, "成交额": 0, "换手率": 0, "总市值": 0, "市盈率": "-"},
        {"股票代码": "002371", "股票简称": "北方华创", "所属行业": "半导体", "区间涨跌幅": 0, "最新价": 0, "主力净流入": 0, "成交额": 0, "换手率": 0, "总市值": 0, "市盈率": "-"},
        {"股票代码": "688981", "股票简称": "中芯国际", "所属行业": "半导体", "区间涨跌幅": 0, "最新价": 0, "主力净流入": 0, "成交额": 0, "换手率": 0, "总市值": 0, "市盈率": "-"},
        {"股票代码": "300308", "股票简称": "中际旭创", "所属行业": "算力AI", "区间涨跌幅": 0, "最新价": 0, "主力净流入": 0, "成交额": 0, "换手率": 0, "总市值": 0, "市盈率": "-"},
        {"股票代码": "601138", "股票简称": "工业富联", "所属行业": "算力AI", "区间涨跌幅": 0, "最新价": 0, "主力净流入": 0, "成交额": 0, "换手率": 0, "总市值": 0, "市盈率": "-"},
        {"股票代码": "002594", "股票简称": "比亚迪", "所属行业": "汽车整车", "区间涨跌幅": 0, "最新价": 0, "主力净流入": 0, "成交额": 0, "换手率": 0, "总市值": 0, "市盈率": "-"},
        {"股票代码": "600276", "股票简称": "恒瑞医药", "所属行业": "创新药", "区间涨跌幅": 0, "最新价": 0, "主力净流入": 0, "成交额": 0, "换手率": 0, "总市值": 0, "市盈率": "-"},
        {"股票代码": "601899", "股票简称": "紫金矿业", "所属行业": "有色金属", "区间涨跌幅": 0, "最新价": 0, "主力净流入": 0, "成交额": 0, "换手率": 0, "总市值": 0, "市盈率": "-"},
        {"股票代码": "600547", "股票简称": "山东黄金", "所属行业": "黄金", "区间涨跌幅": 0, "最新价": 0, "主力净流入": 0, "成交额": 0, "换手率": 0, "总市值": 0, "市盈率": "-"},
        {"股票代码": "688523", "股票简称": "航天环宇", "所属行业": "国防军工", "区间涨跌幅": 0, "最新价": 0, "主力净流入": 0, "成交额": 0, "换手率": 0, "总市值": 0, "市盈率": "-"},
    ]

    INDUSTRY_HINTS = {
        "银行": ["银行"], "证券": ["券商", "证券"], "保险": ["保险"],
        "半导体": ["半导体", "芯片", "集成电路"], "算力AI": ["AI", "算力", "光模块", "服务器"],
        "电池": ["新能源", "锂电", "电池"], "消费电子": ["消费电子", "苹果", "机器人"],
        "食品饮料": ["消费", "白酒"], "创新药": ["医药", "创新药"],
        "有色金属": ["有色", "铜", "铝"], "黄金": ["黄金", "避险"],
        "汽车整车": ["汽车", "新能源车"], "国防军工": ["军工", "低空经济", "航天"]
    }

    def _normalize_code(self, value):
        if pd.isna(value):
            return ""
        text = str(value).strip()
        m = re.search(r"(\d{6})", text)
        return m.group(1) if m else text.zfill(6)[-6:]

    def _standardize_numeric(self, df):
        numeric_cols = ["区间涨跌幅", "最新价", "主力净流入", "成交额", "换手率", "总市值"]
        for col in numeric_cols:
            if col not in df.columns:
                df[col] = 0.0
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        if "市盈率" not in df.columns:
            df["市盈率"] = "-"
        if "所属行业" not in df.columns:
            df["所属行业"] = "未分类"
        return df

    def _infer_industry(self, name: str):
        name = str(name)
        for industry, keys in self.INDUSTRY_HINTS.items():
            if any(k in name for k in keys):
                return industry
        return "未分类"

    def _fetch_eastmoney_fast_pool(self, pz=220):
        """东方财富轻量实时列表。只请求一页，避免 AKShare 多页 tqdm 卡住。"""
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1",
            "pz": str(pz),
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f6",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f2,f3,f6,f8,f9,f12,f14,f20,f21,f62,f184"
        }
        try:
            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Referer": "https://quote.eastmoney.com/center/gridlist.html"
            }
            res = SESSION.get(url, params=params, headers=headers, timeout=8)
            res.raise_for_status()
            js = res.json()
            diff = ((js or {}).get("data") or {}).get("diff") or []
            if not diff:
                return pd.DataFrame(), "东方财富轻量接口返回空"

            rows = []
            for item in diff:
                code = self._normalize_code(item.get("f12", ""))
                name = str(item.get("f14", ""))
                if not re.match(r"^\d{6}$", code):
                    continue
                if "ST" in name or "退" in name:
                    continue
                amount = safe_float(item.get("f6"))
                pct = safe_float(item.get("f3"))
                turnover = safe_float(item.get("f8"))
                market_cap = safe_float(item.get("f20")) / 100000000 if safe_float(item.get("f20")) > 1000000 else safe_float(item.get("f20"))
                main_net = safe_float(item.get("f62"))
                if main_net == 0:
                    main_net = amount * (max(min(pct, 10), -10) / 100.0)
                rows.append({
                    "股票代码": code,
                    "股票简称": name,
                    "所属行业": self._infer_industry(name),
                    "区间涨跌幅": pct,
                    "最新价": safe_float(item.get("f2")),
                    "主力净流入": main_net,
                    "成交额": amount,
                    "换手率": turnover,
                    "总市值": market_cap,
                    "市盈率": item.get("f9", "-"),
                    "资金热度分": 0.0,
                    "数据源": "东方财富轻量实时池"
                })
            df = pd.DataFrame(rows)
            if df.empty:
                return pd.DataFrame(), "东方财富轻量接口无有效股票"
            return self._score_candidates(df), f"东方财富轻量接口成功获取{len(df)}只候选股票"
        except Exception as exc:
            return pd.DataFrame(), f"东方财富轻量接口异常: {exc}"

    def _fetch_static_pool(self):
        df = pd.DataFrame(self.DEFAULT_POOL).copy()
        df["数据源"] = "内置兜底观察池"
        df = self._standardize_numeric(df)
        rows = []
        # 只补前 8 只，避免挨个请求导致卡顿。
        for idx, row in df.iterrows():
            item = row.to_dict()
            if idx < 8:
                try:
                    q = get_stock_quote(item["股票代码"])
                    if q:
                        item["最新价"] = q.get("price", item.get("最新价", 0))
                        item["区间涨跌幅"] = q.get("pct", item.get("区间涨跌幅", 0))
                        item["总市值"] = q.get("market_cap", item.get("总市值", 0))
                        item["市盈率"] = q.get("pe", item.get("市盈率", "-"))
                        item["换手率"] = q.get("turnover", item.get("换手率", 0))
                except Exception:
                    pass
            rows.append(item)
        final_df = pd.DataFrame(rows)
        return self._score_candidates(final_df), f"已启用内置观察池{len(final_df)}只"

    def _score_candidates(self, df):
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.copy()
        df = self._standardize_numeric(df)
        df["股票代码"] = df["股票代码"].apply(self._normalize_code)
        df = df[df["股票代码"].astype(str).str.match(r"^\d{6}$", na=False)]
        df = df.drop_duplicates(subset=["股票代码"]).reset_index(drop=True)
        if df.empty:
            return df

        # 热度评分：不用等待精确资金流，快速给出可排序结果。
        df["成交额_rank"] = df["成交额"].rank(pct=True).fillna(0)
        df["换手率_rank"] = df["换手率"].rank(pct=True).fillna(0)
        df["涨幅_rank"] = df["区间涨跌幅"].rank(pct=True).fillna(0)
        df["净流入_rank"] = df["主力净流入"].rank(pct=True).fillna(0)
        df["资金热度分"] = (
            df["成交额_rank"] * 35
            + df["换手率_rank"] * 25
            + df["净流入_rank"] * 25
            + df["涨幅_rank"] * 15
        ).round(2)
        return df.drop(columns=["成交额_rank", "换手率_rank", "涨幅_rank", "净流入_rank"], errors="ignore")

    def get_main_force_stocks(self, start_date=None, days_ago=None, min_market_cap=10.0, max_market_cap=5000.0):
        # 只走快速路径，不再调用 pywencai/AKShare分页资金流，避免长时间转圈。
        df, msg = self._fetch_eastmoney_fast_pool(pz=220)
        if df.empty:
            df, msg2 = self._fetch_static_pool()
            msg = f"{msg}；{msg2}"
        if df.empty:
            return False, pd.DataFrame(), "所有快速数据源均为空"
        return True, df, msg

    def filter_stocks(self, df: pd.DataFrame, max_range_change=30.0, min_market_cap=10.0, max_market_cap=5000.0):
        if df is None or df.empty:
            return pd.DataFrame()
        filtered_df = df.copy()
        filtered_df = self._standardize_numeric(filtered_df)
        filtered_df = filtered_df[~filtered_df["股票简称"].astype(str).str.contains("ST|退", na=False)]
        if "区间涨跌幅" in filtered_df.columns:
            filtered_df = filtered_df[filtered_df["区间涨跌幅"] <= float(max_range_change)]
        if "总市值" in filtered_df.columns:
            filtered_df = filtered_df[(filtered_df["总市值"] == 0) | ((filtered_df["总市值"] >= min_market_cap) & (filtered_df["总市值"] <= max_market_cap))]
        sort_cols = [c for c in ["资金热度分", "主力净流入", "成交额", "换手率"] if c in filtered_df.columns]
        if sort_cols:
            filtered_df = filtered_df.sort_values(sort_cols, ascending=[False] * len(sort_cols))
        return filtered_df.reset_index(drop=True)

class MainForceAnalyzer:
    """主力选股快速分析引擎。"""
    def __init__(self):
        self.selector = MainForceStockSelector()
        self.db = MainForceBatchDatabase()
        self.fund_flow_analysis = ""
        self.industry_analysis = ""
        self.data_source_msg = ""

    @staticmethod
    def _build_recommendations(filtered_data: pd.DataFrame, final_n: int) -> List[Dict[str, Any]]:
        recs = []
        if filtered_data is None or filtered_data.empty:
            return recs
        df = filtered_data.copy().head(final_n)
        for idx, (_, row) in enumerate(df.iterrows(), start=1):
            symbol = str(row.get("股票代码", "")).zfill(6)[:6]
            name = str(row.get("股票简称", row.get("股票名称", "未知")))
            hot = safe_float(row.get("资金热度分", 0))
            inflow = safe_float(row.get("主力净流入", 0))
            amount = safe_float(row.get("成交额", 0))
            pct = safe_float(row.get("区间涨跌幅", 0))
            turnover = safe_float(row.get("换手率", 0))
            industry = str(row.get("所属行业", "未分类"))
            reasons = [f"资金热度分 {hot:.1f}，在候选池中排名靠前"]
            if inflow:
                reasons.append(f"估算/接口主力净流入约 {inflow:,.0f}")
            if amount:
                reasons.append(f"成交额活跃，约 {amount / 100000000:.2f} 亿元")
            if turnover:
                reasons.append(f"换手率约 {turnover:.2f}%，短线资金关注度较高")
            if pct:
                reasons.append(f"当前涨跌幅约 {pct:.2f}%，需结合位置判断追高风险")
            recs.append({
                "rank": idx,
                "symbol": symbol,
                "name": name,
                "industry": industry,
                "score": hot,
                "reasons": reasons[:4],
                "position": "10%-20%",
                "risks": "该结果为快速资金热度模型筛选，需结合日线位置、公告、板块强度和大盘环境二次确认。"
            })
        return recs

    @staticmethod
    def _extract_json_from_ai_response(text: str) -> Dict[str, Any]:
        if text is None:
            raise ValueError("AI 返回为空")
        raw = str(text).strip()
        fence_match = re.search(r"```(?:json|JSON)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
        if fence_match:
            raw = fence_match.group(1).strip()
        try:
            return json.loads(raw)
        except Exception:
            pass
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(raw[start:end + 1])
        raise ValueError("未能从 AI 回复中提取合法 JSON")

    def run_full_analysis(self, start_date, days_ago, final_n, max_range_change, min_market_cap, max_market_cap, use_ai=True):
        result = {"success": False, "final_recommendations": [], "error": None}
        t0 = time.time()

        success, raw_data, msg = self.selector.get_main_force_stocks(start_date, days_ago, min_market_cap, max_market_cap)
        self.data_source_msg = msg
        if not success:
            result["error"] = msg
            return result

        filtered_data = self.selector.filter_stocks(raw_data, max_range_change, min_market_cap, max_market_cap)
        if filtered_data.empty:
            result["error"] = "筛选后无符合条件的股票。建议提高区间最大涨幅限制或放宽市值范围。"
            return result

        self.raw_stocks = filtered_data
        quick_recs = self._build_recommendations(filtered_data, final_n)
        result["final_recommendations"] = quick_recs
        result["success"] = True
        result["data_source_msg"] = msg
        result["elapsed_fetch"] = round(time.time() - t0, 2)

        # 先完成可展示结果，再做一次短 AI 解读；AI 失败不影响结果。
        top_data = filtered_data.head(min(20, len(filtered_data)))
        show_cols = ["股票代码", "股票简称", "所属行业", "资金热度分", "主力净流入", "成交额", "区间涨跌幅", "换手率", "总市值", "市盈率", "数据源"]
        show_cols = [c for c in show_cols if c in top_data.columns]
        table_text = top_data[show_cols].to_string(index=False)
        self.fund_flow_analysis = "已根据成交额、换手率、估算主力净流入、涨跌幅构造资金热度分，并完成快速排序。"
        self.industry_analysis = "行业分布来自股票名称和内置行业映射，属于快速归类，适合先做观察池，不适合作为唯一买入依据。"

        if use_ai and api_key:
            try:
                prompt = f"""
你是A股短线资金流研究员。请基于以下快速候选池，给出精炼结论。

数据来源说明：{msg}
候选数据：
{table_text}

请严格输出合法 JSON，不要使用 Markdown 代码块：
{{
  "fund_view": "一句话总结资金流状态",
  "industry_view": "一句话总结热点方向",
  "recommendations": [
    {{"rank":1,"symbol":"股票代码","name":"股票名称","reasons":["理由1","理由2"],"position":"建议仓位","risks":"风险提示"}}
  ]
}}
"""
                ai_resp = call_ai(prompt, temperature=0.2)
                parsed = self._extract_json_from_ai_response(ai_resp)
                ai_recs = parsed.get("recommendations", []) if isinstance(parsed, dict) else []
                if isinstance(ai_recs, list) and ai_recs:
                    result["final_recommendations"] = ai_recs[:final_n]
                self.fund_flow_analysis = parsed.get("fund_view", self.fund_flow_analysis) if isinstance(parsed, dict) else self.fund_flow_analysis
                self.industry_analysis = parsed.get("industry_view", self.industry_analysis) if isinstance(parsed, dict) else self.industry_analysis
                result["ai_raw_response"] = ai_resp
            except Exception as exc:
                result["warning"] = f"AI 解读未完成，已使用快速量化结果。原因：{exc}"

        try:
            self.db.save_analysis(
                len(filtered_data),
                len(result["final_recommendations"]),
                json.dumps(result["final_recommendations"], ensure_ascii=False)
            )
        except Exception:
            pass
        return result

def render_main_force_tab():
    """主力选股专属 UI 渲染器（快速版）。"""
    st.markdown("### 🎯 主力资金选股 - 快速资金热度引擎")
    st.write("为避免云端接口长时间卡住，本模块改为轻量行情池 + 资金热度评分 + 单次AI解读。先出结果，再做研判。")
    st.markdown("---")

    col1, col2, col3 = st.columns(3)
    with col1:
        date_option = st.selectbox("监控时间区间", ["最近10天", "最近30天", "最近3个月"])
        days_ago = 10 if date_option == "最近10天" else 30 if date_option == "最近30天" else 90
    with col2:
        final_n = st.slider("最终精选数量", 2, 10, 5)
    with col3:
        max_change = st.number_input("区间最大涨幅限制(%)", value=30.0, step=5.0, help="剔除已经大涨的高位股")

    use_ai = st.checkbox("生成AI解读", value=True, help="关闭后速度最快，只展示量化资金热度结果。")

    if st.button("🚀 启动主力追踪引擎", type="primary", width="stretch"):
        if not api_key and use_ai:
            st.warning("未配置 GROQ_API_KEY，将只展示快速量化结果。")
            use_ai = False

        analyzer = MainForceAnalyzer()
        with st.spinner("正在快速提取候选池并计算资金热度..."):
            result = analyzer.run_full_analysis(
                start_date=None,
                days_ago=days_ago,
                final_n=final_n,
                max_range_change=max_change,
                min_market_cap=30.0,
                max_market_cap=5000.0,
                use_ai=use_ai,
            )

        if result["success"]:
            st.success(f"✅ 计算完成！已锁定 {len(result['final_recommendations'])} 只候选标的。数据源：{result.get('data_source_msg', analyzer.data_source_msg)}")
            if result.get("elapsed_fetch") is not None:
                st.caption(f"数据提取与初筛耗时：{result['elapsed_fetch']} 秒")
            if result.get("warning"):
                st.warning(result["warning"])

            if hasattr(analyzer, "raw_stocks") and analyzer.raw_stocks is not None and not analyzer.raw_stocks.empty:
                with st.expander("📋 查看快速候选池 Top 30", expanded=False):
                    show_cols = ["股票代码", "股票简称", "所属行业", "资金热度分", "主力净流入", "成交额", "区间涨跌幅", "换手率", "总市值", "市盈率", "数据源"]
                    show_cols = [c for c in show_cols if c in analyzer.raw_stocks.columns]
                    st.dataframe(analyzer.raw_stocks[show_cols].head(30), width="stretch", hide_index=True)

            st.markdown("### ⭐ 首席精选标的池")
            for rec in result["final_recommendations"]:
                with st.expander(f"🏅 TOP {rec.get('rank', '-')} | {rec.get('name', '未知')} ({rec.get('symbol', '未知')})", expanded=True):
                    if rec.get("industry"):
                        st.caption(f"所属方向：{rec.get('industry')}")
                    if rec.get("score") is not None:
                        st.metric("资金热度分", f"{safe_float(rec.get('score')):.1f}")
                    st.markdown("**📌 核心逻辑：**")
                    for r in rec.get("reasons", []):
                        st.write(f"- {r}")
                    st.markdown(f"**💰 建议仓位：** {rec.get('position', 'N/A')}")
                    st.markdown(f"**⚠️ 预警提示：** {rec.get('risks', 'N/A')}")

            st.markdown("---")
            st.markdown("### 🤖 投研底稿")
            t1, t2 = st.tabs(["💰 资金流向透视", "📊 行业格局研判"])
            with t1:
                st.write(analyzer.fund_flow_analysis)
            with t2:
                st.write(analyzer.industry_analysis)
        else:
            st.error(f"❌ 运行失败: {result['error']}")
# ===================== 主力选股模块结束 =====================

# ================= 终端全局看板 =================
st.markdown("### 🌍 宏观市场实时看板")
pulse_data = get_market_pulse()
if pulse_data:
    dash_cols = st.columns(len(pulse_data))
    for idx, (key, data) in enumerate(pulse_data.items()):
        with dash_cols[idx]:
            with st.container(border=True):
                if "CNH" in key:
                    st.metric(key, f"{data['price']:.4f}", f"{data['pct']:.2f}%", delta_color="inverse")
                else:
                    st.metric(key, f"{data['price']:.2f}", f"{data['pct']:.2f}%")
else:
    st.warning("宏观看板数据流建立失败。")
st.markdown("<br>", unsafe_allow_html=True)

# ================= 终端功能选项卡 =================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🎯 I. 个股标的解析",
    "📈 II. 宏观大盘推演",
    "🔥 III. 资金热点板块",
    "🦅 IV. 高阶情报终端",
    "🐉 V. 智瞰龙虎榜解析",
    "🐋 VI. 主力资金选股"     # 新增这一行
])

# ================= Tab 1: 个股解析 =================
with tab1:
    with st.container(border=True):
        st.markdown("#### 🔎 个股雷达锁定（多维买卖点测算版）")
        col1, col2 = st.columns([1, 1])
        with col1:
            symbol_input = st.text_input("标的代码", placeholder="例：600519")
            analyze_btn = st.button("启动核心算法", type="primary", use_container_width=True)
        if analyze_btn:
            if not api_key:
                st.error("配置缺失: GROQ_API_KEY")
            elif len(symbol_input.strip()) != 6:
                st.warning("代码规范验证失败")
            else:
                with st.spinner("量子计算与数据提取中 (启用四重行情数据引擎 + 多周期分析)..."):
                    quote = get_stock_quote(symbol_input)
                    df_kline = get_kline(symbol_input, days=220)
                    mtf = get_multi_timeframe_analysis(symbol_input)
                if not quote:
                    st.error("无法捕获行情资产。")
                else:
                    st.markdown("---")
                    name, price, pct = quote["name"], quote["price"], quote["pct"]
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric(f"{name}", f"{price:.2f}", f"{pct:.2f}%")
                    c2.metric("总市值(亿)", f"{quote['market_cap']:.1f}")
                    c3.metric("动态 PE", f"{quote['pe']}")
                    c4.metric("换手率", f"{quote['turnover']:.2f}%")

                    if df_kline is None or len(df_kline) < 15:
                        st.warning("获取到的有效 K 线极少，仅能通过最新行情进行轻量化推演。")
                        with st.spinner("🧠 首席策略官撰写资产评估报告..."):
                            prompt = f"""
作为顶级私募经理，请基于股票 {name}({symbol_input}) 当前状态：
现价 {price}，涨跌幅 {pct}%，市值 {quote['market_cap']} 亿，动态 PE {quote['pe']}，换手率 {quote['turnover']}%。
【请重点进行以下维度的分析】：
1. 🏦 基本面诊断与资金意图盲猜
2. ⚔️ 布局进入与离场推演：
   - 【短期波段】进入点与离场点建议
   - 【中长期配置】建仓点位与长线离场目标
3. 结论定调：[看多 / 观察 / 谨慎 / 偏空]
"""
                            st.markdown(call_ai(prompt))
                    else:
                        df_kline = add_indicators(df_kline)
                        tech = summarize_technicals(df_kline)
                        smc = tech["smc"]
                        fig = build_price_figure(df_kline)
                        st.plotly_chart(fig, use_container_width=True)

                        st.markdown("##### 🔬 核心技术指标与阻力测算")
                        t1, t2, t3, t4 = st.columns(4)
                        t1.metric("趋势", tech["trend"])
                        t2.metric("RSI14", f"{tech['rsi14']:.2f}" if pd.notna(tech["rsi14"]) else "N/A")
                        t3.metric("ATR14", f"{tech['atr14']:.2f}" if pd.notna(tech["atr14"]) else "N/A")
                        t4.metric("MACD 状态", tech["macd_state"])
                        t5, t6, t7, t8 = st.columns(4)
                        t5.metric("布林状态", tech["bb_state"])
                        t6.metric("量能状态", tech["vol_state"])
                        t7.metric("BOS", tech["bos_state"])
                        t8.metric("流动性扫盘", tech["sweep_state"])

                        st.markdown("##### 🧩 FVG / ICT / SMC 结构信息")
                        f1, f2 = st.columns(2)
                        with f1:
                            bull_fvg = tech["nearest_bull_fvg"]
                            if bull_fvg:
                                st.success(f"最近多头 FVG：{bull_fvg['date']} | 区间 {bull_fvg['bottom']:.2f} - {bull_fvg['top']:.2f}")
                            else:
                                st.info("最近未检测到明显多头 FVG")
                            if smc["latest_bull_ob"]:
                                st.success(f"最近多头 OB：{smc['latest_bull_ob']['date']} | 区间 {smc['latest_bull_ob']['bottom']:.2f} - {smc['latest_bull_ob']['top']:.2f}")
                            else:
                                st.info("最近未检测到明显多头 OB")
                        with f2:
                            bear_fvg = tech["nearest_bear_fvg"]
                            if bear_fvg:
                                st.error(f"最近空头 FVG：{bear_fvg['date']} | 区间 {bear_fvg['bottom']:.2f} - {bear_fvg['top']:.2f}")
                            else:
                                st.info("最近未检测到明显空头 FVG")
                            if smc["latest_bear_ob"]:
                                st.error(f"最近空头 OB：{smc['latest_bear_ob']['date']} | 区间 {smc['latest_bear_ob']['bottom']:.2f} - {smc['latest_bear_ob']['top']:.2f}")
                            else:
                                st.info("最近未检测到明显空头 OB")

                        st.markdown("##### 🏗️ 市场结构补充")
                        s1, s2, s3 = st.columns(3)
                        eqh_count = len(smc["eqh"]) if smc["eqh"] else 0
                        eql_count = len(smc["eql"]) if smc["eql"] else 0
                        pd_zone = smc["pd_zone"]["zone"] if smc["pd_zone"] else "N/A"
                        s1.metric("MSS", smc["mss"])
                        s2.metric("EQH / EQL", f"{eqh_count} / {eql_count}")
                        s3.metric("P/D Zone", pd_zone)
                        latest_close = tech["latest_close"]

                        support_zone = min(tech["ema_short"], tech["ema_mid"])
                        pressure_zone = max(tech["ema_short"], tech["ema_mid"])
                        st.markdown("##### 🎯 动态支撑 / 压力")
                        z1, z2, z3 = st.columns(3)
                        z1.metric("最新收盘", f"{latest_close:.2f}")
                        z2.metric("动态支撑参考", f"{support_zone:.2f}")
                        z3.metric("动态压力参考", f"{pressure_zone:.2f}")

                    st.markdown("##### ⏱️ 多周期技术分析")
                    m1, m2, m3 = st.columns(3)
                    with m1:
                        tf = mtf["15m"]
                        st.markdown("**15分钟级别**")
                        st.metric("偏向", tf["bias"])
                        st.metric("趋势", tf["trend"])
                        st.metric("MACD", tf["macd_state"])
                        if tf["rsi"] is not None:
                            st.metric("RSI", f"{tf['rsi']:.2f}")
                        if tf["support"] is not None:
                            st.caption(f"支撑: {tf['support']:.2f}")
                        if tf["pressure"] is not None:
                            st.caption(f"压力: {tf['pressure']:.2f}")
                    with m2:
                        tf = mtf["60m"]
                        st.markdown("**60分钟级别**")
                        st.metric("偏向", tf["bias"])
                        st.metric("趋势", tf["trend"])
                        st.metric("MACD", tf["macd_state"])
                        if tf["rsi"] is not None:
                            st.metric("RSI", f"{tf['rsi']:.2f}")
                        if tf["support"] is not None:
                            st.caption(f"支撑: {tf['support']:.2f}")
                        if tf["pressure"] is not None:
                            st.caption(f"压力: {tf['pressure']:.2f}")
                    with m3:
                        tf = mtf["120m"]
                        st.markdown("**120分钟级别**")
                        st.metric("偏向", tf["bias"])
                        st.metric("趋势", tf["trend"])
                        st.metric("MACD", tf["macd_state"])
                        if tf["rsi"] is not None:
                            st.metric("RSI", f"{tf['rsi']:.2f}")
                        if tf["support"] is not None:
                            st.caption(f"支撑: {tf['support']:.2f}")
                        if tf["pressure"] is not None:
                            st.caption(f"压力: {tf['pressure']:.2f}")

                    st.markdown("##### 🧠 多周期综合结论")
                    st.info(f"综合结论：**{mtf['final_view']}**")

                    with st.spinner(f"🧠 首席策略官正在使用 {selected_model} 进行多维深度解构..."):
                        if df_kline is not None and len(df_kline) >= 15:
                            tech = summarize_technicals(add_indicators(df_kline))
                            smc = tech["smc"]
                            ema_mid_val = f"{tech['ema_mid']:.2f}" if pd.notna(tech['ema_mid']) else "数据不足"
                            ema_long_val = f"{tech['ema_long']:.2f}" if pd.notna(tech['ema_long']) else "数据不足"
                            prompt = f"""
你现在是顶级私募基金的操盘手（精通基本面、量价资金博弈、多周期共振）。
请对股票 {name}({symbol_input}) 做一份极具实战价值的【估值 + 资金流 + 支撑/压力 + 精准买卖点 + 多周期共振】综合研判。
【基础与资金博弈数据】
- 现价: {price} (日涨跌幅: {pct}%)
- 总市值: {quote['market_cap']} 亿 | 动态 PE: {quote['pe']} | 市净率 PB: {quote['pb']}
- 当日换手率: {quote['turnover']}%
- 近期量能状态: {tech['vol_state']}
【核心日线技术与结构数据】
- 趋势状态: {tech['trend']} | RSI14: {tech['rsi14']}
- 最新收盘: {tech['latest_close']}
- 短期生命线 (EMA{ema_short}): {tech['ema_short']}
- 中长期基准 (EMA{ema_mid}/{ema_long}): {ema_mid_val} / {ema_long_val}
- 结构特征: BOS({tech['bos_state']}), MSS({smc['mss']})
- 异常流动性: 扫盘({tech['sweep_state']})
- 核心磁区 (FVG/OB):
  近期多头 FVG: {tech['nearest_bull_fvg']}
  近期空头 FVG: {tech['nearest_bear_fvg']}
  近期多头 OB: {smc['latest_bull_ob']}
  近期空头 OB: {smc['latest_bear_ob']}
【多周期分析】
- 15分钟: {mtf['15m']}
- 60分钟: {mtf['60m']}
- 120分钟: {mtf['120m']}
- 多周期综合结论: {mtf['final_view']}
【请务必输出】
1. 🏦 基本面与估值定位
2. 🌊 资金面穿透
3. 🎯 支撑与压力测算
4. ⚔️ 布局进入与离场推演
   - 【短期波段】
   - 【中长期配置】
5. ⏱️ 多周期共振判断
   - 15分钟、60分钟、120分钟是否共振
   - 是适合追涨、低吸、等回踩，还是观望
6. 最后给出一句明确结论：强势看多 / 偏多观察 / 震荡等待 / 谨慎偏空
要求：语言要专业、直接、机构化，不能空话，尽量像真正交易员盘前计划。
"""
                            st.markdown(call_ai(prompt))
                        else:
                            prompt = f"""
你现在是顶级私募基金操盘手。
请基于股票 {name}({symbol_input}) 当前基础数据与多周期结论做综合研判。
【基础数据】
- 现价: {price}
- 日涨跌幅: {pct}%
- 市值: {quote['market_cap']} 亿
- 动态 PE: {quote['pe']}
- 市净率 PB: {quote['pb']}
- 换手率: {quote['turnover']}%
【多周期分析】
- 15分钟: {mtf['15m']}
- 60分钟: {mtf['60m']}
- 120分钟: {mtf['120m']}
- 多周期综合结论: {mtf['final_view']}
请输出：
1. 当前股性判断
2. 多周期共振解读
3. 短线交易建议
4. 中线观察建议
5. 最后一行给明确结论：看多 / 观察 / 谨慎 / 偏空
"""
                            st.markdown(call_ai(prompt))

# ================= Tab 2: 宏观大盘推演 (已升级为多智能体版本) =================
with tab2:
    with st.container(border=True):
        st.markdown("#### 📊 全局宏观基本面推演")
        display_macro_analysis_ui()


# ================= Tab 3: 热点资金板块 =================
with tab3:
    with st.container(border=True):
        st.markdown("#### 🔥 当日主力资金狂欢地 (附实战标的推荐)")
        st.write("追踪全天涨幅最猛的行业板块，揪出领涨龙头，识别主线题材，并生成配置标的清单。")
        if st.button("扫描板块与生成配置推荐", type="primary"):
            if not api_key:
                st.error("配置缺失: GROQ_API_KEY")
            else:
                with st.spinner("深潜获取东方财富板块异动数据... (若遇熔断将自动切换备用数据源)"):
                    blocks = get_hot_blocks()
                    if blocks:
                        df_blocks = pd.DataFrame(blocks)
                        st.dataframe(df_blocks, use_container_width=True, hide_index=True)
                        with st.spinner("🧠 首席游资操盘手拆解逻辑并筛选跟进标的..."):
                            blocks_str = "\n".join([f"{b['板块名称']} (涨幅:{b['涨跌幅']}%, 领涨龙头:{b['领涨股票']})" for b in blocks[:5]])
                            prompt = f"""
作为顶级游资操盘手，请深度解读今日最强的 5 个板块及其领涨龙头：
{blocks_str}
请输出：
1. 【核心驱动】这些板块背后的底层逻辑或共振政策利好是什么？
2. 【行情定性】这是存量博弈的一日游情绪宣泄，还是具备中线发酵潜力的主线？
3. 🎯 【个股配置与实战推荐】：
   基于上述板块逻辑和领涨股票，为散户推荐 2-3 只可以进行重点配置或埋伏的股票。
   对于推荐的每一只股票，请务必写明：
   - 股票名称与行业归属
   - 核心配置理由
   - 建议的入场姿势
"""
                            st.markdown(call_ai(prompt, temperature=0.4))
                    else:
                        st.error("获取板块数据失败，所有接口均处于熔断保护期。")

# ================= Tab 4: 高阶情报终端 =================
with tab4:
    st.markdown("#### 📡 机构级事件图谱与智能评级矩阵")
    st.write("追踪彭博、推特、美联储、特朗普等宏观变量。已深度适配移动端，引入极客量化风控模块。")
    if st.button("🚨 截获并解析全球突发", type="primary"):
        if not api_key:
            st.error("配置缺失: GROQ_API_KEY")
        else:
            with st.spinner("监听全网节点并执行深度 NLP 解析..."):
                global_news = get_global_news()
                if not global_news:
                    st.warning("当前信号静默或被防火墙拦截。")
                else:
                    news_text = "\n".join(global_news)
                    with st.expander("🕵️‍♂️ 查看底层监听流 (Raw Data)"):
                        st.text(news_text)
                    with st.spinner("🧠 情报官正在生成自适应移动端的情报卡片..."):
                        prompt = f"""
你现在是华尔街顶级对冲基金的【首席宏观情报官】与【高阶量化风控专家】。
我截获了全球金融市场的底层快讯流。请你挑选出最具爆炸性和市场影响力的 5-8 条动态。
重点寻猎靶标：彭博社 (Bloomberg)、推特 (X)、特朗普 (Trump)、马斯克 (Musk)、美联储，以及任何可能引发流动性危机或资金抱团退潮的事件。
⚠️ 【排版严令：禁止使用 Markdown 表格】 ⚠️
为了适配移动端设备的终端显示，你绝对不能使用表格！必须为每一个事件生成一个独立的情报卡片。
输出格式必须如下：
### [评级 Emoji] [[信源/人物]] [真实事件标题]
* ⏰ **时间截获**: [提取对应时间]
* 📝 **情报简述**: [说明发生了什么]
* 🎯 **受波及资产**: [指出利好/利空资产]
* 🧠 **沙盘推演**: [一句话指出实质影响]
* ☢️ **风控预警**: [一个简短硬核预警]
---
评级标准：
🔴 核心：直接引发巨震的突发、大选级人物强硬表态、黑天鹅事件
🟡 重要：关键经济数据、行业重磅政策、流动性显著异动
🔵 一般：常规宏观事件
底层情报数据流：
{news_text}
"""
                        report = call_ai(prompt, temperature=0.2)
                        st.markdown("---")
                        st.markdown(report)

# ================= Tab 5: 智瞰龙虎榜解析 =================
with tab5:
    with st.container(border=True):
        st.markdown("#### 🐉 智瞰龙虎榜 AI 分析集群")
        st.write("获取游资动态，挖掘次日爆发潜力股，识别高风险陷阱。")

        col_date, col_btn = st.columns([1, 2])
        with col_date:
            lhb_date = st.date_input("选择龙虎榜日期", datetime.now() - timedelta(days=1))
        with col_btn:
            st.write("") # 占位用于垂直对齐
            run_lhb_btn = st.button("🚀 启动智瞰龙虎分析集群", type="primary", use_container_width=True)

        if run_lhb_btn:
            if not api_key:
                st.error("配置缺失: GROQ_API_KEY")
            else:
                date_str = lhb_date.strftime('%Y-%m-%d')
                with st.spinner(f"正在深入节点获取 {date_str} 龙虎榜数据..."):
                    fetcher = LonghubangDataFetcher()
                    raw_result = fetcher.get_longhubang_data(date_str)

                if raw_result and raw_result.get('data'):
                    data_list = raw_result['data']
                    summary = fetcher.analyze_data_summary(data_list)
                    formatted_data = fetcher.format_data_for_ai(data_list, summary)

                    st.success(f"✓ 成功获取 {len(data_list)} 条记录！激活AI集群协同计算...")

                    agents = LonghubangAgents()
                    all_analyses = []

                    # 1. 游资行为分析
                    with st.spinner("🎯 游资行为分析师正在勾勒画像..."):
                        yz_res = agents.youzi_behavior_analyst(formatted_data, summary)
                        all_analyses.append(yz_res)
                        with st.expander("🎯 游资行为分析报告", expanded=False):
                            st.markdown(yz_res['analysis'])

                    # 2. 个股潜力分析
                    with st.spinner("📈 个股潜力分析师正在深度挖掘爆发股..."):
                        stock_res = agents.stock_potential_analyst(formatted_data, summary)
                        all_analyses.append(stock_res)
                        with st.expander("📈 个股潜力分析报告", expanded=False):
                            st.markdown(stock_res['analysis'])

                    # 3. 题材追踪分析
                    with st.spinner("🔥 题材追踪分析师正在定位主线轮动..."):
                        theme_res = agents.theme_tracker_analyst(formatted_data, summary)
                        all_analyses.append(theme_res)
                        with st.expander("🔥 题材追踪分析报告", expanded=False):
                            st.markdown(theme_res['analysis'])

                    # 4. 风险控制分析
                    with st.spinner("⚠️ 风险控制专家正在排除雷区与资金陷阱..."):
                        risk_res = agents.risk_control_specialist(formatted_data, summary)
                        all_analyses.append(risk_res)
                        with st.expander("⚠️ 风险控制扫描报告", expanded=False):
                            st.markdown(risk_res['analysis'])

                    # 5. 首席策略师综合评估
                    with st.spinner("👔 首席策略师正在综合各方情报，生成最终军令状..."):
                        chief_res = agents.chief_strategist(all_analyses)
                        st.markdown("### 👔 首席策略师最终研判")
                        st.markdown(chief_res['analysis'])
                else:
                    st.error(f"未能获取到 {date_str} 的龙虎榜数据，该日可能为周末或 API 暂时受限。")
# ================= Tab 6: 主力资金选股 =================
with tab6:
    render_main_force_tab()
