import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# --- 页面设置 ---
st.set_page_config(page_title="DumpDetective V3 | 深度穿透", layout="wide")
st.title("🐋 跨链钱包行为穿透工具 (诊断强化版)")

# --- 侧边栏 ---
st.sidebar.header("🛠️ 核心参数")

# 1. 强制选择网络 - 截图显示 SIREN 在 Ethereum 交易更活跃
network_choice = st.sidebar.selectbox(
    "1. 确认监控网络 (核心步骤)", 
    ["Ethereum (以太坊主网)", "BSC (币安链)"],
    help="Arkham 里的灰色图标选以太坊，黄色图标选 BSC。"
)

# 2. 对应网络的 API Key
api_key = st.sidebar.text_input(f"2. 输入 {network_choice.split(' ')[0]} API Key", type="password")

# 3. 目标钱包地址
target_addr = st.sidebar.text_input("3. 粘贴钱包地址 (0x...)", placeholder="在此输入地址").strip().lower()

# 4. 修复之前报错的参数设置
limit = st.sidebar.select_slider("4. 扫描记录深度", options=[100, 200, 300, 500, 1000], value=200)

st.sidebar.markdown("---")
st.sidebar.info("💡 提示：如果查不到，请检查你的 API Key 是否与网络匹配（Etherscan 还是 BscScan）。")

# --- 核心逻辑 ---
def get_data(addr, key, net, count):
    # 根据网络切换 API
    base_url = "https://api.etherscan.io/api" if "Eth" in net else "https://api.bscscan.com/api"
    
    params = {
        "module": "account",
        "action": "tokentx",
        "address": addr,
        "page": 1,
        "offset": count,
        "sort": "desc",
        "apikey": key
    }
    
    try:
        r = requests.get(base_url, params=params, timeout=15).json()
        return r
    except Exception as e:
        return {"status": "0", "message": str(e)}

# --- 主界面显示 ---
if st.sidebar.button("🔍 立即穿透数据") or (target_addr and api_key):
    if not target_addr.startswith("0x"):
        st.warning("⚠️ 请输入有效的 0x 钱包地址。")
    else:
        with st.spinner(f"正在穿透 {network_choice} 区块数据..."):
            response = get_data(target_addr, api_key, network_choice, limit)
            
            # 状态诊断逻辑
            if response.get("status") == "1":
                results = response.get("result", [])
                st.success(f"✅ 成功调取 {len(results)} 笔代币历史记录")
                
                # 数据转化
                rows = []
                for tx in results:
                    dec = int(tx.get("tokenDecimal", 18))
                    val = float(tx["value"]) / (10**dec)
                    time_str = datetime.fromtimestamp(int(tx["timeStamp"])).strftime('%Y-%m-%d %H:%M')
                    is_out = tx["from"].lower() == target_addr.lower()
                    
                    rows.append({
                        "时间": time_str,
                        "资产": f"{tx['tokenSymbol']}",
                        "动作": "🔴 卖出/转出" if is_out else "🟢 买入/补仓",
                        "数量": f"{val:,.2f}",
                        "代币全名": tx['tokenName'],
                        "哈希": f"https://{'etherscan.io' if 'Eth' in network_choice else 'bscscan.com'}/tx/{tx['hash']}"
                    })
                
                df = pd.DataFrame(rows)
                
                # 美化展示
                st.dataframe(
                    df.style.applymap(lambda x: 'color: #ff4b4b; font-weight: bold' if '🔴' in str(x) else 'color: #28a745; font-weight: bold' if '🟢' in str(x) else '', subset=['动作']),
                    use_container_width=True,
                    column_config={"哈希": st.column_config.LinkColumn("查看详情", display_text="链上凭证")}
                )
            else:
                # 错误诊断：当 API 返回 0 时
                error_msg = response.get("message", "未知错误")
                st.error(f"❌ 搜索未果：API 返回了错误信息 - '{error_msg}'")
                
                if "api-key" in error_msg.lower():
                    st.info("💡 诊断建议：你的 API Key 似乎无效，请重新检查 Key 是否属于当前选择的网络。")
                elif "no transactions found" in error_msg.lower():
                    st.info(f"💡 诊断建议：该地址在 {network_choice} 上确实没有任何代币交易。请去 Arkham 确认他是在哪条链上动的（看图标颜色）。")
