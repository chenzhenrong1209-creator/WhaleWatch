# -*- coding: utf-8 -*-
"""
WhaleWatch v12 Lean Stable
核心目标：
1. 删除多轮累积造成的重复函数、JQData 自动认证、AKShare 阻塞调用和旧兜底观察池。
2. 个股解析 / 资金热点 / 主力资金不再无限加载：所有外部请求都有 timeout，失败后只读最近一次真实缓存。
3. 东方财富直连为主，新浪/腾讯做实时行情兜底，BaoStock 做 T+1 K 线备用。
4. 不使用估算主力资金，不使用内置假热点。
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests
import streamlit as st
import plotly.graph_objects as go

try:
    from groq import Groq
except Exception:  # pragma: no cover
    Groq = None

try:
    import baostock as bs
except Exception:  # pragma: no cover
    bs = None

# =============================
# 全局配置
# =============================
APP_VERSION = "v12.0-LEAN-STABLE"
REQ_TIMEOUT = (3.0, 7.0)  # connect/read timeout
CACHE_DIR = Path(os.getenv("WHALEWATCH_CACHE_DIR", "/tmp/whalewatch_cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

EM_UT = "bd1d9ddb04089700cf9c27f6f7426281"
A_SHARE_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": UA,
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "close",
})

# =============================
# 页面配置
# =============================
st.set_page_config(
    page_title="WhaleWatch 轻量投研终端",
    page_icon="🐳",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
.stTabs [data-baseweb="tab-list"] { gap: 10px; flex-wrap: wrap; }
.stTabs [data-baseweb="tab"] { height: auto; min-height: 42px; white-space: normal; font-weight: 700; }
[data-testid="stMetricValue"] { font-size: 1.55rem; }
.small-note { color: #888; font-size: 0.85rem; }
</style>
""",
    unsafe_allow_html=True,
)

st.title("🐳 WhaleWatch 轻量稳定版")
st.caption(f"{APP_VERSION}｜{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}｜真实数据优先｜失败只读真实缓存｜不估算主力资金")

# =============================
# 工具函数：缓存 / 数值 / 代码转换
# =============================
def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_float(x: Any, default: float | None = None) -> float | None:
    try:
        if x in (None, "", "-", "--"):
            return default
        v = float(x)
        if math.isnan(v):
            return default
        return v
    except Exception:
        return default


def fmt_num(x: Any, digits: int = 2, suffix: str = "") -> str:
    v = safe_float(x)
    if v is None:
        return "-"
    return f"{v:.{digits}f}{suffix}"


def normalize_symbol(symbol: str) -> str:
    return re.sub(r"\D", "", str(symbol or "")).zfill(6)[-6:]


def em_market(symbol: str) -> str:
    symbol = normalize_symbol(symbol)
    return "1" if symbol.startswith(("5", "6", "9")) else "0"


def em_secid(symbol: str) -> str:
    symbol = normalize_symbol(symbol)
    return f"{em_market(symbol)}.{symbol}"


def sina_code(symbol: str) -> str:
    symbol = normalize_symbol(symbol)
    return ("sh" if symbol.startswith(("5", "6", "9")) else "sz") + symbol


def cache_path(kind: str, name: str) -> Path:
    d = CACHE_DIR / kind
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{name}.json"


def save_cache(kind: str, name: str, payload: Any) -> None:
    try:
        p = cache_path(kind, name)
        p.write_text(json.dumps({"time": now_str(), "payload": payload}, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception:
        pass


def load_cache(kind: str, name: str, max_age_sec: int | None = None) -> tuple[Any | None, str | None]:
    try:
        p = cache_path(kind, name)
        if not p.exists():
            return None, None
        obj = json.loads(p.read_text(encoding="utf-8"))
        t = obj.get("time")
        if max_age_sec and t:
            dt = datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
            if (datetime.now() - dt).total_seconds() > max_age_sec:
                return None, None
        return obj.get("payload"), t
    except Exception:
        return None, None


def strip_jsonp(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty response")
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)
    m = re.search(r"^[^(]*\((.*)\)\s*;?$", text, flags=re.S)
    if m:
        return json.loads(m.group(1))
    raise ValueError(text[:120])


def request_json(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout=REQ_TIMEOUT) -> Any:
    h = dict(SESSION.headers)
    if headers:
        h.update(headers)
    r = SESSION.get(url, params=params, headers=h, timeout=timeout)
    r.raise_for_status()
    return strip_jsonp(r.text)


def run_limited(label: str, fn: Callable[[], Any], limit_sec: float = 9.0) -> tuple[Any | None, str | None]:
    """轻量限时保护。用于页面按钮调用，防止某一步长时间占住 UI。"""
    start = time.time()
    try:
        result = fn()
        used = time.time() - start
        if used > limit_sec:
            return None, f"{label} 超过 {limit_sec:.0f}s，已丢弃结果"
        return result, None
    except Exception as exc:
        return None, f"{label} 失败：{exc}"

# =============================
# 东方财富直连接口
# =============================
def em_headers(referer: str = "https://quote.eastmoney.com/") -> dict[str, str]:
    return {
        "Referer": referer,
        "Origin": "https://quote.eastmoney.com",
        "Host": "push2.eastmoney.com",
    }


@st.cache_data(ttl=45, show_spinner=False)
def em_realtime_quotes(secids: tuple[str, ...]) -> list[dict[str, Any]]:
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {
        "fltt": "2",
        "invt": "2",
        "fields": "f12,f14,f2,f3,f4,f5,f6,f8,f9,f20,f21,f23,f62,f184,f100",
        "secids": ",".join(secids),
        "ut": EM_UT,
    }
    obj = request_json(url, params=params, headers=em_headers(), timeout=REQ_TIMEOUT)
    return (((obj or {}).get("data") or {}).get("diff") or [])


@st.cache_data(ttl=120, show_spinner=False)
def em_clist_a_share(pz: int = 800, fid: str = "f62") -> list[dict[str, Any]]:
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": str(int(pz)),
        "po": "1",
        "np": "1",
        "ut": EM_UT,
        "fltt": "2",
        "invt": "2",
        "fid": fid,
        "fs": A_SHARE_FS,
        "fields": "f12,f14,f2,f3,f4,f5,f6,f8,f9,f20,f21,f23,f62,f100,f184",
    }
    obj = request_json(url, params=params, headers=em_headers(), timeout=REQ_TIMEOUT)
    return (((obj or {}).get("data") or {}).get("diff") or [])


@st.cache_data(ttl=3600, show_spinner=False)
def em_kline(symbol: str, days: int = 220) -> pd.DataFrame:
    symbol = normalize_symbol(symbol)
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": em_secid(symbol),
        "ut": EM_UT,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "end": "20500101",
        "lmt": str(int(days) + 40),
    }
    obj = request_json(url, params=params, headers={"Referer": "https://quote.eastmoney.com/"}, timeout=REQ_TIMEOUT)
    rows = (((obj or {}).get("data") or {}).get("klines") or [])
    parsed = []
    for line in rows:
        parts = str(line).split(",")
        if len(parts) < 7:
            continue
        parsed.append({
            "date": parts[0],
            "open": safe_float(parts[1]),
            "close": safe_float(parts[2]),
            "high": safe_float(parts[3]),
            "low": safe_float(parts[4]),
            "volume": safe_float(parts[5]),
            "amount": safe_float(parts[6]),
            "pct": safe_float(parts[8]) if len(parts) > 8 else None,
            "turnover": safe_float(parts[10]) if len(parts) > 10 else None,
        })
    df = pd.DataFrame(parsed).dropna(subset=["date", "close"])
    return df.tail(days).reset_index(drop=True)

# =============================
# 新浪 / 腾讯实时行情兜底
# =============================
def sina_quote(symbol: str) -> dict[str, Any] | None:
    code = sina_code(symbol)
    url = f"https://hq.sinajs.cn/list={code}"
    text = SESSION.get(url, headers={"User-Agent": UA, "Referer": "https://finance.sina.com.cn/"}, timeout=REQ_TIMEOUT).text
    m = re.search(r'="(.*)"', text)
    if not m:
        return None
    arr = m.group(1).split(",")
    if len(arr) < 32 or not arr[0]:
        return None
    price = safe_float(arr[3])
    preclose = safe_float(arr[2])
    pct = (price - preclose) / preclose * 100 if price is not None and preclose else None
    return {
        "code": normalize_symbol(symbol),
        "name": arr[0],
        "price": price,
        "pct": pct,
        "volume": safe_float(arr[8]),
        "amount": safe_float(arr[9]),
        "source": "新浪实时行情",
    }


def tencent_quote(symbol: str) -> dict[str, Any] | None:
    code = sina_code(symbol)
    url = f"https://qt.gtimg.cn/q={code}"
    text = SESSION.get(url, headers={"User-Agent": UA, "Referer": "https://gu.qq.com/"}, timeout=REQ_TIMEOUT).text
    m = re.search(r'="(.*)"', text)
    if not m:
        return None
    arr = m.group(1).split("~")
    if len(arr) < 40:
        return None
    return {
        "code": normalize_symbol(symbol),
        "name": arr[1],
        "price": safe_float(arr[3]),
        "pct": safe_float(arr[32]),
        "volume": safe_float(arr[6]),
        "amount": safe_float(arr[37]),
        "source": "腾讯实时行情",
    }

# =============================
# BaoStock T+1 K线备用
# =============================
def baostock_kline(symbol: str, days: int = 220) -> pd.DataFrame | None:
    if bs is None:
        return None
    symbol = normalize_symbol(symbol)
    bs_code = ("sh." if symbol.startswith(("5", "6", "9")) else "sz.") + symbol
    start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            bs.login()
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount,turn,pctChg",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2",
            )
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
            bs.logout()
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "amount", "turnover", "pct"])
        for c in ["open", "high", "low", "close", "volume", "amount", "turnover", "pct"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna(subset=["date", "close"]).tail(days).reset_index(drop=True)
    except Exception:
        with contextlib.suppress(Exception):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                bs.logout()
        return None

# =============================
# 数据聚合服务
# =============================
def get_stock_quote(symbol: str) -> dict[str, Any] | None:
    symbol = normalize_symbol(symbol)
    cache_name = symbol
    errors = []
    try:
        rows = em_realtime_quotes((em_secid(symbol),))
        if rows:
            r = rows[0]
            out = {
                "code": symbol,
                "name": r.get("f14") or symbol,
                "price": safe_float(r.get("f2")),
                "pct": safe_float(r.get("f3")),
                "change": safe_float(r.get("f4")),
                "volume": safe_float(r.get("f5")),
                "amount": safe_float(r.get("f6")),
                "turnover": safe_float(r.get("f8")),
                "pe": safe_float(r.get("f9")),
                "pb": safe_float(r.get("f23")),
                "market_cap": (safe_float(r.get("f20"), 0) or 0) / 1e8 if safe_float(r.get("f20")) is not None else None,
                "main_net": safe_float(r.get("f62")),
                "main_ratio": safe_float(r.get("f184")),
                "industry": r.get("f100") or "-",
                "source": "东方财富实时行情",
            }
            save_cache("quote", cache_name, out)
            return out
    except Exception as e:
        errors.append(f"东财失败：{e}")

    for name, fn in [("新浪", sina_quote), ("腾讯", tencent_quote)]:
        try:
            q = fn(symbol)
            if q and q.get("price") is not None:
                save_cache("quote", cache_name, q)
                return q
        except Exception as e:
            errors.append(f"{name}失败：{e}")

    cached, t = load_cache("quote", cache_name, max_age_sec=24 * 3600)
    if cached:
        cached["source"] = f"最近一次真实缓存｜{t}"
        return cached
    return None


def get_kline(symbol: str, days: int = 220) -> pd.DataFrame | None:
    symbol = normalize_symbol(symbol)
    try:
        df = em_kline(symbol, days)
        if df is not None and len(df) >= 20:
            save_cache("kline", symbol, df.to_dict("records"))
            return df
    except Exception:
        pass
    # BaoStock T+1 备用，避免强依赖东财历史K。
    df = baostock_kline(symbol, days)
    if df is not None and len(df) >= 20:
        save_cache("kline", symbol, df.to_dict("records"))
        return df
    cached, _t = load_cache("kline", symbol, max_age_sec=14 * 24 * 3600)
    if cached:
        return pd.DataFrame(cached)
    return None


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in ["open", "high", "low", "close", "volume", "amount"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, pd.NA)
    df["rsi14"] = 100 - 100 / (1 + rs)
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    return df


def stock_score(quote: dict[str, Any], df: pd.DataFrame | None) -> dict[str, Any]:
    score = 50
    reasons = []
    pct = safe_float(quote.get("pct"), 0) or 0
    turnover = safe_float(quote.get("turnover"), 0) or 0
    main_net = safe_float(quote.get("main_net"), 0) or 0
    if pct > 3:
        score += 8; reasons.append("日内涨幅较强")
    elif pct < -3:
        score -= 8; reasons.append("日内跌幅较大")
    if turnover > 3:
        score += 5; reasons.append("换手较活跃")
    if main_net > 0:
        score += 8; reasons.append("东财真实主力净流入为正")
    elif main_net < 0:
        score -= 8; reasons.append("东财真实主力净流入为负")
    if df is not None and len(df) >= 60:
        d = add_indicators(df)
        last = d.iloc[-1]
        if last["close"] > last["ma20"] > last["ma60"]:
            score += 12; reasons.append("价格位于中期均线多头结构")
        elif last["close"] < last["ma20"]:
            score -= 8; reasons.append("价格低于20日均线")
        if safe_float(last.get("rsi14"), 50) and last["rsi14"] > 75:
            score -= 5; reasons.append("RSI偏高，短线追高风险增加")
    score = max(0, min(100, int(score)))
    level = "偏强" if score >= 70 else "观察" if score >= 50 else "谨慎"
    return {"score": score, "level": level, "reasons": reasons[:6]}


def get_hot_blocks() -> list[dict[str, Any]]:
    """只用东方财富 clist 的真实字段 f100/f62/f184/f6/f3 聚合热点，避免 AKShare 阻塞。"""
    cache_name = datetime.now().strftime("%Y%m%d")
    try:
        rows = em_clist_a_share(pz=900, fid="f62")
        if not rows:
            raise ValueError("东方财富 clist 返回空")
        groups: dict[str, dict[str, Any]] = {}
        for r in rows:
            industry = str(r.get("f100") or "未分类")
            if not industry or industry == "-":
                industry = "未分类"
            g = groups.setdefault(industry, {
                "板块名称": industry,
                "样本数": 0,
                "上涨家数": 0,
                "下跌家数": 0,
                "涨跌幅合计": 0.0,
                "成交额": 0.0,
                "主力净流入": 0.0,
                "领涨股票": "-",
                "领涨幅": -999.0,
            })
            pct = safe_float(r.get("f3"), 0) or 0
            amount = safe_float(r.get("f6"), 0) or 0
            main = safe_float(r.get("f62"), 0) or 0
            g["样本数"] += 1
            g["上涨家数"] += 1 if pct > 0 else 0
            g["下跌家数"] += 1 if pct < 0 else 0
            g["涨跌幅合计"] += pct
            g["成交额"] += amount
            g["主力净流入"] += main
            if pct > g["领涨幅"]:
                g["领涨幅"] = pct
                g["领涨股票"] = f"{r.get('f14','-')}({r.get('f12','')})"
        out = []
        for g in groups.values():
            n = max(1, g["样本数"])
            avg_pct = g["涨跌幅合计"] / n
            up_ratio = g["上涨家数"] / n * 100
            main_yi = g["主力净流入"] / 1e8
            amount_yi = g["成交额"] / 1e8
            hot = avg_pct * 3 + up_ratio * 0.08 + max(min(main_yi, 50), -50) * 0.8 + math.log1p(max(amount_yi, 0))
            out.append({
                "板块名称": g["板块名称"],
                "热点分": round(hot, 2),
                "平均涨幅%": round(avg_pct, 2),
                "上涨占比%": round(up_ratio, 1),
                "主力净流入(亿)": round(main_yi, 2),
                "成交额(亿)": round(amount_yi, 2),
                "样本数": g["样本数"],
                "领涨股票": g["领涨股票"],
                "数据源": "东方财富clist真实字段聚合",
            })
        out = sorted(out, key=lambda x: (x["热点分"], x["主力净流入(亿)"]), reverse=True)[:30]
        save_cache("hot_blocks", cache_name, out)
        return out
    except Exception as e:
        cached, t = load_cache("hot_blocks", cache_name, max_age_sec=24 * 3600)
        if cached:
            for item in cached:
                item["数据源"] = f"最近一次真实缓存｜{t}"
            return cached
        st.session_state["last_hot_error"] = str(e)
        return []


def get_main_money(limit: int = 40) -> list[dict[str, Any]]:
    cache_name = datetime.now().strftime("%Y%m%d")
    try:
        rows = em_clist_a_share(pz=max(limit * 3, 120), fid="f62")
        out = []
        for r in rows:
            main = safe_float(r.get("f62"))
            if main is None:
                continue
            out.append({
                "代码": r.get("f12"),
                "名称": r.get("f14"),
                "现价": safe_float(r.get("f2")),
                "涨跌幅%": safe_float(r.get("f3")),
                "主力净流入(万)": round(main / 1e4, 2),
                "主力净占比%": safe_float(r.get("f184")),
                "行业": r.get("f100") or "-",
                "数据源": "东方财富f62/f184真实字段",
            })
        out = sorted(out, key=lambda x: x.get("主力净流入(万)") or 0, reverse=True)[:limit]
        save_cache("main_money", cache_name, out)
        return out
    except Exception as e:
        cached, t = load_cache("main_money", cache_name, max_age_sec=24 * 3600)
        if cached:
            for item in cached:
                item["数据源"] = f"最近一次真实缓存｜{t}"
            return cached
        st.session_state["last_money_error"] = str(e)
        return []


def get_market_pulse() -> list[dict[str, Any]]:
    targets = {
        "上证指数": "1.000001",
        "深证成指": "0.399001",
        "创业板指": "0.399006",
        "沪深300": "1.000300",
        "科创50": "1.000688",
    }
    cache_name = "market_pulse"
    try:
        rows = em_realtime_quotes(tuple(targets.values()))
        out = []
        by_code = {f"{em_market(str(r.get('f12','')))}.{r.get('f12')}": r for r in rows}
        # 由于指数 f12 也是 000001 等，直接按返回顺序兜底匹配
        for name, secid in targets.items():
            code = secid.split(".")[1]
            r = next((x for x in rows if str(x.get("f12")) == code), None)
            if not r:
                continue
            out.append({
                "名称": name,
                "点位": safe_float(r.get("f2")),
                "涨跌幅%": safe_float(r.get("f3")),
                "来源": "东方财富指数实时",
            })
        if out:
            save_cache("market", cache_name, out)
            return out
    except Exception:
        pass
    cached, t = load_cache("market", cache_name, max_age_sec=12 * 3600)
    if cached:
        for x in cached:
            x["来源"] = f"最近一次真实缓存｜{t}"
        return cached
    return []

# =============================
# AI：不改动额度逻辑，仅手动触发
# =============================
def get_groq_key() -> str:
    try:
        return str(st.secrets.get("GROQ_API_KEY", "")).strip()
    except Exception:
        return ""


def call_ai(prompt: str, max_tokens: int = 900) -> str:
    key = get_groq_key()
    if not key or Groq is None:
        return "未配置 GROQ_API_KEY，已跳过 AI 解读。"
    try:
        client = Groq(api_key=key)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.35,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"AI 解读失败：{e}"

# =============================
# 图表
# =============================
def build_kline_fig(df: pd.DataFrame, title: str) -> go.Figure:
    d = add_indicators(df)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=d["date"], open=d["open"], high=d["high"], low=d["low"], close=d["close"], name="K线"))
    for col in ["ma5", "ma20", "ma60"]:
        fig.add_trace(go.Scatter(x=d["date"], y=d[col], mode="lines", name=col.upper()))
    fig.update_layout(title=title, xaxis_rangeslider_visible=False, height=520, margin=dict(l=20, r=20, t=45, b=20))
    return fig

# =============================
# 侧边栏
# =============================
with st.sidebar:
    st.header("⚙️ 数据策略")
    st.success("JQData：默认关闭，不参与核心链路")
    st.info("AKShare：本精简版不在关键按钮中调用，避免卡死")
    st.caption("实时：东方财富 → 新浪/腾讯；历史K：东方财富 → BaoStock；资金：东方财富真实字段 f62/f184")
    debug = st.checkbox("显示调试信息", value=False)
    st.markdown("---")
    st.caption(f"缓存目录：{CACHE_DIR}")
    if st.button("清理本地真实缓存"):
        for p in CACHE_DIR.rglob("*.json"):
            with contextlib.suppress(Exception):
                p.unlink()
        st.success("已清理本地缓存。Streamlit Cloud 历史日志无法由代码清空，只能减少后续输出。")

# =============================
# 页面主体
# =============================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🎯 个股解析",
    "🌍 宏观市场",
    "🔥 资金热点",
    "🐋 主力资金",
    "🦅 龙虎榜",
    "📰 新闻情报",
])

with tab1:
    st.subheader("🎯 个股解析")
    st.write("只查单只股票，不做全市场扫描。行情失败时只读最近一次真实缓存。")
    c1, c2 = st.columns([2, 1])
    with c1:
        symbol = st.text_input("股票代码", value="600519", max_chars=6)
    with c2:
        analyze = st.button("启动个股解析", type="primary", width="stretch")
    if analyze:
        symbol = normalize_symbol(symbol)
        start = time.time()
        quote = get_stock_quote(symbol)
        df = get_kline(symbol, days=220)
        st.caption(f"本次数据调用耗时：{time.time() - start:.2f}s")
        if not quote:
            st.error("未获取到该股票真实行情，也没有可用真实缓存。")
        else:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric(f"{quote.get('name', symbol)}", fmt_num(quote.get("price"), 2), fmt_num(quote.get("pct"), 2, "%"))
            m2.metric("总市值(亿)", fmt_num(quote.get("market_cap"), 1))
            m3.metric("动态PE", fmt_num(quote.get("pe"), 2))
            m4.metric("换手率", fmt_num(quote.get("turnover"), 2, "%"))
            st.caption(f"数据源：{quote.get('source')}｜行业：{quote.get('industry','-')}｜主力净流入：{fmt_num((quote.get('main_net') or 0)/1e4, 2)} 万｜主力净占比：{fmt_num(quote.get('main_ratio'), 2, '%')}")
            score = stock_score(quote, df)
            st.markdown(f"### 综合评分：{score['score']}/100｜{score['level']}")
            if score["reasons"]:
                st.write("；".join(score["reasons"]))
            if df is not None and len(df) >= 20:
                st.plotly_chart(build_kline_fig(df, f"{quote.get('name', symbol)} 日K"), width="stretch")
            else:
                st.warning("K线数据不足，已只展示实时行情。")
            if st.button("生成该股AI解读", key=f"ai_{symbol}"):
                prompt = f"请基于以下真实行情数据，对 {quote.get('name')}({symbol}) 做简洁交易分析：{json.dumps(quote, ensure_ascii=False)}，评分：{score}。要求给出观察点、风险点、适合的入场方式，不要编造不存在的数据。"
                st.markdown(call_ai(prompt))

with tab2:
    st.subheader("🌍 宏观市场实时看板")
    data = get_market_pulse()
    if not data:
        st.warning("指数实时接口暂不可用，且没有真实缓存。")
    else:
        cols = st.columns(min(len(data), 5))
        for i, item in enumerate(data):
            with cols[i % len(cols)]:
                st.metric(item["名称"], fmt_num(item.get("点位"), 2), fmt_num(item.get("涨跌幅%"), 2, "%"))
                st.caption(item.get("来源", ""))

with tab3:
    st.subheader("🔥 资金热点板块")
    st.write("基于东方财富 A 股 clist 真实字段聚合行业热点：f100 所属行业、f62 主力净流入、f3 涨跌幅、f6 成交额。")
    if st.button("扫描板块与生成配置推荐", type="primary"):
        start = time.time()
        blocks = get_hot_blocks()
        st.caption(f"本次扫描耗时：{time.time() - start:.2f}s")
        if blocks:
            dfb = pd.DataFrame(blocks)
            st.dataframe(dfb, width="stretch", hide_index=True)
            if st.button("生成热点AI解读"):
                top = dfb.head(8).to_dict("records")
                prompt = f"请根据以下真实聚合得到的热点板块数据，分析今日市场主线和可观察方向，不要编造未出现的数据：{json.dumps(top, ensure_ascii=False)}"
                st.markdown(call_ai(prompt))
        else:
            st.error("真实板块接口暂未返回结果，且没有可用真实缓存。")
            if debug:
                st.caption(st.session_state.get("last_hot_error", "无调试信息"))

with tab4:
    st.subheader("🐋 主力资金")
    st.write("只展示东方财富真实主力资金字段 f62/f184，不使用成交额×涨跌幅等估算。")
    limit = st.slider("显示数量", 10, 80, 40, 10)
    if st.button("启动主力追踪", type="primary"):
        start = time.time()
        rows = get_main_money(limit=limit)
        st.caption(f"本次扫描耗时：{time.time() - start:.2f}s")
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        else:
            st.error("真实主力资金暂不可用，且没有可用真实缓存。")
            if debug:
                st.caption(st.session_state.get("last_money_error", "无调试信息"))

with tab5:
    st.subheader("🦅 龙虎榜")
    st.info("精简稳定版暂未启用龙虎榜深度扫描，避免 AKShare/网页接口长时间阻塞。下一步可以单独接入东方财富 datacenter 接口。")

with tab6:
    st.subheader("📰 新闻情报")
    st.info("新闻列表和 AI 解读已解耦。当前精简版先保留 AI 手动输入，不让新闻接口影响主程序稳定。")
    news_text = st.text_area("粘贴你看到的新闻/公告/研报摘要，我来做分析", height=160)
    if st.button("生成新闻影响分析") and news_text.strip():
        st.markdown(call_ai(f"请分析以下新闻对A股市场、相关行业和个股的潜在影响，注意区分事实和推测：\n{news_text}"))
