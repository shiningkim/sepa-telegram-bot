import os
import yfinance as yf
import FinanceDataReader as fdr
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# ==========================================
# 1. 스탠 와인스타인 & 미네르비니 4단계 판정 함수
# ==========================================
def determine_stage(curr_p, sma50, sma150, sma200, sma200_20d, high_52w, low_52w):
    """
    Stage 1: 기초 형성 / 바닥 다지기 (200일선 평탄 횡보)
    Stage 2: 본격 상승 국면 (정배열 우상향, 최적의 매수 구간)
    Stage 3: 천장 / 분산 국면 (변동성 확대, 200일선 평탄화)
    Stage 4: 본격 하락 국면 (역배열 및 200일선 하향)
    """
    sma200_slope = (sma200 - sma200_20d) / sma200_20d * 100  # 20일간 200일선 기울기(%)
    
    # Stage 2: 본격 상승 (정배열 + 200일선 확실한 우상향)
    if curr_p > sma50 and sma50 > sma150 and sma150 > sma200 and sma200_slope > 0.3:
        stage = "🟢 Stage 2 (본격 상승 국면)"
        desc = "추세 정배열 가속 중. SEPA 템플릿 최적의 매수 타겟 구간입니다."
        action = "피벗/VCP 돌파 시 적극 진입 고려"
    # Stage 4: 본격 하락 (200일선 아래 + 하향세)
    elif curr_p < sma200 and sma200_slope < 0:
        stage = "🔴 Stage 4 (본격 하락 국면)"
        desc = "장기 이평선 아래에서 주가가 흘러내리는 전형적인 역배열 약세장입니다."
        action = "절대 매수 금지 (낙폭과대 매수도 금지)"
    # Stage 3: 천장 / 기관 분산 (고점 부근에서 50일선 이탈 또는 200일선 평탄화)
    elif curr_p >= high_52w * 0.75 and (curr_p < sma50 or sma200_slope <= 0.3):
        stage = "🟡 Stage 3 (천장 / 분산 국면)"
        desc = "기관들의 물량 털기(Distribution)가 진행 중이며 변동성이 커지는 위험 구간입니다."
        action = "신규 매수 금지, 보유자 분할 익절/탈출"
    # Stage 1: 바닥 횡보
    else:
        stage = "⚪ Stage 1 (바닥 형성 / 횡보 국면)"
        desc = "하락을 멈추고 바닥을 다지는 중이나 아직 상승 모멘텀(Stage 2)으로 전환되지 않았습니다."
        action = "매수 금지 (Stage 2 돌파 확인 전까지 관망)"
        
    return stage, desc, action

# ==========================================
# 2. 미네르비니 종목 진단 엔진 (한/미 공용)
# ==========================================
def diagnose_stock(symbol: str) -> str:
    symbol = symbol.strip().upper()
    df = None
    name = symbol
    is_korean = False

    # 한국 주식 판별 (6자리 숫자 티커 또는 한글 종목명)
    if symbol.isdigit() and len(symbol) == 6:
        is_korean = True
        try:
            df = fdr.DataReader(symbol)
        except Exception:
            return f"❌ 종목 코드 `{symbol}`의 데이터를 불러올 수 없습니다."
    elif any('\uac00' <= char <= '\ud7a3' for char in symbol):
        is_korean = True
        try:
            df_krx = fdr.StockListing('KRX')
            matched = df_krx[df_krx['Name'] == symbol]
            if matched.empty:
                return f"❌ 국내 종목명 `{symbol}`을(를) 찾을 수 없습니다. 정확한 명칭을 입력해 주세요."
            code = matched.iloc[0]['Code']
            name = f"{symbol} ({code})"
            df = fdr.DataReader(code)
        except Exception:
            return f"❌ `{symbol}` 데이터 조회 중 오류가 발생했습니다."
    else:
        # 미국 주식
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1y")
            if df is None or len(df) < 50:
                return f"❌ 미국 티커 `{symbol}`을(를) 찾을 수 없습니다."
        except Exception:
            return f"❌ 미국 티커 `{symbol}` 조회 실패."

    if df is None or len(df) < 180:
        return f"⚠️ `{name}`: 분석을 위한 데이터가 부족합니다 (최소 180거래일 일봉 필요)."

    # 컬럼 표준화
    close = df['종가'] if '종가' in df.columns else df['Close']
    high = df['고가'] if '고가' in df.columns else df['High']
    low = df['저가'] if '저가' in df.columns else df['Low']
    volume = df['거래량'] if '거래량' in df.columns else df['Volume']

    curr_p = close.iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    sma150 = close.rolling(150).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1]
    sma200_20d = close.rolling(200).mean().iloc[-20]
    high_52w = close.max()
    low_52w = close.min()

    vol_avg50 = volume.rolling(50).mean().iloc[-1]
    vol_ratio = (volume.iloc[-1] / vol_avg50) * 100 if vol_avg50 > 0 else 100.0
    drop_pct = (curr_p - high_52w) / high_52w * 100
    tight_pct = ((high.iloc[-5:].max() - low.iloc[-5:].min()) / curr_p) * 100

    # 1) Stage 1~4 판정
    stage, stage_desc, stage_action = determine_stage(curr_p, sma50, sma150, sma200, sma200_20d, high_52w, low_52w)

    # 2) 미네르비니 세부 지표 체크 (O / X)
    chk_align = "✅ 통과" if (curr_p > sma50 > sma150 > sma200) else "❌ 미흡"
    chk_200up = "✅ 우상향" if sma200 > sma200_20d else "❌ 하향/평탄"
    chk_near_high = "✅ 최상위 (-8% 이내)" if drop_pct >= -8.0 else ("⚠️ 관찰권 (-15% 이내)" if drop_pct >= -15.0 else "❌ 괴리 큼")
    chk_vdu = "🧊 VDU 고갈 (50% 이하)" if vol_ratio <= 50.0 else ("🔥 대량 수급 (120% 이상)" if vol_ratio >= 120.0 else "⚪ 평범")
    chk_tight = "✅ 극단적 응축 (6% 이하)" if tight_pct <= 6.0 else "❌ 변동성 큼"

    price_str = f"{int(curr_p):,}원" if is_korean else f"${curr_p:.2f}"
    high_str = f"{int(high_52w):,}원" if is_korean else f"${high_52w:.2f}"

    # 메시지 생성
    res = f"📊 *[SEPA 종목 정밀 진단: {name}]*\n"
    res += f"• **현재가**: `{price_str}` (52주 고점: `{high_str}`)\n\n"
    
    # 🌟 Stage 주기 진단 표기
    res += f"🎯 **[추세 주기 진단]**\n"
    res += f"• **상태**: {stage}\n"
    res += f"• **해설**: _{stage_desc}_\n\n"
    
    res += f"📋 **[미네르비니 템플릿 채점표]**\n"
    res += f"1. 이평선 정배열 (50>150>200): {chk_align}\n"
    res += f"2. 200일선 장기 추세: {chk_200up}\n"
    res += f"3. 52주 신고가 근접도: `{drop_pct:.1f}%` ({chk_near_high})\n"
    res += f"4. 오늘 거래량: `평균의 {vol_ratio:.1f}%` ({chk_vdu})\n"
    res += f"5. 최근 5일 주가 진폭: `{tight_pct:.1f}%` ({chk_tight})\n"
    res += "━━━━━━━━━━━━━━━━━━━━\n"

    # 종합 행동 지침
    if "Stage 2" in stage and drop_pct >= -8.0 and vol_ratio <= 60.0 and tight_pct <= 8.0:
        res += "🏆 *종합 판정: Tier 1 A급 VCP 준비 완료*\n"
        res += f"👉 *실전 행동*: 시장 신호등 확인 후 {stage_action}"
    elif "Stage 2" in stage:
        res += "👀 *종합 판정: Stage 2 상승 추세 유지 (핸들 대기)*\n"
        res += "👉 *실전 행동*: 기본 추세는 Stage 2이나, 진폭 축소(Tightness) 또는 VDU 거래량 고갈이 더 완성되어야 안전합니다."
    else:
        res += f"⚠️ *종합 판정: 매수 부적합 ({stage.split()[0]})*\n"
        res += f"👉 *실전 행동*: {stage_action}"

    return res

# ==========================================
# 3. 텔레그램 명령어 핸들러
# ==========================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 *미네르비니 SEPA 트레이딩 비서 가동 중*\n\n"
        "스마트폰에서 아래 명령어로 Stage 1~4 주기와 VCP 조건을 진단받으세요:\n"
        "• `/진단 [티커 또는 종목명]` : Stage 주기 + 템플릿 O/X\n"
        "  - 예: `/진단 TSLA`\n"
        "  - 예: `/진단 FROG`\n"
        "  - 예: `/진단 삼천당제약` (또는 `/진단 000250`)\n"
        "• `/도움말` : 사용법 안내"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_diagnose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("💡 티커나 종목명을 함께 입력해 주세요.\n예: `/진단 TSLA` 또는 `/진단 000250`", parse_mode="Markdown")
        return
        
    target = context.args[0]
    await update.message.reply_text(f"🔍 `{target}` Stage 주기 및 미네르비니 조건 분석 중...", parse_mode="Markdown")
    report = diagnose_stock(target)
    await update.message.reply_text(report, parse_mode="Markdown")

if __name__ == '__main__':
    if not BOT_TOKEN:
        print("BOT_TOKEN 누락")
        exit(1)
        
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("도움말", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("진단", cmd_diagnose))
    
    print("대화형 봇 가동 시작. 텔레그램 메시지 수신 대기 중...")
    app.run_polling()
