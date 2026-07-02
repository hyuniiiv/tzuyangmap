"""재점검 결과 반영:
- #7 요아정: 삭제 (협찬 브랜드 단독 거부)
- #8 서래마을이야기 → 야미도 (자막 주소 명시)
- #15 남영돈 → 영화장 (자막 명시)
- #1 우정 (신당동): Kakao에서 신당동 매장 검색 후 교체
- #3 온정식당 (가평): Kakao에서 가평 매장 검색 후 교체
"""
import sys, json, urllib.request, urllib.parse
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import auto_update as au

GEO = ROOT / "public" / "data" / "restaurants_geo.json"
data = json.loads(GEO.read_text(encoding="utf-8"))
print(f"전체: {len(data)}개")

# 재점검 결과에서 신규 entries 로드
recheck = json.loads((ROOT / "scripts" / ".recheck_recent.json").read_text(encoding="utf-8"))
by_vid = {r["video_id"]: r for r in recheck}


def remove_by_vid(vid):
    global data
    before = len(data)
    data = [r for r in data if r.get("video_id") != vid]
    print(f"  삭제 {before - len(data)}건")

def replace_by_vid(vid, new_entries):
    global data
    before = len(data)
    data = [r for r in data if r.get("video_id") != vid]
    data.extend(new_entries)
    print(f"  교체: 기존 {before - len(data) + len(new_entries)}건 → 신규 {len(new_entries)}건")


def kakao_search(q, region_hint=""):
    """Kakao Local API로 매장 검색."""
    query = f"{region_hint} {q}".strip() if region_hint else q
    params = {"query": query, "size": 5, "category_group_code": "FD6"}
    url = "https://dapi.kakao.com/v2/local/search/keyword.json?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {au.KAKAO_REST}"})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            docs = json.loads(r.read().decode("utf-8")).get("documents", [])
        return docs
    except Exception as e:
        print(f"  Kakao 오류: {e}")
        return []


# ─── #7 요아정 삭제 ────────────────────────────────────────────
print("\n[#7] 요아정 삭제")
remove_by_vid("iMz2KU10u2Q")


# ─── #8 서래마을이야기 → 야미도 ───────────────────────────────
print("\n[#8] 서래마을이야기 → 야미도")
for r in recheck:
    if "도대체 뭘 먹었을까" in r.get("video_title","") or "야미도" in json.dumps(r.get("new_entries",[]), ensure_ascii=False):
        replace_by_vid(r["video_id"], r["new_entries"])
        break


# ─── #15 남영돈 → 영화장 ──────────────────────────────────────
print("\n[#15] 남영돈 → 영화장")
for r in recheck:
    if "20,000칼로리" in r.get("video_title","") or any("영화장" in ne.get("name","") for ne in r.get("new_entries",[])):
        replace_by_vid(r["video_id"], r["new_entries"])
        break


# ─── #1 신당동 우정 수동 검색 ─────────────────────────────────
print("\n[#1] 신당동 우정 매운닭발 수동 검색")
vid = "KS_53b_YcvA"  # 우정 video_id
old_entries = [r for r in data if r.get("video_id") == vid]
if old_entries:
    old = old_entries[0]
    docs = kakao_search("우정 매운닭발", "서울 중구 신당동")
    for d in docs[:3]:
        print(f"   후보: {d['place_name']} @ {d.get('road_address_name') or d.get('address_name')}")
    if docs:
        d = docs[0]
        addr = d.get("road_address_name") or d.get("address_name", "")
        if "신당" in addr or "중구" in addr:
            new_entry = dict(old)
            new_entry.update({
                "name": d["place_name"],
                "address": addr,
                "lat": round(float(d["y"]), 6),
                "lng": round(float(d["x"]), 6),
                "phone": d.get("phone", ""),
                "place_url": d.get("place_url", ""),
                "kakao_category": d.get("category_name", ""),
                "region": "서울",
                "category": "분식",
                "menus": ["매운닭발","닭발","떡볶이"],
            })
            replace_by_vid(vid, [new_entry])
        else:
            print("   ⚠️ 신당동 매칭 실패 — 유지")


# ─── #3 가평 온정식당 수동 검색 ──────────────────────────────
print("\n[#3] 가평 온정식당 수동 검색")
onjeong_vids = [r for r in recheck if "가평" in r.get("video_title","") and "온정" in r.get("video_title","")]
if onjeong_vids:
    vid = onjeong_vids[0]["video_id"]
    old_entries = [r for r in data if r.get("video_id") == vid]
    if old_entries:
        old = old_entries[0]
        docs = kakao_search("온정식당", "경기 가평")
        for d in docs[:3]:
            print(f"   후보: {d['place_name']} @ {d.get('road_address_name') or d.get('address_name')}")
        # 가평 지역 매장 선택
        matched = None
        for d in docs:
            addr = d.get("road_address_name") or d.get("address_name", "")
            if "가평" in addr:
                matched = d; break
        if matched:
            addr = matched.get("road_address_name") or matched.get("address_name", "")
            new_entry = dict(old)
            new_entry.update({
                "name": matched["place_name"],
                "address": addr,
                "lat": round(float(matched["y"]), 6),
                "lng": round(float(matched["x"]), 6),
                "phone": matched.get("phone", ""),
                "place_url": matched.get("place_url", ""),
                "kakao_category": matched.get("category_name", ""),
                "region": "경기",
                "category": "한식",
                "menus": ["김치찜"],
            })
            replace_by_vid(vid, [new_entry])
        else:
            print("   ⚠️ 가평 매칭 실패 — 유지")


# 저장
print(f"\n최종: {len(data)}개")
GEO.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("저장 완료")
