import os
import time
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

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
        resp = requests.post(url, json=payload, timeout=25)
        if resp.status_code != 200:
            print(f"텔레그램 전송 실패: {resp.text}")
    except Exception as e:
        print(f"전송 오류: {e}")

# ==========================================
# 1. 미국 시장 지표 및 티커 풀 구성
# ==========================================
def get_us_universe():
    """S&P 500 및 나스닥 주요 대형/중형 성장주 풀 (약 500개)"""
    try:
        url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
        df = pd.read_csv(url)
        tickers = df['Symbol'].str.replace('.', '-', regex=False).tolist()
        return list(set(tickers))
    except Exception as e:
        print(f"티커 목록 로드 실패, 기본 풀 대체: {e}")
        return ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "FROG", "AMAL"]

# ==========================================
# 2. Stage 1 -> Stage 2 전환기 VCP 판정 엔진
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
        if curr_p < 10.0:  # 동전주/초소형주 필터링
            return None

        # 이평선
        sma50 = close.rolling(50).mean().iloc[-1]
        sma150 = close.rolling(150).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1]
        sma200_20d = close.rolling(200).mean().iloc[-20]

        # 1) 200일선의 평탄화 (Stage 1 바닥 박스권 특징: 20일간 기울기 -0.6% ~ +1.0% 사이)
        slope_200 = (sma200 - sma200_20d) / sma200_20d * 100
        is_stage1_flattening = -0.6 <= slope_200 <= 1.0

        # 2) Stage 2 전환 초입의 주가 위치: 200일선 및 50일선 돌파 안착
        is_above_key_mas = (curr_p > sma200) and (curr_p > sma50) and (sma50 > sma150)

        # 3) 최근 6개월(120거래일) 베이스 박스권 상단(피벗) 및 깊이
        base_high_120d = high.iloc[-120:].max()
        base_low_120d = low.iloc[-120:].min()
        base_depth = (base_high_120d - base_low_120d) / base_high_120d * 100

        # 베이스 깊이가 너무 깊지 않아야 함 (진폭 35% 이내의 단단한 다지기)
        is_sound_base = base_depth <= 35.0

        # 4) 베이스 피벗 저항선 턱밑 위치 (-6.0% ~ 0.0%)
        gap_from_pivot = (curr_p - base_high_120d) / base_high_120d * 100
        is_near_pivot = -6.0 <= gap_from_pivot <= 0.0

        # 5) VCP 거래량 수축(VDU) 및 5거래일 진폭 응축
        vol_avg50 = volume.rolling(50).mean().iloc[-1]
        if vol_avg50 < 100000:  # 유동성 최소 10만 주
            return None

        vol_ratio = (volume.iloc[-1] / vol_avg50) * 100
        is_vdu = vol_ratio <= 55.0  # 거래량 50일 평균의 55% 이하로 마름

        recent_5d_range = ((high.iloc[-5:].max() - low.iloc[-5:].min()) / curr_p) * 100
        is_tight = recent_5d_range <= 6.0  # 5일간 6% 이내의 극단적 응축

        if is_stage1_flattening and is_above_key_mas and is_sound_base and is_near_pivot and is_vdu and is_tight:
            return {
                "ticker": ticker,
                "price": round(curr_p, 2),
                "pivot": round(base_high_120d, 2),
                "gap": round(gap_from_pivot, 1),
                "base_depth": round(base_depth, 1),
                "vol_ratio": round(vol_ratio, 1),
                "tight_pct": round(recent_5d_range, 1),
                "stop_loss": round(curr_p * 0.96, 2)  # -4% 타이트 손절선
            }
    except Exception:
        return None
    return None

def main():
    tickers = get_us_universe()
    print(f"Stage 1 -> 2 전환기 스크리닝 대상: {len(tickers)}개 티커")

    passed = []
    chunk_size = 80
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            data = yf.download(chunk, period="1y", interval="1d", group_by='ticker', threads=True, progress=False)
            for t in chunk:
                if t in data.columns.levels[0]:
                    df = data[t].dropna()
                    res = analyze_early_stage2(df, t)
                    if res:
                        passed.append(res)
        except Exception as e:
            print(f"다운로드 배치 오류: {e}")
        time.sleep(1)

    # 피벗 저항선에 가장 가까운 순서대로 정렬
    passed.sort(key=lambda x: x['gap'], reverse=True)
    total_count = len(passed)

    msg = f"🐣 *[미국장 Stage 1 탈출 ➔ Stage 2 초입 VCP 종목 ({total_count}개)]*\n"
    msg += "_기준: 6개월 박스권 매집 + 200일선 평탄화 후 상향 돌파 + 피벗 턱밑 VDU 거래량 고갈_\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    if passed:
        for idx, s in enumerate(passed[:15], 1):
            msg += f"{idx}. ⭐ *{s['ticker']}*: `${s['price']}`\n"
            msg += f"   • 베이스 피벗 저항선: `${s['pivot']}` (괴리율: `{s['gap']}%`)\n"
            msg += f"   • 6개월 박스권 깊이: `{s['base_depth']}%` (바닥 다지기)\n"
            msg += f"   • 거래량 마름(VDU): `평균의 {s['vol_ratio']}%` 🧊\n"
            msg += f"   • 5일 캔들 응축: `진폭 {s['tight_pct']}%`\n"
            msg += f"   • 권장 스탑로스: `${s['stop_loss']}` (-4%)\n\n"
        msg += "👉 *실전 전략*: 베이스 피벗 저항선 대량 거래 돌파 시 1차 진입, 박스권 재진입 시 기계적 손절"
    else:
        msg += "ℹ️ 오늘 기준 Stage 1 탈출 직전의 엄격한 VCP 조건을 충족한 종목이 없습니다 (바닥 형성 지속)."

    print(f"스크리닝 완료: {total_count}개 종목 포착")
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()