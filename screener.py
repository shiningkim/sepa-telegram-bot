import os
import requests
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_msg(message: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}")

def get_sp500_tickers() -> list:
    """차단 걱정 없는 실시간 S&P 500 공식 티커 데이터셋 로드"""
    url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
    try:
        df = pd.read_csv(url)
        # 야후 파이낸스 티커 호환 (BRK.B -> BRK-B)
        tickers = df['Symbol'].str.replace('.', '-', regex=False).tolist()
        print(f"총 {len(tickers)}개 S&P 500 종목 확보 완료.")
        return tickers
    except Exception as e:
        print(f"티커 로드 실패: {e}, 백업 리스트로 대체")
        return ["MRK", "VRTX", "RS", "FROG", "NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL"]

def check_minervini(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y")
        
        if df is None or len(df) < 200:
            return None
        
        close = df['Close']
        volume = df['Volume']
        current_price = close.iloc[-1]
        
        sma50 = close.rolling(50).mean().iloc[-1]
        sma150 = close.rolling(150).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1]
        sma200_20d_ago = close.rolling(200).mean().iloc[-20]
        
        high_52w = close.max()
        low_52w = close.min()
        
        vol_current = volume.iloc[-1]
        vol_avg50 = volume.rolling(50).mean().iloc[-1]
        vol_ratio = (vol_current / vol_avg50) * 100 if vol_avg50 > 0 else 100.0
        
        # 미네르비니 7대 조건
        c1 = current_price > sma150 and current_price > sma200
        c2 = sma150 > sma200
        c3 = sma200 > sma200_20d_ago
        c4 = sma50 > sma150 and sma50 > sma200
        c5 = current_price > sma50
        c6 = current_price >= (low_52w * 1.25)
        c7 = current_price >= (high_52w * 0.85)  # 52주 신고가 대비 -15% 이내
        
        if c1 and c2 and c3 and c4 and c5 and c6 and c7:
            drop_pct = (current_price - high_52w) / high_52w * 100
            return {
                "ticker": ticker,
                "price": round(current_price, 2),
                "drop_pct": round(drop_pct, 1),
                "vol_ratio": round(vol_ratio, 1)
            }
    except Exception:
        return None
    return None

def main():
    tickers = get_sp500_tickers()
    passed_stocks = []
    
    print(f"{len(tickers)}개 전종목 미네르비니 스크리닝 시작...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_minervini, ticker): ticker for ticker in tickers}
        for future in as_completed(futures):
            res = future.result()
            if res:
                passed_stocks.append(res)
                
    # 52주 신고가 근접도 순서로 정렬
    passed_stocks.sort(key=lambda x: x['drop_pct'], reverse=True)
    
    if passed_stocks:
        total_count = len(passed_stocks)
        msg = f"🎯 *[S&P 500 전수조사 미네르비니 주도주 ({total_count}개)]*\n\n"
        
        # 텔레그램 메시지 길이 제한 대비 상위 30개만 표시
        for s in passed_stocks[:30]:
            if s['vol_ratio'] <= 50:
                v_tag = "🧊(VDU)"
            elif s['vol_ratio'] >= 120:
                v_tag = "🔥(수급)"
            else:
                v_tag = "⚪"
            msg += f"• *{s['ticker']}*: ${s['price']} (고점 대비 {s['drop_pct']}% / 거래량 {s['vol_ratio']}% {v_tag})\n"
            
        if total_count > 30:
            msg += f"\n_...외 {total_count - 30}개 종목 추가 포착됨_"
            
        msg += "\n👉 *대응*: 지수 FTD 확인 시 고점 돌파 종목 선취매"
    else:
        msg = "ℹ️ *[S&P 500 전수조사]*: 오늘 기준 조건 통과 종목 0개 (하락장 리스크 관리)"
        
    print(f"총 {len(passed_stocks)}개 통과. 전송 중...")
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
