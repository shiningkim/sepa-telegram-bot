import os
import time
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
    for attempt in range(1, 4):
        try:
            resp = requests.post(url, json=payload, timeout=25)
            if resp.status_code == 200:
                return
        except Exception as e:
            print(f"[{attempt}/3] 텔레그램 전송 실패: {e}")
            time.sleep(2)

# ==========================================
# 🚦 1. 닛케이 225 시장 신호등 판정 함수
# ==========================================
def analyze_japan_traffic_light():
    """닛케이 225(^N225) 지수의 분산일 및 이평선을 계산하여 신호등 판정"""
    try:
        n225 = yf.Ticker("^N225")
        df = n225.history(period="6mo")
        if len(df) < 50:
            return "🟡 노란불", "지수 데이터 부족", "50%", 0, 0
            
        close = df['Close']
        volume = df['Volume']
        current_price = close.iloc[-1]
        
        sma50 = close.rolling(50).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1]
        
        # 최근 25거래일 기준 분산일 집계 (-0.2% 이상 하락 & 거래량 증가)
        dist_count = 0
        recent_25 = df.iloc[-25:]
        for i in range(1, len(recent_25)):
            price_change = (recent_25['Close'].iloc[i] - recent_25['Close'].iloc[i-1]) / recent_25['Close'].iloc[i-1]
            vol_increase = recent_25['Volume'].iloc[i] > recent_25['Volume'].iloc[i-1]
            if price_change <= -0.002 and vol_increase:
                dist_count += 1
                
        # 신호등 상태 머신
        if current_price < sma50 or dist_count >= 5:
            status = "🔴 빨간불 (Market in Correction)"
            cash_guideline = "80% ~ 100% (신규 매수 금지)"
            comment = f"닛케이 지수가 50일선 아래에 머물거나 분산일({dist_count}개) 누적으로 전면 리스크 관리 국면입니다."
        elif dist_count >= 3:
            status = "🟡 노란불 (Uptrend Under Pressure)"
            cash_guideline = "50% ~ 70% (방어적 운용)"
            comment = f"분산일이 {dist_count}개 누적되었습니다. 주도주 돌파 실패율이 높아지므로 손절선을 -3%로 조이십시오."
        else:
            status = "🟢 초록불 (Confirmed Uptrend)"
            cash_guideline = "0% ~ 20% (적극 매수 국면)"
            comment = "닛케이 지수가 50일선 위에서 건전하게 상승 중입니다. VCP 피벗 돌파 종목에 적극 분할 매수 가능합니다."
            
        return status, comment, cash_guideline, dist_count, round(current_price, 2)
    except Exception as e:
        print(f"일본 지수 분석 실패: {e}")
        return "⚪ 판정 불가", "네트워크 오류", "50%", 0, 0

# ==========================================
# 2. 일본 상장 종목 유니버스 (닛케이 225 전 종목)
# ==========================================
def get_japan_tickers() -> list:
    """도쿄증권거래소 닛케이 225 공식 구성 전 종목 풀 (225개)"""
    nikkei_225 = [
        "1332", "1605", "1721", "1801", "1802", "1803", "1808", "1812", "1925", "1928",
        "1963", "2002", "2269", "2282", "2413", "2432", "2501", "2502", "2503", "2531",
        "2768", "2801", "2802", "2871", "2914", "3086", "3092", "3099", "3289", "3382",
        "3401", "3402", "3405", "3407", "3436", "3659", "3861", "3863", "4004", "4005",
        "4021", "4042", "4043", "4061", "4063", "4151", "4183", "4188", "4208", "4307",
        "4324", "4385", "4452", "4502", "4503", "4506", "4507", "4519", "4523", "4568",
        "4578", "4661", "4689", "4704", "4751", "4755", "4901", "4902", "4911", "5019",
        "5020", "5101", "5108", "5201", "5214", "5232", "5233", "5301", "5332", "5333",
        "5401", "5406", "5411", "5541", "5631", "5703", "5706", "5711", "5713", "5714",
        "5801", "5802", "5803", "6098", "6103", "6113", "6146", "6178", "6273", "6301",
        "6302", "6305", "6326", "6361", "6367", "6471", "6472", "6473", "6479", "6501",
        "6503", "6504", "6506", "6526", "6594", "6645", "6674", "6701", "6702", "6703",
        "6723", "6724", "6752", "6758", "6762", "6770", "6841", "6857", "6861", "6902",
        "6920", "6952", "6954", "6971", "6976", "6981", "6988", "7003", "7011", "7012",
        "7013", "7186", "7201", "7202", "7203", "7205", "7211", "7261", "7267", "7269",
        "7270", "7272", "7731", "7733", "7735", "7741", "7751", "7752", "7762", "7832",
        "7911", "7912", "7951", "7974", "8001", "8002", "8015", "8031", "8035", "8053",
        "8058", "8252", "8253", "8267", "8304", "8306", "8308", "8309", "8316", "8331",
        "8354", "8411", "8601", "8604", "8630", "8697", "8725", "8750", "8766", "8795",
        "8801", "8802", "8804", "8830", "9001", "9005", "9007", "9008", "9009", "9020",
        "9021", "9022", "9064", "9101", "9104", "9107", "9147", "9201", "9202", "9301",
        "9432", "9433", "9434", "9501", "9502", "9503", "9531", "9532", "9602", "9613",
        "9735", "9766", "9843", "9983", "9984"
    ]
    return [f"{t}.T" for t in nikkei_225]

# ==========================================
# 3. 메인 실행 루틴 (미네르비니 Tier 1 정예 VCP 필터)
# ==========================================
def main():
    status, comment, cash_guideline, dist_count, index_price = analyze_japan_traffic_light()
    tickers = get_japan_tickers()
    print(f"일본 신호등: {status} | 닛케이 225 전 종목 ({len(tickers)}개) 스크리닝 시작...")

    passed_stocks = []
    chunk_size = 50
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            data = yf.download(chunk, period="1y", group_by='ticker', threads=True, progress=False)
            for t in chunk:
                try:
                    df = data[t] if len(chunk) > 1 else data
                    df = df.dropna(subset=['Close'])
                    if len(df) < 200:
                        continue
                    
                    close = df['Close']
                    high = df['High']
                    low = df['Low']
                    volume = df['Volume']
                    curr_p = close.iloc[-1]
                    
                    # 1. 가격 및 거래대금 (주가 500엔 이상, 50일 평균 일거래대금 5억 엔 이상)
                    vol_avg50 = volume.rolling(50).mean().iloc[-1]
                    daily_val = curr_p * vol_avg50
                    if curr_p < 500 or vol_avg50 < 100000 or daily_val < 500_000_000:
                        continue

                    # 2. 주가 탄력성 (14일 ATR 비율 >= 2.2% : 둔한 배당/상사/금융주 배제)
                    tr1 = high - low
                    tr2 = (high - close.shift(1)).abs()
                    tr3 = (low - close.shift(1)).abs()
                    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                    atr14 = tr.rolling(14).mean().iloc[-1]
                    atr_ratio = (atr14 / curr_p) * 100
                    if atr_ratio < 2.2:
                        continue

                    # 3. 3개월 모멘텀 (최근 60거래일 주가 상승률 +12% 이상)
                    ret_60d = (curr_p - close.iloc[-60]) / close.iloc[-60] * 100
                    if ret_60d < 12.0:
                        continue

                    sma50 = close.rolling(50).mean().iloc[-1]
                    sma150 = close.rolling(150).mean().iloc[-1]
                    sma200 = close.rolling(200).mean().iloc[-1]
                    sma200_20d = close.rolling(200).mean().iloc[-20]
                    
                    high_52w = close.max()
                    low_52w = close.min()
                    
                    # 4. 미네르비니 추세 템플릿
                    c_trend1 = curr_p > sma150 and curr_p > sma200
                    c_trend2 = sma150 > sma200
                    c_trend3 = sma200 > sma200_20d
                    c_trend4 = sma50 > sma150 and sma50 > sma200
                    c_trend5 = curr_p > sma50
                    c_trend6 = curr_p >= (low_52w * 1.25)
                    
                    # 5. 정예 VCP 필터
                    # - 52주 고점 -8% 이내
                    drop_pct = (curr_p - high_52w) / high_52w * 100
                    c_near_high = drop_pct >= -8.0
                    
                    # - VDU 거래량 고갈 (15% ~ 55% 사이)
                    vol_ratio = (volume.iloc[-1] / vol_avg50) * 100 if vol_avg50 > 0 else 100.0
                    c_vdu = (15.0 <= vol_ratio <= 55.0)
                    
                    # - 5일 캔들 응축 (1.5% ~ 6.5% 사이)
                    recent_5d_range = ((high.iloc[-5:].max() - low.iloc[-5:].min()) / curr_p) * 100
                    c_tight = (1.5 <= recent_5d_range <= 6.5)
                    
                    if (c_trend1 and c_trend2 and c_trend3 and c_trend4 and 
                        c_trend5 and c_trend6 and c_near_high and c_vdu and c_tight):
                        passed_stocks.append({
                            "ticker": t.replace(".T", ""),
                            "price": round(curr_p, 1),
                            "drop_pct": round(drop_pct, 1),
                            "vol_ratio": round(vol_ratio, 1),
                            "tight_pct": round(recent_5d_range, 1),
                            "atr_pct": round(atr_ratio, 1),
                            "ret_60d": round(ret_60d, 1),
                            "high_52w": round(high_52w, 1)
                        })
                except Exception:
                    continue
        except Exception as e:
            print(f"다운로드 에러: {e}")
            time.sleep(1)

    passed_stocks.sort(key=lambda x: x['drop_pct'], reverse=True)
    total_count = len(passed_stocks)

    msg = f"🚦 *[일본장(TSE) SEPA 시장 신호등 & 데일리 브리핑]*\n"
    msg += f"• **상태**: {status}\n"
    msg += f"• **닛케이 225 종가**: `{index_price}`pt (유효 분산일: {dist_count}개)\n"
    msg += f"• **권장 현금 비중**: `{cash_guideline}`\n"
    msg += f"• **진단**: _{comment}_\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    if "🔴 빨간불" in status:
        msg += f"⚠️ *[일본 하락장 경보: 신규 매수 전면 금지 (현금 100%)]*\n"
        msg += f"닛케이 하락 속에서도 추세를 지켜낸 탄력 주도주 **총 {total_count}개**입니다. (FTD 반등 확인 전까지 관찰)\n\n"
    else:
        msg += f"🏆 *[일본장 Tier 1 탄력 성장 주도주 ({total_count}개)]*\n"
        msg += "_필터: 고점 -8% + VDU 고갈(15~55%) + 5일 진폭(1.5~6.5%) + 3개월 모멘텀_\n\n"

    if passed_stocks:
        for idx, s in enumerate(passed_stocks[:15], 1):
            msg += f"{idx}. ⭐ *{s['ticker']}*: `¥{s['price']:,}`\n"
            msg += f"   • 고점 괴리: `{s['drop_pct']}%` (전고점 ¥{s['high_52w']:,})\n"
            msg += f"   • 거래량 수축: `평균의 {s['vol_ratio']}%` 🧊\n"
            msg += f"   • 5일 캔들 응축: `진폭 {s['tight_pct']}%` (일변동: `{s['atr_pct']}%`)\n"
            msg += f"   • 최근 3개월 모멘텀: `+{s['ret_60d']}%`\n\n"
        msg += "👉 *실전 전략*: 베이스 피벗 저항선 대량 거래 돌파 시 분할 매수 진입"
    else:
        msg += "ℹ️ 조건 통과 종목 0개 (현금 보존 국면)"

    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
