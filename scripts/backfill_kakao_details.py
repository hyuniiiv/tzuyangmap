"""
기존 맛집 1,011개에 Kakao API로 전화번호/카카오맵 URL/상세카테고리 보강.
- name + address로 keyword 검색
- 첫 결과의 phone / place_url / category_name 채움
- 이미 phone 있으면 스킵 (재실행 안전)
"""
import json, re, sys, time, urllib.request, urllib.parse, os
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

ROOT     = Path(__file__).parent.parent
GEO_FILE = ROOT / "public" / "data" / "restaurants_geo.json"
ENV_FILE = ROOT / ".env"

KAKAO_REST = ""
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"KAKAO_REST_API_KEY\s*=\s*(.+)", line.strip())
        if m: KAKAO_REST = m.group(1).strip()
KAKAO_REST = os.environ.get("KAKAO_REST_API_KEY", KAKAO_REST)

if not KAKAO_REST:
    print("[!] KAKAO_REST_API_KEY 가 없습니다 (.env 또는 환경변수)")
    sys.exit(1)


def kakao_keyword_search(name: str, lat: float = None, lng: float = None, region: str = ""):
    """name + (좌표/지역)으로 Kakao Local 검색"""
    q = f"{region} {name}".strip() if region else name
    params = {
        "query": q,
        "category_group_code": "FD6",
        "size": 5,
    }
    if lat and lng:
        params["y"] = lat
        params["x"] = lng
        params["radius"] = 1000  # 1km 반경 내 우선
    url = "https://dapi.kakao.com/v2/local/search/keyword.json?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {KAKAO_REST}"})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            return json.loads(r.read().decode("utf-8")).get("documents", [])
    except Exception as e:
        return []


def pick_best_match(name: str, address: str, lat: float, lng: float, docs: list):
    """이름 유사도 + 좌표 거리로 가장 가까운 매장 선택"""
    if not docs: return None

    def name_sim(a: str, b: str) -> float:
        a, b = a.replace(" ", ""), b.replace(" ", "")
        if not a or not b: return 0
        if a == b: return 1.0
        if a in b or b in a: return 0.85
        common = sum(1 for ch in set(a) if ch in b)
        return common / max(len(set(a)), len(set(b)))

    def dist_m(d):
        try:
            dy = lat - float(d["y"])
            dx = lng - float(d["x"])
            return (dy*dy + dx*dx) ** 0.5 * 111000
        except: return 99999

    scored = []
    for d in docs:
        sim = name_sim(name or "", d.get("place_name", ""))
        dist = dist_m(d)
        # 거리 200m 이내 + 이름 유사도 0.4 이상이면 가산점
        score = sim * 100 - dist * 0.05
        if dist < 150: score += 30  # 거리 매우 가까우면 강한 신호
        if sim > 0.7: score += 25
        scored.append((score, sim, dist, d))

    scored.sort(reverse=True, key=lambda x: x[0])
    best = scored[0]
    score, sim, dist, doc = best

    # 임계치: 점수 30 이상, 거리 500m 이하 또는 이름 유사도 0.5+
    if score >= 30 and (dist <= 500 or sim >= 0.5):
        return doc
    return None


def main():
    print("=" * 60)
    print("Kakao 매장 상세정보 백필 (전화번호 / 카카오맵 URL)")
    print("=" * 60)

    if not GEO_FILE.exists():
        print("[!] restaurants_geo.json 없음")
        return

    data = json.loads(GEO_FILE.read_text(encoding="utf-8"))
    total = len(data)
    print(f"전체: {total}개")

    # 이미 phone 있으면 스킵
    targets = [i for i, r in enumerate(data) if not r.get("phone") and r.get("name") and r.get("address")]
    print(f"백필 대상 (phone 없음): {len(targets)}개")
    print(f"이미 처리됨: {total - len(targets)}개\n")

    if not targets:
        print("모두 처리되었습니다.")
        return

    updated = 0
    matched_phone = 0
    matched_url = 0
    matched_cat = 0

    for idx, i in enumerate(targets):
        r = data[i]
        name = r.get("name", "")
        addr = r.get("address", "")
        lat  = r.get("lat")
        lng  = r.get("lng")
        region = r.get("region", "")

        # 진행 표시
        if (idx+1) % 25 == 0 or idx < 3:
            print(f"  [{idx+1}/{len(targets)}] {name[:18]:<18} ", end="", flush=True)

        docs = kakao_keyword_search(name, lat, lng, region)
        best = pick_best_match(name, addr, lat or 0, lng or 0, docs)

        if best:
            ph = best.get("phone", "") or ""
            pu = best.get("place_url", "") or ""
            cat = best.get("category_name", "") or ""

            changed = False
            if ph:
                r["phone"] = ph; matched_phone += 1; changed = True
            if pu:
                r["place_url"] = pu; matched_url += 1; changed = True
            if cat:
                r["kakao_category"] = cat; matched_cat += 1; changed = True

            if changed:
                updated += 1
                if (idx+1) % 25 == 0 or idx < 3:
                    print(f"→ ✓ {ph or '(전화X)'}")
            else:
                if (idx+1) % 25 == 0 or idx < 3:
                    print(f"→ 매칭됐으나 정보 없음")
        else:
            if (idx+1) % 25 == 0 or idx < 3:
                print(f"→ ✗ 매칭 실패")

        # 중간 저장 (안전망: 100개마다)
        if (idx+1) % 100 == 0:
            GEO_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"    [중간 저장 — 누적 {updated}개 업데이트]")

        time.sleep(0.06)  # ~16 req/sec 안전선

    # 최종 저장
    GEO_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("=" * 60)
    print(f"완료: {updated}개 업데이트 / 시도 {len(targets)}개")
    print(f"  전화번호:   {matched_phone}건")
    print(f"  카카오URL:  {matched_url}건")
    print(f"  카테고리:   {matched_cat}건")
    print("=" * 60)


if __name__ == "__main__":
    main()
