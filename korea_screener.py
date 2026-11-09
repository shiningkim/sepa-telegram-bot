import os
import time
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
    for attempt in range(1, 4):
        try:
            resp = requests.post(url, json=payload, timeout=25)
            if resp.status_code == 200:
                return
        except Exception as e:
            print(f"[{attempt}/3] 텔레그램 전송 오류: {e}")
            time.sleep(2)

# ==========================================
# 🚦 1. 코스피 시장 신호등 (오닐/미네르비니 기준)
# ==========================================
def analyze_korea_traffic_light():
    """코스피(KS11) 지수의 분산일 및 이평선을 계산하여 신호등 판정"""
    try:
        today = datetime.today()
        start_date = (today - timedelta(days=180)).strftime("%Y-%m-%d")
        df = fdr.DataReader('KS11', start=start_date)
        
        if len(df) < 50:
            return "🟡 노란불", "지수 데이터 부족", "50%", 0, 0
            
        close = df['종가'] if '종가' in df.columns else df['Close']
        volume = df['거래량'] if '거래량' in df.columns else df['Volume']
        current_price = close.iloc[-1]
        
        sma50 = close.rolling(50).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1]
        
        # 최근 25거래일 기준 분산일(Distribution Days) 집계 (-0.2% 이상 하락 & 거래량 증가)
        dist_count = 0
        recent_25 = df.iloc[-25:]
        for i in range(1, len(recent_25)):
            c_curr = recent_25['종가'].iloc[i] if '종가' in recent_25.columns else recent_25['Close'].iloc[i]
            c_prev = recent_25['종가'].iloc[i-1] if '종가' in recent_25.columns else recent_25['Close'].iloc[i-1]
            v_curr = recent_25['거래량'].iloc[i] if '거래량' in recent_25.columns else recent_25['Volume'].iloc[i]
            v_prev = recent_25['거래량'].iloc[i-1] if '거래량' in recent_25.columns else recent_25['Volume'].iloc[i-1]
            
            price_change = (c_curr - c_prev) / c_prev
            vol_increase = v_curr > v_prev
            if price_change <= -0.002 and vol_increase:
                dist_count += 1
                
        # 신호등 상태 머신
        if current_price < sma50 or dist_count >= 5:
            status = "🔴 빨간불 (Market in Correction)"
            cash_guideline = "80% ~ 100% (신규 매수 금지)"
            comment = f"코스피가 50일선 아래에 머물거나 분산일({dist_count}개) 과다 누적으로 전면 리스크 관리 국면입니다."
        elif dist_count >= 3:
            status = "🟡 노란불 (Uptrend Under Pressure)"
            cash_guideline = "50% ~ 70% (방어적 운용)"
            comment = f"분산일이 {dist_count}개 누적되었습니다. 돌파 실패율이 높아지므로 손절선을 -3%로 조이십시오."
        else:
            status = "🟢 초록불 (Confirmed Uptrend)"
            cash_guideline = "0% ~ 20% (적극 매수 국면)"
            comment = "코스피가 50일선 위에서 분산일이 통제되고 있습니다. VCP 피벗 돌파 종목에 적극 분할 매수 가능합니다."
            
        return status, comment, cash_guideline, dist_count, round(current_price, 2)
    except Exception as e:
        print(f"한국 지수 분석 실패: {e}")
        return "⚪ 판정 불가", "네트워크 오류", "50%", 0, 0

# ==========================================
# 2. 국내 상장 종목 유니버스 (상위 500개)
# ==========================================
def get_target_tickers():
    df_krx = fdr.StockListing('KRX')
    # 스팩, 우선주, 관리/환기성 종목 필터링
    df_clean = df_krx[~df_krx['Name'].str.contains('스팩|우$|우B$|1호|2호|3호|4호|5호', regex=True, na=False)]
    
    kospi = df_clean[df_clean['Market'] == 'KOSPI'].sort_values(by='Marcap', ascending=False).head(200)
    kosdaq = df_clean[df_clean['Market'] == 'KOSDAQ'].sort_values(by='Marcap', ascending=False).head(300)
    
    targets = []
    for _, row in kospi.iterrows():
        targets.append((row['Code'], row['Name'], '코스피'))
    for _, row in kosdaq.iterrows():
        targets.append((row['Code'], row['Name'], '코스닥'))
    return targets

# ==========================================
# 3. 개별 종목 정밀 SEPA & 탄력 VCP 필터
# ==========================================
def analyze_ticker(ticker, name, market_type, start_date):
    try:
        df = fdr.DataReader(ticker, start=start_date)
        if len(df) < 200:
            return None
            
        close = df['종가'] if '종가' in df.columns else df['Close']
        volume = df['거래량'] if '거래량' in df.columns else df['Volume']
        high = df['고가'] if '고가' in df.columns else df['High']
        low = df['저가'] if '저가' in df.columns else df['Low']
        current_price = close.iloc[-1]
        
        # 1. 가격 및 유동성 (주가 3,000원 이상, 50일 평균 거래량 10만 주 이상, 일평균 거래대금 20억 원 이상)
        vol_avg50 = volume.rolling(50).mean().iloc[-1]
        daily_trading_value = current_price * vol_avg50
        if current_price < 3000 or vol_avg50 < 100000 or daily_trading_value < 2_000_000_000:
            return None

        # 2. 평소 주가 탄력성 검증 (14일 ATR 비율 >= 2.5% : 둔한 은행/보험/지주사/공기업 배제)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean().iloc[-1]
        atr_ratio = (atr14 / current_price) * 100
        if atr_ratio < 2.5:
            return None

        # 3. 3개월 모멘텀 검증 (최근 60거래일 주가 상승률 +15% 이상 주도 성장주)
        ret_60d = (current_price - close.iloc[-60]) / close.iloc[-60] * 100
        if ret_60d < 15.0:
            return None
            
        sma50 = close.rolling(50).mean().iloc[-1]
        sma150 = close.rolling(150).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1]
        sma200_20d_ago = close.rolling(200).mean().iloc[-20]
        
        high_52w = close.max()
        low_52w = close.min()
        
        # 4. 미네르비니 추세 템플릿
        c1 = current_price > sma150 and current_price > sma200
        c2 = sma150 > sma200
        c3 = sma200 > sma200_20d_ago
        c4 = sma50 > sma150 and sma50 > sma200
        c5 = current_price > sma50
        c6 = current_price >= (low_52w * 1.30)  # 저점 대비 최소 30% 반등
        
        # 5. 정예 VCP 압축 필터
        # - 신고가 턱밑 (-8% 이내)
        drop_pct = (current_price - high_52w) / high_52w * 100
        c_near_high = drop_pct >= -8.0
        
        # - VDU 거래량 고갈 (15% ~ 55% 사이 : 0% 무체결 종목 원천 배제)
        vol_ratio = (volume.iloc[-1] / vol_avg50) * 100 if vol_avg50 > 0 else 100.0
        c_vdu = (15.0 <= vol_ratio <= 55.0)
        
        # - 5일 캔들 응축 (1.5% ~ 6.5% 사이 : 1% 미만 완전 정체 종목 배제)
        recent_5d_range = ((high.iloc[-5:].max() - low.iloc[-5:].min()) / current_price) * 100
        c_tight = (1.5 <= recent_5d_range <= 6.5)
        
        if c1 and c2 and c3 and c4 and c5 and c6 and c_near_high and c_vdu and c_tight:
            return {
                "name": name,
                "ticker": ticker,
                "market": market_type,
                "price": int(current_price),
                "drop_pct": round(drop_pct, 1),
                "vol_ratio": round(vol_ratio, 1),
                "tight_pct": round(recent_5d_range, 1),
                "atr_pct": round(atr_ratio, 1),
                "ret_60d": round(ret_60d, 1),
                "high_52w": int(high_52w)
            }
    except Exception:
        return None
    return None

# ==========================================
# 4. 메인 실행 루틴
# ==========================================
def main():
    status, comment, cash_guideline, dist_count, index_price = analyze_korea_traffic_light()
    
    today = datetime.today()
    start_date = (today - timedelta(days=365)).strftime("%Y-%m-%d")
    
    targets = get_target_tickers()
    print(f"국내 신호등: {status} | {len(targets)}개 종목 스크리닝 시작...")
    
    passed_stocks = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(analyze_ticker, t[0], t[1], t[2], start_date): t for t in targets}
        for future in as_completed(futures):
            res = future.result()
            if res:
                passed_stocks.append(res)
                
    passed_stocks.sort(key=lambda x: x['drop_pct'], reverse=True)
    total_count = len(passed_stocks)
    
    # 텔레그램 메시지 헤더
    msg = f"🚦 *[국내장 SEPA 시장 신호등 & 데일리 브리핑]*\n"
    msg += f"• **상태**: {status}\n"
    msg += f"• **코스피 종가**: `{index_price}`pt (유효 분산일: {dist_count}개)\n"
    msg += f"• **권장 현금 비중**: `{cash_guideline}`\n"
    msg += f"• **진단**: _{comment}_\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if "🔴 빨간불" in status:
        msg += f"⚠️ *[국내 하락장 경보: 신규 매수 전면 금지 (현금 100%)]*\n"
        msg += f"시장 하락 속에서도 추세를 지켜낸 탄력 주도주 **총 {total_count}개**입니다. (FTD 반등 확인 전까지 관심종목 관찰)\n\n"
    else:
        msg += f"🏆 *[국내장 Tier 1 탄력 성장 주도주 ({total_count}개)]*\n"
        msg += "_필터: 고점 -8% + VDU 고갈(15~55%) + 5일 진폭(1.5~6.5%) + 3개월 상승 탄력주_\n\n"
        
    if passed_stocks:
        for idx, s in enumerate(passed_stocks[:20], 1):
            msg += f"{idx}. ⭐ *{s['name']}* (`{s['ticker']}` / {s['market']}): {s['price']:,}원\n"
            msg += f"   • 고점 괴리: `{s['drop_pct']}%` (전고점 {s['high_52w']:,}원)\n"
            msg += f"   • 거래량 수축: `50일 평균의 {s['vol_ratio']}%` 🧊\n"
            msg += f"   • 5일 캔들 응축: `진폭 {s['tight_pct']}%` (평소 일변동: `{s['atr_pct']}%`)\n"
            msg += f"   • 최근 3개월 모멘텀: `+{s['ret_60d']}%`\n\n"
            
        if "🔴 빨간불" in status:
            msg += "👉 *실전 전략*: 코스피 FTD 반등 확인 전까지는 '눈으로만 관찰'하십시오."
        else:
            msg += "👉 *실전 대응*: 전고점/피벗 돌파 시 -4% 손절선 잡고 1차 분할 매수"
    else:
        msg += "ℹ️ 정체/저변동성 종목 배제 후 조건 통과 종목 0개 (현금 보존 국면)"
        
    print(f"전송 완료. 통과 종목 {total_count}개")
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()