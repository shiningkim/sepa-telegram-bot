import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
import FinanceDataReader as fdr
from concurrent.futures import ThreadPoolExecutor, as_completed

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ==========================================
# 0. 텔레그램 다중 방 동시 전송 함수 (쉼표 구분 지원)
# ==========================================
def send_telegram_msg(message: str):
    chat_ids = [cid.strip() for cid in str(CHAT_ID).split(",") if cid.strip()]
    
    for cid in chat_ids:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": cid,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        for attempt in range(1, 4):
            try:
                resp = requests.post(url, json=payload, timeout=25)
                if resp.status_code == 200:
                    break
            except Exception as e:
                print(f"[{cid}] 전송 오류 ({attempt}/3): {e}")
                time.sleep(2)

# ==========================================
# 1. 국내 시총 상위 500개 종목 풀 (스팩/우선주 제외)
# ==========================================
def get_korea_targets():
    df_krx = fdr.StockListing('KRX')
    df_clean = df_krx[~df_krx['Name'].str.contains('스팩|우$|우B$|1호|2호|3호', regex=True, na=False)]
    
# 기존: 코스피 200 + 코스닥 300 = 500개
# 추천: 코스피 300 + 코스닥 500 = 800개 (시총 약 1,500억 원 선까지 커버)
    kospi = df_clean[df_clean['Market'] == 'KOSPI'].sort_values(by='Marcap', ascending=False).head(300)
    kosdaq = df_clean[df_clean['Market'] == 'KOSDAQ'].sort_values(by='Marcap', ascending=False).head(500)
    
    targets = []
    for _, row in kospi.iterrows():
        targets.append((row['Code'], row['Name'], '코스피'))
    for _, row in kosdaq.iterrows():
        targets.append((row['Code'], row['Name'], '코스닥'))
    return targets

# ==========================================
# 2. Stage 1 -> 2 전환기 VCP 판정 엔진 (초입 최적화)
# ==========================================
def analyze_korea_early_stage2(ticker, name, market_type, start_date):
    try:
        df = fdr.DataReader(ticker, start=start_date)
        if len(df) < 220:
            return None

        close = df['종가'] if '종가' in df.columns else df['Close']
        high = df['고가'] if '고가' in df.columns else df['High']
        low = df['저가'] if '저가' in df.columns else df['Low']
        volume = df['거래량'] if '거래량' in df.columns else df['Volume']

        curr_p = close.iloc[-1]
        vol_avg50 = volume.rolling(50).mean().iloc[-1]
        daily_val = curr_p * vol_avg50
        
        # 1) 유동성 필터 통합: 주가 3,000원 이상, 50일 평균 거래량 10만 주 이상, 일거래대금 20억 원 이상
        if curr_p < 3000 or vol_avg50 < 100000 or daily_val < 2_000_000_000:
            return None

        # 2) 평소 주가 탄력성 검증 (14일 ATR 비율 >= 2.5% : 둔한 가치주 배제)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_ratio = (tr.rolling(14).mean().iloc[-1] / curr_p) * 100
        if atr_ratio < 2.5:
            return None

        # 3) 이평선 계산
        sma50_series = close.rolling(50).mean()
        sma50 = sma50_series.iloc[-1]
        sma50_10d = sma50_series.iloc[-10]
        
        sma200_series = close.rolling(200).mean()
        sma200 = sma200_series.iloc[-1]
        sma200_20d = sma200_series.iloc[-20]

        # 200일선 수평화 (Stage 1 바닥 박스권: 20일간 기울기 -0.6% ~ +1.0%)
        slope_200 = (sma200 - sma200_20d) / sma200_20d * 100
        is_stage1_flattening = -0.6 <= slope_200 <= 1.0

        # [수정됨] Stage 2 초입 주가 위치: 200일선·50일선 돌파 안착 + 50일선 상승 전환 시작
        is_above_key_mas = (curr_p > sma200) and (curr_p > sma50) and (sma50 > sma50_10d)

        # 4) 최근 6개월(120거래일) 베이스 박스권 상단(피벗) 및 깊이 (35% 이내)
        base_high_120d = high.iloc[-120:].max()
        base_low_120d = low.iloc[-120:].min()
        base_depth = (base_high_120d - base_low_120d) / base_high_120d * 100
        is_sound_base = base_depth <= 35.0

        # 5) 베이스 피벗 저항선 턱밑 위치 (-6.0% ~ 0.0%)
        gap_from_pivot = (curr_p - base_high_120d) / base_high_120d * 100
        is_near_pivot = -6.0 <= gap_from_pivot <= 0.0

        # 6) 거래량 고갈 VDU (15% ~ 55% 사이)
        vol_ratio = (volume.iloc[-1] / vol_avg50) * 100
        is_vdu = (15.0 <= vol_ratio <= 55.0)
        
        # 7) 5일 캔들 응축 (1.5% ~ 6.5% 사이)
        recent_5d_range = ((high.iloc[-5:].max() - low.iloc[-5:].min()) / curr_p) * 100
        is_tight = (1.5 <= recent_5d_range <= 6.5)

        if is_stage1_flattening and is_above_key_mas and is_sound_base and is_near_pivot and is_vdu and is_tight:
            return {
                "name": name,
                "ticker": ticker,
                "market": market_type,
                "price": int(curr_p),
                "pivot": int(base_high_120d),
                "gap": round(gap_from_pivot, 1),
                "base_depth": round(base_depth, 1),
                "vol_ratio": round(vol_ratio, 1),
                "tight_pct": round(recent_5d_range, 1),
                "atr_pct": round(atr_ratio, 1),
                "stop_loss": int(curr_p * 0.96)  # -4% 손절 기준가
            }
    except Exception:
        return None
    return None

def main():
    today = datetime.today()
    start_date = (today - timedelta(days=365)).strftime("%Y-%m-%d")
    
    targets = get_korea_targets()
    print(f"한국장 Stage 1 -> 2 전환기 스크리닝 대상: {len(targets)}개 종목")

    passed = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(analyze_korea_early_stage2, t[0], t[1], t[2], start_date): t for t in targets}
        for future in as_completed(futures):
            res = future.result()
            if res:
                passed.append(res)

    passed.sort(key=lambda x: x['gap'], reverse=True)
    total_count = len(passed)

    msg = f"🐣 *[국내장 Stage 1 탈출 ➔ Stage 2 초입 VCP 종목 ({total_count}개)]*\n"
    msg += "_기준: 6개월 박스권 매집 + 200일선 평탄화 후 상향 돌파 + 50일선 턴어라운드 + 피벗 턱밑 VDU 고갈_\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    if passed:
        for idx, s in enumerate(passed[:15], 1):
            msg += f"{idx}. ⭐ *{s['name']}* (`{s['ticker']}` / {s['market']}): `{s['price']:,}원`\n"
            msg += f"   • 베이스 피벗 저항선: `{s['pivot']:,}원` (괴리율: `{s['gap']}%`)\n"
            msg += f"   • 6개월 박스권 깊이: `{s['base_depth']}%` (바닥 다지기)\n"
            msg += f"   • 거래량 마름(VDU): `평균의 {s['vol_ratio']}%` 🧊\n"
            msg += f"   • 5일 캔들 응축: `진폭 {s['tight_pct']}%` (일변동: `{s['atr_pct']}%`)\n"
            msg += f"   • 권장 스탑로스: `{s['stop_loss']:,}원` (-4%)\n\n"
        msg += "👉 *실전 전략*: 베이스 피벗 저항선 대량 거래 돌파 시 1차 분할 매수, 박스권 복귀 시 기계적 컷"
    else:
        msg += "ℹ️ 오늘 기준 Stage 1 탈출 직전의 엄격한 VCP 조건을 충족한 종목이 없습니다 (바닥 형성 지속)."

    print(f"스크리닝 완료: {total_count}개 종목 포착")
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
