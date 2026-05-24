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

# OpenAI (LLM 매장명 추출용)
OPENAI_KEY = os.environ.get("OPEN_AI_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
# .env에서도 시도
if not OPENAI_KEY and ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"(?:OPEN_AI_API_KEY|OPENAI_API_KEY)\s*=\s*(.+)", line.strip())
        if m: OPENAI_KEY = m.group(1).strip(); break

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

def get_video_description(vid_id: str) -> str:
    """영상 설명란 — 주소가 가장 자주 명시되는 신뢰도 높은 소스"""
    try:
        r = subprocess.run(
            ["yt-dlp", "--print", "description", "--skip-download", "--no-warnings",
             f"https://www.youtube.com/watch?v={vid_id}"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=20
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


def get_top_pinned_comment(vid_id: str) -> str:
    """업로더의 고정 댓글 — 설명에 없을 때 백업 (느림: ~30s)"""
    info_path = SUB_DIR / f"{vid_id}.info.json"
    try:
        subprocess.run(
            ["yt-dlp", "--skip-download", "--write-info-json", "--write-comments",
             "--no-warnings",
             "--extractor-args", "youtube:max_comments=20,20;comment_sort=top",
             "-o", str(SUB_DIR / "%(id)s"),
             f"https://www.youtube.com/watch?v={vid_id}"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=60
        )
        if not info_path.exists():
            return ""
        info = json.loads(info_path.read_text(encoding="utf-8"))
        comments = info.get("comments") or []
        # 우선순위: 업로더+고정 > 고정 > 업로더 작성
        pinned_uploader = pinned_other = uploader_first = ""
        for c in comments:
            text = (c.get("text") or "").strip()
            if not text: continue
            is_uploader = c.get("author_is_uploader", False)
            is_pinned   = c.get("is_pinned", False)
            if is_uploader and is_pinned and not pinned_uploader:
                pinned_uploader = text
            elif is_pinned and not pinned_other:
                pinned_other = text
            elif is_uploader and not uploader_first:
                uploader_first = text
        return pinned_uploader or pinned_other or uploader_first
    except Exception:
        return ""


# 한국 주소 정규식 (시/도 + 시군구 + 도로명 + 번지)
KOREAN_ADDR_RE = re.compile(
    r"((?:서울|부산|인천|대구|대전|광주|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
    r"(?:특별시|광역시|특별자치시|특별자치도|도)?\s*"
    r"(?:[가-힣]{1,6}(?:시|군|구|읍|면)\s*)+"
    r"[가-힣\d]+(?:로|길|번길)\s*\d{1,5}(?:-\d+)?)"
)

def extract_address_from_text(text: str) -> str | None:
    """텍스트(설명/댓글)에서 한국 주소 추출 — 가장 많이 등장한 패턴 선택"""
    if not text: return None
    ms = KOREAN_ADDR_RE.findall(text)
    if not ms: return None
    return re.sub(r"\s+", " ", Counter(ms).most_common(1)[0][0]).strip()


def llm_extract_restaurant(title: str, sub_text: str, desc_text: str, pinned_text: str = "") -> dict | None:
    """OpenAI(GPT-4o-mini)로 영상에서 매장명/주소 동시 추출.
    - 메뉴와 매장명 자연어 구분
    - 약칭(엽떡 → 동대문엽기떡볶이) 이해
    - JSON 응답: restaurant_name, address, main_menu, confidence
    """
    if not OPENAI_KEY: return None

    sub  = (sub_text or "")[:2500]
    desc = (desc_text or "")[:800]
    pin  = (pinned_text or "")[:500]

    prompt = (
        "다음 한국 음식 먹방 유튜브 영상에서 방문한 실제 매장 정보를 추출하세요.\n\n"
        f"[영상 제목]\n{title}\n\n"
        f"[자막 (앞부분)]\n{sub}\n\n"
        f"[영상 설명]\n{desc}\n\n"
        f"[고정 댓글]\n{pin}\n\n"
        "규칙:\n"
        "- restaurant_name은 실제 매장명 (예: '동대문엽기떡볶이 가락점', '곰탕한그릇')\n"
        "- 메뉴명/일반명사 절대 금지 (X: '로제떡볶이', '분식', '삼겹살집', '시골마을')\n"
        "- 매장명 못 찾으면 null (추측 금지)\n"
        "- address는 한국 도로명 주소 (예: '서울 송파구 양재대로62길 16')\n"
        "- confidence: high(영상에 명확) / medium(추론 가능) / low(불확실)\n\n"
        'JSON 형식만 출력:\n{"restaurant_name": "...", "address": "...", "main_menu": "...", "confidence": "high|medium|low"}'
    )

    body = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "한국 음식 영상 매장 정보 추출 전문가. JSON만 반환."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    try:
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {OPENAI_KEY}",
                "Content-Type": "application/json",
            }
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.loads(r.read().decode("utf-8"))
        content = res["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as e:
        print(f"    [LLM 실패: {type(e).__name__}: {str(e)[:80]}]")
        return None


def name_similarity(a: str, b: str) -> float:
    """매장명 유사도 (cross-verify에서 LLM 결과 보존 판단용)"""
    if not a or not b: return 0
    a, b = a.replace(" ", ""), b.replace(" ", "")
    if a == b: return 1.0
    if a in b or b in a: return 0.85
    common = sum(1 for ch in set(a) if ch in b)
    return common / max(len(set(a)), len(set(b)))


# 일반명사/메뉴명 (Kakao 검증 실패 시 거부 대상)
GENERIC_NAMES = {
    "맛집","음식점","분식","구이","냉면","해산물","중식","일식","한식","양식","국밥",
    "떡볶이","로제떡볶이","즉석떡볶이","파스타","우동","칼국수","돈까스","초밥","마라탕",
    "삼겹살","갈비","곱창","대창","막창","치킨","피자","피자집","면류","면집","고깃집",
    "회","사시미","활어회","쭈꾸미","낙지","조개","오겹살",
    "시골마을","우리집","추천한집","이사한집","고기집","술집","해녀촌식당","해녀포차",
    "한국인이라면","분이라면","차량이라면","오징어라면","청어알낙지","매운낙지",
    "삼겹살집","돼지국밥","간장게장","숯불구이","모듬구이","모듬떡볶이",
    "곱창막창대창","튀김칼국수","국물떡볶이","커피집","몽땅식품","두번째",
}


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

    # 추가 메타데이터
    phone = ""
    place_url = ""
    kakao_category = ""

    # ── 전략 0: 영상 설명 + (필요 시) 고정댓글 + 자막 → LLM에 통합 추출 ────
    desc_text = get_video_description(video["id"])

    # 정규식으로 description에서 먼저 주소 시도 (LLM 호출 절약 가능)
    addr_from_desc = extract_address_from_text(desc_text)
    if addr_from_desc:
        coords = kakao_geocode(addr_from_desc)
        if coords:
            lat, lng = coords
            address = addr_from_desc
            if not region: region = find_region(addr_from_desc) or region
            print(f"    [description 주소: {addr_from_desc}]")

    # LLM 추출 (가장 정확) — 설명/자막 모두 활용
    llm_name = None
    if OPENAI_KEY:
        llm = llm_extract_restaurant(title, sub_text, desc_text, "")
        # 첫 시도 실패 또는 confidence 낮으면 고정 댓글 추가해서 재시도
        if not llm or llm.get("confidence") == "low":
            pinned = get_top_pinned_comment(video["id"])
            if pinned:
                llm = llm_extract_restaurant(title, sub_text, desc_text, pinned)

        if llm and llm.get("confidence") in ("high", "medium"):
            nm = (llm.get("restaurant_name") or "").strip()
            ad = (llm.get("address") or "").strip()
            conf = llm.get("confidence")
            if nm and nm not in GENERIC_NAMES:
                llm_name = nm
            # LLM이 주소도 제공하면 사용 (description regex 결과보다 우선)
            if ad and not address:
                coords = kakao_geocode(ad)
                if coords:
                    lat, lng = coords
                    address = ad
                    if not region: region = find_region(ad) or region
            if llm_name:
                name = llm_name
            print(f"    [LLM({conf}): {llm_name or '?'} @ {address or '?'}]")

    # ── 전략 1: 자막 NER → 가게명 → Kakao 검색 ──────────────────────────
    sub_names = extract_names_from_sub(sub_text) if sub_text else []
    for sub_name in sub_names:
        # 가게명으로 직접 Kakao 검색 (주소 없이 키워드만)
        params = {
            "query": f"{region} {sub_name}" if region else sub_name,
            "category_group_code": "FD6", "size": 1,
        }
        # description/comment에서 얻은 좌표가 있으면 좁은 반경 안에서 검색 (정확도↑)
        if lat and lng:
            params["y"] = lat; params["x"] = lng
            params["radius"] = 3000  # 3km
        elif region:
            params["y"] = 36.5; params["x"] = 127.8
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
                phone   = d.get("phone", "") or ""
                place_url = d.get("place_url", "") or ""
                kakao_category = d.get("category_name", "") or ""
                break
        except: pass
        time.sleep(0.1)

    # ── 전략 2: 제목 음식 키워드 → Naver 주소 검색 (전략 0, 1 모두 실패 시) ─
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

    # 전략 0에서 주소만 얻고 이름 아직 못 채운 경우 → placeholder
    # (다음 cross-verify에서 정확한 매장명으로 교체됨)
    if not name:
        food = has_food_keyword(title)
        name = food or (region + "맛집" if region else "맛집")

    # ── Kakao Local Search로 정확한 가게명 최종 교차검증 ──────────────────
    food_hint = has_food_keyword(title) or "음식점"
    results = kakao_search_nearby(lat, lng, query=food_hint, radius=100)
    if results:
        best = results[0]
        dist = ((lat - float(best["y"]))**2 + (lng - float(best["x"]))**2)**0.5 * 111000
        if dist < 80:
            kakao_name = best.get("place_name", "")
            sim = name_similarity(name or "", kakao_name)
            # LLM/NER가 잡은 이름과 Kakao 이름이 매우 다르면 LLM 이름 보존
            # (현재 name이 generic이거나, 유사도가 어느 정도 있으면 Kakao로 표준화)
            if (name or "") in GENERIC_NAMES or not name or sim >= 0.4:
                name = kakao_name or name
            # 주소/메타데이터는 항상 Kakao 우선 (포맷 표준화 + 메타 정확)
            address = best.get("road_address_name") or address
            if best.get("phone"):     phone = best.get("phone", "")
            if best.get("place_url"): place_url = best.get("place_url", "")
            if best.get("category_name"): kakao_category = best.get("category_name", "")

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

    # ── 최종 품질 검증 ──────────────────────────────────────────────────
    # Kakao 메타데이터(전화/URL)도 없고 매장명이 일반명사면 거부
    name_clean = (name or "").strip()
    if not phone and not place_url and name_clean in GENERIC_NAMES:
        print(f"    [거부: 검증 실패 + 일반명사 매장명 - {name_clean}]")
        return None

    return {
        "name": name, "address": address,
        "category": category, "region": region_val,
        "video_id": video["id"], "video_title": title,
        "video_url": video["url"], "thumbnail": video["thumbnail"],
        "upload_date": upload_date,
        "lat": round(lat, 6), "lng": round(lng, 6),
        "source": "auto_kakao",
        "channel": video.get("channel", "tzuyang"),
        "phone": phone,
        "place_url": place_url,
        "kakao_category": kakao_category,
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
