import os
import time
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_msg(message: str):
    """텔레그램 메시지 전송 (최대 3회 재시도 및 25초 타임아웃)"""
    if not BOT_TOKEN or not CHAT_ID:
        print("[Telegram] 토큰 또는 Chat ID가 설정되지 않았습니다.")
        return
        
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
# 🚦 1. 윌리엄 오닐 시장 신호등 판정 함수
# ==========================================
def analyze_market_traffic_light():
    """S&P 500 지수를 바탕으로 분산일 및 FTD를 계산하여 신호등 판정"""
    try:
        spy = yf.Ticker("^GSPC")
        df = spy.history(period="6mo")
        if len(df) < 50:
            return "🟡 노란불", "지수 데이터 부족", "50%", 0, 0
            
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
                
        # 신호등 상태 머신 판정
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
        # 비상용 기본 티커 목록 (URL 연결 장애 시)
        return ["NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "FROG", "AMAL", "TSLA", "VRTX", "MRK"]

# ==========================================
# 📊 3. 윌리엄 오닐 스타일 가중 RS 계산 및 랭킹 정렬
# ==========================================
def calculate_rs_score(close_series: pd.Series) -> float:
    """
    윌리엄 오닐 가중 RS 공식:
    RS = (2 * 3M 수익률) + 6M 수익률 + 9M 수익률 + 12M 수익률
    """
    try:
        if len(close_series) < 180:
            return 0.0
            
        curr = close_series.iloc[-1]
        p_3m = (curr - close_series.iloc[-60]) / close_series.iloc[-60] if len(close_series) >= 60 else 0
        p_6m = (curr - close_series.iloc[-120]) / close_series.iloc[-120] if len(close_series) >= 120 else 0
        p_9m = (curr - close_series.iloc[-180]) / close_series.iloc[-180] if len(close_series) >= 180 else 0
        p_12m = (curr - close_series.iloc[0]) / close_series.iloc[0]

        return float((2 * p_3m) + p_6m + p_9m + p_12m)
    except Exception:
        return 0.0

def rank_candidates_by_rs(candidates: list) -> list:
    """후보군 내 상대 강도를 1~99점 백분위 RS Rating으로 환산하고 내림차순 정렬"""
    if not candidates:
        return []

    candidates.sort(key=lambda x: x.get("rs_raw", 0.0), reverse=True)
    total = len(candidates)
    
    for idx, item in enumerate(candidates):
        if total == 1:
            item["rs_score"] = 99
        else:
            # 1위 종목이 99점에 수렴하도록 상대 백분위 부여
            item["rs_score"] = 99 - int((idx / total) * 98)
            
    return candidates

# ==========================================
# 💎 4. CANSLIM 펀더멘털(C, A, I) 정밀 진단
# ==========================================
def check_canslim_fundamentals(ticker: str) -> dict:
    """
    - C (Current EPS): 최근 분기 EPS 성장률 >= 20%
    - A (Annual EPS): Forward EPS 성장 잠재력 >= 15%
    - I (Institutions): 기관 지분율 >= 20%
    """
    summary = {
        "ticker": ticker,
        "is_canslim": False,
        "c_pass": False,
        "a_pass": False,
        "i_pass": False,
        "eps_growth": "N/A",
        "inst_ownership": "N/A",
        "fwd_growth": "N/A",
    }
    try:
        t = yf.Ticker(ticker)
        info = t.info

        # C: 최근 분기 실적 YoY
        eg = info.get("earningsGrowth")
        if eg is not None:
            summary["eps_growth"] = f"{eg * 100:.1f}%"
            if eg >= 0.20:
                summary["c_pass"] = True

        # A: Trailing vs Forward EPS 비교
        t_eps = info.get("trailingEps")
        f_eps = info.get("forwardEps")
        if t_eps and f_eps and t_eps > 0:
            growth = (f_eps - t_eps) / t_eps
            summary["fwd_growth"] = f"{growth * 100:.1f}%"
            if growth >= 0.15:
                summary["a_pass"] = True

        # I: 기관 보유 비중
        inst = info.get("heldPercentInstitutions")
        if inst is not None:
            summary["inst_ownership"] = f"{inst * 100:.1f}%"
            if inst >= 0.20:
                summary["i_pass"] = True

        # 판정: C(분기 실적) 필수 충족 + (A 또는 I 충족 시 CANSLIM 합격)
        if summary["c_pass"] and (summary["a_pass"] or summary["i_pass"]):
            summary["is_canslim"] = True

    except Exception as e:
        print(f"[{ticker}] CANSLIM 진단 예외: {e}")

    return summary

# ==========================================
# 5. 메인 실행 루틴 (SEPA + RS 우선순위 + CANSLIM 2단계)
# ==========================================
def main():
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
                    
                    # 1. 가격 및 기본 유동성 필터 ($12 이상, 50일 평균 거래대금 500만 달러 이상)
                    vol_avg50 = volume.rolling(50).mean().iloc[-1]
                    dollar_vol = current_price * vol_avg50
                    if current_price < 12.0 or vol_avg50 < 250000 or dollar_vol < 5000000:
                        continue
                        
                    # 2. 평소 주가 탄력성 검증 (14일 ATR 비율 >= 2.3% : 둔한 은행/보험주 배제)
                    tr1 = high - low
                    tr2 = (high - close.shift(1)).abs()
                    tr3 = (low - close.shift(1)).abs()
                    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                    atr14 = tr.rolling(14).mean().iloc[-1]
                    atr_ratio = (atr14 / current_price) * 100
                    if atr_ratio < 2.3:
                        continue

                    # 3. 3개월 모멘텀 검증 (최근 60거래일간 주가 +12% 이상 상승한 주도주)
                    ret_60d = (current_price - close.iloc[-60]) / close.iloc[-60] * 100
                    if ret_60d < 12.0:
                        continue

                    sma50 = close.rolling(50).mean().iloc[-1]
                    sma150 = close.rolling(150).mean().iloc[-1]
                    sma200 = close.rolling(200).mean().iloc[-1]
                    sma200_20d_ago = close.rolling(200).mean().iloc[-20]
                    
                    high_52w = close.max()
                    low_52w = close.min()
                    
                    # 4. 미네르비니 추세 템플릿
                    c_trend1 = current_price > sma150 and current_price > sma200
                    c_trend2 = sma150 > sma200
                    c_trend3 = sma200 > sma200_20d_ago
                    c_trend4 = sma50 > sma150 and sma50 > sma200
                    c_trend5 = current_price > sma50
                    c_trend6 = current_price >= (low_52w * 1.30)
                    
                    # 5. 정예 VCP 필터
                    drop_pct = (current_price - high_52w) / high_52w * 100
                    c_near_high = drop_pct >= -8.0
                    
                    vol_ratio = (volume.iloc[-1] / vol_avg50) * 100 if vol_avg50 > 0 else 100.0
                    c_vdu = (15.0 <= vol_ratio <= 55.0)
                    
                    recent_5d_range = ((high.iloc[-5:].max() - low.iloc[-5:].min()) / current_price) * 100
                    c_tight = (1.5 <= recent_5d_range <= 6.0)
                    
                    if (c_trend1 and c_trend2 and c_trend3 and c_trend4 and 
                        c_trend5 and c_trend6 and c_near_high and c_vdu and c_tight):
                        
                        # 오닐 가중 RS Raw Score 사전 계산 (추가 네트워크 호출 없이 다운로드된 df 활용)
                        rs_raw_val = calculate_rs_score(close)
                        
                        passed_stocks.append({
                            "ticker": ticker,
                            "price": round(current_price, 2),
                            "drop_pct": round(drop_pct, 1),
                            "vol_ratio": round(vol_ratio, 1),
                            "tight_pct": round(recent_5d_range, 1),
                            "atr_pct": round(atr_ratio, 1),
                            "ret_60d": round(ret_60d, 1),
                            "high_52w": round(high_52w, 2),
                            "rs_raw": rs_raw_val
                        })
                except Exception:
                    continue
        except Exception:
            continue

    # ==========================================
    # [우선순위 정렬] 오닐 가중 RS 기준으로 종목 정렬 및 1~99 점수 산출
    # ==========================================
    ranked_stocks = rank_candidates_by_rs(passed_stocks)
    total_count = len(ranked_stocks)

    # ==========================================
    # 🚀 [1단계 발송] SEPA Tier 1 기술적 선별 결과
    # ==========================================
    msg1 = f"🚦 *[SEPA 시장 신호등 & 데일리 브리핑]*\n"
    msg1 += f"• **상태**: {status}\n"
    msg1 += f"• **S&P 500 종가**: `{index_price}`pt (유효 분산일: {dist_count}개)\n"
    msg1 += f"• **권장 현금 비중**: `{cash_guideline}`\n"
    msg1 += f"• **진단**: _{comment}_\n"
    msg1 += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if "🔴 빨간불" in status:
        msg1 += f"⚠️ *[하락장 경보: 신규 매수 전면 금지 (현금 100%)]*\n"
        msg1 += f"시장 하락 압력 속에서도 차트를 방어 중인 탄력 성장주 **총 {total_count}개**입니다. (FTD 전까지 관심종목 관찰)\n\n"
    else:
        msg1 += f"🏆 *[오늘의 Tier 1 탄력 주도주 ({total_count}개) - RS 우선순위 순]*\n"
        msg1 += "_필터: 고점 -8% + VDU 고갈(15~55%) + 5일 진폭(1.5~6%) + RS 가중치 정렬_\n\n"

    if ranked_stocks:
        for idx, s in enumerate(ranked_stocks[:20], 1):
            msg1 += f"*{idx}위. {s['ticker']}* (⭐ **RS {s['rs_score']}**): `${s['price']}`\n"
            msg1 += f"   • 고점 괴리: `{s['drop_pct']}%` (전고점 `${s['high_52w']}`)\n"
            msg1 += f"   • 거래량 수축: `평균의 {s['vol_ratio']}%` 🧊\n"
            msg1 += f"   • 5일 캔들 응축: `진폭 {s['tight_pct']}%` (일변동: `{s['atr_pct']}%`)\n"
            msg1 += f"   • 3개월 모멘텀: `+{s['ret_60d']}%`\n\n"
            
        if "🔴 빨간불" in status:
            msg1 += "👉 *실전 전략*: 아무리 자리가 예뻐도 시장 FTD 확인 전까지는 '눈으로만 관찰'하십시오."
        else:
            msg1 += "👉 *실전 대응*: 피벗/핸들 상단 돌파 시 -4% 스탑로스로 1차 분할 진입"
    else:
        msg1 += "ℹ️ 정체/저변동성 종목 배제 후 조건 통과 종목 0개 (적절한 베이스 형성 대기)"
            
    send_telegram_msg(msg1)

    # 종목이 없으면 2단계 실적 체크를 건너뜁니다.
    if not ranked_stocks:
        return

    # 1단계와 2단계 메시지 사이 간격 (순차 노출 및 텔레그램 API 레이트 리밋 방지)
    time.sleep(2)

    # ==========================================
    # 💎 [2단계 발송] CANSLIM 펀더멘털 더블체크
    # ==========================================
    canslim_passed = []
    canslim_failed = []

    print("통과 종목 CANSLIM 펀더멘털 검증 중...")
    for s in ranked_stocks[:20]:
        c_eval = check_canslim_fundamentals(s['ticker'])
        c_eval["rs_score"] = s["rs_score"]
        c_eval["price"] = s["price"]
        
        if c_eval["is_canslim"]:
            canslim_passed.append(c_eval)
        else:
            canslim_failed.append(c_eval)

    msg2 = "💎 *[2단계] CANSLIM 펀더멘털 더블체크*\n"
    msg2 += f"SEPA 상위 {len(ranked_stocks[:20])}개 중 **{len(canslim_passed)}개 적합 판정**\n"
    msg2 += "━━━━━━━━━━━━━━━━━━━━\n\n"

    if canslim_passed:
        msg2 += "🌟 *[최우선 매수 후보: SEPA 기술적 + CANSLIM 실적 겸비]*\n"
        for idx, p in enumerate(canslim_passed, 1):
            msg2 += (
                f"**{idx}순위. {p['ticker']}** (RS: `{p['rs_score']}` | `${p['price']}`)\n"
                f"   • 분기 EPS 성장: `{p['eps_growth']}` (기준: +20% 이상)\n"
                f"   • 포워드 성장 전망: `{p['fwd_growth']}`\n"
                f"   • 기관 보유 지분율: `{p['inst_ownership']}`\n\n"
            )

    if canslim_failed:
        msg2 += "⚠️ *[차트만 완성형 (실적 기준 미달 또는 적자/데이터부족)]*\n"
        for f in canslim_failed:
            msg2 += f"• **{f['ticker']}** (RS `{f['rs_score']}`): 분기EPS `{f['eps_growth']}` / 기관 `{f['inst_ownership']}`\n"

    send_telegram_msg(msg2)

if __name__ == "__main__":
    main()
