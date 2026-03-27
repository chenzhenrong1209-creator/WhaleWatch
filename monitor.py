import time
import requests

# --- 核心配置 ---
SIREN_CONTRACT = "0xD399c6dBe8D7D93616053303491E216B30C7B476"

class WhaleWatch:
    def __init__(self, api_key, target_address):
        self.api_key = api_key
        self.target_address = target_address.lower().strip()
        self.last_tx_hash = None
        # 用于统计
        self.total_out = 0
        self.total_in = 0

    def get_latest_tx(self):
        """从 BscScan 获取最近一笔 SIREN 转账记录"""
        url = f"https://api.bscscan.com/api?module=account&action=tokentx&contractaddress={SIREN_CONTRACT}&address={self.target_address}&page=1&offset=1&sort=desc&apikey={self.api_key}"
        
        try:
            res = requests.get(url).json()
            if res["status"] == "1" and res["result"]:
                return res["result"][0]
        except Exception as e:
            print(f"网络请求错误: {e}")
        return None

    def start(self):
        print(f"\n🚀 雷达已启动！")
        print(f"📡 正在监控: {self.target_address}")
        print(f"⏳ 正在等待新交易... (每15秒轮询一次)")
        print("-" * 50)

        while True:
            tx = self.get_latest_tx()
            
            if tx and tx["hash"] != self.last_tx_hash:
                # 第一次运行只记录哈希，不报警，防止把旧交易当新交易
                if self.last_tx_hash is None:
                    self.last_tx_hash = tx["hash"]
                    continue

                self.last_tx_hash = tx["hash"]
                self.process_tx(tx)
            
            time.sleep(15)

    def process_tx(self, tx):
        val = float(tx["value"]) / (10 ** int(tx["tokenDecimal"]))
        is_sender = tx["from"].lower() == self.target_address
        
        if is_sender:
            self.total_out += val
            action = "🔴 【检测到出货/转出】"
            dest = tx["to"]
        else:
            self.total_in += val
            action = "🟢 【检测到建仓/转入】"
            dest = tx["from"]

        # 打印详细信息
        print(f"{action}")
        print(f"💰 数量: {val:,.2f} SIREN")
        print(f"🤝 对手方: {dest}")
        print(f"📊 今日统计: 总计转出 {self.total_out:,.2f} | 总计转入 {self.total_in:,.2f}")
        print(f"🔗 详情: https://bscscan.com/tx/{tx['hash']}")
        print("-" * 50)

if __name__ == "__main__":
    print("=== WhaleWatch 巨鲸雷达管理系统 ===")
    my_key = input("1. 请粘贴你的 BscScan API Key: ").strip()
    my_addr = input("2. 请输入你想监控的钱包地址: ").strip()
    
    if my_key and my_addr.startswith("0x"):
        watcher = WhaleWatch(my_key, my_addr)
        watcher.start()
    else:
        print("输入信息有误，请重新运行程序。")
