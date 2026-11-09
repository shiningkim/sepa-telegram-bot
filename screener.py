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

# ==========================================
# 🚦 1. 윌리엄 오닐 시장 신호등 판정 함수
# ==========================================
def analyze_market_traffic_light():
    """S&P 500 지수를 바탕으로 분산일 및 FTD를 계산하여 신호등 판정"""
    try:
        spy = yf.Ticker("^GSPC")
        df = spy.history(period="6mo")
        if len(df) < 50:
            return "🟡 노란불", "지수 데이터 부족", 50, 0
            
        close = df['Close']
        volume = df['Volume']
        current_price = close.iloc[-1]
        
        sma50 = close.rolling(50).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1]
        
        # 최근 25거래일 기준 유효 분산일(Distribution Days) 카운트
        dist_count = 0
        recent_25 = df.iloc[-25:]
        for i in range(1, len(recent_25)):
            price_change = (recent_25['Close'].iloc[i] - recent_25['Close'].iloc[i-1]) / recent_25['Close'].iloc[i-1]
            vol_increase = recent_25['Volume'].iloc[i] > recent_25['Volume'].iloc[i-1]
            
            # -0.2% 이상 하락 & 거래량 증가 시 분산일
            if price_change <= -0.002 and vol_increase:
                dist_count += 1
                
        # 최근 15거래일 최저점 및 FTD 체크
        recent_15 = df.iloc[-15:]
        lowest_idx = recent_15['Low'].idxmin()
        days_since_low = len(df.loc[lowest_idx:]) - 1
        
        has_ftd = False
        if 4 <= days_since_low <= 11:
            recent_day_change = (close.iloc[-1] - close.iloc[-2]) / close.iloc[-2]
            recent_vol_inc = volume.iloc[-1] > volume.iloc[-2]
            if recent_day_change >= 0.012 and recent_vol_inc:
                has_ftd = True

        # 신호등 상태 머신 판정
        # 빨간불: 50일선/200일선 아래 + 분산일 4개 이상 또는 명확한 하락 국면
        if current_price < sma50 or dist_count >= 5:
            status = "🔴 빨간불 (Market in Correction)"
            cash_guideline = "80% ~ 100% (매수 금지)"
            comment = f"지수가 50일선 아래에 위치하거나 분산일({dist_count}개) 과다 누적으로 전면 리스크 관리 국면입니다."
        elif dist_count >= 3:
            status = "🟡 노란불 (Uptrend Under Pressure)"
            cash_guideline = "50% ~ 70% (방어적 운용)"
            comment = f"분산일이 {dist_count}개 누적되어 상승 탄력이 둔화되었습니다. 손절선을 -3%로 단축하십시오."
        else:
            status = "🟢 초록불 (Confirmed Uptrend)"
            cash_guideline = "0% ~ 20% (적극 매수 허용)"
            comment = "주요 이평선 위에서 분산일이 통제되고 있어 주도주 피벗 돌파에 적극 진입 가능한 상태입니다."
            
        return status, comment, cash_guideline, dist_count, round(current_price, 2)
    except Exception as e:
        print(f"지수 분석 실패: {e}")
        return "⚪ 판정 불가", "네트워크 오류", "50%", 0, 0

# ==========================================
# 2. 미국 상장 유니버스 수집
# ==========================================
def get_us_tickers() -> list:
    url = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/all/all_tickers.txt"
    try:
        resp = requests.get(url, timeout=15)
        raw_tickers = resp.text.strip().split("\n")
        cleaned = [
            t.strip().replace(".", "-") for t in raw_tickers 
            if t.strip() and not any(c in t for c in ["^", "/", "~", "$", "+"])
        ]
        return cleaned[:2500]
    except Exception:
        return ["MRK", "VRTX", "RS", "FROG", "NVDA", "AAPL", "MSFT"]

# ==========================================
# 3. 메인 실행 루틴
# ==========================================
def main():
    # 1단계: 시장 신호등 상태 우선 판정
    status, comment, cash_guideline, dist_count, index_price = analyze_market_traffic_light()
    
    tickers = get_us_tickers()
    passed_stocks = []
    
    batch_size = 100
    print(f"시장 신호등: {status} | 종목 스크리닝 시작...")
    
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        try:
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
                    
                    if current_price < 10.0:
                        continue
                        
                    sma50 = close.rolling(50).mean().iloc[-1]
                    sma150 = close.rolling(150).mean().iloc[-1]
                    sma200 = close.rolling(200).mean().iloc[-1]
                    sma200_20d_ago = close.rolling(200).mean().iloc[-20]
                    
                    high_52w = close.max()
                    low_52w = close.min()
                    
                    vol_avg50 = volume.rolling(50).mean().iloc[-1]
                    vol_ratio = (volume.iloc[-1] / vol_avg50) * 100 if vol_avg50 > 0 else 100.0
                    
                    # 미네르비니 추세 템플릿
                    c_trend1 = current_price > sma150 and current_price > sma200
                    c_trend2 = sma150 > sma200
                    c_trend3 = sma200 > sma200_20d_ago
                    c_trend4 = sma50 > sma150 and sma50 > sma200
                    c_trend5 = current_price > sma50
                    c_trend6 = current_price >= (low_52w * 1.30)
                    
                    # 정예 압축 필터 (고점 -8% 이내 & VDU 50% 이하 & 5일 진폭 6% 이내)
                    c_near_high = current_price >= (high_52w * 0.92)
                    c_vdu = vol_ratio <= 50.0
                    recent_5d_range = (high.iloc[-5:].max() - low.iloc[-5:].min()) / current_price
                    c_tight = recent_5d_range <= 0.06
                    
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
        except Exception:
            continue

    passed_stocks.sort(key=lambda x: x['drop_pct'], reverse=True)
    
# 텔레그램 메시지 헤더: 시장 신호등 브리핑
    msg = f"🚦 *[SEPA 시장 신호등 & 데일리 브리핑]*\n"
    msg += f"• **상태**: {status}\n"
    msg += f"• **S&P 500 종가**: `{index_price}`pt (유효 분산일: {dist_count}개)\n"
    msg += f"• **권장 현금 비중**: `{cash_guideline}`\n"
    msg += f"• **진단**: _{comment}_\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    total_count = len(passed_stocks)
    
    if "🔴 빨간불" in status:
        msg += f"⚠️ *[하락장 경보: 신규 매수 전면 금지 (현금 100%)]*\n"
        msg += f"지수 급락 속에서도 차트를 방어 중인 괴물 상대강도(RS) 주도주 **총 {total_count}개**입니다. (지금 사지 마시고 지수 FTD가 뜰 때까지 관심종목에만 등록)\n\n"
    else:
        msg += f"🏆 *[오늘의 Tier 1 정예 주도주 ({total_count}개)]*\n\n"

    if passed_stocks:
        # 상위 20개까지 제한 없이 모두 표시
        for idx, s in enumerate(passed_stocks[:20], 1):
            msg += f"{idx}. ⭐ *{s['ticker']}*: ${s['price']}\n"
            msg += f"   • 고점 괴리: `{s['drop_pct']}%` (전고점 ${s['high_52w']})\n"
            msg += f"   • 거래량 수축: `50일 평균의 {s['vol_ratio']}%` 🧊\n"
            msg += f"   • 5일 캔들 응축: `진폭 {s['tight_pct']}%` (Tight)\n\n"
            
        if "🔴 빨간불" in status:
            msg += "👉 *실전 전략*: 아무리 자리가 예뻐도 시장 FTD 확인 전까지는 '눈으로만 관찰'하십시오."
        else:
            msg += "👉 *실전 대응*: 피벗 돌파 시 -4% 스탑로스로 진입"
    else:
        msg += "ℹ️ 조건 통과 종목 0개 (현금 보존 국면)"
            
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
