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
    f"<div class='terminal-header'>TERMINAL BUILD v6.4.3-LHB-NO-STOCKAPI | SYS_TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | MULTI-TF HOTFIX + MANUAL OVERRIDE</div>",
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
def fast_fetch_json(url, timeout=2.5, extra_headers=None):
    """首页/看板专用极速请求：不走重试器，避免一个接口拖住整个页面。"""
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Referer": "https://finance.eastmoney.com/",
        "Accept": "application/json,text/plain,*/*",
    }
    if extra_headers:
        headers.update(extra_headers)
    try:
        res = requests.get(url, headers=headers, timeout=timeout)
        if res.status_code != 200:
            return None
        return res.json()
    except Exception:
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

# ================= 多周期数据与分析（增强稳定版） =================
def normalize_min_df(df: pd.DataFrame):
    """统一分钟 K 线字段，兼容 AKShare / 东方财富返回格式。"""
    if df is None or df.empty:
        return None
    rename_map = {}
    for col in df.columns:
        if col in ["时间", "日期", "datetime", "date", "time"]:
            rename_map[col] = "date"
        elif col in ["开盘", "open"]:
            rename_map[col] = "open"
        elif col in ["收盘", "close"]:
            rename_map[col] = "close"
        elif col in ["最高", "high"]:
            rename_map[col] = "high"
        elif col in ["最低", "low"]:
            rename_map[col] = "low"
        elif col in ["成交量", "volume", "vol"]:
            rename_map[col] = "volume"
    df = df.rename(columns=rename_map).copy()
    need_cols = ["date", "open", "high", "low", "close", "volume"]
    if not all(col in df.columns for col in need_cols):
        return None
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=need_cols).sort_values("date").reset_index(drop=True)
    if df.empty:
        return None
    return df[need_cols]


def _get_market_id(symbol: str) -> str:
    """东方财富 secid 市场代码：沪市/科创/基金为 1，其余深市为 0。"""
    symbol = str(symbol).strip()
    return "1" if symbol.startswith(("6", "9", "5", "7")) else "0"


def fetch_em_minute_df(symbol: str, klt: int = 15, lmt: int = 600):
    """东方财富分钟 K 线兜底。klt 支持 1/5/15/30/60。"""
    market = _get_market_id(symbol)
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get?"
        f"secid={market}.{symbol}&ut=fa5fd1943c7b386f172d6893dbfba10b"
        "&fields1=f1,f2,f3,f4,f5,f6"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
        f"&klt={klt}&fqt=1&end=20500101&lmt={lmt}"
    )
    try:
        res = fetch_json(url, timeout=8)
        if not res or not res.get("data") or not res["data"].get("klines"):
            return None
        rows = []
        for item in res["data"].get("klines", []):
            parts = str(item).split(",")
            if len(parts) >= 6:
                rows.append({
                    "date": parts[0],
                    "open": parts[1],
                    "close": parts[2],
                    "high": parts[3],
                    "low": parts[4],
                    "volume": parts[5],
                })
        return normalize_min_df(pd.DataFrame(rows)) if rows else None
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"东财 {klt}分钟 K 线失败: {e}")
        return None


@st.cache_data(ttl=120, show_spinner=False)
def get_intraday_by_period(symbol: str, period: str, max_rows=320):
    """多源获取分钟 K 线：AKShare 优先，东方财富兜底。"""
    period = str(period)
    try:
        df = ak.stock_zh_a_hist_min_em(symbol=str(symbol), period=period, adjust="")
        df = normalize_min_df(df)
        if df is not None and not df.empty:
            df["source"] = f"AKShare-{period}m"
            return df.tail(max_rows).reset_index(drop=True)
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"AKShare {period}分钟数据失败，切换东财: {e}")
    try:
        df = fetch_em_minute_df(symbol, klt=int(period), lmt=max(max_rows, 600))
        if df is not None and not df.empty:
            df["source"] = f"EastMoney-{period}m"
            return df.tail(max_rows).reset_index(drop=True)
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"东财 {period}分钟数据失败: {e}")
    return None


def get_intraday_15m(symbol, max_rows=320):
    return get_intraday_by_period(symbol, "15", max_rows=max_rows)


def aggregate_minutes(df: pd.DataFrame, bars_per_group: int, label: str | None = None):
    if df is None or df.empty:
        return None
    all_parts = []
    df = df.copy()
    df["trade_day"] = df["date"].dt.date
    for _, day_df in df.groupby("trade_day"):
        day_df = day_df.sort_values("date").reset_index(drop=True)
        grp = pd.Series(range(len(day_df))) // bars_per_group
        g = day_df.groupby(grp)
        part = pd.DataFrame({
            "date": g["date"].last(),
            "open": g["open"].first(),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(),
            "volume": g["volume"].sum(),
        })
        all_parts.append(part)
    if not all_parts:
        return None
    out = pd.concat(all_parts, ignore_index=True).dropna().reset_index(drop=True)
    if not out.empty:
        out["source"] = label or "聚合分钟线"
    return out


def _fallback_daily_as_intraday(symbol: str, days: int = 60):
    """分钟数据完全失败时，用日线降级，确保页面不再全是 N/A。"""
    try:
        df = get_kline(symbol, days=days)
        if df is not None and not df.empty:
            df = df[["date", "open", "high", "low", "close", "volume"]].copy()
            df["source"] = "日线降级"
            return df.reset_index(drop=True)
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"日线降级失败: {e}")
    return None


def summarize_intraday_tf(df: pd.DataFrame, label: str):
    """输出尽量可用的多周期结果。即使样本较少，也给轻量判断。"""
    empty_result = {
        "label": label, "status": "无数据", "source": "无", "bars": 0,
        "latest_time": "-", "trend": "无法判断", "rsi": None, "macd_state": "无法判断",
        "support": None, "pressure": None, "close": None, "change_pct": None,
        "vol_ratio": None, "bias": "无法判断", "score": 0,
        "entry_zone": "-", "stop_loss": None, "target_1": None, "target_2": None,
        "advice": "数据不足，先观察"
    }
    if df is None or df.empty:
        return empty_result

    df = df.copy().dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if df.empty:
        return empty_result

    source = str(df["source"].iloc[-1]) if "source" in df.columns else "行情源"
    bars = len(df)
    latest = df.iloc[-1]
    close = float(latest["close"])
    support = float(df.tail(min(20, bars))["low"].min())
    pressure = float(df.tail(min(20, bars))["high"].max())
    latest_time = str(pd.to_datetime(latest["date"]).strftime("%Y-%m-%d %H:%M")) if pd.notna(latest["date"]) else "-"
    first_close = float(df.iloc[0]["close"])
    change_pct = round((close - first_close) / first_close * 100, 2) if first_close else 0.0

    if bars < 12:
        recent_close = df["close"].tail(min(5, bars))
        slope = recent_close.iloc[-1] - recent_close.iloc[0] if len(recent_close) >= 2 else 0
        loc = (close - support) / (pressure - support) if pressure > support else 0.5
        score = 0
        score += 1 if slope > 0 else -1 if slope < 0 else 0
        score += 1 if change_pct > 0 else -1 if change_pct < 0 else 0
        score += 1 if loc > 0.55 else -1 if loc < 0.35 else 0
        trend = "偏强" if score > 0 else "偏弱" if score < 0 else "震荡"
        bias = "轻量偏多" if score >= 1 else "轻量偏空" if score <= -1 else "轻量震荡"
        stop_loss = round(support * 0.985, 2) if support else None
        target_1 = round(pressure, 2) if pressure else None
        target_2 = round(close + (close - stop_loss) * 1.5, 2) if stop_loss else None
        return {
            "label": label, "status": "样本较少", "source": source, "bars": bars,
            "latest_time": latest_time, "trend": trend, "rsi": None, "macd_state": "简化判断",
            "support": support, "pressure": pressure, "close": close, "change_pct": change_pct,
            "vol_ratio": None, "bias": bias, "score": score,
            "entry_zone": f"{support:.2f} - {close:.2f}", "stop_loss": stop_loss,
            "target_1": target_1, "target_2": target_2,
            "advice": "样本较少，仅作为轻量参考"
        }

    df = add_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    close = float(latest["close"])
    ema_s = latest.get("ema_short", pd.NA)
    ema_m = latest.get("ema_mid", pd.NA)
    rsi = latest.get("rsi14", pd.NA)
    atr = latest.get("atr14", pd.NA)

    trend = "震荡"
    if pd.notna(ema_s) and pd.notna(ema_m) and close > ema_s > ema_m:
        trend = "多头"
    elif pd.notna(ema_s) and pd.notna(ema_m) and close < ema_s < ema_m:
        trend = "空头"
    elif pd.notna(ema_s) and close > ema_s:
        trend = "偏强"
    elif pd.notna(ema_s) and close < ema_s:
        trend = "偏弱"

    macd_state = "中性"
    if pd.notna(latest.get("macd")) and pd.notna(latest.get("macd_signal")):
        if latest["macd"] > latest["macd_signal"] and latest["macd_hist"] >= prev["macd_hist"]:
            macd_state = "偏多"
        elif latest["macd"] < latest["macd_signal"] and latest["macd_hist"] <= prev["macd_hist"]:
            macd_state = "偏空"

    support = float(df.tail(min(20, len(df)))["low"].min())
    pressure = float(df.tail(min(20, len(df)))["high"].max())
    avg_vol = df["volume"].tail(min(20, len(df))).mean()
    vol_ratio = round(float(latest["volume"]) / avg_vol, 2) if avg_vol and avg_vol > 0 else None

    score = 0
    score += 2 if trend == "多头" else 1 if trend == "偏强" else -2 if trend == "空头" else -1 if trend == "偏弱" else 0
    score += 1 if macd_state == "偏多" else -1 if macd_state == "偏空" else 0
    if pd.notna(rsi):
        score += 1 if 55 <= rsi <= 70 else -1 if rsi < 45 or rsi > 82 else 0
    if vol_ratio is not None:
        score += 1 if vol_ratio >= 1.3 and change_pct >= 0 else -1 if vol_ratio >= 1.3 and change_pct < 0 else 0

    bias = "多头占优" if score >= 3 else "偏多观察" if score >= 1 else "空头占优" if score <= -3 else "偏空谨慎" if score <= -1 else "震荡分歧"
    atr_val = float(atr) if pd.notna(atr) and atr > 0 else max((pressure - support) / 4, close * 0.015)
    entry_low = max(support, close - atr_val * 0.8)
    entry_high = close
    stop_loss = max(0, support - atr_val * 0.35)
    target_1 = pressure
    target_2 = close + max(close - stop_loss, atr_val) * 1.8
    advice = "顺势持有/回踩低吸" if score >= 3 else "偏多但等回踩确认" if score >= 1 else "谨慎，等重新站上均线" if score <= -1 else "震荡，等方向选择"

    return {
        "label": label, "status": "有效", "source": source, "bars": len(df),
        "latest_time": latest_time, "trend": trend, "rsi": float(rsi) if pd.notna(rsi) else None,
        "macd_state": macd_state, "support": support, "pressure": pressure, "close": close,
        "change_pct": change_pct, "vol_ratio": vol_ratio, "bias": bias, "score": score,
        "entry_zone": f"{entry_low:.2f} - {entry_high:.2f}", "stop_loss": round(stop_loss, 2),
        "target_1": round(target_1, 2), "target_2": round(target_2, 2), "advice": advice
    }


def get_multi_timeframe_analysis(symbol: str):
    df15 = get_intraday_15m(symbol)
    df60_direct = get_intraday_by_period(symbol, "60", max_rows=260)
    df60 = df60_direct if df60_direct is not None and not df60_direct.empty else aggregate_minutes(df15, 4, label="15m聚合60m")
    df120 = aggregate_minutes(df60, 2, label="60m聚合120m") if df60 is not None else aggregate_minutes(df15, 8, label="15m聚合120m")

    fallback_daily = None
    if df15 is None and df60 is None and df120 is None:
        fallback_daily = _fallback_daily_as_intraday(symbol)
    if df15 is None and fallback_daily is not None:
        df15 = fallback_daily.tail(30).copy()
        df15["source"] = "日线降级-短周期参考"
    if df60 is None and fallback_daily is not None:
        df60 = fallback_daily.tail(45).copy()
        df60["source"] = "日线降级-中周期参考"
    if df120 is None and fallback_daily is not None:
        df120 = fallback_daily.tail(60).copy()
        df120["source"] = "日线降级-长周期参考"

    tf15 = summarize_intraday_tf(df15, "15分钟")
    tf60 = summarize_intraday_tf(df60, "60分钟")
    tf120 = summarize_intraday_tf(df120, "120分钟")

    score = tf15.get("score", 0) + tf60.get("score", 0) * 1.2 + tf120.get("score", 0) * 1.5
    if score >= 6:
        final_view = "多周期强共振偏多"
        action = "可关注回踩低吸或突破确认"
    elif score >= 2:
        final_view = "多周期偏多，但需确认"
        action = "不追高，等回踩支撑或放量突破"
    elif score <= -6:
        final_view = "多周期共振偏空"
        action = "控制仓位，等待止跌结构"
    elif score <= -2:
        final_view = "多周期偏弱"
        action = "谨慎观察，暂不主动加仓"
    else:
        final_view = "多周期分歧，偏观察"
        action = "等 15m 和 60m 同向后再行动"

    support_candidates = [x.get("support") for x in [tf15, tf60, tf120] if x.get("support")]
    pressure_candidates = [x.get("pressure") for x in [tf15, tf60, tf120] if x.get("pressure")]
    close_candidates = [x.get("close") for x in [tf15, tf60, tf120] if x.get("close")]
    key_support = round(min(support_candidates), 2) if support_candidates else None
    key_pressure = round(max(pressure_candidates), 2) if pressure_candidates else None
    current_close = round(close_candidates[0], 2) if close_candidates else None

    return {
        "15m": tf15,
        "60m": tf60,
        "120m": tf120,
        "final_view": final_view,
        "action": action,
        "score": round(score, 2),
        "key_support": key_support,
        "key_pressure": key_pressure,
        "current_close": current_close,
        "data_quality": "分钟线" if fallback_daily is None else "分钟线失败，已使用日线降级参考"
    }


def render_tf_card(tf: dict, title: str):
    """移动端友好的多周期卡片。"""
    st.markdown(f"**{title}**")
    st.caption(f"数据源：{tf.get('source', '-')}｜样本：{tf.get('bars', 0)}｜时间：{tf.get('latest_time', '-')}")
    st.metric("偏向", tf.get("bias", "无法判断"))
    st.metric("趋势", tf.get("trend", "无法判断"))
    st.metric("MACD", tf.get("macd_state", "无法判断"))
    if tf.get("rsi") is not None:
        st.metric("RSI", f"{tf['rsi']:.2f}")
    if tf.get("close") is not None:
        st.caption(f"收盘/现价: {tf['close']:.2f}")
    if tf.get("support") is not None:
        st.caption(f"支撑: {tf['support']:.2f}")
    if tf.get("pressure") is not None:
        st.caption(f"压力: {tf['pressure']:.2f}")
    if tf.get("entry_zone") and tf.get("entry_zone") != "-":
        st.caption(f"参考低吸区: {tf['entry_zone']}")
    if tf.get("stop_loss") is not None:
        st.caption(f"风控位: {tf['stop_loss']:.2f}")
    if tf.get("target_1") is not None:
        st.caption(f"目标1: {tf['target_1']:.2f}")
    st.info(tf.get("advice", "等待确认"))


# ================= 个股评分、交易计划、自选池扫描增强 =================
def _clamp(value, low=0, high=20):
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return low


def _score_label(total_score: float) -> str:
    if total_score >= 82:
        return "强势观察"
    if total_score >= 70:
        return "偏多观察"
    if total_score >= 58:
        return "震荡观察"
    if total_score >= 45:
        return "谨慎等待"
    return "暂不参与"


def _action_suggestion(total_score: float, mtf_view: str, rr: float) -> str:
    if total_score >= 82 and rr >= 1.5:
        return "强势票，优先等回踩低吸或放量突破确认"
    if total_score >= 70:
        return "偏多，但不追高；等分时回踩支撑后再判断"
    if "偏空" in str(mtf_view) or total_score < 45:
        return "先回避，等重新站回关键均线或多周期转强"
    return "观察为主，等待15分钟与60分钟同向"


def build_trade_plan_from_inputs(quote: dict, df_kline: pd.DataFrame | None, mtf: dict) -> dict:
    price = safe_float(quote.get("price"), mtf.get("current_close") or 0)
    key_support = mtf.get("key_support")
    key_pressure = mtf.get("key_pressure")
    atr = None
    recent_low = None
    recent_high = None
    if df_kline is not None and not df_kline.empty:
        try:
            tmp = add_indicators(df_kline.copy())
            last = tmp.iloc[-1]
            atr = safe_float(last.get("atr14"), 0)
            recent_low = float(tmp.tail(min(30, len(tmp)))["low"].min())
            recent_high = float(tmp.tail(min(30, len(tmp)))["high"].max())
        except Exception:
            pass
    if not key_support:
        key_support = recent_low or price * 0.94
    if not key_pressure:
        key_pressure = recent_high or price * 1.08
    atr = atr if atr and atr > 0 else max(price * 0.025, (key_pressure - key_support) / 6 if key_pressure > key_support else price * 0.025)

    aggressive_entry = round(price, 2)
    steady_low = round(max(key_support, price - atr * 1.2), 2)
    steady_high = round(max(key_support, price - atr * 0.35), 2)
    breakout_price = round(key_pressure * 1.01, 2)
    stop_loss = round(max(0.01, min(key_support - atr * 0.35, price * 0.93)), 2)
    target_1 = round(max(key_pressure, price + atr * 1.2), 2)
    risk = max(price - stop_loss, price * 0.01)
    target_2 = round(price + risk * 2.0, 2)
    rr = round(max(target_1 - price, 0) / risk, 2) if risk > 0 else 0

    invalidation = "跌破风控位且无法快速收回；或放量跌破60分钟支撑"
    if mtf.get("final_view") and "偏空" in mtf.get("final_view"):
        invalidation = "多周期仍偏空，未重新站上15/60分钟关键压力前不主动进攻"

    return {
        "current_price": round(price, 2),
        "aggressive_entry": aggressive_entry,
        "steady_entry_zone": f"{steady_low:.2f} - {steady_high:.2f}",
        "breakout_price": breakout_price,
        "stop_loss": stop_loss,
        "target_1": target_1,
        "target_2": target_2,
        "rr": rr,
        "invalidation": invalidation,
        "position_advice": "观察仓10%-20%" if rr < 1.2 else "试探仓20%-30%" if rr < 2 else "趋势确认后可提高至30%-40%",
    }


def score_stock_analysis(quote: dict, df_kline: pd.DataFrame | None, mtf: dict) -> dict:
    turnover = safe_float(quote.get("turnover"), 0)
    pct = safe_float(quote.get("pct"), 0)
    pe = safe_float(quote.get("pe"), 0)
    market_cap = safe_float(quote.get("market_cap"), 0)

    tech_score = 8
    volume_score = 8
    position_score = 8
    risk_score = 10
    tech_summary = {}

    if df_kline is not None and not df_kline.empty and len(df_kline) >= 15:
        try:
            tmp = add_indicators(df_kline.copy())
            tech = summarize_technicals(tmp)
            latest = tmp.iloc[-1]
            high_60 = float(tmp.tail(min(60, len(tmp)))["high"].max())
            low_60 = float(tmp.tail(min(60, len(tmp)))["low"].min())
            loc = (float(latest["close"]) - low_60) / (high_60 - low_60) if high_60 > low_60 else 0.5

            tech_score = 10
            if tech.get("trend") == "多头趋势":
                tech_score += 5
            elif tech.get("trend") == "空头趋势":
                tech_score -= 4
            if tech.get("macd_state") == "金叉后增强":
                tech_score += 3
            elif tech.get("macd_state") == "死叉后走弱":
                tech_score -= 3
            if pd.notna(tech.get("rsi14")):
                rsi = float(tech.get("rsi14"))
                if 52 <= rsi <= 68:
                    tech_score += 2
                elif rsi >= 78 or rsi <= 35:
                    tech_score -= 2
            if "向上" in str(tech.get("bos_state")):
                tech_score += 2
            if "向下" in str(tech.get("bos_state")):
                tech_score -= 2
            if "向下扫流动性后收回" in str(tech.get("sweep_state")):
                tech_score += 1
            if "向上扫流动性后回落" in str(tech.get("sweep_state")):
                tech_score -= 1

            volume_score = 8
            if tech.get("vol_state") == "显著放量" and pct >= 0:
                volume_score += 6
            elif tech.get("vol_state") == "显著放量" and pct < 0:
                volume_score -= 4
            elif tech.get("vol_state") == "明显缩量":
                volume_score -= 1
            if turnover >= 8:
                volume_score += 4
            elif turnover >= 3:
                volume_score += 2
            if pct >= 5:
                volume_score += 2
            elif pct <= -4:
                volume_score -= 3

            if loc <= 0.25:
                position_score = 15
            elif loc <= 0.55:
                position_score = 18
            elif loc <= 0.78:
                position_score = 14
            else:
                position_score = 9
            if float(latest["close"]) > float(latest.get("ema_short", latest["close"])):
                position_score += 2
            if float(latest["close"]) < float(latest.get("ema_mid", latest["close"])):
                position_score -= 3

            risk_score = 12
            if pe and pe > 120:
                risk_score -= 4
            elif pe and 0 < pe < 35:
                risk_score += 2
            if market_cap and market_cap < 80:
                risk_score -= 1
            if loc > 0.85 and pct > 5:
                risk_score -= 4
            if turnover > 18:
                risk_score -= 2
            tech_summary = tech
        except Exception as e:
            if DEBUG_MODE:
                st.warning(f"评分计算降级: {e}")

    mtf_score_raw = safe_float(mtf.get("score"), 0)
    mtf_score = 10 + mtf_score_raw * 1.6
    if "强共振偏多" in str(mtf.get("final_view")):
        mtf_score += 4
    elif "偏多" in str(mtf.get("final_view")):
        mtf_score += 2
    elif "偏空" in str(mtf.get("final_view")):
        mtf_score -= 4
    elif "分歧" in str(mtf.get("final_view")):
        mtf_score -= 1

    detail_scores = {
        "趋势结构": round(_clamp(tech_score), 1),
        "多周期共振": round(_clamp(mtf_score), 1),
        "量能资金": round(_clamp(volume_score), 1),
        "位置舒适度": round(_clamp(position_score), 1),
        "风险控制": round(_clamp(risk_score), 1),
    }
    total = round(sum(detail_scores.values()), 1)
    plan = build_trade_plan_from_inputs(quote, df_kline, mtf)
    label = _score_label(total)
    action = _action_suggestion(total, mtf.get("final_view", ""), safe_float(plan.get("rr"), 0))

    return {
        "total_score": total,
        "label": label,
        "action": action,
        "detail_scores": detail_scores,
        "plan": plan,
        "tech_summary": tech_summary,
    }


def render_score_panel(assessment: dict):
    st.markdown("##### 🧮 个股评分系统（新增）")
    total = assessment.get("total_score", 0)
    label = assessment.get("label", "-")
    a1, a2 = st.columns([1, 2])
    with a1:
        st.metric("综合评分", f"{total:.1f}/100", label)
    with a2:
        st.info(f"执行建议：**{assessment.get('action', '等待确认')}**")
    score_df = pd.DataFrame([
        {"维度": k, "得分": v, "满分": 20} for k, v in assessment.get("detail_scores", {}).items()
    ])
    st.dataframe(score_df, width="stretch", hide_index=True)


def render_trade_plan_card(assessment: dict):
    st.markdown("##### 🧾 买卖计划卡片（新增）")
    plan = assessment.get("plan", {})
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("当前参考价", f"{plan.get('current_price', 0):.2f}")
    p2.metric("激进介入", f"{plan.get('aggressive_entry', 0):.2f}")
    p3.metric("止损位", f"{plan.get('stop_loss', 0):.2f}")
    p4.metric("盈亏比", f"{plan.get('rr', 0):.2f}")
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("稳健低吸区", str(plan.get("steady_entry_zone", "-")))
    q2.metric("突破确认价", f"{plan.get('breakout_price', 0):.2f}")
    q3.metric("目标一", f"{plan.get('target_1', 0):.2f}")
    q4.metric("目标二", f"{plan.get('target_2', 0):.2f}")
    st.caption(f"仓位建议：{plan.get('position_advice', '-')}｜失效条件：{plan.get('invalidation', '-')}")


@st.cache_data(ttl=300, show_spinner=False)
def analyze_stock_for_watchlist(symbol: str) -> dict:
    symbol = str(symbol).strip()
    quote = get_stock_quote(symbol)
    if not quote:
        return {"代码": symbol, "名称": "无法获取", "评分": 0, "状态": "无数据", "操作": "跳过"}
    df_kline = get_kline(symbol, days=160)
    mtf = get_multi_timeframe_analysis(symbol)
    assessment = score_stock_analysis(quote, df_kline, mtf)
    plan = assessment.get("plan", {})
    return {
        "代码": symbol,
        "名称": quote.get("name", "未知"),
        "现价": round(safe_float(quote.get("price")), 2),
        "涨跌幅%": round(safe_float(quote.get("pct")), 2),
        "换手率%": round(safe_float(quote.get("turnover")), 2),
        "评分": assessment.get("total_score", 0),
        "状态": assessment.get("label", "-"),
        "多周期": mtf.get("final_view", "-"),
        "低吸区": plan.get("steady_entry_zone", "-"),
        "突破价": plan.get("breakout_price", "-"),
        "止损": plan.get("stop_loss", "-"),
        "目标一": plan.get("target_1", "-"),
        "操作": assessment.get("action", "等待确认"),
    }


def render_watchlist_scanner():
    st.markdown("#### 📋 自选股池批量扫描（新增）")
    st.caption("一次扫描多只股票，自动给出评分、状态、低吸区、突破价、止损位和操作建议。建议一次 5-10 只，云端更稳定。")
    default_pool = "688523,300750,600276,002371,300308,601138"
    pool_text = st.text_area("输入自选股代码，用逗号、空格或换行分隔", value=default_pool, height=90)
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        max_scan = st.slider("本次最多扫描", 3, 20, 8)
    with c2:
        min_score = st.slider("最低显示评分", 0, 100, 0)
    with c3:
        run_scan = st.button("🚀 批量扫描自选股", type="primary", width="stretch")
    if run_scan:
        codes = [x.strip() for x in re.split(r"[，,\s]+", pool_text) if x.strip()]
        codes = [c for c in codes if re.fullmatch(r"\d{6}", c)]
        codes = list(dict.fromkeys(codes))[:max_scan]
        if not codes:
            st.warning("请至少输入一个 6 位股票代码。")
            return
        progress = st.progress(0)
        rows = []
        for i, code in enumerate(codes, start=1):
            progress.progress(i / len(codes), text=f"正在扫描 {code} ({i}/{len(codes)})")
            try:
                rows.append(analyze_stock_for_watchlist(code))
            except Exception as e:
                rows.append({"代码": code, "名称": "扫描失败", "评分": 0, "状态": "异常", "操作": str(e)[:60]})
        progress.empty()
        df_scan = pd.DataFrame(rows)
        if "评分" in df_scan.columns:
            df_scan = df_scan[df_scan["评分"] >= min_score].sort_values("评分", ascending=False)
        st.success(f"扫描完成：共 {len(codes)} 只，显示 {len(df_scan)} 只。")
        st.dataframe(df_scan, width="stretch", hide_index=True)
        if not df_scan.empty:
            top = df_scan.iloc[0]
            st.info(f"当前评分最高：**{top.get('名称')}({top.get('代码')})**，评分 **{top.get('评分')}**，操作建议：{top.get('操作')}")

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

def _normalize_market_price(value, prefer_scale=None):
    """指数/汇率价格归一化，兼容东财不同接口偶发的放大倍数。"""
    price = safe_float(value, default=0.0)
    if price <= 0:
        return 0.0
    if prefer_scale:
        return price / prefer_scale
    # 指数常见区间 500-10000；东财有时返回 306422 这种扩大100倍的值
    if price > 100000:
        return price / 100
    if price > 20000:
        return price / 100
    return price


def _build_pulse_item(price=0.0, pct=0.0, source="", status="正常"):
    return {
        "price": safe_float(price, 0.0),
        "pct": safe_float(pct, 0.0),
        "source": source,
        "status": status,
    }


@st.cache_data(ttl=30, show_spinner=False)
def get_market_pulse():
    """
    宏观看板极速稳定版 2.0：
    - 首页只使用轻量批量接口，一次请求多个指数，避免逐个请求拖慢；
    - 不在首页调用 AKShare 等重数据源；
    - 任一接口失败立即降级为“待同步”，不影响其他模块；
    - 成功数据写入 session_state，接口临时失败时可回显上一次成功数据。
    """
    targets = [
        {"name": "上证指数", "secid": "1.000001"},
        {"name": "深证成指", "secid": "0.399001"},
        {"name": "创业板指", "secid": "0.399006"},
        {"name": "沪深300", "secid": "1.000300"},
        {"name": "科创50", "secid": "1.000688"},
    ]

    pulse = {}
    secids = ",".join([x["secid"] for x in targets])

    # 1）东方财富批量轻量接口：比逐个 get 快很多
    try:
        url = (
            "https://push2.eastmoney.com/api/qt/ulist.np/get?"
            f"secids={secids}&fltt=2&invt=2"
            "&fields=f12,f14,f2,f3,f4,f6,f104,f105,f106"
        )
        res = fast_fetch_json(url, timeout=2.8)
        data = res.get("data", {}) if isinstance(res, dict) else {}
        diff = data.get("diff", []) if isinstance(data, dict) else []
        code_to_name = {x["secid"].split(".")[-1]: x["name"] for x in targets}
        for row in diff:
            code = str(row.get("f12", ""))
            name = code_to_name.get(code) or row.get("f14")
            if not name:
                continue
            price = safe_float(row.get("f2"), 0.0)
            pct = safe_float(row.get("f3"), 0.0)
            if price > 0:
                pulse[name] = {
                    "price": price,
                    "pct": pct,
                    "source": "东方财富批量",
                    "status": "正常",
                    "available": True,
                }
    except Exception as e:
        if DEBUG_MODE:
            st.caption(f"宏观看板批量接口失败：{e}")

    # 2）如果批量接口漏项，用单项轻量接口补一次，但每项超时很短
    for item in targets:
        name = item["name"]
        if name in pulse:
            continue
        try:
            url = (
                "https://push2.eastmoney.com/api/qt/stock/get?"
                f"secid={item['secid']}&ut=fa5fd1943c7b386f172d6893dbfba10b"
                "&fltt=2&invt=2&fields=f43,f170,f60"
            )
            res = fast_fetch_json(url, timeout=1.6)
            data = res.get("data") if isinstance(res, dict) else None
            if data:
                raw_price = safe_float(data.get("f43"), 0.0)
                prev_close = safe_float(data.get("f60"), 0.0)
                price = normalize_em_price(raw_price, prev_close)
                pct = safe_float(data.get("f170"), 0.0)
                if price > 0:
                    pulse[name] = {
                        "price": price,
                        "pct": pct,
                        "source": "东方财富",
                        "status": "正常",
                        "available": True,
                    }
        except Exception:
            pass

    # 3）离岸人民币，失败不影响指数看板
    try:
        cnh_url = (
            "https://push2.eastmoney.com/api/qt/stock/get?"
            "secid=133.USDCNH&ut=fa5fd1943c7b386f172d6893dbfba10b"
            "&fltt=2&invt=2&fields=f43,f170"
        )
        cnh_res = fast_fetch_json(cnh_url, timeout=1.6)
        cnh_data = cnh_res.get("data") if isinstance(cnh_res, dict) else None
        if cnh_data:
            cnh_price = safe_float(cnh_data.get("f43"), 0.0)
            cnh_pct = safe_float(cnh_data.get("f170"), 0.0)
            if cnh_price > 0:
                pulse["USD/CNH(离岸)"] = {
                    "price": cnh_price,
                    "pct": cnh_pct,
                    "source": "东方财富",
                    "status": "正常",
                    "available": True,
                }
    except Exception:
        pass

    # 4）上次成功数据回显：避免页面刷新后全部空白
    last_good = st.session_state.get("_last_good_market_pulse", {})
    for name, data in list(pulse.items()):
        if isinstance(data, dict) and data.get("available") and safe_float(data.get("price"), 0) > 0:
            last_good[name] = data
    st.session_state["_last_good_market_pulse"] = last_good

    for item in targets:
        name = item["name"]
        if name not in pulse and name in last_good:
            old = dict(last_good[name])
            old["status"] = "缓存回显"
            old["source"] = old.get("source", "上次成功")
            pulse[name] = old

    if "USD/CNH(离岸)" not in pulse and "USD/CNH(离岸)" in last_good:
        old = dict(last_good["USD/CNH(离岸)"])
        old["status"] = "缓存回显"
        pulse["USD/CNH(离岸)"] = old

    # 5）最终占位：保证首页永不空白
    for item in targets:
        if item["name"] not in pulse:
            pulse[item["name"]] = {
                "price": 0.0,
                "pct": 0.0,
                "source": "待同步",
                "status": "实时源暂不可用",
                "available": False,
            }

    if "USD/CNH(离岸)" not in pulse:
        pulse["USD/CNH(离岸)"] = {
            "price": 0.0,
            "pct": 0.0,
            "source": "待同步",
            "status": "实时源暂不可用",
            "available": False,
        }

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

@st.cache_data(ttl=30, show_spinner=False)
def get_stock_quote(symbol):
    """
    个股实时行情极速版：
    先走东方财富单股轻量接口，避免每次查询都拉取全市场 AKShare 实时列表；
    东方财富失败后，再用 AKShare 兜底。
    """
    symbol = str(symbol).strip()
    market = "1" if symbol.startswith(("6", "9", "5", "7")) else "0"

    # 1）东方财富单股轻量接口：速度最快
    try:
        url = (
            "https://push2.eastmoney.com/api/qt/stock/get?"
            f"secid={market}.{symbol}&ut=fa5fd1943c7b386f172d6893dbfba10b"
            "&fltt=2&invt=2&fields=f58,f43,f60,f170,f116,f162,f168,f167"
        )
        res = fetch_json(url, timeout=4)
        if res and res.get("data"):
            d = res["data"]
            prev_close = safe_float(d.get("f60"))
            price = normalize_em_price(d.get("f43"), prev_close)
            if price > 0:
                return {
                    "name": d.get("f58", "未知"),
                    "price": price,
                    "pct": safe_float(d.get("f170")),
                    "market_cap": safe_float(d.get("f116")) / 100000000,
                    "pe": d.get("f162", "-"),
                    "pb": d.get("f167", "-"),
                    "turnover": safe_float(d.get("f168")),
                }
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"东方财富实时行情失败，回退 AKShare: {e}")

    # 2）AKShare 全市场实时列表兜底
    try:
        spot_df = ak.stock_zh_a_spot_em()
        if spot_df is not None and not spot_df.empty:
            row = spot_df[spot_df["代码"].astype(str).str.zfill(6) == symbol.zfill(6)]
            if not row.empty:
                row = row.iloc[0]
                return {
                    "name": row.get("名称", "未知"),
                    "price": safe_float(row.get("最新价")),
                    "pct": safe_float(row.get("涨跌幅")),
                    "market_cap": safe_float(row.get("总市值")) / 100000000,
                    "pe": row.get("市盈率-动态", "-"),
                    "pb": row.get("市净率", "-"),
                    "turnover": safe_float(row.get("换手率")),
                }
    except Exception as e:
        if DEBUG_MODE:
            st.warning(f"AKShare 实时行情兜底失败: {e}")

    return None

@st.cache_data(ttl=300, show_spinner=False)
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
    if st.button("🚀 启动全局宏观深度推演", type="primary", width="stretch"):
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
                    st.dataframe(df_snap, width="stretch", hide_index=True)
            with mt3:
                st.markdown(res["agents_analysis"]["sector"]["analysis"])
            with mt4:
                with st.expander("宏观总量分析师报告"): st.markdown(res["agents_analysis"]["macro"]["analysis"])
                with st.expander("政策流动性分析师报告"): st.markdown(res["agents_analysis"]["policy"]["analysis"])
                with st.expander("优质标的筛选报告"): st.markdown(res["agents_analysis"]["stock"]["analysis"])
        else:
            st.error(f"推演失败: {res.get('error')}")
# ================= 宏观分析板块结束 =================
# ================= 智瞰龙虎榜数据与分析模块 V2 =================
# 整合来源：智瞰龙虎数据采集模块、智瞰龙虎AI分析模块、智瞰龙虎综合分析引擎
class LonghubangDataFetcher:
    """龙虎榜数据获取与清洗。

    设计原则：
    1. 先走 ws4 智瞰龙虎接口，保留游资席位字段；
    2. 失败后走 AKShare 东方财富龙虎榜详情；
    3. 自动向前回溯最近可用交易日；
    4. 统一字段结构，避免 UI 和 AI 模块因字段不一致崩溃。
    """

    def __init__(self, api_key=None):
        self.base_url = "http://lhb-api.ws4.cn/v1"
        self.api_key = api_key
        self.max_retries = 2
        self.retry_delay = 0.8
        self.request_delay = 0.05

    def _safe_request(self, url, params=None, timeout=8):
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        for attempt in range(self.max_retries):
            try:
                response = SESSION.get(url, params=params, headers=headers, timeout=timeout)
                time.sleep(self.request_delay)
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, dict) and data.get("code") in [20000, 200, "200", None]:
                        return data
                    if DEBUG_MODE:
                        st.warning(f"龙虎榜 API 返回异常: {data}")
                    return data if isinstance(data, dict) else None
                if DEBUG_MODE:
                    st.warning(f"龙虎榜 HTTP 错误: {response.status_code}")
            except Exception as e:
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                elif DEBUG_MODE:
                    st.warning(f"龙虎榜请求失败: {e}")
        return None

    def _extract_data_list(self, raw_result):
        if not raw_result:
            return []
        if isinstance(raw_result, list):
            return raw_result
        if not isinstance(raw_result, dict):
            return []
        payload = raw_result.get("data")
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ["list", "items", "records", "data", "rows"]:
                val = payload.get(key)
                if isinstance(val, list):
                    return val
        return []

    def _normalize_record(self, record, default_date=None, source="ws4"):
        if not isinstance(record, dict):
            return None
        code = str(record.get("gpdm") or record.get("股票代码") or record.get("代码") or "").strip()
        m = re.search(r"(\d{6})", code)
        code = m.group(1) if m else code
        name = str(record.get("gpmc") or record.get("股票名称") or record.get("名称") or record.get("股票简称") or "").strip()
        if not code and not name:
            return None
        return {
            "yzmc": str(record.get("yzmc") or record.get("游资名称") or record.get("营业部名称") or record.get("营业部") or "龙虎榜汇总"),
            "yyb": str(record.get("yyb") or record.get("营业部") or record.get("营业部名称") or record.get("上榜原因") or ""),
            "sblx": str(record.get("sblx") or record.get("榜单类型") or record.get("上榜原因") or "龙虎榜"),
            "gpdm": code,
            "gpmc": name,
            "mrje": safe_float(record.get("mrje") or record.get("买入金额") or record.get("龙虎榜买入额") or record.get("买入额") or 0),
            "mcje": safe_float(record.get("mcje") or record.get("卖出金额") or record.get("龙虎榜卖出额") or record.get("卖出额") or 0),
            "jlrje": safe_float(record.get("jlrje") or record.get("净流入金额") or record.get("龙虎榜净买额") or record.get("净买额") or record.get("净买入") or 0),
            "rq": str(record.get("rq") or record.get("日期") or record.get("上榜日") or default_date or ""),
            "gl": str(record.get("gl") or record.get("概念") or record.get("解读") or record.get("上榜原因") or ""),
            "source": source,
        }

    def get_longhubang_data(self, date):
        url = f"{self.base_url}/youzi/all"
        raw = self._safe_request(url, params={"date": date})
        records = []
        for item in self._extract_data_list(raw):
            norm = self._normalize_record(item, default_date=date, source="ws4 智瞰龙虎接口")
            if norm:
                records.append(norm)
        return records

    def get_longhubang_data_akshare(self, date):
        date_ymd = str(date).replace("-", "")
        records = []
        try:
            df = ak.stock_lhb_detail_em(start_date=date_ymd, end_date=date_ymd)
            if df is None or df.empty:
                return []
            for _, row in df.iterrows():
                rec = {
                    "gpdm": row.get("代码", row.get("股票代码", "")),
                    "gpmc": row.get("名称", row.get("股票简称", "")),
                    "yzmc": "龙虎榜汇总",
                    "yyb": row.get("上榜原因", row.get("解读", "")),
                    "sblx": row.get("上榜原因", "龙虎榜"),
                    "mrje": row.get("龙虎榜买入额", row.get("买入额", 0)),
                    "mcje": row.get("龙虎榜卖出额", row.get("卖出额", 0)),
                    "jlrje": row.get("龙虎榜净买额", row.get("净买额", row.get("净流入金额", 0))),
                    "rq": row.get("上榜日", date),
                    "gl": row.get("解读", row.get("上榜原因", "")),
                }
                norm = self._normalize_record(rec, default_date=date, source="AKShare 东方财富龙虎榜")
                if norm:
                    records.append(norm)
            return records
        except Exception as e:
            if DEBUG_MODE:
                st.warning(f"AKShare 龙虎榜备用源失败: {e}")
            return []

    def get_longhubang_data_auto(self, date, lookback_days=10):
        errors = []
        base_date = pd.to_datetime(date).date()
        for offset in range(0, lookback_days + 1):
            current_date = base_date - timedelta(days=offset)
            # 周末也允许尝试一次，但优先提示
            date_str = current_date.strftime("%Y-%m-%d")
            ws4_data = self.get_longhubang_data(date_str)
            if ws4_data:
                return {"success": True, "requested_date": str(date), "used_date": date_str, "source": "ws4 智瞰龙虎接口", "data": ws4_data, "errors": errors}
            errors.append(f"{date_str} ws4 无数据或受限")
            ak_data = self.get_longhubang_data_akshare(date_str)
            if ak_data:
                return {"success": True, "requested_date": str(date), "used_date": date_str, "source": "AKShare 东方财富龙虎榜", "data": ak_data, "errors": errors}
            errors.append(f"{date_str} AKShare 无数据或受限")
        return {"success": False, "requested_date": str(date), "used_date": None, "source": "无可用源", "data": [], "errors": errors}

    def parse_to_dataframe(self, data_list):
        if not data_list:
            return pd.DataFrame()
        df = pd.DataFrame(data_list)
        mapping = {
            "yzmc": "游资名称", "yyb": "营业部", "sblx": "榜单类型",
            "gpdm": "股票代码", "gpmc": "股票名称", "mrje": "买入金额",
            "mcje": "卖出金额", "jlrje": "净流入金额", "rq": "日期", "gl": "概念", "source": "数据源"
        }
        df = df.rename(columns=mapping)
        for col in ["买入金额", "卖出金额", "净流入金额"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        if "股票代码" in df.columns:
            df["股票代码"] = df["股票代码"].astype(str).str.extract(r"(\d{6})", expand=False).fillna(df["股票代码"].astype(str))
        if "净流入金额" in df.columns:
            df = df.sort_values("净流入金额", ascending=False)
        return df

    def analyze_data_summary(self, data_list):
        if not data_list:
            return {}
        df = self.parse_to_dataframe(data_list)
        summary = {
            "total_records": len(df),
            "total_stocks": df["股票代码"].nunique() if "股票代码" in df.columns else 0,
            "total_youzi": df["游资名称"].nunique() if "游资名称" in df.columns else 0,
            "total_buy_amount": df["买入金额"].sum() if "买入金额" in df.columns else 0,
            "total_sell_amount": df["卖出金额"].sum() if "卖出金额" in df.columns else 0,
            "total_net_inflow": df["净流入金额"].sum() if "净流入金额" in df.columns else 0,
        }
        if "游资名称" in df.columns and "净流入金额" in df.columns:
            summary["top_youzi"] = df.groupby("游资名称")["净流入金额"].sum().sort_values(ascending=False).head(15).to_dict()
        if "股票代码" in df.columns and "净流入金额" in df.columns:
            top_stocks = df.groupby(["股票代码", "股票名称"], dropna=False)["净流入金额"].sum().sort_values(ascending=False)
            summary["top_stocks"] = [{"code": code, "name": name, "net_inflow": amount} for (code, name), amount in top_stocks.head(20).items()]
        if "概念" in df.columns:
            concepts = []
            for val in df["概念"].dropna():
                for part in re.split(r"[,，/、;；\s]+", str(val)):
                    part = part.strip()
                    if part and part not in ["nan", "None", "龙虎榜"]:
                        concepts.append(part)
            summary["hot_concepts"] = dict(Counter(concepts).most_common(20))
        return summary

    def format_data_for_ai(self, data_list, summary=None):
        if not data_list:
            return "暂无龙虎榜数据"
        df = self.parse_to_dataframe(data_list)
        summary = summary or self.analyze_data_summary(data_list)
        parts = [f"""
【龙虎榜总体概况】
数据时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
记录总数: {summary.get('total_records', 0)}
涉及股票: {summary.get('total_stocks', 0)} 只
涉及游资: {summary.get('total_youzi', 0)} 个
总买入金额: {summary.get('total_buy_amount', 0):,.2f} 元
总卖出金额: {summary.get('total_sell_amount', 0):,.2f} 元
净流入金额: {summary.get('total_net_inflow', 0):,.2f} 元
"""]
        if summary.get("top_youzi"):
            parts.append("\n【活跃游资 TOP15】")
            for idx, (name, amount) in enumerate(summary["top_youzi"].items(), 1):
                parts.append(f"{idx}. {name}: 净流入 {amount:,.2f} 元")
        if summary.get("top_stocks"):
            parts.append("\n【资金净流入 TOP20 股票】")
            for idx, stock in enumerate(summary["top_stocks"], 1):
                parts.append(f"{idx}. {stock['name']}({stock['code']}): {stock['net_inflow']:,.2f} 元")
        if summary.get("hot_concepts"):
            parts.append("\n【热门概念 TOP20】")
            for idx, (concept, count) in enumerate(summary["hot_concepts"].items(), 1):
                parts.append(f"{idx}. {concept}: {count} 次")
        parts.append("\n【详细交易记录 TOP80】")
        for _, row in df.head(80).iterrows():
            parts.append(
                f"{row.get('游资名称', 'N/A')} | {row.get('股票名称', 'N/A')}({row.get('股票代码', 'N/A')}) | "
                f"买入:{safe_float(row.get('买入金额')):,.0f} 卖出:{safe_float(row.get('卖出金额')):,.0f} "
                f"净流入:{safe_float(row.get('净流入金额')):,.0f} | 日期:{row.get('日期', 'N/A')} | 类型:{row.get('榜单类型', '')}"
            )
        return "\n".join(parts)


class LonghubangScoring:
    """龙虎榜轻量评分器：先给结构化排名，再交给 AI 深度分析。"""

    def score_all_stocks(self, data_list):
        fetcher = LonghubangDataFetcher()
        df = fetcher.parse_to_dataframe(data_list)
        if df.empty or "股票代码" not in df.columns:
            return pd.DataFrame()
        grouped = df.groupby(["股票代码", "股票名称"], dropna=False).agg(
            净流入金额=("净流入金额", "sum"),
            买入金额=("买入金额", "sum"),
            卖出金额=("卖出金额", "sum"),
            上榜次数=("股票代码", "count"),
            游资数量=("游资名称", "nunique"),
            概念=("概念", lambda x: "、".join([str(i) for i in x.dropna().head(3)])),
        ).reset_index()
        if grouped.empty:
            return grouped
        net = grouped["净流入金额"].fillna(0)
        buy = grouped["买入金额"].fillna(0)
        sell = grouped["卖出金额"].fillna(0)
        grouped["资金强度分"] = (net.rank(pct=True) * 35).round(1)
        grouped["席位合力分"] = (grouped["游资数量"].rank(pct=True) * 20).round(1)
        grouped["热度持续分"] = (grouped["上榜次数"].rank(pct=True) * 15).round(1)
        grouped["买卖优势分"] = (((buy + 1) / (sell + 1)).clip(0, 5).rank(pct=True) * 20).round(1)
        grouped["风险扣分"] = grouped.apply(lambda r: 10 if r["净流入金额"] < 0 or r["卖出金额"] > r["买入金额"] * 1.5 else 0, axis=1)
        grouped["智瞰评分"] = (grouped["资金强度分"] + grouped["席位合力分"] + grouped["热度持续分"] + grouped["买卖优势分"] - grouped["风险扣分"]).clip(0, 100).round(1)
        grouped["信号标签"] = grouped["智瞰评分"].apply(lambda x: "强势进攻" if x >= 75 else "偏多观察" if x >= 60 else "分歧博弈" if x >= 45 else "风险优先")
        grouped = grouped.sort_values(["智瞰评分", "净流入金额"], ascending=False)
        return grouped


class LonghubangAgents:
    """龙虎榜 AI 分析师集合。复用主程序 call_ai/Groq，不依赖 DeepSeek 外部模块。"""

    def __init__(self, model=None):
        self.model = model or selected_model

    def _run(self, role, prompt, max_chars=9000):
        final_prompt = f"你现在扮演【{role}】。请用中文输出，结构清晰，避免空话，重点给出可执行结论。\n\n{prompt[:max_chars]}"
        return call_ai(final_prompt, model=self.model, temperature=0.25)

    def youzi_behavior_analyst(self, longhubang_data: str, summary: Dict) -> Dict[str, Any]:
        youzi_info = ""
        if summary.get("top_youzi"):
            youzi_info = "\n【活跃游资统计】\n" + "\n".join([f"{i}. {n}: 净流入 {a:,.2f} 元" for i, (n, a) in enumerate(list(summary["top_youzi"].items())[:15], 1)])
        prompt = f"""
【龙虎榜数据概况】
记录总数: {summary.get('total_records', 0)}
涉及股票: {summary.get('total_stocks', 0)} 只
涉及游资: {summary.get('total_youzi', 0)} 个
总买入金额: {summary.get('total_buy_amount', 0):,.2f} 元
总卖出金额: {summary.get('total_sell_amount', 0):,.2f} 元
净流入金额: {summary.get('total_net_inflow', 0):,.2f} 元
{youzi_info}
{longhubang_data}

请分析：1. 活跃游资画像；2. 操作风格；3. 目标股票；4. 进出节奏；5. 题材偏好；6. 风险与机会；7. 跟随策略。
"""
        return {"agent_name": "游资行为分析师", "agent_role": "分析游资操作特征、意图和目标股票", "analysis": self._run("资深游资行为分析师", prompt), "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}

    def stock_potential_analyst(self, longhubang_data: str, summary: Dict) -> Dict[str, Any]:
        stock_info = ""
        if summary.get("top_stocks"):
            stock_info = "\n【热门股票统计】\n" + "\n".join([f"{i}. {s['name']}({s['code']}): 净流入 {s['net_inflow']:,.2f} 元" for i, s in enumerate(summary["top_stocks"][:20], 1)])
        prompt = f"""
【龙虎榜数据概况】
记录总数: {summary.get('total_records', 0)}；涉及股票: {summary.get('total_stocks', 0)} 只；涉及游资: {summary.get('total_youzi', 0)} 个
{stock_info}
{longhubang_data}

请重点挖掘：1. 次日大概率上涨股票 TOP5-8；2. 资金流入强度；3. 技术位置假设；4. 题材逻辑；5. 风险股票；6. 买入价位、目标、止损、持有周期。
"""
        return {"agent_name": "个股潜力分析师", "agent_role": "挖掘次日大概率上涨的潜力股票", "analysis": self._run("短线个股潜力分析师", prompt), "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}

    def theme_tracker_analyst(self, longhubang_data: str, summary: Dict) -> Dict[str, Any]:
        concept_info = ""
        if summary.get("hot_concepts"):
            concept_info = "\n【热门概念统计】\n" + "\n".join([f"{i}. {c}: 出现 {cnt} 次" for i, (c, cnt) in enumerate(list(summary["hot_concepts"].items())[:20], 1)])
        prompt = f"""
【龙虎榜数据概况】记录总数: {summary.get('total_records', 0)}，涉及股票: {summary.get('total_stocks', 0)} 只
{concept_info}
{longhubang_data}

请分析：1. 热点题材；2. 炒作周期；3. 龙头与梯队；4. 游资对题材的态度；5. 题材轮动；6. 题材风险；7. 题材投资策略。
"""
        return {"agent_name": "题材追踪分析师", "agent_role": "识别热点题材，分析炒作周期，预判轮动方向", "analysis": self._run("题材追踪分析师", prompt), "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}

    def risk_control_specialist(self, longhubang_data: str, summary: Dict) -> Dict[str, Any]:
        prompt = f"""
【龙虎榜数据概况】
记录总数: {summary.get('total_records', 0)}；涉及股票: {summary.get('total_stocks', 0)}；净流入金额: {summary.get('total_net_inflow', 0):,.2f} 元
{longhubang_data}

请从保守风控视角分析：1. 高风险股票；2. 游资出货信号；3. 资金陷阱；4. 题材退潮风险；5. 技术面风险；6. 情绪风险；7. 仓位与止损纪律。
"""
        return {"agent_name": "风险控制专家", "agent_role": "识别高风险股票、游资出货信号和市场陷阱", "analysis": self._run("风险控制专家", prompt), "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}

    def chief_strategist(self, all_analyses: List[Dict], summary: Dict = None, scoring_df: pd.DataFrame = None) -> Dict[str, Any]:
        analyses_text = ""
        for a in all_analyses:
            analyses_text += f"\n{'='*40}\n【{a['agent_name']}】{a['agent_role']}\n{'='*40}\n{a['analysis']}\n"
        score_text = ""
        if scoring_df is not None and not scoring_df.empty:
            score_text = "\n【智瞰量化评分 TOP10】\n" + scoring_df.head(10).to_string(index=False)
        prompt = f"""
你是一名首席投资策略师。请综合以下分析师意见和量化评分，给出最终龙虎榜策略报告。
{score_text}
{analyses_text[:14000]}

请输出：1. 市场总体研判和热度分；2. 次日重点推荐股票 TOP5-8；3. 高风险警示股票 TOP3-5；4. 热点题材总结；5. 仓位和操作策略；6. 纪律与预案。
"""
        return {"agent_name": "首席策略师", "agent_role": "综合多维度分析，给出最终投资建议和推荐股票清单", "analysis": self._run("首席投资策略师", prompt, max_chars=16000), "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}


class LonghubangEngine:
    """智瞰龙虎综合分析引擎：数据获取 → 摘要统计 → 量化评分 → AI 分析 → 最终报告。"""

    def __init__(self, model=None):
        self.fetcher = LonghubangDataFetcher()
        self.scoring = LonghubangScoring()
        self.agents = LonghubangAgents(model=model)

    def run_comprehensive_analysis(self, date=None, lookback_days=10, ai_depth="标准", run_ai=True):
        results = {
            "success": False,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data_info": {},
            "agents_analysis": {},
            "recommended_stocks": [],
            "errors": [],
        }
        date = date or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        auto = self.fetcher.get_longhubang_data_auto(date, lookback_days=lookback_days)
        results.update({"requested_date": date, "used_date": auto.get("used_date"), "source": auto.get("source"), "errors": auto.get("errors", [])})
        data_list = auto.get("data", [])
        if not auto.get("success") or not data_list:
            results["error"] = "未获取到龙虎榜数据"
            return results

        summary = self.fetcher.analyze_data_summary(data_list)
        formatted_data = self.fetcher.format_data_for_ai(data_list, summary)
        df = self.fetcher.parse_to_dataframe(data_list)
        scoring_df = self.scoring.score_all_stocks(data_list)
        recommended = []
        if scoring_df is not None and not scoring_df.empty:
            for idx, row in scoring_df.head(10).iterrows():
                recommended.append({
                    "rank": len(recommended) + 1,
                    "code": row.get("股票代码"),
                    "name": row.get("股票名称"),
                    "score": row.get("智瞰评分"),
                    "tag": row.get("信号标签"),
                    "net_inflow": row.get("净流入金额"),
                    "reason": f"净流入{safe_float(row.get('净流入金额')):,.0f}元，{row.get('游资数量', 0)}个席位参与，上榜{row.get('上榜次数', 0)}次",
                })

        results["data_info"] = {"total_records": summary.get("total_records", 0), "total_stocks": summary.get("total_stocks", 0), "total_youzi": summary.get("total_youzi", 0), "summary": summary}
        results["dataframe"] = df
        results["scoring_ranking"] = scoring_df
        results["recommended_stocks"] = recommended
        results["formatted_data"] = formatted_data

        if run_ai:
            agents_results = {}
            all_analyses = []
            # 标准模式：个股、风险、首席；深度模式：四位分析师 + 首席
            if ai_depth == "深度":
                yz = self.agents.youzi_behavior_analyst(formatted_data, summary); agents_results["youzi"] = yz; all_analyses.append(yz)
                th = self.agents.theme_tracker_analyst(formatted_data, summary); agents_results["theme"] = th; all_analyses.append(th)
            stock = self.agents.stock_potential_analyst(formatted_data, summary); agents_results["stock"] = stock; all_analyses.append(stock)
            risk = self.agents.risk_control_specialist(formatted_data, summary); agents_results["risk"] = risk; all_analyses.append(risk)
            chief = self.agents.chief_strategist(all_analyses, summary=summary, scoring_df=scoring_df); agents_results["chief"] = chief
            results["agents_analysis"] = agents_results
        results["success"] = True
        return results
# ================= 智瞰龙虎榜数据与分析模块结束 =================

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


# ================= 高端新闻情报终端模块 =================
# 整合思路来源：news_announcement_data / news_flow_data / news_flow_agents / news_flow_engine / news_flow_db / news_flow_ui
# 采用单文件内嵌方式，避免 Streamlit Cloud 因外部模块缺失导致部署失败。

NEWS_KEYWORD_SECTOR_MAP = {
    "AI": ["人工智能", "算力", "CPO", "数据中心", "机器人"],
    "算力": ["算力", "CPO", "光模块", "服务器", "液冷", "数据中心"],
    "半导体": ["芯片", "半导体", "存储", "先进封装", "光刻机", "国产替代"],
    "新能源车": ["新能源车", "汽车", "智能驾驶", "固态电池", "锂电", "充电桩"],
    "机器人": ["机器人", "人形机器人", "减速器", "伺服", "传感器"],
    "低空经济": ["低空", "飞行汽车", "eVTOL", "无人机", "通航"],
    "医药": ["创新药", "医药", "医疗", "减肥药", "CXO"],
    "消费": ["消费", "白酒", "旅游", "餐饮", "家电", "零售"],
    "金融": ["银行", "券商", "保险", "并购重组", "资本市场"],
    "地产链": ["房地产", "地产", "城中村", "家居", "建材"],
    "军工": ["军工", "航天", "卫星", "商业航天", "低轨"],
    "黄金有色": ["黄金", "铜", "铝", "稀土", "有色", "贵金属"],
}

NEWS_SECTOR_STOCK_POOL = {
    "AI": [{"code": "300308", "name": "中际旭创"}, {"code": "601138", "name": "工业富联"}, {"code": "000977", "name": "浪潮信息"}],
    "算力": [{"code": "300308", "name": "中际旭创"}, {"code": "300502", "name": "新易盛"}, {"code": "601138", "name": "工业富联"}],
    "半导体": [{"code": "002371", "name": "北方华创"}, {"code": "688981", "name": "中芯国际"}, {"code": "688256", "name": "寒武纪"}],
    "新能源车": [{"code": "300750", "name": "宁德时代"}, {"code": "002594", "name": "比亚迪"}, {"code": "601689", "name": "拓普集团"}],
    "机器人": [{"code": "300124", "name": "汇川技术"}, {"code": "002050", "name": "三花智控"}, {"code": "002472", "name": "双环传动"}],
    "低空经济": [{"code": "002085", "name": "万丰奥威"}, {"code": "600879", "name": "航天电子"}, {"code": "300159", "name": "新研股份"}],
    "医药": [{"code": "600276", "name": "恒瑞医药"}, {"code": "300760", "name": "迈瑞医疗"}, {"code": "688235", "name": "百济神州"}],
    "消费": [{"code": "600519", "name": "贵州茅台"}, {"code": "000858", "name": "五粮液"}, {"code": "000333", "name": "美的集团"}],
    "金融": [{"code": "600030", "name": "中信证券"}, {"code": "600036", "name": "招商银行"}, {"code": "300059", "name": "东方财富"}],
    "地产链": [{"code": "600048", "name": "保利发展"}, {"code": "000002", "name": "万科A"}, {"code": "000651", "name": "格力电器"}],
    "军工": [{"code": "600760", "name": "中航沈飞"}, {"code": "000768", "name": "中航西飞"}, {"code": "002179", "name": "中航光电"}],
    "黄金有色": [{"code": "600547", "name": "山东黄金"}, {"code": "601899", "name": "紫金矿业"}, {"code": "600111", "name": "北方稀土"}],
}

class HighEndNewsDB:
    """轻量情报缓存库。优先写入本地 sqlite；失败时不影响主流程。"""
    def __init__(self, db_path="news_terminal_cache.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS news_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT,
                    mode TEXT,
                    stock_code TEXT,
                    score REAL,
                    summary TEXT
                )
            """)
            conn.commit()
            conn.close()
        except Exception:
            pass

    def save_run(self, mode, stock_code, score, summary):
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO news_runs(ts, mode, stock_code, score, summary) VALUES (?, ?, ?, ?, ?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), mode, stock_code or "", safe_float(score), str(summary)[:2000])
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def recent_runs(self, limit=10):
        try:
            conn = sqlite3.connect(self.db_path)
            df = pd.read_sql_query("SELECT * FROM news_runs ORDER BY id DESC LIMIT ?", conn, params=(limit,))
            conn.close()
            return df
        except Exception:
            return pd.DataFrame()

class HighEndNewsFetcher:
    """高端情报数据采集器：全网快讯 + 财经新闻 + 个股新闻公告。"""
    def __init__(self, max_items=60):
        self.max_items = max_items
        self.errors = []

    def collect(self, stock_code="", max_items=60, include_wencai=False):
        items = []
        self.errors = []
        items.extend(self._fetch_sina_live(max_items=max_items))
        items.extend(self._fetch_em_global(max_items=max_items))
        items.extend(self._fetch_em_announcements(max_items=max_items))
        if stock_code:
            items.extend(self._fetch_stock_announcements_em(stock_code, max_items=max_items))
            if include_wencai:
                items.extend(self._fetch_wencai_stock_news(stock_code, max_items=min(15, max_items)))

        seen = set()
        cleaned = []
        for item in items:
            title = str(item.get("title") or item.get("summary") or "").strip()
            if not title:
                continue
            key = re.sub(r"\s+", "", title)[:80]
            if key in seen:
                continue
            seen.add(key)
            item["title"] = title
            item["impact_score"] = self._score_item(item)
            item["matched_sectors"] = self._match_sectors(title + " " + str(item.get("summary", "")))
            cleaned.append(item)

        cleaned = sorted(cleaned, key=lambda x: (safe_float(x.get("impact_score")), str(x.get("time", ""))), reverse=True)
        return {"items": cleaned[:max_items], "errors": self.errors, "count": len(cleaned[:max_items])}

    def _fetch_sina_live(self, max_items=60):
        url = "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=80&zhibo_id=152&tag_id=0&dire=f&dpc=1"
        res = fetch_json(url, timeout=6, extra_headers={"Referer": "https://finance.sina.com.cn/"})
        out = []
        try:
            rows = res.get("result", {}).get("data", {}).get("feed", {}).get("list", []) if res else []
            for row in rows[:max_items]:
                text = re.sub(r"<[^>]+>", "", str(row.get("rich_text", "")).strip())
                if len(text) >= 10:
                    out.append({"source": "新浪财经直播", "platform": "财经快讯", "title": text, "summary": text, "time": row.get("create_time", "")})
        except Exception as e:
            self.errors.append(f"新浪财经直播失败: {e}")
        return out

    def _fetch_em_global(self, max_items=60):
        out = []
        try:
            df = ak.stock_info_global_em()
            if df is not None and not df.empty:
                for _, row in df.head(max_items).iterrows():
                    title = str(row.get("标题") or row.get("title") or "")
                    if title:
                        out.append({"source": "东方财富全球财经", "platform": "财经新闻", "title": title, "summary": str(row.get("摘要", "")), "time": str(row.get("发布时间", ""))})
        except Exception as e:
            self.errors.append(f"东方财富全球财经失败: {e}")
        return out

    def _fetch_em_announcements(self, max_items=60):
        url = "https://np-anotice-stock.eastmoney.com/api/security/ann?page_size=30&page_index=1&ann_type=A"
        res = fetch_json(url, timeout=6, extra_headers={"Referer": "https://data.eastmoney.com/"})
        out = []
        try:
            rows = res.get("data", {}).get("list", []) if res else []
            for row in rows[:max_items]:
                title = str(row.get("title") or row.get("art_code") or "")
                if title:
                    out.append({"source": "东方财富公告", "platform": "公告", "title": title, "summary": str(row.get("columns", "")), "time": str(row.get("notice_date", ""))})
        except Exception as e:
            self.errors.append(f"东方财富公告失败: {e}")
        return out

    def _fetch_stock_announcements_em(self, stock_code, max_items=30):
        out = []
        try:
            # 尝试 AKShare 个股公告接口；不同版本字段不完全一致，所以做宽松解析。
            if hasattr(ak, "stock_notice_report"):
                df = ak.stock_notice_report(symbol="全部")
                if df is not None and not df.empty:
                    code_cols = [c for c in df.columns if "代码" in str(c)]
                    if code_cols:
                        df = df[df[code_cols[0]].astype(str).str.contains(str(stock_code), na=False)]
                    for _, row in df.head(max_items).iterrows():
                        title = str(row.get("公告标题") or row.get("标题") or row.get("公告名称") or row.to_dict())
                        out.append({"source": "AKShare个股公告", "platform": "个股公告", "title": title, "summary": str(row.to_dict())[:600], "time": str(row.get("公告日期", row.get("日期", "")))})
        except Exception as e:
            self.errors.append(f"个股公告备用源失败: {e}")
        return out

    def _fetch_wencai_stock_news(self, stock_code, max_items=15):
        out = []
        try:
            for query_type in ["新闻", "公告"]:
                try:
                    result = pywencai.get(query=f"{stock_code}{query_type}", loop=False)
                except Exception as e:
                    self.errors.append(f"问财{query_type}失败: {e}")
                    continue
                if isinstance(result, pd.DataFrame) and not result.empty:
                    df = result.head(max_items)
                elif isinstance(result, dict):
                    df = pd.DataFrame([result])
                else:
                    continue
                for _, row in df.iterrows():
                    vals = [str(v) for v in row.to_dict().values() if str(v) not in ["nan", "None", ""]]
                    title = " | ".join(vals[:3])[:300]
                    if title:
                        out.append({"source": f"问财{query_type}", "platform": "问财", "title": title, "summary": " | ".join(vals)[:800], "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        except Exception as e:
            self.errors.append(f"问财新闻公告总失败: {e}")
        return out

    def _match_sectors(self, text):
        matched = []
        for sector, kws in NEWS_KEYWORD_SECTOR_MAP.items():
            if any(k.lower() in text.lower() for k in kws):
                matched.append(sector)
        return matched

    def _score_item(self, item):
        text = f"{item.get('title','')} {item.get('summary','')}"
        high_words = ["重磅", "突发", "大涨", "暴涨", "涨停", "政策", "央行", "国务院", "并购", "重组", "制裁", "降息", "关税", "突破", "新高"]
        risk_words = ["下跌", "暴跌", "风险", "处罚", "立案", "减持", "亏损", "退市", "监管", "调查"]
        score = 30
        score += sum(8 for w in high_words if w in text)
        score += sum(6 for w in risk_words if w in text)
        score += 8 * len(self._match_sectors(text))
        if item.get("platform") == "公告":
            score += 8
        return min(100, score)

class HighEndNewsAnalyzer:
    """高端新闻流分析器：热点抽取、流量评分、板块映射、AI 投研。"""
    def __init__(self):
        pass

    def analyze(self, items, stock_code="", use_ai=True, mode="标准"):
        topics = self.extract_topics(items)
        sector_view = self.build_sector_view(items, topics)
        flow = self.calc_flow_score(items, topics)
        risk = self.calc_risk(items, flow)
        candidate_stocks = self.build_candidate_stocks(sector_view)
        ai_report = {}
        if use_ai and api_key:
            ai_report = self.run_ai_agents(items, topics, sector_view, flow, risk, candidate_stocks, stock_code, mode)
        else:
            ai_report = self.fallback_ai_report(sector_view, flow, risk, candidate_stocks)
        return {"topics": topics, "sector_view": sector_view, "flow": flow, "risk": risk, "candidate_stocks": candidate_stocks, "ai_report": ai_report}

    def extract_topics(self, items):
        counter = Counter()
        for item in items:
            text = f"{item.get('title','')} {item.get('summary','')}"
            for sector, kws in NEWS_KEYWORD_SECTOR_MAP.items():
                for kw in kws:
                    if kw.lower() in text.lower():
                        counter[kw] += 1
        topics = []
        for kw, cnt in counter.most_common(15):
            topics.append({"topic": kw, "heat": cnt * 10, "cross_platform": self._count_platform_for_kw(items, kw)})
        return topics

    def _count_platform_for_kw(self, items, kw):
        return len(set([i.get("platform", "未知") for i in items if kw.lower() in f"{i.get('title','')} {i.get('summary','')}".lower()]))

    def build_sector_view(self, items, topics):
        sector_counter = Counter()
        sector_sources = {}
        for item in items:
            for sec in item.get("matched_sectors", []):
                sector_counter[sec] += max(1, int(safe_float(item.get("impact_score")) // 20))
                sector_sources.setdefault(sec, []).append(item.get("title", "")[:80])
        rows = []
        for sec, val in sector_counter.most_common(12):
            rows.append({
                "板块": sec,
                "热度分": min(100, val * 8),
                "影响方向": "偏利好" if val >= 2 else "观察",
                "核心线索": "；".join(sector_sources.get(sec, [])[:3]),
                "候选标的": "、".join([s["name"] for s in NEWS_SECTOR_STOCK_POOL.get(sec, [])[:3]])
            })
        return rows

    def calc_flow_score(self, items, topics):
        source_count = len(set([i.get("platform", "未知") for i in items]))
        avg_impact = sum([safe_float(i.get("impact_score")) for i in items]) / max(1, len(items))
        topic_heat = sum([safe_float(t.get("heat")) for t in topics[:5]])
        score = min(100, int(avg_impact * 0.45 + source_count * 8 + topic_heat * 0.35))
        if score >= 80:
            level = "高热度"
            stage = "高潮扩散期"
        elif score >= 60:
            level = "中高热度"
            stage = "发酵加速期"
        elif score >= 40:
            level = "中性热度"
            stage = "观察酝酿期"
        else:
            level = "低热度"
            stage = "低位潜伏期"
        return {"score": score, "level": level, "stage": stage, "source_count": source_count, "item_count": len(items)}

    def calc_risk(self, items, flow):
        risk_words = ["减持", "立案", "处罚", "亏损", "退市", "监管", "暴跌", "调查", "风险", "澄清"]
        risk_hits = []
        for item in items:
            text = f"{item.get('title','')} {item.get('summary','')}"
            if any(w in text for w in risk_words):
                risk_hits.append(item.get("title", ""))
        risk_score = min(100, len(risk_hits) * 12 + (20 if flow.get("stage") == "高潮扩散期" else 0))
        level = "高" if risk_score >= 65 else "中" if risk_score >= 35 else "低"
        return {"risk_score": risk_score, "risk_level": level, "risk_factors": risk_hits[:8]}

    def build_candidate_stocks(self, sector_view):
        out = []
        rank = 1
        for row in sector_view[:5]:
            sec = row.get("板块")
            for stock in NEWS_SECTOR_STOCK_POOL.get(sec, [])[:2]:
                out.append({"rank": rank, "code": stock["code"], "name": stock["name"], "sector": sec, "reason": f"新闻流量映射到{sec}，板块热度分{row.get('热度分')}"})
                rank += 1
        return out[:10]

    def run_ai_agents(self, items, topics, sector_view, flow, risk, candidate_stocks, stock_code, mode):
        compact_news = "\n".join([f"- [{i.get('platform')}/{i.get('source')}] {i.get('title')}" for i in items[:35]])
        topics_text = json.dumps(topics[:12], ensure_ascii=False)
        sectors_text = json.dumps(sector_view[:10], ensure_ascii=False)
        stocks_text = json.dumps(candidate_stocks[:10], ensure_ascii=False)
        risk_text = json.dumps(risk, ensure_ascii=False)
        prompt = f"""
你是顶级对冲基金的A股新闻流情报官。请基于以下数据生成【高端情报终端报告】。

【分析模式】{mode}
【关注个股】{stock_code or '无'}
【流量状态】{json.dumps(flow, ensure_ascii=False)}
【热点话题】{topics_text}
【板块映射】{sectors_text}
【候选股票】{stocks_text}
【风险信号】{risk_text}
【新闻流】
{compact_news}

请按以下结构输出，禁止空话：
1. 📡 情报总览：今天新闻流的主线是什么，处于潜伏/发酵/高潮/退潮哪个阶段。
2. 🔥 题材与板块映射：列出3-5条最可能影响A股的题材链条。
3. 🎯 重点股票观察池：从候选股里筛5只，写清催化剂、观察点、风险。
4. ⚠️ 风险雷达：哪些新闻可能造成高位兑现、监管、业绩或情绪风险。
5. 🧭 次日操作计划：追涨、低吸、观望、回避分别适用什么条件。
6. 最后给一句明确结论：进攻 / 轻仓试错 / 观望 / 防守。
"""
        report = call_ai(prompt, temperature=0.25)
        return {"chief_report": report}

    def fallback_ai_report(self, sector_view, flow, risk, candidate_stocks):
        lines = [f"当前新闻流量等级：{flow.get('level')}，阶段：{flow.get('stage')}，风险等级：{risk.get('risk_level')}。"]
        if sector_view:
            lines.append("重点关注板块：" + "、".join([x.get("板块", "") for x in sector_view[:5]]))
        if candidate_stocks:
            lines.append("候选股票：" + "、".join([f"{x['name']}({x['code']})" for x in candidate_stocks[:6]]))
        return {"chief_report": "\n\n".join(lines)}

def render_high_end_news_terminal():
    st.markdown("#### 🛰️ 高端情报终端 Pro")
    st.write("整合全网快讯、公告、个股新闻、题材映射、风险雷达与 AI 多智能体研判，用来判断新闻流对 A 股板块和个股的影响。")

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        stock_code = st.text_input("关注个股代码（可选）", placeholder="例如：300750", key="news_stock_code")
    with c2:
        max_items = st.slider("情报数量", 20, 120, 60, 10)
    with c3:
        mode = st.selectbox("情报模式", ["标准", "深度", "极速"], index=0)

    c4, c5 = st.columns([1, 1])
    with c4:
        include_wencai = st.checkbox("启用问财个股新闻/公告（可能较慢）", value=False)
    with c5:
        use_ai_news = st.checkbox("生成 AI 情报报告", value=True)

    if st.button("🚀 启动高端情报扫描", type="primary", width="stretch"):
        if use_ai_news and not api_key:
            st.warning("未配置 GROQ_API_KEY，将只展示规则引擎分析。")
            use_ai_news = False

        with st.spinner("正在抓取新闻流、公告流与财经快讯..."):
            fetcher = HighEndNewsFetcher(max_items=max_items)
            raw = fetcher.collect(stock_code=stock_code.strip(), max_items=max_items, include_wencai=include_wencai)
            items = raw.get("items", [])

        if not items:
            st.error("未获取到有效新闻数据。可能是云端接口受限，请稍后再试或关闭问财选项。")
            if raw.get("errors"):
                with st.expander("查看错误详情"):
                    st.write(raw.get("errors"))
            return

        analyzer = HighEndNewsAnalyzer()
        with st.spinner("正在进行题材识别、板块映射与风险雷达计算..."):
            res = analyzer.analyze(items, stock_code=stock_code.strip(), use_ai=use_ai_news, mode=mode)

        flow = res.get("flow", {})
        risk = res.get("risk", {})
        st.success(f"情报扫描完成：共获取 {len(items)} 条有效信息。")
        if raw.get("errors"):
            with st.expander("数据源提示 / 失败记录", expanded=False):
                st.write("\n".join(raw.get("errors", [])[-20:]))

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("新闻流量分", f"{flow.get('score', 0)}")
        m2.metric("流量阶段", flow.get("stage", "未知"))
        m3.metric("风险等级", risk.get("risk_level", "未知"), f"{risk.get('risk_score', 0)}")
        m4.metric("数据源数量", f"{flow.get('source_count', 0)}")

        tab_a, tab_b, tab_c, tab_d, tab_e, tab_f = st.tabs(["📌 首席结论", "🔥 热点话题", "🏭 板块映射", "🎯 股票观察池", "⚠️ 风险雷达", "🧾 原始情报"])
        with tab_a:
            st.markdown(res.get("ai_report", {}).get("chief_report", "暂无报告"))
            try:
                HighEndNewsDB().save_run(mode, stock_code, flow.get("score", 0), res.get("ai_report", {}).get("chief_report", ""))
            except Exception:
                pass
        with tab_b:
            topics = res.get("topics", [])
            if topics:
                st.dataframe(pd.DataFrame(topics), width="stretch", hide_index=True)
            else:
                st.info("暂未识别出明确热点话题。")
        with tab_c:
            sector_view = res.get("sector_view", [])
            if sector_view:
                st.dataframe(pd.DataFrame(sector_view), width="stretch", hide_index=True)
            else:
                st.info("暂未形成明确板块映射。")
        with tab_d:
            cands = res.get("candidate_stocks", [])
            if cands:
                st.dataframe(pd.DataFrame(cands), width="stretch", hide_index=True)
            else:
                st.info("暂无候选股票。")
        with tab_e:
            factors = risk.get("risk_factors", [])
            if factors:
                for x in factors:
                    st.warning(x)
            else:
                st.success("暂未识别到明显高风险新闻词。")
        with tab_f:
            show_cols = ["time", "platform", "source", "title", "impact_score", "matched_sectors"]
            df_items = pd.DataFrame(items)
            show_cols = [c for c in show_cols if c in df_items.columns]
            st.dataframe(df_items[show_cols], width="stretch", hide_index=True)

    with st.expander("📚 查看最近情报运行记录", expanded=False):
        hist = HighEndNewsDB().recent_runs(10)
        if hist is not None and not hist.empty:
            st.dataframe(hist, width="stretch", hide_index=True)
        else:
            st.info("暂无历史记录。")

# ================= 高端新闻情报终端模块结束 =================

st.markdown("### 🌍 宏观市场实时看板")

# 宏观看板必须独立、轻量、可降级；任何接口失败都不能影响主程序。
try:
    pulse_data = get_market_pulse()
except Exception as e:
    if DEBUG_MODE:
        st.warning(f"宏观看板函数异常，已启用本地占位：{e}")
    pulse_data = {
        "上证指数": {"price": 0.0, "pct": 0.0, "source": "本地占位", "status": "函数异常", "available": False},
        "深证成指": {"price": 0.0, "pct": 0.0, "source": "本地占位", "status": "函数异常", "available": False},
        "创业板指": {"price": 0.0, "pct": 0.0, "source": "本地占位", "status": "函数异常", "available": False},
        "沪深300": {"price": 0.0, "pct": 0.0, "source": "本地占位", "status": "函数异常", "available": False},
        "USD/CNH(离岸)": {"price": 0.0, "pct": 0.0, "source": "本地占位", "status": "函数异常", "available": False},
    }

if not pulse_data:
    pulse_data = {
        "上证指数": {"price": 0.0, "pct": 0.0, "source": "本地占位", "status": "空数据", "available": False},
        "深证成指": {"price": 0.0, "pct": 0.0, "source": "本地占位", "status": "空数据", "available": False},
        "创业板指": {"price": 0.0, "pct": 0.0, "source": "本地占位", "status": "空数据", "available": False},
        "沪深300": {"price": 0.0, "pct": 0.0, "source": "本地占位", "status": "空数据", "available": False},
        "USD/CNH(离岸)": {"price": 0.0, "pct": 0.0, "source": "本地占位", "status": "空数据", "available": False},
    }

available_count = sum(1 for v in pulse_data.values() if isinstance(v, dict) and v.get("available"))
if available_count == 0:
    st.caption("宏观看板：实时源暂不可用，已启用占位卡片；不影响下方个股、龙虎榜、主力资金和新闻情报模块。")
else:
    st.caption(f"宏观看板：已同步 {available_count}/{len(pulse_data)} 项实时数据。")

cols = st.columns(min(len(pulse_data), 6))
for idx, (key, data) in enumerate(pulse_data.items()):
    with cols[idx % len(cols)]:
        with st.container(border=True):
            data = data if isinstance(data, dict) else {}
            price = safe_float(data.get("price"), 0.0)
            pct = safe_float(data.get("pct"), 0.0)
            source = data.get("source", "-")
            status = data.get("status", "-")
            available = bool(data.get("available", False))
            if available and price > 0:
                if "CNH" in key:
                    st.metric(key, f"{price:.4f}", f"{pct:.2f}%", delta_color="inverse")
                else:
                    st.metric(key, f"{price:.2f}", f"{pct:.2f}%")
            else:
                st.metric(key, "待同步", "--")
            st.caption(f"{source} · {status}")

st.markdown("<br>", unsafe_allow_html=True)

# ================= 终端功能选项卡 =================
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🎯 I. 个股标的解析",
    "📈 II. 宏观大盘推演",
    "🔥 III. 资金热点板块",
    "🦅 IV. 高阶情报终端",
    "🐉 V. 智瞰龙虎榜解析",
    "🐋 VI. 主力资金选股",
    "🛰️ VII. 高端情报终端"
])

# ================= Tab 1: 个股解析 =================
with tab1:
    with st.container(border=True):
        st.markdown("#### 🔎 个股雷达锁定（多维买卖点测算版）")
        col1, col2 = st.columns([1, 1])
        with col1:
            symbol_input = st.text_input("标的代码", placeholder="例：600519")
            analyze_btn = st.button("启动核心算法", type="primary", width="stretch")
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

                    # 新增：先给出结构化评分和交易计划，再进入详细技术图与 AI 解读
                    assessment = score_stock_analysis(quote, df_kline, mtf)
                    render_score_panel(assessment)
                    render_trade_plan_card(assessment)

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
                        st.plotly_chart(fig, width="stretch")

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
                    st.caption(f"数据质量：{mtf.get('data_quality', '未知')}｜综合分：{mtf.get('score', 0)}")
                    m1, m2, m3 = st.columns(3)
                    with m1:
                        render_tf_card(mtf["15m"], "15分钟级别")
                    with m2:
                        render_tf_card(mtf["60m"], "60分钟级别")
                    with m3:
                        render_tf_card(mtf["120m"], "120分钟级别")

                    st.markdown("##### 🧠 多周期综合结论")
                    v1, v2, v3, v4 = st.columns(4)
                    v1.metric("综合结论", mtf.get("final_view", "无法判断"))
                    v2.metric("操作倾向", mtf.get("action", "等待确认"))
                    v3.metric("关键支撑", f"{mtf['key_support']:.2f}" if mtf.get("key_support") is not None else "N/A")
                    v4.metric("关键压力", f"{mtf['key_pressure']:.2f}" if mtf.get("key_pressure") is not None else "N/A")
                    st.info(f"综合结论：**{mtf.get('final_view', '无法判断')}**；执行建议：**{mtf.get('action', '等待确认')}**")

                    # 新增：量化交易计划卡片，便于直接转化为盘中观察点
                    st.markdown("##### 🎯 交易计划辅助")
                    current_px = mtf.get("current_close") or price
                    key_support = mtf.get("key_support")
                    key_pressure = mtf.get("key_pressure")
                    if key_support and key_pressure and current_px:
                        risk = max(current_px - key_support, current_px * 0.01)
                        reward = max(key_pressure - current_px, 0)
                        rr = reward / risk if risk > 0 else 0
                        p1, p2, p3, p4 = st.columns(4)
                        p1.metric("当前参考价", f"{current_px:.2f}")
                        p2.metric("回撤观察区", f"{key_support:.2f} - {current_px:.2f}")
                        p3.metric("突破确认位", f"{key_pressure:.2f}")
                        p4.metric("估算盈亏比", f"{rr:.2f}")
                        if rr < 1:
                            st.warning("当前价格距离压力较近，盈亏比一般，适合等回踩或放量突破后再判断。")
                        elif rr >= 2:
                            st.success("当前盈亏比较好，但仍需结合成交量与大盘环境确认。")
                        else:
                            st.info("盈亏比中性，适合小仓位观察或等待更清晰信号。")
                    else:
                        st.warning("关键支撑/压力尚不完整，建议先以日线结构和成交量为主。")

                    # 新增：多周期结构明细表，方便手机端复制与复盘
                    tf_table = pd.DataFrame([
                        {
                            "周期": "15分钟",
                            "偏向": mtf["15m"].get("bias"),
                            "趋势": mtf["15m"].get("trend"),
                            "MACD": mtf["15m"].get("macd_state"),
                            "RSI": round(mtf["15m"].get("rsi"), 2) if mtf["15m"].get("rsi") is not None else "-",
                            "支撑": round(mtf["15m"].get("support"), 2) if mtf["15m"].get("support") is not None else "-",
                            "压力": round(mtf["15m"].get("pressure"), 2) if mtf["15m"].get("pressure") is not None else "-",
                            "样本": mtf["15m"].get("bars"),
                            "数据源": mtf["15m"].get("source")
                        },
                        {
                            "周期": "60分钟",
                            "偏向": mtf["60m"].get("bias"),
                            "趋势": mtf["60m"].get("trend"),
                            "MACD": mtf["60m"].get("macd_state"),
                            "RSI": round(mtf["60m"].get("rsi"), 2) if mtf["60m"].get("rsi") is not None else "-",
                            "支撑": round(mtf["60m"].get("support"), 2) if mtf["60m"].get("support") is not None else "-",
                            "压力": round(mtf["60m"].get("pressure"), 2) if mtf["60m"].get("pressure") is not None else "-",
                            "样本": mtf["60m"].get("bars"),
                            "数据源": mtf["60m"].get("source")
                        },
                        {
                            "周期": "120分钟",
                            "偏向": mtf["120m"].get("bias"),
                            "趋势": mtf["120m"].get("trend"),
                            "MACD": mtf["120m"].get("macd_state"),
                            "RSI": round(mtf["120m"].get("rsi"), 2) if mtf["120m"].get("rsi") is not None else "-",
                            "支撑": round(mtf["120m"].get("support"), 2) if mtf["120m"].get("support") is not None else "-",
                            "压力": round(mtf["120m"].get("pressure"), 2) if mtf["120m"].get("pressure") is not None else "-",
                            "样本": mtf["120m"].get("bars"),
                            "数据源": mtf["120m"].get("source")
                        }
                    ])
                    st.dataframe(tf_table, width="stretch", hide_index=True)

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

    st.markdown("---")
    with st.container(border=True):
        render_watchlist_scanner()

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
                        st.dataframe(df_blocks, width="stretch", hide_index=True)
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
        st.markdown("#### 🐉 智瞰龙虎榜 AI 分析集群 3.0")
        st.write("整合优化版龙虎榜数据采集、自动回溯、量化评分、游资行为、个股潜力、题材追踪、风险控制与首席策略师综合研判。已移除外部付费数据源依赖。")

        col_date, col_lookback, col_depth = st.columns([1, 1, 1])
        with col_date:
            lhb_date = st.date_input("选择龙虎榜日期", datetime.now() - timedelta(days=1))
        with col_lookback:
            lookback_days = st.slider("无数据时自动回溯天数", 3, 20, 10, 1)
        with col_depth:
            ai_depth = st.selectbox("AI 分析深度", ["标准", "深度"], index=0, help="标准更快：个股潜力+风险控制+首席策略；深度会增加游资画像和题材追踪。")

        col_opt1, col_opt2 = st.columns([1, 1])
        with col_opt1:
            run_ai_lhb = st.checkbox("生成 AI 分析报告", value=True, help="关闭后只显示数据、评分和候选股票，速度最快。")
        with col_opt2:
            show_raw_lhb = st.checkbox("显示原始明细数据", value=False)

        run_lhb_btn = st.button("🚀 启动智瞰龙虎分析集群", type="primary", width="stretch")

        if run_lhb_btn:
            if run_ai_lhb and not api_key:
                st.error("配置缺失: GROQ_API_KEY。你可以先关闭“生成 AI 分析报告”，只查看龙虎榜数据和量化评分。")
            else:
                date_str = lhb_date.strftime("%Y-%m-%d")
                with st.spinner(f"正在获取 {date_str} 龙虎榜数据，并自动回溯最近可用交易日..."):
                    engine = LonghubangEngine(model=selected_model)
                    res = engine.run_comprehensive_analysis(
                        date=date_str,
                        lookback_days=lookback_days,
                        ai_depth=ai_depth,
                        run_ai=run_ai_lhb,
                    )

                if not res.get("success"):
                    st.error(f"未能获取到 {date_str} 及最近 {lookback_days} 天的龙虎榜数据。可能是 API 受限、云端访问不稳定，或近期无交易日数据。")
                    with st.expander("查看失败明细", expanded=False):
                        st.write("\n".join(res.get("errors", [])))
                else:
                    used_date = res.get("used_date") or date_str
                    source = res.get("source", "未知数据源")
                    info = res.get("data_info", {})
                    summary = info.get("summary", {})
                    df_lhb = res.get("dataframe", pd.DataFrame())
                    scoring_df = res.get("scoring_ranking", pd.DataFrame())

                    if used_date != date_str:
                        st.warning(f"{date_str} 未获取到有效龙虎榜数据，已自动切换到最近可用日期：{used_date}。")
                    st.success(f"✓ 成功获取 {used_date} 的龙虎榜数据。数据源：{source}。")

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("记录总数", f"{info.get('total_records', 0)}")
                    m2.metric("涉及股票", f"{info.get('total_stocks', 0)}")
                    m3.metric("涉及游资", f"{info.get('total_youzi', 0)}")
                    m4.metric("净流入合计", f"{safe_float(summary.get('total_net_inflow'))/100000000:.2f} 亿")

                    if res.get("errors"):
                        with st.expander("查看数据源回溯记录", expanded=False):
                            st.write("\n".join(res.get("errors", [])[-30:]))

                    st.markdown("### 🧮 智瞰量化评分排名")
                    if scoring_df is not None and not scoring_df.empty:
                        display_cols = [c for c in ["股票代码", "股票名称", "智瞰评分", "信号标签", "净流入金额", "买入金额", "卖出金额", "上榜次数", "游资数量", "概念"] if c in scoring_df.columns]
                        st.dataframe(scoring_df[display_cols].head(20), width="stretch", hide_index=True)
                    else:
                        st.info("暂无可评分数据。")

                    st.markdown("### 🎯 次日重点观察池")
                    recs = res.get("recommended_stocks", [])
                    if recs:
                        rec_df = pd.DataFrame(recs)
                        st.dataframe(rec_df, width="stretch", hide_index=True)
                    else:
                        st.info("暂无推荐候选。")

                    tab_overview, tab_youzi, tab_stock, tab_theme, tab_risk, tab_chief, tab_raw = st.tabs([
                        "📊 数据概况", "🎯 游资画像", "📈 个股潜力", "🔥 题材追踪", "⚠️ 风险控制", "👔 首席策略", "🧾 明细数据"
                    ])

                    with tab_overview:
                        c1, c2 = st.columns(2)
                        with c1:
                            st.markdown("##### 活跃游资 TOP")
                            top_youzi = summary.get("top_youzi", {})
                            if top_youzi:
                                st.dataframe(pd.DataFrame([{"游资名称": k, "净流入金额": v} for k, v in top_youzi.items()]), width="stretch", hide_index=True)
                            else:
                                st.info("当前数据源未提供明确游资席位。")
                        with c2:
                            st.markdown("##### 热门概念 TOP")
                            hot_concepts = summary.get("hot_concepts", {})
                            if hot_concepts:
                                st.dataframe(pd.DataFrame([{"概念": k, "出现次数": v} for k, v in hot_concepts.items()]), width="stretch", hide_index=True)
                            else:
                                st.info("当前数据源未提供明确概念字段。")

                    agents = res.get("agents_analysis", {})
                    with tab_youzi:
                        if agents.get("youzi"):
                            st.markdown(agents["youzi"].get("analysis", ""))
                        elif ai_depth != "深度":
                            st.info("当前为标准模式，未运行游资画像分析。选择 AI 分析深度为“深度”后可生成。")
                        else:
                            st.info("暂无游资画像报告。")
                    with tab_stock:
                        if agents.get("stock"):
                            st.markdown(agents["stock"].get("analysis", ""))
                        else:
                            st.info("暂无个股潜力报告。")
                    with tab_theme:
                        if agents.get("theme"):
                            st.markdown(agents["theme"].get("analysis", ""))
                        elif ai_depth != "深度":
                            st.info("当前为标准模式，未运行题材追踪分析。选择 AI 分析深度为“深度”后可生成。")
                        else:
                            st.info("暂无题材追踪报告。")
                    with tab_risk:
                        if agents.get("risk"):
                            st.markdown(agents["risk"].get("analysis", ""))
                        else:
                            st.info("暂无风险控制报告。")
                    with tab_chief:
                        if agents.get("chief"):
                            st.markdown(agents["chief"].get("analysis", ""))
                        elif not run_ai_lhb:
                            st.info("你已关闭 AI 报告，本页仅展示量化评分与数据概况。")
                        else:
                            st.info("暂无首席策略报告。")
                    with tab_raw:
                        if show_raw_lhb and df_lhb is not None and not df_lhb.empty:
                            st.dataframe(df_lhb, width="stretch", hide_index=True)
                        else:
                            st.info("勾选“显示原始明细数据”后展示完整龙虎榜明细。")
# ================= Tab 6: 主力资金选股 =================

with tab6:
    render_main_force_tab()

# ================= Tab 7: 高端情报终端 Pro =================
with tab7:
    with st.container(border=True):
        render_high_end_news_terminal()
