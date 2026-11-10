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
# 1. 닛케이 225 전 종목 풀 (225개)
# ==========================================
def get_japan_universe() -> list:
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
# 2. 일본 Stage 1 -> 2 전환기 VCP 판정 엔진
# ==========================================
def analyze_japan_early_stage2(df, ticker):
    try:
        if len(df) < 220:
            return None

        close = df['Close']
        high = df['High']
        low = df['Low']
        volume = df['Volume']

        curr_p = close.iloc[-1]
        vol_avg50 = volume.rolling(50).mean().iloc[-1]
        daily_val = curr_p * vol_avg50

        # 1) 가격 및 유동성 필터 (주가 500엔 이상, 50일 평균 거래량 10만 주 이상, 일거래대금 5억 엔 이상)
        if curr_p < 500 or vol_avg50 < 100000 or daily_val < 500_000_000:
            return None

        # 2) 평소 주가 탄력성 검증 (14일 ATR 비율 >= 2.2% : 둔한 배당/상사/금융주 배제)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean().iloc[-1]
        atr_ratio = (atr14 / curr_p) * 100
        if atr_ratio < 2.2:
            return None

        # 3) 이평선 계산
        sma50 = close.rolling(50).mean().iloc[-1]
        sma150 = close.rolling(150).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1]
        sma200_20d = close.rolling(200).mean().iloc[-20]

        # 200일선 평탄화 (Stage 1 바닥 박스권: 20일간 기울기 -0.6% ~ +1.0% 사이)
        slope_200 = (sma200 - sma200_20d) / sma200_20d * 100
        if not (-0.6 <= slope_200 <= 1.0):
            return None

        # Stage 2 초입 위치: 200일선 및 50일선 돌파 안착
        if not (curr_p > sma200 and curr_p > sma50 and sma50 > sma150):
            return None

        # 4) 최근 6개월(120거래일) 베이스 박스권 상단(피벗) 및 깊이
        base_high_120d = high.iloc[-120:].max()
        base_low_120d = low.iloc[-120:].min()
        base_depth = (base_high_120d - base_low_120d) / base_high_120d * 100

        # 박스권 깊이 35% 이내의 단단한 다지기
        if base_depth > 35.0:
            return None

        # 베이스 피벗 저항선 턱밑 위치 (-6.0% ~ 0.0%)
        gap_from_pivot = (curr_p - base_high_120d) / base_high_120d * 100
        if not (-6.0 <= gap_from_pivot <= 0.0):
            return None

        # 5) VCP 거래량 수축(15% ~ 55%) 및 5거래일 진폭 응축(1.5% ~ 6.5%)
        vol_ratio = (volume.iloc[-1] / vol_avg50) * 100
        if not (15.0 <= vol_ratio <= 55.0):
            return None

        recent_5d_range = ((high.iloc[-5:].max() - low.iloc[-5:].min()) / curr_p) * 100
        if not (1.5 <= recent_5d_range <= 6.5):
            return None

        return {
            "ticker": ticker.replace(".T", ""),
            "price": round(curr_p, 1),
            "pivot": round(base_high_120d, 1),
            "gap": round(gap_from_pivot, 1),
            "base_depth": round(base_depth, 1),
            "vol_ratio": round(vol_ratio, 1),
            "tight_pct": round(recent_5d_range, 1),
            "atr_pct": round(atr_ratio, 1),
            "stop_loss": round(curr_p * 0.96, 1)
        }
    except Exception:
        return None

# ==========================================
# 3. 메인 실행 루틴
# ==========================================
def main():
    tickers = get_japan_universe()
    print(f"일본장 Stage 1 -> 2 전환기 스크리닝 대상: {len(tickers)}개 티커")

    passed = []
    chunk_size = 50
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            data = yf.download(chunk, period="1y", interval="1d", group_by='ticker', threads=True, progress=False)
            for t in chunk:
                try:
                    df = data[t] if len(chunk) > 1 else data
                    df = df.dropna(subset=['Close'])
                    res = analyze_japan_early_stage2(df, t)
                    if res:
                        passed.append(res)
                except Exception:
                    continue
        except Exception as e:
            print(f"다운로드 배치 오류: {e}")
            time.sleep(1)

    passed.sort(key=lambda x: x['gap'], reverse=True)
    total_count = len(passed)

    msg = f"🐣 *[일본장 Stage 1 탈출 ➔ Stage 2 초입 VCP 종목 ({total_count}개)]*\n"
    msg += "_기준: 6개월 박스권 매집 + 200일선 평탄화 후 상향 돌파 + 피벗 턱밑 VDU 고갈(15~55%) + 5일 진폭(1.5~6.5%)_\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    if passed:
        for idx, s in enumerate(passed[:15], 1):
            msg += f"{idx}. ⭐ *{s['ticker']}*: `¥{s['price']:,}`\n"
            msg += f"   • 베이스 피벗 저항선: `¥{s['pivot']:,}` (괴리율: `{s['gap']}%`)\n"
            msg += f"   • 6개월 박스권 깊이: `{s['base_depth']}%` (바닥 다지기)\n"
            msg += f"   • 거래량 마름(VDU): `평균의 {s['vol_ratio']}%` 🧊\n"
            msg += f"   • 5일 캔들 응축: `진폭 {s['tight_pct']}%` (일변동: `{s['atr_pct']}%`)\n"
            msg += f"   • 권장 스탑로스: `¥{s['stop_loss']:,}` (-4%)\n\n"
        msg += "👉 *실전 전략*: 베이스 피벗 저항선 대량 거래 돌파 시 1차 분할 진입, 박스권 재진입 시 기계적 손절"
    else:
        msg += "ℹ️ 오늘 기준 Stage 1 탈출 직전의 엄격한 VCP 조건을 충족한 종목이 없습니다 (바닥 형성 지속)."

    print(f"스크리닝 완료: {total_count}개 종목 포착")
    send_telegram_msg(msg)

if __name__ == "__main__":
    main()
