import os
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime

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

def get_us_tickers() -> list:
    """미국 전체 상장 보통주 유니버스 수집"""
    print("미국 상장 종목 목록 수집 중...")
    url = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/all/all_tickers.txt"
    try:
        resp = requests.get(url, timeout=15)
        raw_tickers = resp.text.strip().split("\n")
        cleaned = [
            t.strip().replace(".", "-") for t in raw_tickers 
            if t.strip() and not any(c in t for c in ["^", "/", "~", "$", "+"])
        ]
        print(f"총 {len(cleaned)}개 종목 확보.")
        return cleaned[:2500]  # 유효 상위 2,500개 종목 대상
    except Exception as e:
        print(f"티커 로드 실패: {e}")
        return ["MRK", "VRTX", "RS", "FROG", "NVDA", "AAPL", "MSFT"]

def main():
    tickers = get_us_tickers()
    passed_stocks = []
    
    batch_size = 100
    print(f"미네르비니 Tier 1 정예 압축 스크리닝 시작 (총 {len(tickers)}개 대상)...")
    
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        try:
            # 100개씩 묶음 일괄 다운로드 (속도 최적화)
            data = yf.download(batch, period="1y", group_by='ticker', threads=True, progress=False)
            
            for ticker in batch:
                try:
                    df = data[ticker] if len(batch) > 1 else data
                    df = df.dropna(subset=['Close'])
                    if len(df) < 200:
                        continue
                    
                    close = df['Close']
                    high = df['High']
                    low = df['Low']
                    volume = df['Volume']
                    
                    current_price = close.iloc[-1]
                    
                    # 1. 기관 매매 가능 종목 필터 ($10 이상 종목만 선별)
                    if current_price < 10.0:
                        continue
                        
                    sma50 = close.rolling(50).mean().iloc[-1]
                    sma150 = close.rolling(150).mean().iloc[-1]
                    sma200 = close.rolling(200).mean().iloc[-1]
                    sma200_20d_ago = close.rolling(200).mean().iloc[-20]
                    
                    high_52w = close.max()
                    low_52w = close.min()
                    
                    vol_current = volume.iloc[-1]
                    vol_avg50 = volume.rolling(50).mean().iloc[-1]
                    vol_ratio = (vol_current / vol_avg50) * 100 if vol_avg50 > 0 else 100.0
                    
                    # 2. 미네르비니 추세 템플릿 기본 룰
                    c_trend1 = current_price > sma150 and current_price > sma200
                    c_trend2 = sma150 > sma200
                    c_trend3 = sma200 > sma200_20d_ago                      # 200일선 우상향
                    c_trend4 = sma50 > sma150 and sma50 > sma200            # 정배열 완성
                    c_trend5 = current_price > sma50                        # 50일선 사수
                    c_trend6 = current_price >= (low_52w * 1.30)            # 52주 저점 대비 +30% 이상
                    
                    # 3. ★ 핵심 압축 3대 필터 ★
                    # 필터 A: 52주 신고가 대비 -8% 이내 초밀착 (신고가 턱밑 대장주만)
                    c_near_high = current_price >= (high_52w * 0.92)
                    
                    # 필터 B: 거래량 바짝 마름(VDU) 필수 조건 (평균 대비 50% 이하)
                    c_vdu = vol_ratio <= 50.0
                    
                    # 필터 C: VCP 캔들 변동성 응축(Tightness) (최근 5일간 고저 진폭 6% 이내)
                    recent_5d_range = (high.iloc[-5:].max() - low.iloc[-5:].min()) / current_price
                    c_tight = recent_5d_range <= 0.06
                    
                    # 모든 조건 통과 종목만 엄선
                    if (c_trend1 and c_trend2 and c_trend3 and c_trend4 and 
                        c_trend5 and c_trend6 and c_near_high and c_vdu and c_tight):
                        
                        drop_pct = (current_price - high_52w) / high_52w * 100
                        passed_stocks.append({
                            "ticker": ticker,
                            "price": round(current_price, 2),
                            "drop_pct": round(drop_pct, 1),
                            "vol_ratio": round(vol_ratio, 1),
                            "tight_pct": round(recent_5d_range * 100, 1),
                            "high_52w": round(high_52w, 2)
                        })
                except Exception:
                    continue
        except Exception as e:
            print(f"배치 에러: {e}")
            continue

    # 최고가에 가장 가까운 순서대로 정렬
    passed_stocks.sort(key=lambda x: x['drop_pct'], reverse=True)
    
    # 텔레그램 메시지 구성
    if passed_stocks:
        total_count = len(passed_stocks)
        msg = f"🏆 *[미네르비니 Tier 1 정예 주도주 ({total_count}개)]*\n"
        msg += "_조건: 신고가 -8% 이내 + VDU 거래량 고갈 + 5일 진폭 6% 이하 응축_\n\n"
        
        for s in passed_stocks:
            msg += f"⭐ *{s['ticker']}*: ${s['price']}\n"
            msg += f"   • 최고가 괴리: `{s['drop_pct']}%` (전고점 ${s['high_52w']})\n"
            msg += f"   • 거래량 수축: `50일 평균의 {s['vol_ratio']}%` 🧊\n"
            msg += f"   • 5일 캔들 응축: `진폭 {s['tight_pct']}%` (Tight)\n\n"
            
        msg += "👉 *실전 전략*: 전고점/핸들 상단 돌파 시 -4% 손절선 잡고 1차 진입"
    else:
        msg = "ℹ️ *[미네르비니 정예 스크리너]*: 오늘 기준 완벽한 VCP/VDU 조건을 만족한 종목 0개 (현금 보존 및 관망 국면)"
        
    print(f"최종 엄선 {len(passed_stocks)}개 통과. 전송 중...")
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
