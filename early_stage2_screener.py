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
# 1. 미국 상장 유니버스 수집 (2,500개 풀로 확장)
# ==========================================
def get_us_universe() -> list:
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
        return ["NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "FROG", "AMAL", "TSLA"]

# ==========================================
# 2. Stage 1 -> 2 전환기 VCP 판정 엔진
# ==========================================
def analyze_early_stage2(df, ticker):
    try:
        if len(df) < 220:
            return None

        close = df['Close']
        high = df['High']
        low = df['Low']
        volume = df['Volume']

        curr_p = close.iloc[-1]
        vol_avg50 = volume.rolling(50).mean().iloc[-1]
        dollar_vol = curr_p * vol_avg50

        # 가격 및 유동성 필터 ($10 이상, 50일 평균 거래량 25만 주 이상, 일거래대금 $5M 이상)
        if curr_p < 10.0 or vol_avg50 < 250000 or dollar_vol < 5000000:
            return None

        # 평소 주가 탄력성 검증 (14일 ATR 비율 >= 2.3% : 둔한 은행/보험주 배제)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean().iloc[-1]
        atr_ratio = (atr14 / curr_p) * 100
        if atr_ratio < 2.3:
            return None

        # 이평선 계산
        sma50 = close.rolling(50).mean().iloc[-1]
        sma150 = close.rolling(150).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1]
        sma200_20d = close.rolling(200).mean().iloc[-20]

        # 200일선 평탄화 (Stage 1 바닥 박스권: 20일간 기울기 -0.6% ~ +1.0% 사이)
        slope_200 = (sma200 - sma200_20d) / sma200_20d * 100
        if not (-0.6 <= slope_200 <= 1.0):
            return None

        # Stage 2 초입 주가 위치: 200일선 및 50일선 돌파 안착
        if not (curr_p > sma200 and curr_p > sma50 and sma50 > sma150):
            return None

        # 최근 6개월(120거래일) 베이스 박스권 상단(피벗) 및 깊이
        base_high_120d = high.iloc[-120:].max()
        base_low_120d = low.iloc[-120:].min()
        base_depth = (base_high_120d - base_low_120d) / base_high_120d * 100

        # 박스권 깊이 35% 이내 다지기
        if base_depth > 35.0:
            return None

        # 베이스 피벗 저항선 턱밑 위치 (-6.0% ~ 0.0%)
        gap_from_pivot = (curr_p - base_high_120d) / base_high_120d * 100
        if not (-6.0 <= gap_from_pivot <= 0.0):
            return None

        # VCP 거래량 수축(15% ~ 55%) 및 5거래일 진폭 응축(1.5% ~ 6.0%)
        vol_ratio = (volume.iloc[-1] / vol_avg50) * 100
        if not (15.0 <= vol_ratio <= 55.0):
            return None

        recent_5d_range = ((high.iloc[-5:].max() - low.iloc[-5:].min()) / curr_p) * 100
        if not (1.5 <= recent_5d_range <= 6.0):
            return None

        return {
            "ticker": ticker,
            "price": round(curr_p, 2),
            "pivot": round(base_high_120d, 2),
            "gap": round(gap_from_pivot, 1),
            "base_depth": round(base_depth, 1),
            "vol_ratio": round(vol_ratio, 1),
            "tight_pct": round(recent_5d_range, 1),
            "atr_pct": round(atr_ratio, 1),
            "stop_loss": round(curr_p * 0.96, 2)
        }
    except Exception:
        return None

# ==========================================
# 3. 메인 실행 루틴
# ==========================================
def main():
    tickers = get_us_universe()
    print(f"Stage 1 -> 2 전환기 스크리닝 대상: {len(tickers)}개 티커")

    passed = []
    chunk_size = 100
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            data = yf.download(chunk, period="1y", interval="1d", group_by='ticker', threads=True, progress=False)
            for t in chunk:
                try:
                    df = data[t] if len(chunk) > 1 else data
                    df = df.dropna(subset=['Close'])
                    res = analyze_early_stage2(df, t)
                    if res:
                        passed.append(res)
                except Exception:
                    continue
        except Exception as e:
            print(f"다운로드 배치 오류: {e}")
            time.sleep(1)

    passed.sort(key=lambda x: x['gap'], reverse=True)
    total_count = len(passed)

    msg = f"🐣 *[미국장 Stage 1 탈출 ➔ Stage 2 초입 VCP 종목 ({total_count}개)]*\n"
    msg += "_기준: 6개월 박스권 매집 + 200일선 평탄화 후 상향 돌파 + 피벗 턱밑 VDU 고갈(15~55%) + 5일 진폭(1.5~6%)_\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    if passed:
        for idx, s in enumerate(passed[:15], 1):
            msg += f"{idx}. ⭐ *{s['ticker']}*: `${s['price']}`\n"
            msg += f"   • 베이스 피벗 저항선: `${s['pivot']}` (괴리율: `{s['gap']}%`)\n"
            msg += f"   • 6개월 박스권 깊이: `{s['base_depth']}%` (바닥 다지기)\n"
            msg += f"   • 거래량 마름(VDU): `평균의 {s['vol_ratio']}%` 🧊\n"
            msg += f"   • 5일 캔들 응축: `진폭 {s['tight_pct']}%` (일변동: `{s['atr_pct']}%`)\n"
            msg += f"   • 권장 스탑로스: `${s['stop_loss']}` (-4%)\n\n"
        msg += "👉 *실전 전략*: 베이스 피벗 저항선 대량 거래 돌파 시 1차 분할 진입, 박스권 재진입 시 기계적 손절"
    else:
        msg += "ℹ️ 오늘 기준 Stage 1 탈출 직전의 엄격한 VCP 조건을 충족한 종목이 없습니다 (바닥 형성 지속)."

    print(f"스크리닝 완료: {total_count}개 종목 포착")
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
