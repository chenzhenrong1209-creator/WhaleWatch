import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import time

# --- 页面设置 ---
st.set_page_config(page_title="DumpDetective Pro X | 多链雷达", layout="wide")
st.title("🐋 DumpDetective Pro X - 跨链巨鲸追踪器")

# --- 侧边栏配置 ---
st.sidebar.header("📡 核心配置")

# 1. 关键点：增加网络选择
network = st.sidebar.selectbox("1. 选择监控网络 (对照 Arkham 图标)", ["Ethereum (以太坊)", "BSC (币安链)"])
api_key = st.sidebar.text_input(f"2. 输入 {network.split(' ')[0]} API Key", type="password")

# 根据网络配置 API 终点
if "Ethereum" in network:
    api_url = "https://api.etherscan.io/api"
else:
    api_url = "https://api.bscscan.com/api"

st.sidebar.markdown("---")
token_contract = st.sidebar.text_input("3. 代币合约地址 (从 Arkham 复制)", placeholder="0x...").strip().lower()
target_wallet = st.sidebar.text_input("4. 巨鲸钱包地址", placeholder="0x...").strip().lower()

st.sidebar.markdown("---")
record_limit = st.sidebar.select_slider("检索历史深度", options=[50, 100, 200, 500], value=100)
refresh_rate = st.sidebar.slider("刷新频率 (秒)", 10, 60, 30)

# --- 核心数据获取逻辑 ---
def get_token_tx(wallet, token, key, limit, base_url):
    url = f"{base_url}?module=account&action=tokentx&contractaddress={token}&address={wallet}&page=1&offset={limit}&sort=desc&apikey={key}"
    try:
        r = requests.get(url, timeout=10).json()
        if r["status"] == "1" and r["result"]:
            return r["result"]
    except Exception as e:
        st.error(f"API 请求异常: {e}")
    return []

# --- 主界面 ---
if st.sidebar.button("🚀 开启跨链追踪"):
    if not api_key or not token_contract or not target_wallet:
        st.error("配置不完整，请检查 API Key 和地址")
    else:
        st.rerun()

if api_key and target_wallet.startswith("0x") and token_contract.startswith("0x"):
    st.subheader(f"🌐 当前网络: {network}")
    st.info(f"正在扫描: {token_contract[:15]}...")
    
    placeholder = st.empty()

    while True:
        with placeholder.container():
            txs = get_token_tx(target_wallet, token_contract, api_key, record_limit, api_url)
            
            if txs:
                data_list = []
                for tx in txs:
                    val = float(tx["value"]) / (10**int(tx["tokenDecimal"]))
                    time_str = datetime.fromtimestamp(int(tx["timeStamp"])).strftime('%Y-%m-%d %H:%M')
                    is_out = tx["from"].lower() == target_wallet
                    
                    data_list.append({
                        '时间': time_str,
                        '动作': "🔴 转出/卖出" if is_out else "🟢 转入/补仓",
                        '数量': f"{val:,.2f} {tx['tokenSymbol']}",
                        '对手方': tx["to"] if is_out else tx["from"],
                        '哈希': f"https://{'etherscan.io' if 'Eth' in network else 'bscscan.com'}/tx/{tx['hash']}"
                    })
                
                df = pd.DataFrame(data_list)
                st.dataframe(df.style.applymap(lambda x: 'color: #ff4b4b' if '🔴' in str(x) else 'color: #28a745' if '🟢' in str(x) else '', subset=['动作']), use_container_width=True)
                st.caption(f"✅ 数据已更新 | 网络: {network} | 笔数: {len(txs)}")
            else:
                st.warning(f"⚠️ 在 {network} 网络上未发现交易。")
                st.write("💡 **请检查：** 你在 Arkham 看到的交易图标是灰色的（ETH）还是黄色的（BSC）？如果是灰色的，请确保侧边栏选择了 Ethereum 并使用了 Etherscan 的 Key。")
            
            time.sleep(refresh_rate)
            st.rerun()
