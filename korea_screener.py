import os
import requests
import pandas as pd
from datetime import datetime, timedelta
import FinanceDataReader as fdr
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

def get_target_tickers():
    """KRX 로그인 없이 네이버/KRX 상장사 목록에서 코스피/코스닥 상위 500개 추출"""
    df_krx = fdr.StockListing('KRX')
    
    # 스팩(SPAC), 우선주, 환기종목 등 배제
    df_clean = df_krx[~df_krx['Name'].str.contains('스팩|우$|우B$|1호|2호|3호', regex=True, na=False)]
    
    # 코스피 200 + 코스닥 300 (시총 순)
    kospi = df_clean[df_clean['Market'] == 'KOSPI'].sort_values(by='Marcap', ascending=False).head(200)
    kosdaq = df_clean[df_clean['Market'] == 'KOSDAQ'].sort_values(by='Marcap', ascending=False).head(300)
    
    targets = []
    for _, row in kospi.iterrows():
        targets.append((row['Code'], row['Name'], '코스피'))
    for _, row in kosdaq.iterrows():
        targets.append((row['Code'], row['Name'], '코스닥'))
        
    return targets

def analyze_ticker(ticker, name, market_type, start_date):
    try:
        # 네이버 금융 경유 1년치 일봉 로드 (로그인 불필요)
        df = fdr.DataReader(ticker, start=start_date)
        if len(df) < 180:
            return None
            
        close = df['Close']
        volume = df['Volume']
        high = df['High']
        low = df['Low']
        current_price = close.iloc[-1]
        
        # 1. 환금성 (거래량 50일 평균 5만 주 이상, 주가 3,000원 이상)
        vol_avg50 = volume.rolling(50).mean().iloc[-1]
        if current_price < 3000 or vol_avg50 < 50000:
            return None
            
        sma50 = close.rolling(50).mean().iloc[-1]
        sma150 = close.rolling(150).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1]
        sma200_20d_ago = close.rolling(200).mean().iloc[-20]
        
        high_52w = close.max()
        low_52w = close.min()
        vol_ratio = (volume.iloc[-1] / vol_avg50) * 100 if vol_avg50 > 0 else 100.0
        
        # 미네르비니 템플릿
        c1 = current_price > sma150 and current_price > sma200
        c2 = sma150 > sma200
        c3 = sma200 > sma200_20d_ago
        c4 = sma50 > sma150 and sma50 > sma200
        c5 = current_price > sma50
        c6 = current_price >= (low_52w * 1.25)
        
        # 정예 압축: 신고가 -10% 이내 + VDU(60% 이하) + 5일 변동성 8% 이내
        c_near_high = current_price >= (high_52w * 0.90)
        c_vdu = vol_ratio <= 60.0
        recent_5d_range = (high.iloc[-5:].max() - low.iloc[-5:].min()) / current_price
        c_tight = recent_5d_range <= 0.08
        
        if c1 and c2 and c3 and c4 and c5 and c6 and c_near_high and c_vdu and c_tight:
            drop_pct = (current_price - high_52w) / high_52w * 100
            return {
                "name": name,
                "ticker": ticker,
                "market": market_type,
                "price": int(current_price),
                "drop_pct": round(drop_pct, 1),
                "vol_ratio": round(vol_ratio, 1),
                "tight_pct": round(recent_5d_range * 100, 1)
            }
    except Exception:
        return None
    return None

def main():
    today = datetime.today()
    start_date = (today - timedelta(days=365)).strftime("%Y-%m-%d")
    
    targets = get_target_tickers()
    print(f"총 {len(targets)}개 국내 핵심 종목 스크리닝 시작 (FinanceDataReader)...")
    
    passed_stocks = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(analyze_ticker, t[0], t[1], t[2], start_date): t for t in targets}
        for future in as_completed(futures):
            res = future.result()
            if res:
                passed_stocks.append(res)
                
    passed_stocks.sort(key=lambda x: x['drop_pct'], reverse=True)
    
    if passed_stocks:
        total_count = len(passed_stocks)
        msg = f"🇰🇷 *[국내장 미네르비니 Tier 1 주도주 ({total_count}개)]*\n"
        msg += "_조건: 시총 상위 500개 중 신고가 -10% + VDU 거래량 고갈 + 5일 수축_\n\n"
        for s in passed_stocks[:15]:
            msg += f"⭐ *{s['name']}* (`{s['ticker']}` / {s['market']}): {s['price']:,}원\n"
            msg += f"   • 고점 괴리: `{s['drop_pct']}%` | 거래량 수축: `{s['vol_ratio']}%` 🧊\n"
            msg += f"   • 5일 캔들 응축: `진폭 {s['tight_pct']}%`\n\n"
        msg += "👉 *대응*: 코스피 FTD 발생 전까지는 관망, 피벗 돌파 시 진입"
    else:
        msg = "ℹ️ *[국내장 스크리너]*: 오늘 기준 정예 VCP/VDU 조건 통과 종목 0개 (하락장 현금 보존)"
        
    print(f"완료. {len(passed_stocks)}개 전송.")
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
