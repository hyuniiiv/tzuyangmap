"""
restaurants_geo.json 품질 감사
- Kakao 교차검증 결과 + 추가 메타데이터로 신뢰도 등급 분류
- 'BAD' 등급 (이름/위치 모두 의심) 만 골라 sample + count 출력
- --apply 옵션을 주면 bad 항목 제거 (.bak 백업 생성)
"""
import json, sys, re, argparse
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).parent.parent
GEO_FILE = ROOT / "public" / "data" / "restaurants_geo.json"

# 메뉴/음식명 (매장명으로 잘못 쓰이기 쉬운 일반명사)
MENU_VOCAB = {
    "로제떡볶이","떡볶이","짜장면","짬뽕","우동","라멘","라면","돈까스","돈가스",
    "초밥","스시","비빔밥","된장찌개","김치찌개","순두부찌개","갈비탕","설렁탕",
    "냉면","물냉면","비빔냉면","평양냉면","함흥냉면",
    "치킨","후라이드","양념치킨","피자","파스타","스파게티",
    "삼겹살","목살","갈비","곱창","대창","막창",
    "분식","구이","해산물","중식","일식","한식","양식","국밥","면류",
    "회","사시미","활어회","모둠회","연어회",
    "보쌈","족발","순대","김밥","마라탕","마라샹궈","훠궈",
    "감자탕","뼈해장국","해장국","청국장","김치볶음밥",
    "탕수육","깐풍기","유린기","꿔바로우","마파두부",
    "쭈꾸미","낙지","조개","오겹살","숯불구이","모듬구이","모듬떡볶이",
    "즉석떡볶이","매운낙지","청어알낙지","돼지국밥","간장게장","곱창막창대창",
    "튀김칼국수","국물떡볶이","고기집","술집","우리집","시골마을","이사한집",
    "추천한집","두번째","커피집","해녀촌식당","해녀포차","한국인이라면",
    "분이라면","차량이라면","키이로","몽땅식품",
}

def looks_like_menu(name: str) -> bool:
    """매장명이 메뉴/일반명사로 의심되면 True"""
    if not name: return True
    n = name.strip()
    if n in MENU_VOCAB: return True
    # 한 단어로 끝나는 너무 일반적인 패턴
    if re.fullmatch(r"[가-힣]{2,4}(?:집|식당|가게|포차|음식점|구이|찌개|국밥)", n):
        return False  # "할매네집" 같은건 통과
    return False


def grade(r: dict) -> str:
    """엔트리 신뢰도 등급"""
    kv = r.get("kakao_verified")
    sim  = (kv or {}).get("similarity", None)
    dist = (kv or {}).get("distance_m", None)
    name = r.get("name", "")
    has_kakao_meta = bool(r.get("phone") or r.get("place_url"))
    is_menu_name = looks_like_menu(name)

    # S: Kakao 직접 검색 결과 (auto_kakao) 또는 검증 매우 강함
    if r.get("source") == "auto_kakao":
        return "S"
    if has_kakao_meta and sim is not None and sim >= 0.5:
        return "S"

    # A: 검증 통과 또는 백필로 메타데이터 확보됨
    if has_kakao_meta:
        return "A"
    if sim is not None and sim >= 0.5 and dist is not None and dist < 100:
        return "A"

    # B: 매장명은 의심스럽지만 위치는 가까움 (구제 가능)
    if sim == 0.0 and dist is not None and dist < 50:
        return "B"

    # BAD: similarity 0 + 거리 멈 + 메타데이터 없음 ← 정리 대상
    if sim == 0.0 and dist is not None and dist >= 100:
        return "BAD"

    # 추가 BAD: 메뉴/일반명사 매장명 + 메타데이터 없음 + 검증 실패
    if is_menu_name and not has_kakao_meta and (sim is None or sim < 0.4):
        return "BAD-MENU"

    # C: Kakao 검증 정보 자체가 없음
    if kv is None:
        return "C"

    # D: 그 외
    return "D"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="BAD 항목을 실제로 제거 (.bak 백업)")
    ap.add_argument("--samples", type=int, default=8, help="각 등급별 출력 샘플 수")
    args = ap.parse_args()

    data = json.loads(GEO_FILE.read_text(encoding="utf-8"))
    print(f"전체 엔트리: {len(data)}개\n")

    graded = []
    counts = Counter()
    for r in data:
        g = grade(r)
        counts[g] += 1
        graded.append((g, r))

    print("=" * 60)
    print("신뢰도 등급별 카운트")
    print("=" * 60)
    for g in ["S","A","B","C","D","BAD","BAD-MENU"]:
        print(f"  {g:<10}: {counts[g]:>5}개")
    print()

    # BAD 샘플
    print("=" * 60)
    print(f"BAD 샘플 (similarity=0.0 & distance≥100m, 메타데이터 없음)")
    print("=" * 60)
    bad = [r for g, r in graded if g == "BAD"][:args.samples]
    for r in bad:
        kv = r.get("kakao_verified", {})
        print(f"  · {r.get('name','?'):<20} | {r.get('address','')[:35]:<35}")
        print(f"    영상: {r.get('video_title','')[:50]}")
        print(f"    Kakao 매칭 시도: {kv.get('name','')} ({kv.get('distance_m','?')}m, sim={kv.get('similarity','?')})")
    print()

    # BAD-MENU 샘플
    print("=" * 60)
    print(f"BAD-MENU 샘플 (메뉴/일반명사 + 검증 실패 + 메타 없음)")
    print("=" * 60)
    bad_menu = [r for g, r in graded if g == "BAD-MENU"][:args.samples]
    for r in bad_menu:
        print(f"  · {r.get('name','?'):<20} | {r.get('address','')[:35]:<35}")
        print(f"    영상: {r.get('video_title','')[:50]}")
    print()

    # B 샘플 (참고: 이름은 의심스럽지만 위치는 가까운 항목)
    print("=" * 60)
    print(f"B 샘플 (참고: 위치는 가까우나 이름 의심)")
    print("=" * 60)
    b = [r for g, r in graded if g == "B"][:args.samples]
    for r in b:
        kv = r.get("kakao_verified", {})
        print(f"  · {r.get('name','?'):<20} | {r.get('address','')[:35]:<35}")
        print(f"    Kakao 근처: {kv.get('name','')} ({kv.get('distance_m','?')}m)")
    print()

    total_to_remove = counts["BAD"] + counts["BAD-MENU"]
    print(f"제거 대상 (BAD + BAD-MENU): {total_to_remove}개  ({total_to_remove/len(data)*100:.1f}%)")
    print(f"남는 엔트리: {len(data) - total_to_remove}개")

    if args.apply:
        # 백업
        bak = GEO_FILE.with_suffix(".json.bak")
        bak.write_text(GEO_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"\n백업: {bak.name}")

        kept = [r for g, r in graded if g not in ("BAD","BAD-MENU")]
        GEO_FILE.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"정리 완료: {len(kept)}개 (제거 {total_to_remove}개)")


if __name__ == "__main__":
    main()
