import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import time

# --- 页面设置 ---
st.set_page_config(page_title="DumpDetective Pro X | 巨鲸雷达", layout="wide")
st.title("🐋 DumpDetective Pro X - 链上巨鲸出货雷达")
st.markdown("*自定义代币监控模式：支持手动输入代币合约与钱包地址*")

# --- 侧边栏配置 ---
st.sidebar.header("📡 监控配置")
api_key = st.sidebar.text_input("1. 输入 BscScan API Key", type="password")

# 优化点 1：支持手动输入代币合约地址
st.sidebar.markdown("---")
st.sidebar.subheader("💎 代币设置")
default_token = "0xD399c6dBe8D7D93616053303491E216B30C7B476" # 预设 SIREN 地址
token_contract = st.sidebar.text_input("输入要监控的代币合约地址", value=default_token).strip().lower()

# 优化点 2：钱包设置
st.sidebar.markdown("---")
st.sidebar.subheader("👤 巨鲸设置")
default_wallets = [
    "0xb2AF49dBF526054FAf19602860A5E298a79F3D05",
    "0x9f5D230F8152CB35372138805F99839352e0D7cE"
]
selected_wallet = st.sidebar.selectbox("选择或输入监控钱包", default_wallets + ["手动输入"])
if selected_wallet == "手动输入":
    target_wallet = st.sidebar.text_input("请输入钱包 0x 地址").strip().lower()
else:
    target_wallet = selected_wallet.lower()

# 优化点 3：刷新与深度
record_limit = st.sidebar.select_slider("检索历史深度 (笔数)", options=[20, 50, 100, 200, 500], value=100)
refresh_rate = st.sidebar.slider("自动刷新频率 (秒)", 15, 60, 30)

# --- 核心数据获取逻辑 ---
def get_token_tx_history(wallet, token, key, limit):
    # 使用 tokentx 接口查询特定钱包下特定代币的转账记录
    url = f"https://api.bscscan.com/api?module=account&action=tokentx&contractaddress={token}&address={wallet}&page=1&offset={limit}&sort=desc&apikey={key}"
    try:
        response = requests.get(url, timeout=10).json()
        if response["status"] == "1" and response["result"]:
            return response["result"]
    except Exception as e:
        st.error(f"API 请求失败: {e}")
        return []
    return []

# --- 主界面 UI ---
if st.sidebar.button("🚀 开始同步数据"):
    if not api_key:
        st.error("请输入 API Key")
    elif not token_contract.startswith("0x"):
        st.error("请输入正确的代币合约地址")
    else:
        st.rerun()

# 检查必要参数
if api_key and target_wallet.startswith("0x") and token_contract.startswith("0x"):
    st.subheader(f"🔄 正在追踪: {target_wallet[:15]}...")
    st.info(f"当前监控代币合约: {token_contract}")
    
    placeholder = st.empty()

    while True:
        with placeholder.container():
            transactions = get_token_tx_history(target_wallet, token_contract, api_key, record_limit)
            
            if transactions:
                data_list = []
                for tx in transactions:
                    # 处理精度
                    val = float(tx["value"]) / (10**int(tx["tokenDecimal"]))
                    time_str = datetime.fromtimestamp(int(tx["timeStamp"])).strftime('%Y-%m-%d %H:%M')
                    symbol = tx["tokenSymbol"]
                    
                    is_out = tx["from"].lower() == target_wallet
                    
                    data_list.append({
                        '时间': time_str,
                        '行为': "🔴 转出 (SELL/LP)" if is_out else "🟢 转入 (BUY/WALLET)",
                        '数量': f"{val:,.2f} {symbol}",
                        '对手方': tx["to"] if is_out else tx["from"],
                        '交易哈希': f"https://bscscan.com/tx/{tx['hash']}"
                    })
                
                df = pd.DataFrame(data_list)
                
                # 样式美化
                def color_action(val):
                    color = '#ff4b4b' if '🔴' in val else '#28a745'
                    return f'color: {color}; font-weight: bold'

                st.dataframe(
                    df.style.applymap(color_action, subset=['行为']),
                    use_container_width=True,
                    column_config={
                        "交易哈希": st.column_config.LinkColumn("BscScan 详情", display_text="点击查看")
                    }
                )
                st.caption(f"✅ 监控中... 成功获取 {len(transactions)} 笔交易 | 更新时间: {datetime.now().strftime('%H:%M:%S')}")
            else:
                st.warning("⚠️ 暂未发现该代币的交易记录。")
                st.write("可能原因：1. 代币合约地址不正确；2. 该钱包在此深度下没有该代币的变动。")
            
            # 等待刷新并执行 rerun
            time.sleep(refresh_rate)
            st.rerun()
