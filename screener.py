import os
import requests
import yfinance as yf
import pandas as pd

# 텔레그램 환경변수 로드
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 1. 감시할 후보 티커 리스트 (미국 핵심 주도주 및 나스닥/S&P 주요 종목)
WATCHLIST = [
    "MRK", "VRTX", "RS", "FROG", "ABSI", "TSLA", "LNG", "TXN", 
    "NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "AVGO", "COST"
]

def send_telegram_msg(message: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def check_minervini(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y")
        if len(df) < 200:
            return None
        
        close = df['Close']
        current_price = close.iloc[-1]
        
        # 이동평균선
        sma50 = close.rolling(50).mean().iloc[-1]
        sma150 = close.rolling(150).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1]
        sma200_20d_ago = close.rolling(200).mean().iloc[-20]
        
        # 52주 고/저가
        high_52w = close.max()
        low_52w = close.min()
        
        # 거래량 (50일 평균 대비)
        vol_current = df['Volume'].iloc[-1]
        vol_avg50 = df['Volume'].rolling(50).mean().iloc[-1]
        vol_ratio = (vol_current / vol_avg50) * 100
        
        # 조건 검증
        c1 = current_price > sma150 and current_price > sma200
        c2 = sma150 > sma200
        c3 = sma200 > sma200_20d_ago  # 200일선 우상향
        c4 = sma50 > sma150 and sma50 > sma200
        c5 = current_price > sma50
        c6 = current_price >= (low_52w * 1.25)   # 저점 대비 +25% 이상
        c7 = current_price >= (high_52w * 0.85)  # 고점 대비 -15% 이내 (엄격한 기준)
        
        if c1 and c2 and c3 and c4 and c5 and c6 and c7:
            drop_pct = (current_price - high_52w) / high_52w * 100
            return {
                "ticker": ticker,
                "price": round(current_price, 2),
                "drop_pct": round(drop_pct, 1),
                "vol_ratio": round(vol_ratio, 1)
            }
    except Exception as e:
        print(f"Error {ticker}: {e}")
    return None

def main():
    passed_stocks = []
    for ticker in WATCHLIST:
        res = check_minervini(ticker)
        if res:
            passed_stocks.append(res)
            
    if passed_stocks:
        msg = "🎯 *[SEPA 미네르비니 주도주 포착 알림]*\n\n"
        for s in passed_stocks:
            vdu_icon = "🧊(거래량 고갈)" if s['vol_ratio'] <= 50 else "🔥(거래량 동반)"
            msg += f"• *{s['ticker']}*: ${s['price']} (고점 대비 {s['drop_pct']}%)\n"
            msg += f"   - 거래량: 50일 평균 대비 {s['vol_ratio']}% {vdu_icon}\n\n"
        msg += "👉 *대응*: 지수 FTD 확인 및 피벗 돌파 시 -4% 손절선 세팅"
    else:
        msg = "ℹ️ *[SEPA 스크리너]*: 오늘 기준 템플릿 통과 종목 없음 (현금 보존 국면)"
        
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
