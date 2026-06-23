"""menus + category 재정리 (사용자 친화 버전).

문제:
1. menus에 '한식','중국요리','해물' 등 카테고리어가 메뉴로 들어가 있음
2. category='기타'가 43% — cat_map 부실로 분류 안 됨

해결:
- menus: 카테고리어 강제 제외 + 영상 제목 음식 키워드 합치기
- category: kakao_category mid-level (한식/분식/일식/중식 등)을 우선 매핑
"""
import json, re
from pathlib import Path

ROOT = Path(__file__).parent.parent
GEO = ROOT / "public" / "data" / "restaurants_geo.json"

# 카테고리어 — menus에 절대 들어가면 안 되는 일반어
GENERIC_CAT_WORDS = {
    # mid-level
    "한식","중식","일식","양식","분식","간식","치킨","피자",
    "음식점","술집","카페","제과,베이커리","패스트푸드","이탈리아음식",
    "뷔페","요리주점","호프,요리주점","아시아음식","유흥주점",
    # leaf 일반어
    "중국요리","중요리","해물","생선","해물,생선","술집,요리주점",
    "베이커리","제과","제빵","아이스크림","디저트","간식,분식",
    "스시","찌개","전골","찌개,전골","구이","쥬스","음료","음료수",
    "묵","두부","묵,두부","면","면류","면,라면",
    "한정식","경양식","고기","육류","육류,고기",
    "샐러드","스낵","요리","음식",
    # 너무 일반적인 카테고리 단어
    "닭요리","해산물요리","고기요리","면요리","국수",
    "전","술","밥","국","탕","면",
}

# kakao_category에서 추출하되, 의미있는 메뉴어만 통과시키는 화이트리스트 강화
# (실제 음식명만)
MENU_WORDS = {
    "곰탕","설렁탕","곰탕,설렁탕","떡볶이","갈비","갈비탕","찜닭",
    "곱창","막창","대창","곱창,막창","곱창,막창,대창","막창,대창",
    "칼국수","쌈밥","회","초밥","짜장","짬뽕","짬뽕,짜장","짜장,짬뽕",
    "냉면","우동","라면","돈까스","수제비","족발","보쌈","족발,보쌈",
    "치킨","피자","햄버거","버거","파스타","스테이크","감자탕",
    "삼겹살","오겹살","한우","숯불구이","훈제","바베큐","바비큐",
    "낙지","쭈꾸미","조개","장어","게장","꽃게","대게","랍스타","랍스터",
    "마라탕","훠궈","양꼬치","딤섬","마라샹궈","마파두부",
    "샤브샤브","스키야키","돈부리","규동","오므라이스",
    "베이글","케이크","마카롱","와플","팬케이크","빙수","아이스크림",
    "닭갈비","닭발","닭한마리","닭볶음탕","백숙","삼계탕",
    "국밥","순대","순대국","해장국","육개장","갈비찜","불고기",
    "낚지","장어구이","민물장어","장어덮밥",
    "타코","케밥","쌀국수","팟타이","나시고렝","똠양꿍",
    "맥주","와인","사케","칵테일","호프",
    "추어탕","추어","뼈해장국","뼈찜","두루치기",
    "만두","만두,만두국","왕만두","군만두","찐만두","물만두",
    "분식","김밥","라면",
    "라멘","우동,라면","돈까스,일식",
    "빈대떡","파전","녹두전","해물파전",
    "튀김","꼬치","구이,꼬치",
    "꼬리곰탕","갈비탕,설렁탕","수육","족발,수육",
    "빙수,파르페","팬케이크,파르페",
    "샌드위치","토스트","핫도그","피쉬앤칩스",
    "초밥,롤","사시미","우니","연어","참치",
    "쌀국수,베트남","베트남","태국","인도","말레이시아",
}

# 영상 제목에서 추출할 음식 키워드 (메뉴로 추가)
# 주의: 1글자 단어는 매칭이 너무 광범위함 ('전' → 전통/전부/전국). 2글자 이상만.
TITLE_FOODS = [
    "엽기떡볶이","로제떡볶이","즉석떡볶이","떡볶이",
    "곰탕","설렁탕","갈비탕","감자탕","해장국","순대국","국밥","육개장","삼계탕","추어탕",
    "곱창","막창","대창","순대","족발","보쌈","수육",
    "삼겹살","오겹살","목살","항정살","갈비","갈매기살","돼지갈비","소갈비","갈비찜","한우",
    "치킨","피자","햄버거","버거","파스타","스테이크","리조또",
    "짜장","짬뽕","탕수육","마라탕","훠궈","양꼬치","마라샹궈","마파두부",
    "회","사시미","초밥","스시","롤","사케","우니","연어","참치","장어","민물장어",
    "돈까스","돈가스","돈부리","규동","오므라이스","라멘","우동","소바","우니",
    "냉면","평양냉면","함흥냉면","비빔냉면","물냉면",
    "라면","컵라면","짜파게티","불닭",
    "낙지","쭈꾸미","조개","바지락","꼬막","홍합","문어","해삼","멍게",
    "꽃게","대게","킹크랩","랍스타","랍스터","새우","오징어",
    "샤브샤브","샤브","스키야키",
    "케이크","빵","베이글","마카롱","와플","빙수","팬케이크","크로플",
    "닭갈비","닭발","닭한마리","닭볶음탕","백숙","찜닭",
    "빈대떡","파전","해물파전","녹두전",
    "만두","왕만두","찐만두","군만두",
    "쌀국수","팟타이","나시고렝","똠양꿍","케밥","타코",
    "맥주","호프","와인",
    "김밥","토스트","핫도그","샌드위치",
    "막국수","칼국수","수제비","잔치국수","비빔국수",
    "곱창전골","부대찌개","김치찌개","된장찌개","순두부",
    "불고기","두루치기","제육볶음","오삼불고기",
]


def normalize_menu(token: str) -> str:
    return token.strip()


def menus_from_kakao(cat: str) -> list:
    """kakao_category leaf를 메뉴 후보로 변환."""
    if not cat: return []
    parts = [p.strip() for p in cat.split(">") if p.strip()]
    if not parts: return []
    leaf = parts[-1]
    # 쉼표/슬래시 분리
    out = []
    for token in leaf.replace("/", ",").split(","):
        token = normalize_menu(token)
        if not token: continue
        # GENERIC 제외
        if token in GENERIC_CAT_WORDS: continue
        # 너무 짧으면 (1글자) 제외 (회/빵은 의미있는 단어로 유지)
        if len(token) == 1 and token not in {"회","빵"}: continue
        out.append(token)
    return out


def menus_from_title(title: str) -> list:
    """영상 제목에서 음식 키워드 추출."""
    if not title: return []
    out = []
    seen = set()
    # 긴 키워드부터 매칭 (엽기떡볶이 > 떡볶이)
    for kw in sorted(TITLE_FOODS, key=len, reverse=True):
        if kw in title and kw not in seen:
            # 부분 중복 방지 (이미 더 긴 게 들어갔으면 짧은 건 스킵)
            if any(kw in p for p in out): continue
            out.append(kw)
            seen.add(kw)
    return out


# category 재매핑 — kakao_category mid-level 기준
MID_TO_CAT = {
    "한식": "한식",
    "분식": "분식",
    "일식": "일식",
    "중식": "중식",
    "양식": "양식",
    "치킨": "치킨",
    "카페": "카페",
    "술집": "술집",
    "패스트푸드": "양식",
    "아시아음식": "아시아음식",
    "뷔페": "뷔페",
}

# leaf-level fine-tuning (mid 매핑보다 더 구체적으로)
LEAF_TO_CAT = {
    "냉면": "냉면",
    "닭갈비": "닭갈비",
    "치킨": "치킨",
    "피자": "피자",
    "해물,생선": "해산물",
    "회": "해산물",
    "조개,꼬막": "해산물",
    "곰탕,설렁탕": "국밥",
    "추어탕": "국밥",
    "감자탕": "국밥",
    "곱창,막창": "구이",
    "곱창,막창,대창": "구이",
    "막창,대창": "구이",
    "갈비": "구이",
    "삼겹살": "구이",
    "한우": "구이",
    "구이": "구이",
    "쌈밥": "한식",
    "돈까스": "일식",
    "초밥": "일식",
    "초밥,롤": "일식",
    "스시": "일식",
    "라멘": "일식",
    "우동,라면": "일식",
    "떡볶이": "분식",
    "분식": "분식",
    "만두": "분식",
    "만두,만두국": "분식",
    "김밥": "분식",
    "라면": "면류",
    "면": "면류",
    "칼국수": "면류",
    "쌀국수,베트남": "아시아음식",
    "베트남": "아시아음식",
    "태국": "아시아음식",
    "베이커리": "카페",
    "제과,베이커리": "카페",
    "디저트": "카페",
    "아이스크림": "카페",
    "빙수": "카페",
}


def remap_category(r: dict) -> str:
    """카카오 카테고리 기반 표준 카테고리 매핑."""
    cat = r.get("kakao_category", "") or ""
    parts = [p.strip() for p in cat.split(">") if p.strip()]

    # 1) leaf 우선
    if parts:
        leaf = parts[-1]
        if leaf in LEAF_TO_CAT:
            return LEAF_TO_CAT[leaf]
        # leaf 토큰별로도 시도
        for token in leaf.replace("/", ",").split(","):
            token = token.strip()
            if token in LEAF_TO_CAT:
                return LEAF_TO_CAT[token]

    # 2) mid-level
    if len(parts) >= 2:
        mid = parts[1]
        if mid in MID_TO_CAT:
            return MID_TO_CAT[mid]

    # 3) 영상 제목 폴백
    title = r.get("video_title", "") or ""
    title_food_map = {
        "떡볶이":"분식","냉면":"냉면","닭갈비":"닭갈비","게장":"해산물","국밥":"국밥",
        "갈비":"구이","곱창":"구이","순대":"분식","칼국수":"면류","돈까스":"일식",
        "초밥":"일식","스시":"일식","짜장":"중식","짬뽕":"중식","삼겹살":"구이","치킨":"치킨",
        "라면":"면류","우동":"면류","만두":"분식","해산물":"해산물","회":"해산물",
        "보쌈":"한식","족발":"한식","한우":"구이","비빔밥":"한식","피자":"피자",
        "햄버거":"양식","버거":"양식","파스타":"양식","감자탕":"국밥","곰탕":"국밥",
        "삼계탕":"국밥","해장국":"국밥","순대국":"국밥","육개장":"국밥","추어탕":"국밥",
        "닭한마리":"닭갈비","닭발":"닭갈비","찜닭":"닭갈비",
        "마라탕":"중식","훠궈":"중식","양꼬치":"중식","탕수육":"중식",
        "라멘":"일식","돈부리":"일식","규동":"일식",
        "케이크":"카페","빵":"카페","빙수":"카페","베이글":"카페","와플":"카페",
        "쌀국수":"아시아음식","팟타이":"아시아음식","케밥":"아시아음식","타코":"양식",
        "맥주":"술집","호프":"술집","와인":"술집",
    }
    for kw, c in title_food_map.items():
        if kw in title:
            return c

    # 4) 진짜 못 찾으면 기타
    return r.get("category", "기타") or "기타"


def main():
    data = json.load(open(GEO, encoding="utf-8"))
    print(f"전체: {len(data)}개")

    menu_changed = 0
    cat_changed = 0
    menu_empty = 0

    for r in data:
        # menus 재구성
        old_menus = r.get("menus") or []
        m_kakao = menus_from_kakao(r.get("kakao_category", "") or "")
        m_title = menus_from_title(r.get("video_title", "") or "")
        # 합치기 (제목 키워드 우선 — 영상에서 실제로 먹은 거)
        new_menus = []
        for x in m_title + m_kakao:
            if x and x not in new_menus and x not in GENERIC_CAT_WORDS:
                new_menus.append(x)
        # 최대 6개
        new_menus = new_menus[:6]
        if new_menus != old_menus:
            menu_changed += 1
        if not new_menus:
            menu_empty += 1
        r["menus"] = new_menus

        # category 재매핑
        old_cat = r.get("category", "기타")
        new_cat = remap_category(r)
        if new_cat != old_cat:
            cat_changed += 1
        r["category"] = new_cat

    # 통계
    from collections import Counter
    cat_dist = Counter(r.get("category", "기타") for r in data)

    print(f"\nmenus 변경: {menu_changed}건")
    print(f"menus 빈값: {menu_empty}건")
    print(f"category 변경: {cat_changed}건")
    print(f"\n=== 새 category 분포 ===")
    for c, n in cat_dist.most_common():
        print(f"  {c}: {n}")

    # 새 menus Top 30
    from collections import Counter
    mc = Counter()
    for r in data:
        for m in (r.get("menus") or []):
            mc[m] += 1
    print(f"\n=== 새 menus Top 30 ===")
    for m, n in mc.most_common(30):
        print(f"  {m}: {n}")

    json.dump(data, open(GEO, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n저장 완료")


if __name__ == "__main__":
    main()
