import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# --- 页面设置 ---
st.set_page_config(page_title="Arkham-Style 智能搜索", layout="wide")
st.title("🔍 钱包全资产历史轨迹查询")
st.markdown("输入钱包地址，直接穿透区块数据库，还原 Arkham 式的交易列表。")

# --- 侧边栏：搜索中心 ---
st.sidebar.header("🎯 搜索配置")

# 网络切换：Arkham 的核心是多链，这里提供最常用的两个切换
network = st.sidebar.selectbox(
    "1. 选择区块链网络", 
    ["Ethereum (以太坊)", "BSC (币安链)"],
    help="请根据 Arkham 上显示的图标选择。灰色钻石选以太坊，黄色方块选 BSC。"
)

# API Key 配置
api_key = st.sidebar.text_input(f"2. 输入 {network.split(' ')[0]} API Key", type="password")

# 目标地址
target_address = st.sidebar.text_input("3. 粘贴目标钱包地址 (0x...)", placeholder="在此输入地址...").strip().lower()

# 深度选择
limit = st.sidebar.select_slider("4. 检索深度", options=[100, 300, 500, 1000], value=200)

# --- 核心查询引擎 ---
def fetch_wallet_history(address, key, net, count):
    # 根据网络选择接口端点
    base_url = "https://api.etherscan.io/api" if "Eth" in net else "https://api.bscscan.com/api"
    
    # Arkham 逻辑：查询该地址所有的 ERC-20 (或 BEP-20) 转账
    params = {
        "module": "account",
        "action": "tokentx",
        "address": address,
        "page": 1,
        "offset": count,
        "sort": "desc",
        "apikey": key
    }
    
    try:
        response = requests.get(base_url, params=params, timeout=20).json()
        if response.get("status") == "1":
            return response.get("result", [])
        return []
    except Exception as e:
        st.error(f"连接数据库失败: {e}")
        return []

# --- 主界面逻辑 ---
if st.sidebar.button("🚀 开启深度搜索") or (target_address and api_key):
    if not target_address.startswith("0x"):
        st.info("💡 请在左侧输入正确的钱包地址并确保 API Key 已填入。")
    else:
        with st.spinner(f"正在调取 {network} 历史数据..."):
            raw_data = fetch_wallet_history(target_address, api_key, network, limit)
            
            if raw_data:
                st.success(f"成功还原最近 {len(raw_data)} 笔代币变动记录")
                
                # 格式化数据
                display_list = []
                for tx in raw_data:
                    # 数量精度换算
                    decimals = int(tx.get("tokenDecimal", 18))
                    value = float(tx["value"]) / (10**decimals)
                    
                    # 时间转换
                    dt = datetime.fromtimestamp(int(tx["timeStamp"])).strftime('%Y-%m-%d %H:%M')
                    
                    # 进出判断
                    direction = "🔴 卖出/转出" if tx["from"].lower() == target_address.lower() else "🟢 买入/转入"
                    
                    display_list.append({
                        "交易时间": dt,
                        "代币资产": f"{tx['tokenName']} ({tx['tokenSymbol']})",
                        "行为": direction,
                        "数量": f"{value:,.2f}",
                        "交易对手": tx["to"] if "🔴" in direction else tx["from"],
                        "区块链接": f"https://{'etherscan.io' if 'Eth' in network else 'bscscan.com'}/tx/{tx['hash']}"
                    })
                
                df = pd.DataFrame(display_list)
                
                # 渲染表格
                st.dataframe(
                    df.style.applymap(
                        lambda x: 'color: #ff4b4b; font-weight: bold' if '🔴' in str(x) else 'color: #28a745; font-weight: bold' if '🟢' in str(x) else '',
                        subset=['行为']
                    ),
                    use_container_width=True,
                    column_config={
                        "区块链接": st.column_config.LinkColumn("查看详情", display_text="链上凭证")
                    }
                )
            else:
                st.warning("未发现匹配记录。")
                st.info("💡 请确认：\n1. 网络是否选对（以太坊 vs BSC）？\n2. API Key 是否对应当前网络？\n3. 地址是否正确？")

else:
    st.info("👋 欢迎使用。请在左侧配置搜索参数。")
