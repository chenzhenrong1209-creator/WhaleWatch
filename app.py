import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# --- 页面基础设置 ---
st.set_page_config(page_title="Arkham Pro 智能追踪", layout="wide")
st.title("🐋 巨鲸资产穿透 (Secrets 自动登录版)")

# --- 核心：安全读取 API Key ---
# 自动从 Streamlit 后台的 Secrets 中读取，无需手动输入
ETH_KEY = st.secrets.get("ETH_API_KEY", "")
BSC_KEY = st.secrets.get("BSC_API_KEY", "")

# --- 侧边栏：功能配置 ---
st.sidebar.header("🎯 追踪配置")

# 1. 切换网络 (Arkham 截图里显示 SIREN 在以太坊更火，但现在 BSC 也要防)
network = st.sidebar.selectbox(
    "选择区块链网络", 
    ["Ethereum (以太坊)", "BSC (币安链)"],
    help="根据代币所在的链选择。SIREN 大户通常在以太坊。"
)

# 2. 自动匹配当前需要的 Key
current_key = ETH_KEY if "Eth" in network else BSC_KEY

# 如果后台没配置，则显示警告
if not current_key:
    st.sidebar.error(f"❌ 未检测到 {network} 的 Secrets 配置")
    current_key = st.sidebar.text_input("手动输入临时 API Key", type="password")

# 3. 输入巨鲸地址
target_addr = st.sidebar.text_input("粘贴钱包地址 (0x...)", placeholder="输入地址回车开始扫描").strip().lower()

# 4. 检索深度
limit = st.sidebar.select_slider("检索记录深度", options=[100, 200, 300, 500], value=200)

# --- 核心查询函数 ---
def fetch_whale_movements(addr, key, net, count):
    # 根据网络切换 API 终点
    base_url = "https://api.etherscan.io/api" if "Eth" in net else "https://api.bscscan.com/api"
    
    params = {
        "module": "account",
        "action": "tokentx",  # 关键：查询代币转账流水
        "address": addr,
        "page": 1,
        "offset": count,
        "sort": "desc",
        "apikey": key
    }
    
    try:
        response = requests.get(base_url, params=params, timeout=15).json()
        return response
    except Exception as e:
        return {"status": "0", "result": str(e)}

# --- 逻辑执行与展示 ---
if target_addr:
    if not current_key:
        st.warning("⚠️ 请先在后台配置 API Key 或在左侧手动输入。")
    else:
        with st.spinner(f"正在穿透 {network} 实时数据..."):
            res = fetch_whale_movements(target_addr, current_key, network, limit)
            
            if res.get("status") == "1":
                data = res.get("result", [])
                st.success(f"✅ 监控中：发现 {len(data)} 笔代币变动")
                
                # 格式化展示数据
                rows = []
                for tx in data:
                    dec = int(tx.get("tokenDecimal", 18))
                    val = float(tx["value"]) / (10**dec)
                    time_s = datetime.fromtimestamp(int(tx["timeStamp"])).strftime('%Y-%m-%d %H:%M')
                    is_out = tx["from"].lower() == target_addr.lower()
                    
                    rows.append({
                        "时间": time_s,
                        "资产": f"{tx['tokenSymbol']}",
                        "方向": "🔴 卖出/出货" if is_out else "🟢 买入/进货",
                        "数量": f"{val:,.2f}",
                        "代币全名": tx['tokenName'],
                        "区块链接": f"https://{'etherscan.io' if 'Eth' in network else 'bscscan.com'}/tx/{tx['hash']}"
                    })
                
                df = pd.DataFrame(rows)
                
                # 美化表格样式
                st.dataframe(
                    df.style.applymap(
                        lambda x: 'color: #ff4b4b; font-weight: bold' if '🔴' in str(x) else 'color: #28a745; font-weight: bold' if '🟢' in str(x) else '',
                        subset=['方向']
                    ),
                    use_container_width=True,
                    column_config={"区块链接": st.column_config.LinkColumn("查看", display_text="Open")}
                )
            else:
                msg = res.get("result", "未找到数据")
                st.error(f"❌ 检索失败：{msg}")
                st.info("💡 建议排查：\n1. 确认 API Key 是否属于当前链。\n2. 确认该地址是否在另一条链活跃。")
else:
    st.info("👋 欢迎回来！在左侧填入地址，即可全自动追踪巨鲸动向。")
