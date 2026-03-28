import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import time

# --- 基础配置 ---
SIREN_CONTRACT = "0xD399c6dBe8D7D93616053303491E216B30C7B476"
DEFAULT_WALLETS = [
    "0xb2AF49dBF526054FAf19602860A5E298a79F3D05",
    "0x9f5D230F8152CB35372138805F99839352e0D7cE"
]

# --- 页面设置 ---
st.set_page_config(page_title="DumpDetective Pro X | 历史追踪", layout="wide")
st.title("🐋 DumpDetective Pro X - 巨鲸历史行为追踪")

# --- 侧边栏配置 ---
st.sidebar.header("📡 监控配置")
api_key = st.sidebar.text_input("1. 输入 BscScan API Key", type="password")
selected_wallet = st.sidebar.selectbox("2. 选择监控地址", DEFAULT_WALLETS + ["手动输入"])

if selected_wallet == "手动输入":
    target_wallet = st.sidebar.text_input("手动输入地址").strip().lower()
else:
    target_wallet = selected_wallet.lower()

# 历史深度调节，为了看到之前的记录，建议选 100 或 200
record_limit = st.sidebar.select_slider("3. 检索历史深度 (笔数)", options=[20, 50, 100, 200, 500], value=100)
refresh_rate = st.sidebar.slider("4. 自动刷新频率 (秒)", 15, 60, 30)

# --- 核心逻辑 ---
def get_token_tx_history(wallet, key, limit):
    # 增加 offset 以获取更多历史记录
    url = f"https://api.bscscan.com/api?module=account&action=tokentx&contractaddress={SIREN_CONTRACT}&address={wallet}&page=1&offset={limit}&sort=desc&apikey={key}"
    try:
        response = requests.get(url, timeout=10).json()
        if response["status"] == "1" and response["result"]:
            return response["result"]
    except Exception as e:
        st.error(f"API 请求失败: {e}")
        return []
    return []

# --- 主界面 UI ---
if st.sidebar.button("开始同步数据"):
    if not api_key:
        st.error("请输入 API Key")
    else:
        # 已彻底移除 experimental_ 前缀，规避日志报错
        st.rerun()

if api_key and target_wallet.startswith("0x"):
    st.subheader(f"🔄 正在显示 {target_wallet[:10]}... 的最近 {record_limit} 笔交易记录")
    placeholder = st.empty()

    while True:
        with placeholder.container():
            transactions = get_token_tx_history(target_wallet, api_key, record_limit)
            
            if transactions:
                data_list = []
                for tx in transactions:
                    val = float(tx["value"]) / (10**int(tx["tokenDecimal"]))
                    # 转换时间戳
                    dt_object = datetime.fromtimestamp(int(tx["timeStamp"]))
                    time_str = dt_object.strftime('%Y-%m-%d %H:%M')
                    
                    is_out = tx["from"].lower() == target_wallet
                    
                    data_list.append({
                        '时间': time_str,
                        '行为': "🔴 转出 (卖出/减仓)" if is_out else "🟢 转入 (买入/增仓)",
                        '数量 (SIREN)': round(val, 2),
                        '对手方': tx["to"] if is_out else tx["from"],
                        '交易详情': f"https://bscscan.com/tx/{tx['hash']}"
                    })
                
                df = pd.DataFrame(data_list)
                
                # 行为列颜色高亮
                def color_action(val):
                    color = '#ff4b4b' if '🔴' in val else '#28a745'
                    return f'color: {color}; font-weight: bold'

                # 使用最新的 st.dataframe 展示
                st.dataframe(
                    df.style.applymap(color_action, subset=['行为']),
                    use_container_width=True,
                    column_config={
                        "交易详情": st.column_config.LinkColumn("查看哈希", display_text="点击跳转 BscScan")
                    }
                )
                st.caption(f"✅ 数据同步成功。当前显示深度：{len(transactions)} 笔 | 刷新倒计时: {refresh_rate}s")
            else:
                st.warning("在此历史深度下未发现该代币的交易记录。建议在侧边栏调大‘检索历史深度’再试。")
            
            # 等待刷新
            time.sleep(refresh_rate)
            # 已彻底移除 experimental_ 前缀，规避日志报错
            st.rerun()
