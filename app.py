import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# --- 页面基础设置 ---
st.set_page_config(page_title="Arkham-Style 历史查询", layout="wide")
st.title("🔍 钱包历史行为全扫描 (Arkham 逻辑)")

# --- 侧边栏：搜索入口 ---
st.sidebar.header("🔎 搜索配置")

# 网络选择（Arkham 截图里显示的是以太坊，请务必选对）
network = st.sidebar.selectbox(
    "1. 选择区块链网络", 
    ["Ethereum (以太坊)", "BSC (币安链)"]
)

# API Key 配置
api_key = st.sidebar.text_input(f"2. 输入 {network.split(' ')[0]} API Key", type="password")

# 目标钱包
target_address = st.sidebar.text_input("3. 粘贴要查询的钱包地址 (0x...)", placeholder="输入地址后回车").strip().lower()

# 查询深度
limit = st.sidebar.select_slider("4. 查询历史深度", options=[100, 200, 500, 1000], value=200)

# --- 核心查询函数 ---
def get_arkham_style_data(wallet, key, net, count):
    # 根据网络选择接口
    if "Eth" in net:
        base_url = "https://api.etherscan.io/api"
    else:
        base_url = "https://api.bscscan.com/api"
    
    # 核心逻辑：不带 contractaddress，直接查整个钱包的代币流水
    params = {
        "module": "account",
        "action": "tokentx",
        "address": wallet,
        "page": 1,
        "offset": count,
        "sort": "desc",
        "apikey": key
    }
    
    try:
        r = requests.get(base_url, params=params, timeout=20).json()
        return r.get("result", []) if r.get("status") == "1" else []
    except Exception as e:
        st.error(f"连接失败: {e}")
        return []

# --- 界面展示 ---
if st.sidebar.button("🚀 立即搜索历史记录") or target_address:
    if not api_key:
        st.warning("👈 请在左侧输入 API Key 后开始。")
    elif not target_address.startswith("0x"):
        st.error("请输入正确的 0x 钱包地址。")
    else:
        with st.spinner(f"正在像 Arkham 一样穿透 {network} 区块数据..."):
            raw_data = get_arkham_style_data(target_address, api_key, network, limit)
            
            if raw_data:
                st.success(f"找到最近 {len(raw_data)} 笔代币交易记录")
                
                # 处理数据
                processed_list = []
                for tx in raw_data:
                    # 计算真实数量
                    decimals = int(tx.get("tokenDecimal", 18))
                    val = float(tx["value"]) / (10**decimals)
                    
                    # 时间转换
                    time_stamp = datetime.fromtimestamp(int(tx["timeStamp"])).strftime('%Y-%m-%d %H:%M')
                    
                    # 判断进出
                    is_out = tx["from"].lower() == target_address.lower()
                    
                    processed_list.append({
                        "时间": time_stamp,
                        "代币": f"{tx['tokenName']} ({tx['tokenSymbol']})",
                        "动作": "🔴 转出 (卖出/发送)" if is_out else "🟢 转入 (买入/接收)",
                        "数量": f"{val:,.2f}",
                        "交易对手": tx["to"] if is_out else tx["from"],
                        "查看哈希": f"https://{'etherscan.io' if 'Eth' in network else 'bscscan.com'}/tx/{tx['hash']}"
                    })
                
                df = pd.DataFrame(processed_list)
                
                # 使用 Streamlit 最强的数据渲染组件
                st.dataframe(
                    df.style.applymap(
                        lambda x: 'color: #ff4b4b; font-weight: bold' if '🔴' in str(x) else 'color: #28a745; font-weight: bold' if '🟢' in str(x) else '',
                        subset=['动作']
                    ),
                    use_container_width=True,
                    column_config={
                        "查看哈希": st.column_config.LinkColumn("区块详情", display_text="Open BscScan/EthScan")
                    }
                )
            else:
                st.info("查询完成：该地址在这个链上没有任何代币转账记录，或者 API Key 不正确。")
                st.write("💡 提示：如果你查不到 Arkham 里的 SIREN，请在左侧切换【以太坊】或【币安链】后再试。")
