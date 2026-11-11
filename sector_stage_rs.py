import os
import time
import requests
import pandas as pd
import yfinance as yf

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(text: str):
    """텔레그램 메시지 발송 (마크다운 파싱 실패 시 일반 텍스트 재전송)"""
    if not BOT_TOKEN or not CHAT_ID:
        print("[콘솔 출력]\n" + text)
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    for attempt in range(1, 4):
        try:
            resp = requests.post(url, json=payload, timeout=20)
            if resp.status_code == 200:
                return
            else:
                # 마크다운 특수문자 에러 시 일반 텍스트 재시도
                payload.pop("parse_mode", None)
                resp_fb = requests.post(url, json=payload, timeout=20)
                if resp_fb.status_code == 200:
                    return
        except Exception as e:
            print(f"[{attempt}/3] 텔레그램 전송 실패: {e}")
        time.sleep(2)

# ==========================================
# 📊 미국 핵심 31개 서브섹터 & 테마 ETF 맵
# ==========================================
SECTOR_MAP = {
    # 1. 테크 & 성장 (Tech & Growth)
    "SMH": "반도체",
    "IGV": "소프트웨어/SaaS",
    "CIBR": "사이버보안",
    "BOTZ": "AI/로보틱스",
    "FINX": "핀테크/결제",
    "FDN": "인터넷기업",
    
    # 2. 산업 & 미래 인프라 (Industrials & Infrastructure)
    "ITA": "우주항공/방위산업",
    "PAVE": "미국 인프라/건설",
    "GRID": "전력망/스마트그리드",
    "IYT": "운송/물류",
    "JETS": "항공사",
    
    # 3. 원자재 & 에너지 (Materials & Energy)
    "XOP": "원유/가스탐사",
    "OIH": "유전서비스/장비",
    "URA": "우라늄/원자력",
    "COPX": "구리/광물",
    "XME": "금속/채굴",
    "GDX": "금광",
    "TAN": "태양광에너지",
    
    # 4. 바이오 & 헬스케어 (Biotech & Healthcare)
    "XBI": "바이오테크",
    "IHI": "의료기기/장비",
    "XPH": "제약/신약",
    "IHF": "건강보험/의료서비스",
    
    # 5. 소비재 & 주택 (Consumer & Housing)
    "ITB": "주택건설",
    "XRT": "소매/유통",
    "PEJ": "레저/식당/여행",
    
    # 6. 금융 세부 (Financial Sub-sectors)
    "KRE": "지역은행",
    "KBE": "상업은행",
    "IAK": "보험",
    "IAI": "증권/거래소",
    
    # 7. 방어 & 배당 & 부동산 (Defensive & Real Estate)
    "XLU": "유틸리티(전력/가스)",
    "XLP": "필수소비재",
    "VNQ": "부동산리츠"
}

def determine_stage(close: pd.Series) -> tuple[str, str]:
    """와인스타인 / 미네르비니 이평선 정배열 기준 Stage 판정"""
    sma50 = close.rolling(50).mean().iloc[-1]
    sma150 = close.rolling(150).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1]
    sma200_20d_ago = close.rolling(200).mean().iloc[-20]
    curr = close.iloc[-1]

    # 200일선 우상향 여부
    ma200_rising = sma200 > sma200_20d_ago

    # Stage 2 (확정 상승): 가격 > 50 > 150 > 200 & 200일선 우상향
    if curr > sma50 and sma50 > sma150 and sma150 > sma200 and ma200_rising:
        return "Stage 2 (정배열 상승)", "🟢"
    # Stage 2 초기 (50일/200일선 돌파 안착)
    elif curr > sma50 and curr > sma200 and ma200_rising:
        return "Stage 2 진입 (초기)", "🟡"
    # Stage 4 (하락 추세): 200일선 하회 및 데드크로스
    elif curr < sma200 and sma50 < sma200:
        return "Stage 4 (역배열 하락)", "🔴"
    # Stage 1/3 (박스권 횡보 / 전환기)
    else:
        return "Stage 1/3 (횡보/전환)", "⚪"

def calculate_rs(etf_close: pd.Series, spy_close: pd.Series) -> float:
    """SPY 대비 상대강도(RS Line)의 최근 60거래일(3개월) 모멘텀 추산"""
    rs_line = etf_close / spy_close
    rs_mom_3m = (rs_line.iloc[-1] - rs_line.iloc[-60]) / rs_line.iloc[-60] * 100
    return round(rs_mom_3m, 2)

def main():
    symbols = list(SECTOR_MAP.keys()) + ["SPY"]
    print(f"서브섹터 ETF {len(SECTOR_MAP)}개 및 SPY 다운로드 중...")
    
    # 1년치 데이터 일괄 다운로드
    data = yf.download(symbols, period="1y", group_by='ticker', progress=False)
    spy_close = data["SPY"]["Close"].dropna()

    results = []
    for ticker, name in SECTOR_MAP.items():
        try:
            df = data[ticker].dropna(subset=["Close"])
            if len(df) < 200:
                continue
            
            close = df["Close"]
            stage_str, stage_badge = determine_stage(close)
            rs_score = calculate_rs(close, spy_close)
            
            results.append({
                "ticker": ticker,
                "name": name,
                "price": round(close.iloc[-1], 2),
                "stage": stage_str,
                "badge": stage_badge,
                "rs_3m": rs_score
            })
        except Exception:
            continue

    # RS가 높은 순(시장 대비 초과수익 순) 정렬
    results.sort(key=lambda x: x["rs_3m"], reverse=True)

    # 1. Tier 1: 확정 Stage 2 + 시장 초과수익 (RS > 0)
    leading_stage2 = [r for r in results if "Stage 2 (정배열 상승)" in r["stage"] and r["rs_3m"] > 0]
    
    # 2. Stage 2 초기 전환군 (바닥 탈출 후보)
    emerging_stage2 = [r for r in results if "Stage 2 진입" in r["stage"]]
    
    # 3. 하락/역배열 군 (Stage 4)
    lagging_stage4 = [r for r in results if "Stage 4" in r["stage"]][:5]

    # ==========================================
    # 텔레그램 리포트 메시지 작성
    # ==========================================
    msg = f"📊 *[미국 31개 서브섹터 Stage & RS 주도 산업 분석]*\n"
    msg += f"• **진단 대상**: 핵심 31개 산업 ETF (vs SPY 기준 3개월 RS)\n"
    msg += f"• **Tier 1 확정 주도주**: `{len(leading_stage2)}개 산업` 포착\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    # 1. Tier 1 주도 산업 리스트
    msg += f"🏆 *[Tier 1 최우선 공략 산업 (Stage 2 + RS 강세)]*\n"
    if leading_stage2:
        for idx, r in enumerate(leading_stage2, 1):
            msg += f"*{idx}위. {r['name']}* (`{r['ticker']}`): `${r['price']}`\n"
            msg += f"   • 상태: `{r['stage']}`\n"
            msg += f"   • SPY 대비 3M RS: `+{r['rs_3m']}%` 🚀\n\n"
    else:
        msg += "   - 현재 정배열과 초과수익을 동시에 만족하는 주도 섹터 없음 (시장 조정 국면)\n\n"

    # 2. 초기 턴어라운드/바닥 탈출 관심 산업
    if emerging_stage2:
        msg += f"🌱 *[Stage 2 진입 초기 산업 (바닥 탈출 모니터링)]*\n"
        for r in emerging_stage2[:4]:
            rs_sign = "+" if r['rs_3m'] > 0 else ""
            msg += f"• {r['badge']} *{r['name']}* (`{r['ticker']}`): `${r['price']}` (RS: `{rs_sign}{r['rs_3m']}%`)\n"
        msg += "\n"

    # 3. 약세/역배열 산업 (매수 금지)
    if lagging_stage4:
        msg += f"⚠️ *[Stage 4 역배열 하락 산업 (진입 금지/관망)]*\n"
        for r in lagging_stage4:
            msg += f"• {r['badge']} *{r['name']}* (`{r['ticker']}`): RS `{r['rs_3m']}%`\n"
        msg += "\n"

    msg += "👉 *가이드*: 개별 종목 매매 시 **Tier 1 주도 산업군**에 속해 있는 종목을 1순위로 선정하십시오."

    send_telegram(msg)

if __name__ == "__main__":
    main()
