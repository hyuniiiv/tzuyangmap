"""기존 데이터에 menus 필드 백필 — kakao_category에서 메뉴명 파싱.
예: '음식점 > 한식 > 곰탕,설렁탕' → menus=['곰탕','설렁탕']
예: '음식점 > 분식 > 떡볶이 > 동대문엽기떡볶이' → menus=['떡볶이']
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
GEO = ROOT / "public" / "data" / "restaurants_geo.json"

# 카테고리 leaf의 일반어 (메뉴로 보지 않을 단어)
GENERIC_CAT_WORDS = {
    "한식","중식","일식","양식","분식","면류","간식","치킨","피자",
    "음식점","육류,고기","해물,생선","술집","카페","제과,베이커리",
    "패스트푸드","이탈리아음식","뷔페","요리주점","호프,요리주점",
    "베이커리","제과","제빵","아이스크림","디저트","간식,분식",
    "스시","찌개,전골","구이","유흥주점","쥬스","음료",
}


def extract_menus_from_kakao_cat(cat: str) -> list[str]:
    if not cat: return []
    parts = [p.strip() for p in cat.split(">") if p.strip()]
    if not parts: return []
    leaf = parts[-1]  # 가장 구체적 leaf
    # 쉼표/슬래시로 분리
    items = []
    for token in leaf.replace("/", ",").split(","):
        token = token.strip()
        if not token: continue
        # 너무 일반적이면 제외
        if token in GENERIC_CAT_WORDS: continue
        items.append(token)
    return items


data = json.load(open(GEO, encoding="utf-8"))
print(f"전체: {len(data)}개")

updated = 0
for r in data:
    if r.get("menus"): continue  # 이미 있으면 skip
    menus = extract_menus_from_kakao_cat(r.get("kakao_category", ""))
    if menus:
        r["menus"] = menus
        updated += 1

print(f"menus 백필: {updated}건")

# 샘플
import random
sample = random.sample([r for r in data if r.get("menus")], min(10, len([r for r in data if r.get("menus")])))
print("\n샘플:")
for r in sample:
    print(f"  {r.get('name'):<25} cat='{r.get('kakao_category','')[:30]}' → menus={r.get('menus')}")

json.dump(data, open(GEO, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n저장 완료")
