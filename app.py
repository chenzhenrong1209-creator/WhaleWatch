import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import time

# --- 基础配置 ---
SIREN_CONTRACT = "0xD399c6dBe8D7D93616053303491E216B30C7B476"
# 你截图里那个巨鲸地址
DEFAULT_WALLETS = [
    "0xb2AF49dBF526054FAf19602860A5E298a79F3D05",
    "0x9f5D230F8152CB35372138805F99839352e0D7cE" # 这是另一个关联的做市地址，可以选填
]

# --- 页面设置 ---
st.set_page_config(page_title="DumpDetective Pro X | 巨鲸雷达", layout="wide")
st.title("🐋 DumpDetective Pro X - 链上巨鲸出货雷达")
st.markdown("*实时监控 BSC 链上 SIREN 代币的大额异动*")

# --- 侧边栏配置 ---
st.sidebar.header("📡 监控配置")
api_key = st.sidebar.text_input("1. 输入 BscScan API Key", type="password")
selected_wallet = st.sidebar.selectbox("2. 选择/输入监控地址", DEFAULT_WALLETS + ["手动输入"])
if selected_wallet == "手动输入":
    target_wallet = st.sidebar.text_input("请输入新的 0x 地址").strip().lower()
else:
    target_wallet = selected_wallet.lower()

refresh_rate = st.sidebar.slider("3. 刷新频率 (秒)", 15, 60, 30)

# 初始化 SessionState 用于保存历史交易
if 'tx_history' not in st.session_state:
    st.session_state['tx_history'] = pd.DataFrame(columns=[
        '时间', '行为', '数量 (SIREN)', '对手方', '对手方性质', '哈希'
    ])

# --- 核心逻辑 ---
def get_latest_token_tx(wallet, key):
    url = f"https://api.bscscan.com/api?module=account&action=tokentx&contractaddress={SIREN_CONTRACT}&address={wallet}&page=1&offset=20&sort=desc&apikey={key}"
    try:
        response = requests.get(url, timeout=10).json()
        if response["status"] == "1" and response["result"]:
            return response["result"]
    except:
        return []
    return []

# --- 主界面 UI ---
if st.sidebar.button("开始监控"):
    if not api_key:
        st.error("请先输入有效的 BscScan API Key")
    elif not target_wallet.startswith("0x"):
        st.error("请输入有效的以太坊/BSC 地址")
    else:
        st.info(f"正在启动监控: {target_wallet[:10]}... 设置已保存")
        time.sleep(1)
        st.experimental_rerun()

if api_key and target_wallet.startswith("0x"):
    # 创建布局
    col1, col2 = st.columns([1, 4])
    with col1:
        st.subheader("📊 今日统计")
        st.metric(label="当前余额 (SIREN)", value="1.11M") # 这里可以做成动态的，先放个静态数据
        st.write("---")
        st.write("对手方分布:")
        # 这里可以加个饼图
        
    with col2:
        st.subheader(f"🔄 最近交易流水 (目标: {target_wallet[:10]}...)")
        placeholder = st.empty()

    # 循环刷新 (由于Streamlit的机制，这里用一个巧妙的方法)
    while True:
        with placeholder.container():
            transactions = get_latest_token_tx(target_wallet, api_key)
            
            if transactions:
                # 处理数据
                temp_df = []
                for tx in transactions:
                    val = float(tx["value"]) / (10**int(tx["tokenDecimal"]))
                    time_str = datetime.fromtimestamp(int(tx["timeStamp"])).strftime('%Y-%m-%d %H:%M:%S')
                    is_out = tx["from"].lower() == target_wallet
                    
                    # 行为与高亮判定
                    if is_out:
                        action = "🔴 [出货/转出]"
                        peer = tx["to"]
                        peer_type = "DEX (做市)" # 可以通过合约反查来完善
                    else:
                        action = "🟢 [补仓/转入]"
                        peer = tx["from"]
                        peer_type = "CEX (充值)"
                    
                    hash_link = f"https://bscscan.com/tx/{tx['hash']}"
                    
                    temp_df.append({
                        '时间': time_str,
                        '行为': action,
                        '数量 (SIREN)': f"{val:,.2f}",
                        '对手方': f"{peer[:10]}...",
                        '对手方性质': peer_type,
                        '哈希': hash_link
                    })
                
                new_data = pd.DataFrame(temp_df)
                
                # 数据表格显示 (带颜色高亮)
                def color_rows(row):
                    if '🔴' in row['行为']:
                        return ['background-color: #ffcccc'] * len(row)
                    elif '🟢' in row['行为']:
                        return ['background-color: #ccffcc'] * len(row)
                    return [''] * len(row)
                
                styled_df = new_data.style.apply(color_rows, axis=1)
                
                # 将哈希变成可点击的链接
                st.dataframe(styled_df, use_container_width=True)
                
                st.caption(f"上次更新: {datetime.now().strftime('%H:%M:%S')}")
            else:
                st.warning("暂无交易记录，正在等待...")
            
            time.sleep(refresh_rate)
            st.experimental_rerun()
