import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import time

# --- 页面设置 ---
st.set_page_config(page_title="DumpDetective Pro X | 精准雷达", layout="wide")
st.title("🐋 DumpDetective Pro X - 巨鲸雷达 (手动精准版)")

# --- 侧边栏配置 ---
st.sidebar.header("📡 监控配置")
api_key = st.sidebar.text_input("1. 输入 BscScan API Key", type="password")

st.sidebar.markdown("---")
st.sidebar.subheader("💎 目标代币 (Token)")
# 允许手动输入，默认留空或填一个参考值
token_contract = st.sidebar.text_input("输入正确的代币合约地址 (0x...)", placeholder="请从 Arkham 复制正确合约粘贴在此").strip().lower()

st.sidebar.markdown("---")
st.sidebar.subheader("👤 监控钱包 (Whale)")
target_wallet = st.sidebar.text_input("输入要监控的巨鲸钱包地址 (0x...)", placeholder="0xb2AF...").strip().lower()

st.sidebar.markdown("---")
record_limit = st.sidebar.select_slider("检索历史深度 (笔数)", options=[50, 100, 200, 500, 1000], value=100)
refresh_rate = st.sidebar.slider("自动刷新频率 (秒)", 10, 60, 30)

# --- 核心数据获取逻辑 ---
def get_token_tx(wallet, token, key, limit):
    # 核心 API：获取特定钱包、特定代币的 BEP-20 转账记录
    url = f"https://api.bscscan.com/api?module=account&action=tokentx&contractaddress={token}&address={wallet}&page=1&offset={limit}&sort=desc&apikey={key}"
    try:
        r = requests.get(url, timeout=10).json()
        if r["status"] == "1" and r["result"]:
            return r["result"]
    except Exception as e:
        st.error(f"API 请求失败: {e}")
    return []

# --- 主界面 UI ---
if st.sidebar.button("🚀 开始精准同步"):
    if not api_key or not token_contract or not target_wallet:
        st.error("请完整填写 API Key、代币地址和钱包地址")
    else:
        st.rerun() # 修复日志中的 experimental_rerun 报错

if api_key and target_wallet.startswith("0x") and token_contract.startswith("0x"):
    st.info(f"🛰️ 正在精准扫描 \n\n 代币: `{token_contract}` \n\n 目标: `{target_wallet}`")
    
    placeholder = st.empty()

    while True:
        with placeholder.container():
            txs = get_token_tx(target_wallet, token_contract, api_key, record_limit)
            
            if txs:
                data_list = []
                for tx in txs:
                    # 自动根据代币精度计算数量
                    val = float(tx["value"]) / (10**int(tx["tokenDecimal"]))
                    time_str = datetime.fromtimestamp(int(tx["timeStamp"])).strftime('%Y-%m-%d %H:%M:%S')
                    is_out = tx["from"].lower() == target_wallet
                    
                    data_list.append({
                        '时间': time_str,
                        '方向': "🔴 卖出/转出" if is_out else "🟢 买入/转入",
                        '数量': f"{val:,.2f} {tx['tokenSymbol']}",
                        '交易对手': tx["to"] if is_out else tx["from"],
                        '链上哈希': f"https://bscscan.com/tx/{tx['hash']}"
                    })
                
                df = pd.DataFrame(data_list)

                # 样式美化：红色代表卖出，绿色代表买入
                def style_action(val):
                    color = '#ff4b4b' if '🔴' in val else '#28a745'
                    return f'color: {color}; font-weight: bold'

                st.dataframe(
                    df.style.applymap(style_action, subset=['方向']),
                    use_container_width=True,
                    column_config={
                        "链上哈希": st.column_config.LinkColumn("查看详情", display_text="BscScan")
                    }
                )
                st.caption(f"✅ 成功提取 {len(txs)} 笔历史记录 | 刷新倒计时: {refresh_rate}s")
            else:
                st.warning("⚠️ 依然没查到记录？")
                st.write("请对照 Arkham 检查：\n1. 确保代币地址是 **BSC 链** 的合约（Arkham 有时会显示以太坊链的记录）。\n2. 确保这个巨鲸是在 **PancakeSwap** 等 DEX 进行的转账，而不是直接在交易所内部划转。")
            
            time.sleep(refresh_rate)
            st.rerun() # 确保最新版 Streamlit 不报错
