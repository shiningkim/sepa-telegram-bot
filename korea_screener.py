import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from pykrx import stock

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

def get_recent_trading_days(days=300):
    """최근 300영업일 날짜 계산"""
    today = datetime.today()
    start_date = today - timedelta(days=days * 1.5)
    return start_date.strftime("%Y%m%d"), today.strftime("%Y%m%d")

def main():
    start_date, end_date = get_recent_trading_days()
    today_str = datetime.today().strftime("%Y%m%d")
    
    print("국내 코스피/코스닥 전종목 티커 수집 중...")
    kospi_tickers = stock.get_market_ticker_list(today_str, market="KOSPI")
    kosdaq_tickers = stock.get_market_ticker_list(today_str, market="KOSDAQ")
    all_tickers = kospi_tickers + kosdaq_tickers
    print(f"총 {len(all_tickers)}개 종목 수집 완료.")

    passed_stocks = []
    
    # 전종목 검사 (빠른 속도를 위해 단봉 일괄 조회 또는 필터 적용)
    for ticker in all_tickers:
        name = stock.get_market_ticker_name(ticker)
        
        # 스팩(SPAC), 우선주 배제
        if "스팩" in name or name.endswith("우") or name.endswith("우B"):
            continue
            
        try:
            # 1년 치 OHLCV 데이터 조회
            df = stock.get_market_ohlcv_by_date(start_date, end_date, ticker)
            if len(df) < 200:
                continue
                
            close = df['종가']
            volume = df['거래량']
            high = df['고가']
            low = df['저가']
            current_price = close.iloc[-1]
            
            # 1. 동전주/환금성 배제 (주가 3,000원 이상, 50일 평균 거래량 10만 주 이상)
            vol_avg50 = volume.rolling(50).mean().iloc[-1]
            if current_price < 3000 or vol_avg50 < 100000:
                continue
                
            # 2. 이동평균선
            sma50 = close.rolling(50).mean().iloc[-1]
            sma150 = close.rolling(150).mean().iloc[-1]
            sma200 = close.rolling(200).mean().iloc[-1]
            sma200_20d_ago = close.rolling(200).mean().iloc[-20]
            
            high_52w = close.max()
            low_52w = close.min()
            
            vol_current = volume.iloc[-1]
            vol_ratio = (vol_current / vol_avg50) * 100 if vol_avg50 > 0 else 100.0
            
            # 미네르비니 추세 템플릿
            c_trend1 = current_price > sma150 and current_price > sma200
            c_trend2 = sma150 > sma200
            c_trend3 = sma200 > sma200_20d_ago                      # 200일선 우상향
            c_trend4 = sma50 > sma150 and sma50 > sma200            # 정배열
            c_trend5 = current_price > sma50                        # 50일선 사수
            c_trend6 = current_price >= (low_52w * 1.30)            # 저점 대비 +30% 이상
            
            # 핵심 정예 조건: 신고가 -10% 이내 & 거래량 고갈(VDU 50% 이하) & 5일 변동성 7% 이내
            c_near_high = current_price >= (high_52w * 0.90)
            c_vdu = vol_ratio <= 50.0
            recent_5d_range = (high.iloc[-5:].max() - low.iloc[-5:].min()) / current_price
            c_tight = recent_5d_range <= 0.07
            
            if (c_trend1 and c_trend2 and c_trend3 and c_trend4 and 
                c_trend5 and c_trend6 and c_near_high and c_vdu and c_tight):
                
                drop_pct = (current_price - high_52w) / high_52w * 100
                market_type = "코스피" if ticker in kospi_tickers else "코스닥"
                passed_stocks.append({
                    "ticker": ticker,
                    "name": name,
                    "market": market_type,
                    "price": int(current_price),
                    "drop_pct": round(drop_pct, 1),
                    "vol_ratio": round(vol_ratio, 1),
                    "tight_pct": round(recent_5d_range * 100, 1)
                })
        except Exception:
            continue

    # 고점 근접도 순 정렬
    passed_stocks.sort(key=lambda x: x['drop_pct'], reverse=True)
    
    if passed_stocks:
        total_count = len(passed_stocks)
        msg = f"🇰🇷 *[국내장 미네르비니 Tier 1 정예 주도주 ({total_count}개)]*\n"
        msg += "_조건: 신고가 -10% + 거래량 고갈(VDU) + 5일 진폭 7% 응축_\n\n"
        for s in passed_stocks[:20]:
            msg += f"⭐ *{s['name']}* ({s['ticker']} / {s['market']}): {s['price']:,}원\n"
            msg += f"   • 고점 괴리: `{s['drop_pct']}%` | 거래량 수축: `{s['vol_ratio']}%` 🧊\n"
            msg += f"   • 5일 캔들 응축: `진폭 {s['tight_pct']}%`\n\n"
        msg += "👉 *대응*: 지수 FTD 확인 시 직전 넥라인/피벗 돌파 매수"
    else:
        msg = "ℹ️ *[국내장 스크리너]*: 오늘 기준 완벽한 VCP/VDU 조건 종목 0개 (지수 하락에 따른 현금 보존)"
        
    print(f"통과 종목 {len(passed_stocks)}개 전송 완료.")
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
