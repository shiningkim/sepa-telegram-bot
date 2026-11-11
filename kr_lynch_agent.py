import time

def get_market_universe(market_type="KOSPI", top_n=100):
    """
    market_type: 'KOSPI' (sosok=0) 또는 'KOSDAQ' (sosok=1)
    상위 top_n개 종목 코드 자동 수집
    """
    sosok = 0 if market_type == "KOSPI" else 1
    codes = []
    page = 1
    headers = {"User-Agent": "Mozilla/5.0"}
    
    while len(codes) < top_n and page <= 5:
        url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
        res = requests.get(url, headers=headers)
        # 테이블 내 종목 링크에서 코드 추출
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(res.text, "html.parser")
        links = soup.select("a.tltle")
        if not links:
            break
        for a in links:
            code = a["href"].split("code=")[-1]
            codes.append(code)
            if len(codes) >= top_n:
                break
        page += 1
    return codes

def main():
    print("모집단 수집 중 (코스피 100 + 코스닥 100)...")
    # 코스피 상위 100개, 코스닥 상위 100개 (총 200개)
    universe = get_market_universe("KOSPI", 100) + get_market_universe("KOSDAQ", 100)
    
    hits = []
    scanned_count = 0

    for code in universe:
        res = screen_kr_stock(code)
        if res:
            scanned_count += 1
            if res["is_hit"]:
                hits.append(res)
        time.sleep(0.1) # 네이버 API 부하 방지용 짧은 딜레이

    if hits:
        # PEG가 가장 낮은 순(더 저평가된 순)으로 정렬하여 상위 10개만 리포트
        hits = sorted(hits, key=lambda x: x["peg"])[:10]
        
        msg = f"🇰🇷 *[피터 린치 Agent - 한국 저평가 고성장주]*\n"
        msg += f"• 검사: {scanned_count}개 / 통과: {len(hits)}개\n\n"
        for item in hits:
            msg += f"• *{item['name']} ({item['code']})*\n"
            msg += f"  - 주가: {item['price']:,}원\n"
            msg += f"  - PEG: `{item['peg']}` (PER: {item['per']} / 영업익성장: {item['growth']}%)\n"
            msg += f"  - 부채비율: `{item['debt_ratio']}%`\n\n"
    else:
        msg = f"🇰🇷 *[피터 린치 Agent - 한국 스크리닝 완료]*\n"
        msg += f"• 총 {scanned_count}개 종목 검사 완료\n"
        msg += f"• 조건 만족 종목이 없습니다."

    send_telegram(msg)
