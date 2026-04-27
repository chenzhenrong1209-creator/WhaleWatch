import streamlit as st
from groq import Groq
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import re
import akshare as ak
import tushare as ts
import baostock as bs
import random
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import Counter
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import warnings
import json
import logging
import urllib3

warnings.filterwarnings('ignore')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    f"<div class='terminal-header'>TERMINAL BUILD v6.4.0 | SYS_TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | MULTI-TF HOTFIX + MANUAL OVERRIDE + MACRO AGENTS</div>",
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
    st.success("宏观多智能体 : ACTIVE")

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
        pass # 已复用主程序 call_ai 接口，无需初始化

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
活跃游资识别与画像  ⭐ 核心
识别当前最活跃的5-8个游资席位
分析每个游资的操作风格（激进型/稳健型/超短型/波段型）
评估游资的胜率和成功案例
识别知名"牛散"和"游资大佬"
游资操作特征分析
分析游资的买入特征（追高/低吸/打板/潜伏）
分析游资的卖出特征（一日游/持有周期/止盈止损）
识别游资的联合操作和接力特征
判断游资是否存在抱团现象
游资目标股票分析
分析游资重点关注的股票（前10只）
识别游资集体看好的股票（多席位介入）
分析游资选股的共性特征（题材/概念/技术形态）
评估游资介入股票的后续爆发力
游资进出节奏
判断游资整体是进攻还是防守状态
分析游资对热点的跟随速度
识别游资撤退的信号和板块
评估游资的持续作战能力
游资与题材的匹配
分析游资偏好的题材和概念
识别游资正在炒作的热点
判断题材的炒作周期位置
预判下一个游资可能关注的题材
风险与机会提示
识别游资可能设置的"陷阱"股票
提示游资一致性过高的风险（容易崩盘）
发现游资刚开始介入的潜力股
评估跟随游资的风险收益比
投资策略建议
推荐3-5只游资看好的潜力股票
提示2-3只游资可能出货的风险股票
给出跟随游资的操作建议
提供仓位和止损建议
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
次日大概率上涨股票挖掘  ⭐⭐⭐ 最核心
识别5-8只次日大概率上涨的股票
详细分析每只股票的上涨逻辑（资金面、技术面、题材面）
评估每只股票的上涨空间和确定性（高/中/低）
给出具体的买入价位和止损位
资金流向强度分析
识别主力资金大幅流入的股票（净买入前10）
分析资金流入的集中度和持续性
识别多席位联合买入的股票（强烈看好信号）
判断资金流入是真实买入还是诱多
技术形态评估
分析上榜股票的技术位置（突破/回调/整理）
识别处于启动阶段的股票
评估股票的技术支撑和阻力
判断股票的短期走势方向
题材与概念分析
识别当前最热门的题材和概念
分析题材的持续性和爆发力
找出题材龙头和低位补涨股
预判题材的炒作周期
游资持仓分析
识别游资重仓持有的股票
分析游资的一致性程度
判断游资是建仓、加仓还是出货
评估游资持仓的稳定性
上榜类型分析
分析日榜和三日榜的差异
识别连续上榜的股票（关注度高）
判断上榜的性质（放量突破/涨停板/异常波动）
评估不同上榜类型的后续表现概率
风险股票识别
识别3-5只高风险股票（游资可能出货）
分析卖出金额大于买入金额的股票
提示游资一日游后撤离的股票
警示技术面走坏的股票
操作策略建议
推荐5-8只次日重点关注的股票（按优先级排序）
给出每只股票的买入逻辑、买入价位、目标价位、止损价位
提供仓位分配建议
给出持有周期建议（超短/短线/波段）
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
热点题材识别  ⭐ 核心
识别当前最热门的5-8个题材/概念
分析每个题材的核心逻辑和催化剂
评估题材的市场关注度和参与度
判断题材是主流还是伪题材
题材炒作周期分析
判断每个题材所处的炒作周期（萌芽期/爆发期/高潮期/退潮期）
分析题材的爆发力和持续性
识别即将启动的新题材（萌芽期）
提示即将退潮的老题材（高潮期）
题材龙头与梯队
识别每个题材的龙头股（1-2只）
找出题材的跟风股和补涨股
分析龙头的地位是否稳固
判断是否存在龙头切换
游资对题材的态度
分析游资重点炒作的题材
判断游资对题材的认同度（一致/分歧）
识别游资集体进攻的题材（强势题材）
发现游资开始撤离的题材（弱势题材）
题材轮动特征
分析题材之间的轮动关系
识别强势题材和弱势题材
判断资金从哪个题材流向哪个题材
预判下一个可能启动的题材
题材与市场环境匹配度
分析题材是否符合当前市场风格
评估题材的政策支持度
判断题材的基本面支撑
识别纯粹炒作的题材
题材风险评估
识别过度炒作的题材（泡沫风险）
提示游资分歧加大的题材
警示题材逻辑破裂的风险
评估题材的回调风险
投资策略建议
推荐3-5个值得关注的强势题材
每个题材推荐1-2只最优标的
提供题材投资的时机选择
给出题材仓位和持有周期建议
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
高风险股票识别  ⭐ 核心
识别5-8只高风险股票（次日大概率下跌）
分析每只股票的风险点（游资出货/技术破位/题材退潮）
评估每只股票的风险等级（高/中/低）
给出规避建议和止损位
游资出货信号识别
识别卖出金额远大于买入金额的股票
分析游资"一日游"后撤离的股票
识别游资集体出货的股票（多席位卖出）
判断游资出货是正常获利了结还是预期恶化
资金陷阱识别
识别"虚假放量"的股票（实为对倒出货）
分析"高位放量滞涨"的股票
识别"拉高出货"的经典手法
提示"击鼓传花"的末期信号
题材风险评估
识别过度炒作的题材（泡沫严重）
分析题材逻辑破裂的风险
提示题材退潮的信号
评估题材的持续性风险
技术面风险提示
识别技术面走坏的股票（破位/跌破支撑）
分析高位震荡的股票（出货迹象）
提示连续上涨后的回调风险
评估短期超买的股票
情绪风险评估
识别市场情绪过热的信号
分析游资一致性过高的风险（易崩盘）
提示跟风盘过多的股票（接盘侠风险）
评估短期投机氛围的风险
系统性风险提示
分析整体龙虎榜数据反映的市场风险
评估游资整体是进攻还是防守
判断市场风险偏好的变化
提示可能的系统性调整风险
风险管理建议
提供仓位控制建议（重仓/轻仓/空仓）
给出止损止盈的纪律要求
建议规避的板块和题材
提供风险对冲策略
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
市场总体研判
综合评估当前龙虎榜反映的市场状态
判断游资整体的进攻或防守态度
评估短期市场的机会和风险
给出市场情绪和热度评分（0-100分）
次日重点推荐股票（TOP5-8）  ⭐⭐⭐ 最核心
综合4位分析师的意见，筛选出5-8只次日最有潜力的股票
每只股票必须包含：股票名称和代码、推荐理由、确定性评级、买入价位区间、目标价位、止损价位、持有周期建议
按推荐优先级排序
高风险警示股票（TOP3-5）
综合识别3-5只高风险股票
说明风险原因并给出规避建议
热点题材总结
总结当前2-3个最强势题材
每个题材推荐1-2只最优标的
操作策略建议
仓位管理建议（进攻/平衡/防守）
选股思路和方向
买卖时机选择
风险控制要求
注意事项
提示关键风险点
强调纪律执行
给出应对预案
"""
        analysis = call_ai(prompt)
        return {
            "agent_name": "首席策略师",
            "agent_role": "综合多维度分析，给出最终投资建议",
            "analysis": analysis,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

# ================= 新增：宏观分析核心模块 =================
class MacroAnalysisDataFetcher:
    """宏观分析板块数据获取器"""
    NBS_URL = "https://data.stats.gov.cn/easyquery.htm"

    NBS_SERIES_CONFIG = {
        "gdp_yoy": {"dbcode": "hgjd", "group_code": "A0103", "series_code": "A010301", "label": "GDP当季同比", "unit": "%", "period": "LAST8", "transform": "index_minus_100"},
        "gdp_qoq": {"dbcode": "hgjd", "group_code": "A0104", "series_code": "A010401", "label": "GDP环比增长", "unit": "%", "period": "LAST8"},
        "industrial_yoy": {"dbcode": "hgyd", "group_code": "A0201", "series_code": "A020101", "label": "规上工业增加值同比", "unit": "%", "period": "LAST8"},
        "cpi_yoy": {"dbcode": "hgyd", "group_code": "A01010J", "series_code": "A01010J01", "label": "CPI同比", "unit": "%", "period": "LAST8", "transform": "index_minus_100"},
        "ppi_yoy": {"dbcode": "hgyd", "group_code": "A010801", "series_code": "A01080101", "label": "PPI同比", "unit": "%", "period": "LAST8", "transform": "index_minus_100"},
        "manufacturing_pmi": {"dbcode": "hgyd", "group_code": "A0B01", "series_code": "A0B0101", "label": "制造业PMI", "unit": "", "period": "LAST8"},
        "non_manufacturing_pmi": {"dbcode": "hgyd", "group_code": "A0B02", "series_code": "A0B0201", "label": "非制造业商务活动指数", "unit": "", "period": "LAST8"},
        "composite_pmi": {"dbcode": "hgyd", "group_code": "A0B03", "series_code": "A0B0301", "label": "综合PMI产出指数", "unit": "", "period": "LAST8"},
        "m2_yoy": {"dbcode": "hgyd", "group_code": "A0D01", "series_code": "A0D0102", "label": "M2同比", "unit": "%", "period": "LAST8"},
        "retail_sales_yoy": {"dbcode": "hgyd", "group_code": "A0701", "series_code": "A070104", "label": "社零累计同比", "unit": "%", "period": "LAST8"},
        "fixed_asset_yoy": {"dbcode": "hgyd", "group_code": "A0401", "series_code": "A040102", "label": "固定资产投资累计同比", "unit": "%", "period": "LAST8"},
        "real_estate_invest_yoy": {"dbcode": "hgyd", "group_code": "A0601", "series_code": "A060102", "label": "房地产开发投资累计同比", "unit": "%", "period": "LAST8"},
        "urban_unemployment": {"dbcode": "hgyd", "group_code": "A0E01", "series_code": "A0E0101", "label": "全国城镇调查失业率", "unit": "%", "period": "LAST8"},
    }

    A_SHARE_INDEX_CONFIG = {
        "上证指数": "sh000001", "深证成指": "sz399001", "创业板指": "sz399006", "沪深300": "sh000300",
    }

    SECTOR_STOCK_POOLS = {
        "银行": [{"code": "600036", "name": "招商银行"}, {"code": "601166", "name": "兴业银行"}, {"code": "600919", "name": "江苏银行"}],
        "券商": [{"code": "600030", "name": "中信证券"}, {"code": "300059", "name": "东方财富"}, {"code": "601688", "name": "华泰证券"}],
        "保险": [{"code": "601318", "name": "中国平安"}, {"code": "601628", "name": "中国人寿"}, {"code": "601601", "name": "中国太保"}],
        "公用事业": [{"code": "600900", "name": "长江电力"}, {"code": "600025", "name": "华能水电"}, {"code": "600674", "name": "川投能源"}],
        "电网设备": [{"code": "600406", "name": "国电南瑞"}, {"code": "000400", "name": "许继电气"}, {"code": "600312", "name": "平高电气"}],
        "半导体": [{"code": "002371", "name": "北方华创"}, {"code": "688981", "name": "中芯国际"}, {"code": "603986", "name": "兆易创新"}],
        "算力AI": [{"code": "300308", "name": "中际旭创"}, {"code": "601138", "name": "工业富联"}, {"code": "000977", "name": "浪潮信息"}],
        "软件信创": [{"code": "688111", "name": "金山办公"}, {"code": "600588", "name": "用友网络"}, {"code": "600536", "name": "中国软件"}],
        "消费电子": [{"code": "002475", "name": "立讯精密"}, {"code": "002241", "name": "歌尔股份"}, {"code": "300433", "name": "蓝思科技"}],
        "食品饮料": [{"code": "600519", "name": "贵州茅台"}, {"code": "600887", "name": "伊利股份"}, {"code": "603288", "name": "海天味业"}],
        "家电": [{"code": "000333", "name": "美的集团"}, {"code": "000651", "name": "格力电器"}, {"code": "600690", "name": "海尔智家"}],
        "创新药": [{"code": "600276", "name": "恒瑞医药"}, {"code": "688235", "name": "百济神州"}, {"code": "002422", "name": "科伦药业"}],
        "汽车整车": [{"code": "002594", "name": "比亚迪"}, {"code": "000625", "name": "长安汽车"}, {"code": "600066", "name": "宇通客车"}],
        "工程机械": [{"code": "600031", "name": "三一重工"}, {"code": "000425", "name": "徐工机械"}, {"code": "000157", "name": "中联重科"}],
        "有色金属": [{"code": "601899", "name": "紫金矿业"}, {"code": "603993", "name": "洛阳钼业"}, {"code": "601600", "name": "中国铝业"}],
        "黄金": [{"code": "600547", "name": "山东黄金"}, {"code": "600489", "name": "中金黄金"}, {"code": "600988", "name": "赤峰黄金"}],
        "石油石化": [{"code": "600938", "name": "中国海油"}, {"code": "601857", "name": "中国石油"}, {"code": "600028", "name": "中国石化"}],
        "煤炭": [{"code": "601088", "name": "中国神华"}, {"code": "601225", "name": "陕西煤业"}, {"code": "601898", "name": "中煤能源"}],
        "通信运营商": [{"code": "600941", "name": "中国移动"}, {"code": "601728", "name": "中国电信"}, {"code": "600050", "name": "中国联通"}],
        "旅游酒店": [{"code": "601888", "name": "中国中免"}, {"code": "600258", "name": "首旅酒店"}, {"code": "600754", "name": "锦江酒店"}],
        "房地产": [{"code": "600048", "name": "保利发展"}, {"code": "001979", "name": "招商蛇口"}, {"code": "000002", "name": "万科A"}],
        "建材家居": [{"code": "002271", "name": "东方雨虹"}, {"code": "000786", "name": "北新建材"}, {"code": "603833", "name": "欧派家居"}],
        "农业": [{"code": "002714", "name": "牧原股份"}, {"code": "002311", "name": "海大集团"}, {"code": "000998", "name": "隆平高科"}],
        "军工": [{"code": "600760", "name": "中航沈飞"}, {"code": "000768", "name": "中航西飞"}, {"code": "600893", "name": "航发动力"}],
    }

    SECTOR_ALIASES = {
        "高股息": ["银行", "保险", "公用事业", "煤炭", "通信运营商"],
        "红利": ["银行", "保险", "公用事业", "煤炭", "通信运营商"],
        "电力": ["公用事业"], "电网": ["电网设备"], "算力": ["算力AI"], "AI": ["算力AI"],
        "信创": ["软件信创"], "医药": ["创新药"], "消费": ["食品饮料", "家电", "旅游酒店"],
        "顺周期": ["有色金属", "工程机械", "石油石化", "煤炭"],
    }

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        if not self.logger.handlers:
            logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")

    def fetch_all_data(self) -> Dict[str, Any]:
        result = {
            "success": False, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "macro_series": {}, "macro_snapshot": {}, "macro_tables": {},
            "market_indices": {}, "news": [], "candidate_pools": self.SECTION_POOLS_FOR_PROMPT(),
            "rule_based_sector_view": {}, "errors": [],
        }

        for key, config in self.NBS_SERIES_CONFIG.items():
            try:
                series = self._fetch_nbs_series(config)
                result["macro_series"][key] = series
            except Exception as exc:
                result["errors"].append(f"{config['label']}: {exc}")
                self.logger.warning("获取统计局指标失败 %s: %s", config["label"], exc)

        result["macro_snapshot"] = self._build_macro_snapshot(result["macro_series"])
        result["macro_tables"] = self._build_macro_tables(result["macro_series"])
        result["rule_based_sector_view"] = self.build_rule_based_sector_view(result["macro_snapshot"])

        try:
            result["market_indices"] = self._fetch_market_indices()
        except Exception as exc:
            result["errors"].append(f"市场指数: {exc}")

        try:
            result["news"] = self._fetch_macro_news()
        except Exception as exc:
            result["errors"].append(f"宏观新闻: {exc}")

        result["success"] = bool(result["macro_snapshot"])
        return result

    def SECTION_POOLS_FOR_PROMPT(self) -> Dict[str, List[Dict[str, str]]]:
        return self.SECTOR_STOCK_POOLS

    def _post_query(self, params: Dict[str, Any]) -> Dict[str, Any]:
        response = requests.post(
            self.NBS_URL, params=params, verify=False, allow_redirects=True, timeout=30
        )
        response.raise_for_status()
        data = response.json()
        if data.get("returncode") != 200:
            raise ValueError(data.get("returndata", "统计局接口返回异常"))
        return data["returndata"]

    def _fetch_nbs_series(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        params = {
            "m": "QueryData", "dbcode": config["dbcode"], "rowcode": "zb", "colcode": "sj",
            "wds": "[]",
            "dfwds": json.dumps([{"wdcode": "zb", "valuecode": config["group_code"]}, {"wdcode": "sj", "valuecode": config["period"]}], ensure_ascii=False),
            "k1": str(int(time.time() * 1000)),
        }
        data = self._post_query(params)
        wdnodes = data["wdnodes"]
        indicator_nodes = {item["code"]: item for item in wdnodes[0]["nodes"]}
        time_nodes = {item["code"]: item for item in wdnodes[1]["nodes"]}

        rows: List[Dict[str, Any]] = []
        for node in data["datanodes"]:
            match = re.search(r"zb\.([^_]+)_sj\.([^_]+)", node["code"])
            if not match: continue
            series_code, period_code = match.groups()
            if series_code != config["series_code"]: continue
            node_data = node.get("data", {}) or {}
            value = node_data.get("data")
            if node_data.get("strdata", "") == "" or value in ("", None): continue
            rows.append({
                "series_code": series_code,
                "series_label": indicator_nodes.get(series_code, {}).get("cname", config["label"]),
                "period_code": period_code,
                "period_label": time_nodes.get(period_code, {}).get("cname", period_code),
                "value_raw": float(value),
                "value": self._transform_value(float(value), config),
                "unit": config.get("unit", ""),
            })
        rows.sort(key=lambda item: item["period_code"], reverse=True)
        return rows

    @staticmethod
    def _transform_value(value: float, config: Dict[str, Any]) -> float:
        if config.get("transform") == "index_minus_100":
            return round(value - 100, 2)
        return round(value, 2)

    def _build_macro_snapshot(self, macro_series: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {}
        for key, series in macro_series.items():
            if not series: continue
            latest = series[0]
            previous = series[1] if len(series) > 1 else None
            change = round(latest["value"] - previous["value"], 2) if previous else None
            snapshot[key] = {
                "label": self.NBS_SERIES_CONFIG[key]["label"],
                "value": latest["value"], "value_raw": latest["value_raw"], "unit": latest["unit"],
                "period_label": latest["period_label"],
                "previous_value": previous["value"] if previous else None,
                "previous_period_label": previous["period_label"] if previous else None,
                "change": change,
            }
        return snapshot

    def _build_macro_tables(self, macro_series: Dict[str, List[Dict[str, Any]]]) -> Dict[str, pd.DataFrame]:
        tables: Dict[str, pd.DataFrame] = {}
        for key, series in macro_series.items():
            if not series: continue
            tables[key] = pd.DataFrame([{
                "期间": item["period_label"], "数值": item["value"], "原始值": item["value_raw"], "单位": item["unit"] or "-"
            } for item in series])
        return tables

    def _fetch_market_indices(self) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for label, symbol in self.A_SHARE_INDEX_CONFIG.items():
            df = ak.stock_zh_index_daily(symbol=symbol)
            if df is None or df.empty: continue
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest
            result[label] = {
                "close": round(float(latest["close"]), 2), "date": str(latest["date"]),
                "daily_change_pct": round(((float(latest["close"]) - float(prev["close"])) / float(prev["close"])) * 100, 2) if float(prev["close"]) != 0 else 0.0,
                "pct_20d": self._calc_return(df, 20), "pct_60d": self._calc_return(df, 60),
            }
        return result

    @staticmethod
    def _calc_return(df: pd.DataFrame, days: int) -> float:
        if len(df) <= days: return 0.0
        latest = float(df.iloc[-1]["close"])
        base = float(df.iloc[-days - 1]["close"])
        if base == 0: return 0.0
        return round((latest - base) / base * 100, 2)

    def _fetch_macro_news(self, limit: int = 12) -> List[Dict[str, str]]:
        df = ak.stock_info_global_em()
        if df is None or df.empty: return []
        keywords = ["财政", "货币", "央行", "国常会", "国务院", "地产", "消费", "PMI", "CPI", "PPI", "失业率", "投资", "论坛"]
        rows: List[Dict[str, str]] = []
        for _, row in df.iterrows():
            title, summary = str(row.get("标题", "")), str(row.get("摘要", ""))
            if keywords and not any(word in title or word in summary for word in keywords): continue
            rows.append({
                "title": title, "summary": summary[:180],
                "publish_time": str(row.get("发布时间", "")), "url": str(row.get("链接", "")),
            })
            if len(rows) >= limit: break
        return rows

    def build_rule_based_sector_view(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        scores = {sector: 0 for sector in self.SECTOR_STOCK_POOLS.keys()}
        reasons = {sector: [] for sector in self.SECTOR_STOCK_POOLS.keys()}
        def value_of(key: str) -> Optional[float]: return snapshot.get(key, {}).get("value")

        m2_yoy = value_of("m2_yoy")
        cpi_yoy = value_of("cpi_yoy")
        manufacturing_pmi = value_of("manufacturing_pmi")
        non_manufacturing_pmi = value_of("non_manufacturing_pmi")
        retail_sales_yoy = value_of("retail_sales_yoy")
        fixed_asset_yoy = value_of("fixed_asset_yoy")
        industrial_yoy = value_of("industrial_yoy")
        ppi_yoy = value_of("ppi_yoy")
        real_estate_yoy = value_of("real_estate_invest_yoy")
        unemployment = value_of("urban_unemployment")

        if m2_yoy is not None and m2_yoy >= 7:
            for s in ["银行", "券商", "保险", "公用事业", "通信运营商"]: scores[s] += 2; reasons[s].append("流动性保持充裕")
        if cpi_yoy is not None and cpi_yoy <= 1:
            for s in ["银行", "公用事业", "食品饮料", "家电"]: scores[s] += 1; reasons[s].append("通胀温和为估值修复留出空间")
        if manufacturing_pmi is not None and manufacturing_pmi >= 50:
            for s in ["工程机械", "有色金属", "半导体", "算力AI", "软件信创"]: scores[s] += 2; reasons[s].append("制造业景气改善")
        elif manufacturing_pmi is not None:
            for s in ["工程机械", "有色金属", "半导体"]: scores[s] -= 1; reasons[s].append("制造业景气仍在荣枯线下")
        if non_manufacturing_pmi is not None and non_manufacturing_pmi >= 50:
            for s in ["旅游酒店", "食品饮料", "家电", "汽车整车"]: scores[s] += 1; reasons[s].append("服务消费活跃度改善")
        if retail_sales_yoy is not None and retail_sales_yoy >= 4:
            for s in ["食品饮料", "家电", "旅游酒店", "汽车整车"]: scores[s] += 2; reasons[s].append("消费数据偏强")
        if fixed_asset_yoy is not None and fixed_asset_yoy >= 3:
            for s in ["工程机械", "电网设备", "有色金属"]: scores[s] += 2; reasons[s].append("投资端仍有托底")
        if industrial_yoy is not None and industrial_yoy >= 5:
            for s in ["工程机械", "有色金属", "军工", "半导体"]: scores[s] += 1; reasons[s].append("工业生产维持扩张")
        if ppi_yoy is not None and ppi_yoy < 0:
            for s in ["煤炭", "石油石化", "有色金属"]: scores[s] -= 1; reasons[s].append("工业品价格仍承压")
        if real_estate_yoy is not None and real_estate_yoy < 0:
            for s in ["房地产", "建材家居"]: scores[s] -= 3; reasons[s].append("地产投资仍弱")
        if unemployment is not None and unemployment >= 5.3:
            for s in ["可选消费", "旅游酒店"]:
                if s in scores: scores[s] -= 1; reasons[s].append("就业压力抑制可选消费")

        bullish = sorted([{"sector": s, "score": sc, "logic": "；".join(reasons[s][:3]) or "宏观环境相对受益"} for s, sc in scores.items() if sc > 0], key=lambda x: x["score"], reverse=True)[:6]
        bearish = sorted([{"sector": s, "score": sc, "logic": "；".join(reasons[s][:3]) or "宏观环境相对承压"} for s, sc in scores.items() if sc < 0], key=lambda x: x["score"])[:4]

        return {
            "market_view": self._infer_market_view(snapshot),
            "bullish_sectors": bullish, "bearish_sectors": bearish,
            "watch_signals": self._build_watch_signals(snapshot),
        }

    def _infer_market_view(self, snapshot: Dict[str, Any]) -> str:
        growth_score = sum([
            1 if snapshot.get("gdp_yoy", {}).get("value", 0) >= 4.5 else 0,
            1 if snapshot.get("manufacturing_pmi", {}).get("value", 0) >= 50 else 0,
            1 if snapshot.get("retail_sales_yoy", {}).get("value", 0) >= 4 else 0,
            -1 if snapshot.get("real_estate_invest_yoy", {}).get("value", 0) < 0 else 0,
            -1 if snapshot.get("urban_unemployment", {}).get("value", 0) >= 5.3 else 0
        ])
        if growth_score >= 2: return "震荡偏多"
        if growth_score <= -1: return "震荡偏谨慎"
        return "结构性机会为主"

    def _build_watch_signals(self, snapshot: Dict[str, Any]) -> List[str]:
        signals = []
        for key in ["manufacturing_pmi", "retail_sales_yoy", "m2_yoy", "real_estate_invest_yoy"]:
            item = snapshot.get(key)
            if not item: continue
            signals.append(
                f"{item['label']} 最新 {item['period_label']} 为 {item['value']}{item['unit']}，"
                f"较上一期变动 {item['change']:+.2f}{item['unit'] if item['change'] is not None else ''}" if item.get("change") is not None else f"{item['label']} 最新 {item['period_label']} 为 {item['value']}{item['unit']}"
            )
        return signals

    def build_stock_candidates_for_sectors(self, sectors: List[str], limit_per_sector: int = 3, total_limit: int = 12) -> List[Dict[str, Any]]:
        selected_sector_keys: List[str] = []
        for sector in sectors:
            for key in self._match_sector_keys(sector):
                if key not in selected_sector_keys: selected_sector_keys.append(key)
        if not selected_sector_keys: selected_sector_keys = ["银行", "公用事业", "食品饮料", "半导体"]

        candidates: List[Dict[str, Any]] = []
        for sector_key in selected_sector_keys:
            for stock in self.SECTOR_STOCK_POOLS.get(sector_key, [])[:limit_per_sector]:
                enriched = self._enrich_stock_snapshot(stock["code"], stock["name"], sector_key)
                if enriched: candidates.append(enriched)
                if len(candidates) >= total_limit: return candidates
        return candidates

    def _match_sector_keys(self, sector_name: str) -> List[str]:
        if sector_name in self.SECTOR_STOCK_POOLS: return [sector_name]
        matches = [k for k in self.SECTOR_STOCK_POOLS.keys() if sector_name in k or k in sector_name]
        if matches: return matches
        for alias, mapped in self.SECTOR_ALIASES.items():
            if alias in sector_name: return mapped
        return []

    def _enrich_stock_snapshot(self, code: str, fallback_name: str, sector_name: str) -> Optional[Dict[str, Any]]:
        info_map = {}
        try:
            info_df = ak.stock_individual_info_em(symbol=code)
            if info_df is not None and not info_df.empty:
                info_map = {str(row["item"]).strip(): str(row["value"]).strip() for _, row in info_df.iterrows()}
        except Exception: pass

        base_res = {
            "code": code, "name": info_map.get("股票简称", fallback_name),
            "sector": sector_name, "industry": info_map.get("行业", sector_name),
            "price": None, "daily_change_pct": None, "change_amount": None,
            "turnover_rate": None, "volume": None,
            "pe_ratio": self._to_float(info_map.get("市盈率(动态)")), "pb_ratio": self._to_float(info_map.get("市净率")),
            "market_cap": self._to_float(info_map.get("总市值")),
            "recent_20d_return": None, "recent_60d_return": None, "listed_date": info_map.get("上市时间", "")
        }
        try:
            start_date = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")
            end_date = datetime.now().strftime("%Y%m%d")
            hist_df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
            if hist_df is not None and not hist_df.empty:
                latest = hist_df.iloc[-1]
                base_res.update({
                    "price": round(float(latest["收盘"]), 2), "daily_change_pct": round(float(latest["涨跌幅"]), 2),
                    "change_amount": round(float(latest["涨跌额"]), 2), "turnover_rate": self._to_float(latest.get("换手率")),
                    "volume": self._to_float(latest.get("成交量")),
                    "recent_20d_return": self._calc_hist_return(hist_df, 20), "recent_60d_return": self._calc_hist_return(hist_df, 60),
                })
        except Exception: pass
        return base_res

    @staticmethod
    def _calc_hist_return(hist_df: pd.DataFrame, days: int) -> float:
        if len(hist_df) <= days: return 0.0
        latest, base = float(hist_df.iloc[-1]["收盘"]), float(hist_df.iloc[-days - 1]["收盘"])
        if base == 0: return 0.0
        return round((latest - base) / base * 100, 2)

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        if value in (None, "", "-", "--"): return None
        try: return round(float(str(value).replace(",", "")), 2)
        except Exception: return None

    def build_prompt_context(self, data: Dict[str, Any]) -> str:
        snapshot = data.get("macro_snapshot", {})
        lines = ["===== 当前国内宏观数据快照（国家统计局） ====="]
        for key in self.NBS_SERIES_CONFIG.keys():
            item = snapshot.get(key)
            if not item: continue
            change_str = f"，较上一期变动 {item['change']:+.2f}{item['unit']}" if item.get("change") is not None else ""
            lines.append(f"- {item['label']}: {item['value']}{item['unit']} ({item['period_label']}){change_str}")

        lines.append("\n===== A股指数快照 =====")
        for name, info in data.get("market_indices", {}).items():
            lines.append(f"- {name}: {info['close']}，日涨跌 {info['daily_change_pct']:+.2f}%，20日 {info['pct_20d']:+.2f}%，60日 {info['pct_60d']:+.2f}%")

        if data.get("news"):
            lines.append("\n===== 宏观新闻样本 =====")
            for item in data["news"][:8]:
                lines.append(f"- {item['publish_time']} | {item['title']} | {item['summary']}")

        lines.append("\n===== 可选行业板块池（供AI输出时严格从中选择） =====")
        lines.append("、".join(self.SECTOR_STOCK_POOLS.keys()))
        return "\n".join(lines)

class MacroAnalysisAgents:
    """宏观分析多智能体 (基于主引擎 call_ai 重构)"""
    def __init__(self, model: str | None = None) -> None:
        self.model = model

    def macro_analyst_agent(self, context_text: str) -> Dict[str, Any]:
        prompt = f"""
你是一位资深中国宏观经济研究员。请严格基于下面的数据，分析当前国内宏观经济形势。

{context_text}

请重点回答：
1. 当前中国经济处于什么阶段，增长、通胀、就业、地产、信用各自是什么状态。
2. 当前宏观环境的核心矛盾是什么。
3. 未来1-2个季度最关键的跟踪变量有哪些。
4. 输出必须紧扣中国A股投资，不要空泛。
"""
        return self._call_text(
            "你是中国宏观经济分析师，擅长从官方数据中提炼当前经济主线。",
            prompt, agent_name="宏观总量分析师", focus_areas=["增长", "通胀", "就业", "地产", "信用"],
        )

    def policy_analyst_agent(self, context_text: str) -> Dict[str, Any]:
        prompt = f"""
你是一位资深的政策与流动性分析师。请基于下面的数据和新闻，评估当前中国政策环境与流动性状态。

{context_text}

请重点回答：
1. 当前政策组合更偏稳增长、稳地产、稳信用还是防风险。
2. 流动性是否对A股估值形成支撑。
3. 哪些方向更可能获得政策支持，哪些方向政策弹性偏弱。
4. 必须写出对A股风格和板块轮动的含义。
"""
        return self._call_text(
            "你是中国政策与流动性分析师，擅长把政策信号映射到A股行业风格。",
            prompt, agent_name="政策流动性分析师", focus_areas=["货币", "财政", "产业政策", "估值", "风格"],
        )

    def sector_mapper_agent(self, context_text: str, rule_view: Dict[str, Any], sector_pool: List[str]) -> Dict[str, Any]:
        prompt = f"""
你是一位A股行业配置分析师。请严格从给定行业板块池中选择，结合宏观数据、政策环境与A股指数状态，输出未来1-2个季度更可能受益和承压的行业板块。

可选板块池：
{", ".join(sector_pool)}

规则基线（可修正，但不能完全脱离）：
{json.dumps(rule_view, ensure_ascii=False, indent=2)}

宏观与市场上下文：
{context_text}

请只返回 JSON，不要写任何额外解释。格式如下：
{{
  "market_view": "震荡偏多/结构性机会/震荡偏谨慎",
  "bullish_sectors": [
    {{"sector": "银行", "logic": "逻辑", "confidence": 0.78}},
    {{"sector": "公用事业", "logic": "逻辑", "confidence": 0.72}}
  ],
  "bearish_sectors": [
    {{"sector": "房地产", "logic": "逻辑", "confidence": 0.81}}
  ],
  "watch_signals": ["一句话监控点1", "一句话监控点2"]
}}

要求：
1. `bullish_sectors` 输出 4-6 个；
2. `bearish_sectors` 输出 2-4 个；
3. 行业名称必须从板块池中选择；
4. `confidence` 用 0-1 之间小数；
5. 逻辑必须结合宏观数据，不要泛化成“政策支持”四个字。
"""
        structured = self._call_json("你是A股行业配置分析师，只输出合法JSON。", prompt, fallback=rule_view)
        analysis_prompt = f"""
请基于以下结构化结论，写一份可读性强的中文行业配置报告：
{json.dumps(structured, ensure_ascii=False, indent=2)}

要求：
1. 先说市场主线；
2. 再解释看多板块和看空板块；
3. 每个板块都要写出宏观传导链；
4. 结尾补一段风格偏好与风险提示。
"""
        full_prompt = f"你是A股行业配置分析师，擅长把结构化结论写成可执行策略。\n\n{analysis_prompt}"
        analysis = call_ai(full_prompt, model=self.model, temperature=0.5)
        return {
            "agent_name": "行业映射分析师", "agent_role": "将宏观变量映射为A股行业利好与利空方向",
            "analysis": analysis, "structured": structured,
            "focus_areas": ["行业轮动", "顺周期", "红利", "科技成长"],
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def stock_selector_agent(self, context_text: str, sector_view: Dict[str, Any], stock_candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        candidate_text = json.dumps(stock_candidates, ensure_ascii=False, indent=2)
        prompt = f"""
你是一位A股选股分析师。请从候选股票中挑选更适合当前宏观环境的优质标的。

宏观与行业上下文：
{context_text}

行业配置结论：
{json.dumps(sector_view, ensure_ascii=False, indent=2)}

候选股票池：
{candidate_text}

请只返回 JSON，格式如下：
{{
  "recommended_stocks": [
    {{
      "code": "600036",
      "name": "招商银行",
      "sector": "银行",
      "reason": "推荐逻辑",
      "risk": "主要风险",
      "style": "稳健/进攻/均衡",
      "confidence": 0.82
    }}
  ],
  "watchlist": [
    {{"code": "002371", "name": "北方华创", "sector": "半导体", "reason": "观察逻辑"}}
  ]
}}

要求：
1. `recommended_stocks` 输出 4-8 只；
2. 优先选择与当前宏观主线匹配、质量相对更高、回撤承受度更可控的标的；
3. 推荐逻辑要结合行业、估值/质量、走势位置三个维度；
4. 不要推荐候选池外的股票。
"""
        fallback = {"recommended_stocks": stock_candidates[:6], "watchlist": stock_candidates[6:10]}
        structured = self._call_json("你是A股选股分析师，只输出合法JSON。", prompt, fallback=fallback)
        analysis_prompt = f"""
请基于以下结构化选股结果，输出一份中文选股说明：
{json.dumps(structured, ensure_ascii=False, indent=2)}

要求：
1. 解释为什么这些股票适配当前宏观环境；
2. 每只股票都要写一句核心催化与一句核心风险；
3. 明确区分“优先关注”和“观察名单”。
"""
        full_prompt = f"你是A股选股分析师，输出简洁、专业、可执行。\n\n{analysis_prompt}"
        analysis = call_ai(full_prompt, model=self.model, temperature=0.5)
        return {
            "agent_name": "优质标的分析师", "agent_role": "从宏观受益方向中筛选更适合当前环境的A股标的",
            "analysis": analysis, "structured": structured,
            "focus_areas": ["候选股筛选", "风险收益比", "风格适配"],
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def chief_strategist_agent(self, context_text: str, macro_report: str, policy_report: str, sector_view: Dict[str, Any], stock_view: Dict[str, Any]) -> Dict[str, Any]:
        prompt = f"""
你是一位首席策略官，需要给出当前A股后市的综合结论。

宏观与市场上下文：
{context_text}

【宏观总量分析师】
{macro_report}

【政策流动性分析师】
{policy_report}

【行业映射结论】
{json.dumps(sector_view, ensure_ascii=False, indent=2)}

【优质标的结论】
{json.dumps(stock_view, ensure_ascii=False, indent=2)}

请输出一份结构清晰的综合报告，至少包含：
1. 当前宏观判断
2. A股后市展望
3. 利好板块与逻辑
4. 利空板块与逻辑
5. 优质标的与关注理由
6. 风险提示与需要跟踪的数据点
"""
        return self._call_text("你是首席策略官，擅长把宏观、行业和选股结论整合成完整投资框架。", prompt, agent_name="首席策略官", focus_areas=["总策略", "行业配置", "选股落地", "风险提示"])

    def _call_text(self, system_prompt: str, user_prompt: str, agent_name: str, focus_areas: List[str], max_tokens: int = 3200, temperature: float = 0.45) -> Dict[str, Any]:
        prompt = f"{system_prompt}\n\n{user_prompt}"
        analysis = call_ai(prompt, model=self.model, temperature=temperature)
        return {
            "agent_name": agent_name, "analysis": analysis,
            "focus_areas": focus_areas, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _call_json(self, system_prompt: str, user_prompt: str, fallback: Dict[str, Any], max_tokens: int = 2800) -> Dict[str, Any]:
        prompt = f"{system_prompt}\n\n{user_prompt}\n\n请严格返回合法的JSON对象。"
        response = call_ai(prompt, model=self.model, temperature=0.2)
        parsed = self._extract_json(response)
        if isinstance(parsed, dict):
            return parsed
        return fallback

    @staticmethod
    def _extract_json(text: str) -> Dict[str, Any] | None:
        if not text: return None
        text = text.strip()
        candidates = [text]
        fenced = re.findall(r"
http://googleusercontent.com/immersive_entry_chip/0
