import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import time

# --- 页面设置 ---
st.set_page_config(page_title="DumpDetective Pro X | 自定义雷达", layout="wide")
st.title("🐋 DumpDetective Pro X - 链上巨鲸出货雷达")
st.markdown("*手动输入代币与钱包地址，精准追踪链上异动*")

# --- 侧边栏配置 ---
st.sidebar.header("📡 监控配置")
api_key = st.sidebar.text_input("1. 输入 BscScan API Key", type="password")

st.sidebar.markdown("---")
st.sidebar.subheader("💎 目标代币")
# 默认放一个可能的地址，但你可以直接在网页上修改它
default_token = "0xD399c6dBe8D7D93616053303491E216B30C7B476" 
token_contract = st.sidebar.text_input("代币合约地址 (Contract)", value=default_token).strip().lower()

st.sidebar.markdown("---")
st.sidebar.subheader("👤 监控钱包")
default_wallet = "0xb2AF49dBF526054FAf19602860A5E298a79F3D05"
target_wallet = st.sidebar.text_input("巨鲸钱包地址", value=default_wallet).strip().lower()

st.sidebar.markdown("---")
record_limit = st.sidebar.select_slider("检索历史深度 (笔数)", options=[20, 50, 100, 200, 500], value=100)
refresh_rate = st.sidebar.slider("自动刷新频率 (秒)", 10, 60, 30)

# --- 核心数据获取逻辑 ---
def get_token_tx(wallet, token, key, limit):
    # 使用 BscScan 的 tokentx 接口查询
    url = f"https://api.bscscan.com/api?module=account&action=tokentx&contractaddress={token}&address={wallet}&page=1&offset={limit}&sort=desc&apikey={key}"
    try:
        r = requests.get(url, timeout=10).json()
        if r["status"] == "1" and r["result"]:
            return r["result"]
    except Exception as e:
        st.error(f"连接 API 失败: {e}")
    return []

# --- 主界面 UI ---
if st.sidebar.button("🚀 开始同步"):
    if not api_key:
        st.error("请先输入 API Key")
    else:
        st.rerun() # 彻底移除 experimental_ 前缀，解决日志中的崩溃问题

if api_key and target_wallet.startswith("0x") and token_contract.startswith("0x"):
    st.info(f"🛰️ 正在扫描代币: `{token_contract}` \n\n🎯 监控目标: `{target_wallet}`")
    
    placeholder = st.empty()

    while True:
        with placeholder.container():
            txs = get_token_tx(target_wallet, token_contract, api_key, record_limit)
            
            if txs:
                data_list = []
                for tx in txs:
                    val = float(tx["value"]) / (10**int(tx["tokenDecimal"]))
                    time_str = datetime.fromtimestamp(int(tx["timeStamp"])).strftime('%Y-%m-%d %H:%M:%S')
                    is_out = tx["from"].lower() == target_wallet
                    
                    data_list.append({
                        '时间': time_str,
                        '动作': "🔴 卖出/转出" if is_out else "🟢 买入/转入",
                        '数量': f"{val:,.2f} {tx['tokenSymbol']}",
                        '对手方': tx["to"] if is_out else tx["from"],
                        '哈希': f"https://bscscan.com/tx/{tx['hash']}"
                    })
                
                df = pd.DataFrame(data_list)

                # 样式美化
                def style_action(val):
                    color = '#ff4b4b' if '🔴' in val else '#28a745'
                    return f'color: {color}; font-weight: bold'

                st.dataframe(
                    df.style.applymap(style_action, subset=['动作']),
                    use_container_width=True,
                    column_config={
                        "哈希": st.column_config.LinkColumn("BscScan 详情", display_text="点击跳转")
                    }
                )
                st.caption(f"✅ 成功获取 {len(txs)} 笔记录 | 下次更新: {refresh_rate}秒后")
            else:
                st.warning("⚠️ 未在该地址下发现对应代币的交易记录。")
                st.write("💡 请检查：1. 代币合约地址是否正确；2. BscScan API Key 是否有效。")
            
            time.sleep(refresh_rate)
            st.rerun() # 保持最新语法，规避报错
