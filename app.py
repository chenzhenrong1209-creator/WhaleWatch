import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# --- 页面基础设置 ---
st.set_page_config(page_title="DumpDetective | 历史记录查询", layout="wide")
st.title("🐋 巨鲸历史交易流水查询器")
st.markdown("不用实时监控，直接调取 BscScan/Etherscan 数据库中的所有历史记录。")

# --- 侧边栏配置 ---
st.sidebar.header("⚙️ 第一步：基础配置")

# 关键：根据 Arkham 上的图标选择网络
network = st.sidebar.selectbox(
    "1. 选择对应的区块链网络", 
    ["Ethereum (以太坊主网)", "BSC (币安智能链)"],
    help="Arkham 里的灰色图标选以太坊，黄色图标选 BSC"
)

api_key = st.sidebar.text_input(f"2. 输入 {network.split(' ')[0]} 的 API Key", type="password")

st.sidebar.markdown("---")
st.sidebar.header("🔍 第二步：目标设置")

# 允许手动输入，确保地址 100% 准确
token_addr = st.sidebar.text_input("代币合约地址 (Token Contract)", placeholder="从 Arkham 复制 0x...").strip().lower()
whale_addr = st.sidebar.text_input("巨鲸钱包地址 (Whale Wallet)", placeholder="从 Arkham 复制 0x...").strip().lower()

# 增加查询深度
limit = st.sidebar.slider("查询最近多少笔记录？", 50, 500, 100)

# --- 数据拉取逻辑 ---
def fetch_history(net, key, t_addr, w_addr, count):
    # 根据网络选择接口地址
    base_url = "https://api.etherscan.io/api" if "Ethereum" in net else "https://api.bscscan.com/api"
    
    params = {
        "module": "account",
        "action": "tokentx",
        "contractaddress": t_addr,
        "address": w_addr,
        "page": 1,
        "offset": count,
        "sort": "desc",
        "apikey": key
    }
    
    try:
        r = requests.get(base_url, params=params, timeout=15).json()
        if r["status"] == "1":
            return r["result"]
        else:
            st.warning(f"接口提示: {r['message']} (通常是因为该地址下无记录)")
            return []
    except Exception as e:
        st.error(f"网络连接失败: {e}")
        return []

# --- 主界面逻辑 ---
if st.sidebar.button("📊 立即拉取历史数据"):
    if not (api_key and token_addr and whale_addr):
        st.error("请把 API Key、代币地址和钱包地址填全了再查。")
    else:
        with st.spinner("正在穿透区块数据..."):
            results = fetch_history(network, api_key, token_addr, whale_addr, limit)
            
            if results:
                st.success(f"成功找到 {len(results)} 笔历史交易")
                
                # 数据处理
                df_data = []
                for tx in results:
                    val = float(tx["value"]) / (10**int(tx["tokenDecimal"]))
                    time_str = datetime.fromtimestamp(int(tx["timeStamp"])).strftime('%Y-%m-%d %H:%M:%S')
                    is_out = tx["from"].lower() == whale_addr.lower()
                    
                    df_data.append({
                        "时间": time_str,
                        "方向": "🔴 卖出/转出" if is_out else "🟢 买入/转入",
                        "数量": f"{val:,.2f} {tx['tokenSymbol']}",
                        "交易对手": tx["to"] if is_out else tx["from"],
                        "查看详情": f"https://{'etherscan.io' if 'Eth' in network else 'bscscan.com'}/tx/{tx['hash']}"
                    })
                
                df = pd.DataFrame(df_data)
                
                # 结果展示
                st.dataframe(
                    df.style.applymap(lambda x: 'color: #ff4b4b; font-weight: bold' if '🔴' in str(x) else 'color: #28a745; font-weight: bold' if '🟢' in str(x) else '', subset=['方向']),
                    use_container_width=True,
                    column_config={"查看详情": st.column_config.LinkColumn("区块浏览器", display_text="点击跳转")}
                )
            else:
                st.error("❌ 查询失败：数据库中未找到任何匹配记录。")
                st.info("💡 建议排查：你确信这是 BSC 链吗？Arkham 里的 SIREN 很多是在 Ethereum 主网的，请尝试切换网络并使用 Etherscan 的 Key。")

# 初始提示
if not (api_key and token_addr and whale_addr):
    st.write("---")
    st.write("👈 请在左侧输入信息后点击按钮。")
