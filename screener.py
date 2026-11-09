import os
import io
import requests
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

# 텔레그램 환경변수
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
    """위키피디아에서 S&P 500 전종목 티커를 실시간 크롤링"""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    resp = requests.get(url, headers=headers)
    
    tables = pd.read_html(io.StringIO(resp.text))
    sp500_table = tables[0]
    
    # 야후 파이낸스 티커 표기법 맞춤 (예: BRK.B -> BRK-B, BF.B -> BF-B)
    tickers = sp500_table['Symbol'].str.replace('.', '-', regex=False).tolist()
    print(f"총 {len(tickers)}개 S&P 500 종목 수집 완료.")
    return tickers

def check_minervini(ticker: str):
    """단일 종목 미네르비니 추세 템플릿 검증"""
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y")
        
        # 최소 200거래일 데이터 필요
        if df is None or len(df) < 200:
            return None
        
        close = df['Close']
        volume = df['Volume']
        current_price = close.iloc[-1]
        
        # 1. 이동평균선 계산
        sma50 = close.rolling(50).mean().iloc[-1]
        sma150 = close.rolling(150).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1]
        sma200_20d_ago = close.rolling(200).mean().iloc[-20]
        
        # 2. 52주 고점 / 저점
        high_52w = close.max()
        low_52w = close.min()
        
        # 3. 거래량 비교
        vol_current = volume.iloc[-1]
        vol_avg50 = volume.rolling(50).mean().iloc[-1]
        vol_ratio = (vol_current / vol_avg50) * 100 if vol_avg50 > 0 else 100.0
        
        # 미네르비니 추세 템플릿 7대 조건
        c1 = current_price > sma150 and current_price > sma200
        c2 = sma150 > sma200
        c3 = sma200 > sma200_20d_ago                      # 200일선 우상향
        c4 = sma50 > sma150 and sma50 > sma200            # 정배열 완성
        c5 = current_price > sma50                        # 50일선 사수
        c6 = current_price >= (low_52w * 1.25)            # 52주 저점 대비 +25% 이상
        c7 = current_price >= (high_52w * 0.85)           # 52주 고점 대비 -15% 이내 초밀착
        
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
    
    print("S&P 500 종목 전수 스크리닝 시작 (멀티스레딩)...")
    # 10개 스레드로 동시 병렬 다운로드 (속도 10배 향상)
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_minervini, ticker): ticker for ticker in tickers}
        for future in as_completed(futures):
            res = future.result()
            if res:
                passed_stocks.append(res)
                
    # 52주 신고가 근접도 순서로 정렬 (고점과 가까운 대장주 우선)
    passed_stocks.sort(key=lambda x: x['drop_pct'], reverse=True)
    
    # 텔레그램 메시지 생성 및 전송
    if passed_stocks:
        total_count = len(passed_stocks)
        msg = f"🎯 *[S&P 500 미네르비니 주도주 포착 ({total_count}개)]*\n\n"
        
        for s in passed_stocks:
            # 거래량이 50% 미만이면 VDU(거래량 고갈), 120% 이상이면 돌파 거래량
            if s['vol_ratio'] <= 50:
                v_tag = "🧊(VDU 수축)"
            elif s['vol_ratio'] >= 120:
                v_tag = "🔥(대량 수급)"
            else:
                v_tag = "⚪(보통)"
                
            msg += f"• *{s['ticker']}*: ${s['price']} (고점 대비 {s['drop_pct']}%)\n"
            msg += f"   - 거래량: 평균 대비 {s['vol_ratio']}% {v_tag}\n"
            
        msg += "\n👉 *대응*: 지수 FTD 발생 시 고점 피벗 돌파 종목 선취매"
    else:
        msg = "ℹ️ *[S&P 500 스크리너]*: 오늘 기준 템플릿 통과 종목 0개 (시장 전체 리스크 관리 국면)"
        
    print(f"통과 종목 {len(passed_stocks)}개 포착. 텔레그램 전송 중...")
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
