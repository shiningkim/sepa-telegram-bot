import os
import requests
import yfinance as yf

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_alert(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def screen_us_stock(ticker_symbol: str):
    try:
        stock = yf.Ticker(ticker_symbol)
        info = stock.info

        # 1. PER 및 성장률 확인
        pe = info.get("trailingPE") or info.get("forwardPE")
        growth_rate = info.get("earningsGrowth") or info.get("revenueGrowth")

        if not pe or not growth_rate or growth_rate <= 0:
            return None

        # 성장률(소수점)을 퍼센트(%)로 변환
        growth_pct = growth_rate * 100
        peg = pe / growth_pct

        # 2. 재무 안정성 (부채비율)
        debt_to_equity = info.get("debtToEquity", 999) # yfinance는 % 단위 (예: 80 = 80%)

        # 3. 린치 기준 필터링
        # - PEG < 1.0 (성장 대비 저평가)
        # - EPS/매출 성장률 15% ~ 40% (안정적 고성장)
        # - 부채비율 80% 이하
        if peg < 1.0 and 15 <= growth_pct <= 45 and debt_to_equity <= 80:
            return {
                "ticker": ticker_symbol,
                "name": info.get("shortName", ticker_symbol),
                "price": info.get("currentPrice"),
                "pe": round(pe, 2),
                "growth": round(growth_pct, 2),
                "peg": round(peg, 2),
                "de": round(debt_to_equity, 2),
            }
    except Exception as e:
        return None

def run_us_agent(watchlist):
    hits = []
    for ticker in watchlist:
        res = screen_us_stock(ticker)
        if res:
            hits.append(res)

    if not hits:
        return

    msg = "🇺🇸 *[피터 린치 Agent - 미국 유망주 포착]*\n\n"
    for item in hits:
        msg += f"• *{item['name']} ({item['ticker']})*\n"
        msg += f"  - 주가: ${item['price']}\n"
        msg += f"  - PEG: `{item['peg']}` (PER: {item['pe']} / 성장률: {item['growth']}%)\n"
        msg += f"  - 부채비율: `{item['de']}%`\n\n"

    send_telegram_alert(msg)

if __name__ == "__main__":
    # S&P 500, Russell 1000 리스트 또는 선별 유니버스 투입
    us_universe = ["AAPL", "GOOGL", "CROX", "ELF", "LULU", "MEDP", "DECK"]
    run_us_agent(us_universe)
