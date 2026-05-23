"""
쯔양맵 자동 업데이트 스크립트
- 두 채널의 새 영상 감지
- 자막/웹검색으로 매장명+주소 수집
- Kakao 지오코딩 + 교차검증
- restaurants_geo.json 업데이트
"""
import json, re, sys, time, subprocess, urllib.request, urllib.parse, random
sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None
sys.stderr.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stderr, "reconfigure") else None
from pathlib import Path
from collections import Counter
from datetime import date, datetime

ROOT     = Path(__file__).parent.parent
GEO_FILE = ROOT / "public" / "data" / "restaurants_geo.json"
SUB_DIR  = ROOT / "scripts" / "subs"
SUB_DIR.mkdir(exist_ok=True)

# .env 읽기
ENV_FILE = ROOT / ".env"
KAKAO_REST = ""
KAKAO_JS   = ""
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"KAKAO_REST_API_KEY\s*=\s*(.+)", line.strip())
        if m: KAKAO_REST = m.group(1).strip()
        m = re.match(r"KAKAO_JAVASCRIPT_KEY\s*=\s*(.+)", line.strip())
        if m: KAKAO_JS = m.group(1).strip()

# GitHub Actions 환경변수 지원
import os
KAKAO_REST = os.environ.get("KAKAO_REST_API_KEY", KAKAO_REST)
KAKAO_JS   = os.environ.get("KAKAO_JAVASCRIPT_KEY", KAKAO_JS)

CHANNELS = [
    ("https://www.youtube.com/@tzuyang6145/videos", "tzuyang", "쯔양"),
    # 밖정원 채널은 비식당 콘텐츠 비중이 높아 메인 채널만 처리
    # ("https://www.youtube.com/@v-tzuyang/videos", "vtzuyang", "쯔양밖정원"),
]

OVERSEAS_KW = [
    "이스탄불","홍콩","일본","홋카이도","삿포로","오사카","도쿄",
    "인도네시아","반둥","대만","중국","베트남","태국","싱가포르",
    "말레이시아","미국","파리","런던","유럽","몽골","인도","필리핀",
    "뉴욕","두바이","하와이","호주","스페인","이탈리아","터키",
    "istanbul","hong kong","japan","bandung","taiwan","vietnam",
    "thailand","usa","paris","london","singapore","maldives",
    "sydney","budapest","las vegas","jakarta","bali",
]


FOOD_KWS = [
    "떡볶이","냉면","닭갈비","게장","국밥","갈비","곱창","순대","칼국수",
    "돈까스","초밥","짜장","짬뽕","보쌈","족발","삼겹살","치킨","라면",
    "우동","만두","비빔밥","해장국","설렁탕","대창","막창","한우",
    "쌀국수","감자전","파전","구이","곰탕","삼계탕","샤브샤브",
    "군만두","김밥","쭈꾸미","낙지","조개","오겹살",
    # "회"는 "회사","회전" 오탐 방지 — 별도 처리
]

def has_food_keyword(title: str) -> str | None:
    """음식 키워드 추출 (단어 경계 고려)"""
    for kw in FOOD_KWS:
        if kw in title:
            return kw
    # "회"는 앞뒤에 먹방/집/횟 붙은 경우만 허용
    if re.search(r"(?:횟집|회먹방|회포장|생선회|활어회|모둠회|회덮|회초밥)", title):
        return "회"
    return None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# ── 1. 채널 영상 목록 ──────────────────────────────────────────────────────

def fetch_channel_videos(url: str, channel_id: str) -> list:
    r = subprocess.run(
        ["yt-dlp", "--flat-playlist", "--dump-json", "--no-warnings",
         "--extractor-args", "youtube:lang=ko",
         "--playlist-end", "10",   # 최신 10개만 확인 (이틀치면 충분)
         url],
        capture_output=True, encoding="utf-8", errors="replace", timeout=60
    )
    videos = []
    for line in r.stdout.splitlines():
        if not line.strip(): continue
        try:
            d = json.loads(line)
            vid = d.get("id")
            if not vid: continue
            thumbs = d.get("thumbnails") or []
            thumb = thumbs[-1]["url"] if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
            videos.append({
                "id": vid, "title": d.get("title",""),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "thumbnail": thumb, "channel": channel_id,
            })
        except: continue
    return videos


# ── 2. 새 영상 감지 ────────────────────────────────────────────────────────

def get_existing_video_ids() -> set:
    if not GEO_FILE.exists(): return set()
    with open(GEO_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return {r["video_id"] for r in data if r.get("video_id")}


# ── 3. 매장명+주소 수집 ────────────────────────────────────────────────────

def get_subtitle_text(vid_id: str) -> str:
    vtt_path = SUB_DIR / f"{vid_id}.ko.vtt"
    if not (vtt_path.exists() and vtt_path.stat().st_size > 300):
        subprocess.run([
            "yt-dlp", "--skip-download", "--write-auto-subs",
            "--sub-lang", "ko", "--sub-format", "vtt",
            "-o", str(SUB_DIR / "%(id)s"), "--no-warnings",
            f"https://www.youtube.com/watch?v={vid_id}",
        ], capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    if not (vtt_path.exists() and vtt_path.stat().st_size > 300): return ""
    raw = vtt_path.read_text(encoding="utf-8", errors="replace")
    t = re.sub(r"<[^>]+>", "", raw)
    t = re.sub(r"\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*[^\n]+", "", t)
    lines, prev = [], ""
    for ln in t.splitlines():
        ln = ln.strip()
        if not ln or ln == prev: continue
        prev = ln; lines.append(ln)
    return " ".join(lines)

def find_region(text: str) -> str:
    REGIONS = {
        "서울","부산","인천","대구","대전","광주","울산","세종",
        "수원","성남","고양","용인","안산","안양","구리","평택","파주","광명","시흥",
        "춘천","강릉","원주","속초","태백",
        "청주","천안","아산","공주","논산","서산","당진","보령","홍성","태안","부여",
        "전주","군산","익산","전주",
        "여수","순천","목포","광양","나주",
        "포항","경주","구미","안동","영주",
        "창원","진주","통영","거제","양산",
        "제주","서귀포",
        "홍대","강남","명동","이태원","신촌","건대","청량리","성수","방이","잠실",
        "망원","신사","여의도","을지로","수유","남영","양평",
    }
    for r in REGIONS:
        if r in text: return r
    return ""

def kakao_search_nearby(lat: float, lng: float, query: str = "", radius: int = 200) -> list:
    if not KAKAO_REST: return []
    params = {
        "query": query or "음식점", "y": lat, "x": lng,
        "radius": radius, "category_group_code": "FD6", "size": 3,
    }
    url = "https://dapi.kakao.com/v2/local/search/keyword.json?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {KAKAO_REST}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode("utf-8")).get("documents", [])
    except: return []

def kakao_geocode(address: str) -> tuple | None:
    if not KAKAO_REST or not address: return None
    enc = urllib.parse.quote(address)
    url = f"https://dapi.kakao.com/v2/local/search/address.json?query={enc}&size=1"
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {KAKAO_REST}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            docs = json.loads(r.read().decode("utf-8")).get("documents", [])
        if docs:
            return float(docs[0]["y"]), float(docs[0]["x"])
    except: pass
    return None

def naver_search_address(query: str) -> str | None:
    ADDR_RE = re.compile(
        r"((?:서울|부산|인천|대구|대전|광주|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
        r"(?:특별시|광역시|특별자치시|특별자치도|도)?\s*"
        r"(?:[가-힣]{1,6}(?:시|군|구|읍|면)\s*)+"
        r"[가-힣\d]+(?:로|길|번길)\s*\d{1,5}(?:-\d+)?)"
    )
    enc = urllib.parse.quote(query)
    req = urllib.request.Request(
        f"https://search.naver.com/search.naver?query={enc}", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            html = r.read().decode("utf-8", errors="replace")
        html = re.sub(r"<[^>]+>", " ", html)
        ms = ADDR_RE.findall(html)
        if ms: return re.sub(r"\s+", " ", Counter(ms).most_common(1)[0][0]).strip()
    except: pass
    return None

# ── 자막 NER (방문 선언 패턴) ─────────────────────────────────────────────

_V = r"(?:가\s*보도록\s*하겠|가보도록\s*하겠|가\s*보겠|가보겠|가겠습니다|왔어요|왔습니다|도착했|들어가겠|먹으러\s*왔|먼저\s*가)"
_I = r"(?:라는\s*(?:곳|집|식당|가게)|이라는\s*(?:곳|집)|이라고|인데요?|이에요|예요|입니다)"

SUB_PATTERNS = [
    rf"([가-힣]{{1,6}}(?:\s[가-힣]{{1,6}})?(?:으로|로))\s*(?:먼저\s*)?{_V}",
    rf"여기(?:가|는)\s+([가-힣]{{1,6}}(?:\s[가-힣]{{1,6}})?)\s*{_I}",
    r"안녕하세요\.\s*([가-힣]{2,12})(?:입니다|이에요|예요)",
    r"([가-힣]{2,7}이네)(?:로|에서|에|이에요|입니다|라고)",
    r"([가-힣]{2,12}(?:본점|지점|분점))\s*(?:에서|에|이|로)",
]

_NOISE = {
    "저","나","너","우리","저희","여기","거기","지금","오늘","이번",
    "맛집","가게","식당","먹방","정말","진짜","완전","엄청","그냥",
    "삼대","사대","번째","겉바속촉","이제","이렇",
}

def extract_names_from_sub(text: str) -> list[str]:
    """자막에서 가게명 후보 추출"""
    found = []
    for pat in SUB_PATTERNS:
        for m in re.finditer(pat, text):
            name = re.sub(r"(?:으로|로)$", "", m.group(1).strip().replace(" ", ""))
            if (len(name) >= 2 and name not in _NOISE
                    and not re.search(r"\d", name)
                    and not re.search(r"(?:하는|있는|없는|먹는|같은|싶은)$", name)):
                found.append(name)
    from collections import Counter
    cnt = Counter(found)
    return [n for n, f in cnt.most_common(4) if f >= 1][:3]


def process_new_video(video: dict) -> dict | None:
    title = video["title"]

    # 해외 스킵
    if any(k in title.lower() for k in OVERSEAS_KW): return None

    # 자막 수집
    sub_text = get_subtitle_text(video["id"])
    region   = find_region(title + " " + sub_text[:500])
    upload_date = date.today().strftime("%Y-%m-%d")

    address = None
    name    = None
    lat = lng = None

    # ── 전략 1: 자막 NER → 가게명 → Kakao 검색 ──────────────────────────
    sub_names = extract_names_from_sub(sub_text) if sub_text else []
    for sub_name in sub_names:
        # 가게명으로 직접 Kakao 검색 (주소 없이 키워드만)
        params = {
            "query": f"{region} {sub_name}" if region else sub_name,
            "category_group_code": "FD6", "size": 1,
        }
        if region:
            params["y"] = 36.5; params["x"] = 127.8  # 한국 중심
        url = "https://dapi.kakao.com/v2/local/search/keyword.json?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {KAKAO_REST}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                docs = json.loads(r.read().decode("utf-8")).get("documents", [])
            if docs:
                d = docs[0]
                name    = d.get("place_name", sub_name)
                address = d.get("road_address_name") or d.get("address_name", "")
                lat     = float(d["y"])
                lng     = float(d["x"])
                break
        except: pass
        time.sleep(0.1)

    # ── 전략 2: 제목 음식 키워드 → Naver 주소 검색 (자막 실패 시) ──────────
    if not address:
        food = has_food_keyword(title)
        if not food: return None
        query = f"쯔양 {region} {food} 맛집 주소" if region else f"쯔양 {food} 맛집 주소"
        address = naver_search_address(query)
        if not address: return None

        coords = kakao_geocode(address)
        if not coords: return None
        lat, lng = coords
        name = f"{region}{food}" if region else food

    if not lat or not lng: return None

    # ── Kakao Local Search로 정확한 가게명 최종 교차검증 ──────────────────
    food_hint = has_food_keyword(title) or "음식점"
    results = kakao_search_nearby(lat, lng, query=food_hint, radius=100)
    if results:
        best = results[0]
        dist = ((lat - float(best["y"]))**2 + (lng - float(best["x"]))**2)**0.5 * 111000
        if dist < 80:
            name    = best.get("place_name", name)
            address = best.get("road_address_name") or address

    cat_map = {
        "떡볶이":"분식","냉면":"냉면","닭갈비":"닭갈비","게장":"해산물","국밥":"국밥",
        "갈비":"구이","곱창":"구이","순대":"분식","칼국수":"면류","돈까스":"일식",
        "초밥":"일식","짜장":"중식","짬뽕":"중식","삼겹살":"구이","치킨":"치킨",
        "라면":"면류","우동":"면류","만두":"분식","해산물":"해산물","구이":"구이",
        "회":"해산물","보쌈":"한식","족발":"한식","한우":"한식","비빔밥":"한식",
    }
    category = cat_map.get(food, "기타")

    # region_of
    region_map = {
        "서울":"서울","부산":"부산","인천":"인천","대구":"대구","대전":"대전",
        "광주":"광주","울산":"울산","세종":"세종","제주":"제주",
        "수원":"경기","성남":"경기","고양":"경기","용인":"경기","안산":"경기",
        "안양":"경기","파주":"경기","광명":"경기","시흥":"경기",
        "춘천":"강원","강릉":"강원","원주":"강원","속초":"강원","태백":"강원",
        "청주":"충북","천안":"충남","아산":"충남","공주":"충남","논산":"충남",
        "서산":"충남","당진":"충남","보령":"충남","홍성":"충남","태안":"충남",
        "전주":"전북","군산":"전북","익산":"전북",
        "여수":"전남","순천":"전남","목포":"전남","광양":"전남","나주":"전남",
        "포항":"경북","경주":"경북","구미":"경북","안동":"경북","영주":"경북",
        "창원":"경남","진주":"경남","통영":"경남","거제":"경남",
    }
    region_val = region_map.get(region, "기타")
    if region_val == "기타":
        for city, r in region_map.items():
            if city in address: region_val = r; break

    return {
        "name": name, "address": address,
        "category": category, "region": region_val,
        "video_id": video["id"], "video_title": title,
        "video_url": video["url"], "thumbnail": video["thumbnail"],
        "upload_date": upload_date,
        "lat": round(lat, 6), "lng": round(lng, 6),
        "source": "auto_kakao",
        "channel": video.get("channel", "tzuyang"),
    }


# ── 4. 메인 ────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print(f"쯔양맵 자동 업데이트 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # 기존 데이터 로드
    if GEO_FILE.exists():
        with open(GEO_FILE, encoding="utf-8") as f:
            geo = json.load(f)
    else:
        geo = []

    existing_ids = get_existing_video_ids()
    print(f"기존 맛집: {len(geo)}개 / 기존 영상: {len(existing_ids)}개\n")

    new_entries = []

    for channel_url, channel_id, channel_name in CHANNELS:
        print(f"채널 확인: {channel_name}")
        videos = fetch_channel_videos(channel_url, channel_id)
        new_videos = [v for v in videos if v["id"] not in existing_ids]
        print(f"  전체: {len(videos)}개 / 신규: {len(new_videos)}개")

        for v in new_videos:
            print(f"  처리: {v['title'][:55]}")
            entry = process_new_video(v)
            if entry:
                new_entries.append(entry)
                print(f"    → {entry['name']} | {entry['address'][:40]}")
                existing_ids.add(v["id"])  # 중복 방지
            time.sleep(random.uniform(1.5, 2.5))  # Naver 차단 방지

    if new_entries:
        geo.extend(new_entries)
        with open(GEO_FILE, "w", encoding="utf-8") as f:
            json.dump(geo, f, ensure_ascii=False, indent=2)
        print(f"\n✅ {len(new_entries)}개 신규 맛집 추가 → 총 {len(geo)}개")
    else:
        print("\n신규 맛집 없음")

    print("=" * 60)
    return len(new_entries)


if __name__ == "__main__":
    main()
