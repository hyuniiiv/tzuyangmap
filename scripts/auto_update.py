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

# .env 읽기 — ROOT 또는 ROOT 부모(workspace 루트)에서 찾음
ENV_FILE = ROOT / ".env"
if not ENV_FILE.exists():
    parent_env = ROOT.parent / ".env"
    if parent_env.exists():
        ENV_FILE = parent_env

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
    "이스탄불","홍콩","일본","홋카이도","삿포로","오사카","도쿄","교토","후쿠오카",
    "인도네시아","반둥","대만","대만(타이","중국","베트남","태국","싱가포르","발리",
    "말레이시아","미국","파리","런던","유럽","몽골","인도","필리핀","사이판","괌",
    "뉴욕","두바이","하와이","호주","스페인","이탈리아","터키","라스베가스","베가스",
    "캐나다","독일","프랑스","스위스","스웨덴","노르웨이","핀란드","러시아","우크라이나",
    "istanbul","hong kong","japan","bandung","taiwan","vietnam","cambodia","laos",
    "thailand","usa","paris","london","singapore","maldives","tokyo","osaka",
    "sydney","budapest","las vegas","vegas","jakarta","bali","macau","macao",
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
         "--playlist-end", "2",    # 최신 2개만 (LLM API 비용 제어)
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


def get_all_top_comments(vid_id: str, max_n: int = 150) -> str:
    """상위 댓글 + 하트 받은 댓글을 텍스트로 합쳐 반환.
    yt-dlp이 GitHub IP에서 봇 차단당해서 youtube-comment-downloader 사용.
    (web 스크래핑 방식 — 봇 차단 우회)
    매장 식별의 핵심 신호이므로 max 150개까지."""
    try:
        from youtube_comment_downloader import YoutubeCommentDownloader, SORT_BY_POPULAR
    except ImportError:
        print("    [경고: youtube-comment-downloader 미설치]")
        return ""

    try:
        dl = YoutubeCommentDownloader()
        url = f"https://www.youtube.com/watch?v={vid_id}"
        comments = []
        for i, c in enumerate(dl.get_comments_from_url(url, sort_by=SORT_BY_POPULAR, language="ko")):
            if i >= max_n: break
            comments.append(c)

        # 우선순위 정렬: 하트(업로더 좋아요) → 좋아요 수
        def rank(c):
            r = 0
            if c.get("heart"): r += 5000     # 쯔양이 직접 하트 누른 댓글
            if c.get("paid"):  r += 2000     # 슈퍼챗
            try:
                # "1.2K" "354" 같은 문자열을 정수로
                votes = c.get("votes", "0")
                if isinstance(votes, str):
                    s = votes.replace(",", "").upper()
                    if s.endswith("K"): votes = int(float(s[:-1]) * 1000)
                    elif s.endswith("M"): votes = int(float(s[:-1]) * 1000000)
                    else: votes = int(s)
                r += votes
            except: pass
            return -r
        comments.sort(key=rank)

        parts = []
        for c in comments:
            text = (c.get("text") or "").strip()
            if not text: continue
            tag = ""
            if c.get("heart"): tag += "[♥쯔양추천] "
            parts.append(f"{tag}{text}")
        return "\n---\n".join(parts)
    except Exception as e:
        print(f"    [댓글 수집 실패: {type(e).__name__}: {str(e)[:80]}]")
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


def naver_search_snippets(query: str, max_chars: int = 2500) -> str:
    """Naver 검색 결과 페이지 텍스트 추출 — LLM 컨텍스트로 사용.
    블로그/뉴스 본문 일부가 검색결과 페이지에 노출되어 주소/매장명 단서 가능."""
    enc = urllib.parse.quote(query)
    req = urllib.request.Request(
        f"https://search.naver.com/search.naver?query={enc}",
        headers=HEADERS
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            html = r.read().decode("utf-8", errors="replace")
        text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>",   " ", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception:
        return ""


def llm_extract_restaurant(title: str, sub_text: str, desc_text: str,
                           comments_text: str = "", web_snippets: str = "",
                           thumbnail_url: str = "") -> dict | None:
    """OpenAI(GPT-4o-mini Vision)로 영상에서 매장명/주소 추출.
    - 자막/설명/댓글(전부) + 웹 검색 + 썸네일 이미지 종합 분석
    - 자막은 화자(쯔양/사장님) 발화에서 위치 단서 추출 핵심 소스
    - 댓글은 팬들이 지점/주소 언급하는 보조 신호
    - JSON: restaurant_name, brand, address, main_menu, confidence, evidence
    """
    if not OPENAI_KEY: return None

    sub  = (sub_text or "")[:3000]   # 자막 3000자 (이전 5000)
    desc = (desc_text or "")[:500]
    com  = (comments_text or "")[:6000]  # 댓글 6000자 (~100개, 이전 10000)
    web  = (web_snippets or "")[:1000]   # 웹스니펫 1000자 (이전 2000)

    prompt = (
        "한국 음식 먹방 영상에서 매장 정보 추출. 정확도 0순위.\n\n"
        f"[제목] {title}\n"
        f"[자막]\n{sub or '(없음)'}\n"
        f"[설명]\n{desc or '(없음)'}\n"
        f"[댓글]\n{com or '(없음)'}\n"
        f"[웹검색]\n{web or '(없음)'}\n"
        "[썸네일 첨부]\n\n"
        "분석 우선순위:\n"
        "1. 댓글에서 매장명/지점/주소 언급 (예: 'OO점이에요', '주소가 어디?' 답글 도로명)\n"
        "2. 자막에서 화자 발언 (사장님 자기소개, 쯔양 도착멘트, 메뉴유래)\n"
        "3. 썸네일 간판/로고/메뉴판\n"
        "4. 웹 검색 결과 블로그/뉴스\n\n"
        "규칙:\n"
        "- 약칭→정식명 (엽떡→동대문엽기떡볶이)\n"
        "- 체인은 지점명 포함 (단서 있을 때만, 추측 금지)\n"
        "- 시장/거리/골목도 OK (노량진수산시장, 남대문갈치골목)\n"
        "- 다중 매장 영상은 restaurants 배열에 모두\n"
        "- 메뉴/일반명사 금지 (X: 로제떡볶이, 삼겹살집)\n"
        "- 불확실하면 restaurant_name=null, brand만\n\n"
        "confidence: high(2+ 소스 일치) / medium(1소스 또는 브랜드만 확실) / low\n"
        "evidence: 어느 소스의 어떤 문구에서 단서.\n\n"
        "JSON: restaurants(array of {restaurant_name, brand, address, main_menu}), confidence, evidence"
    )

    user_content = [{"type": "text", "text": prompt}]
    if thumbnail_url:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": thumbnail_url, "detail": "low"},
        })

    # JSON Schema로 응답 구조 강제 (항상 restaurants 배열 반환)
    json_schema = {
        "name": "restaurant_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "restaurants": {
                    "type": "array",
                    "description": "방문 매장(들). 단일 매장이면 1개, 다중 매장이면 N개.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "restaurant_name": {"type": ["string", "null"]},
                            "brand": {"type": ["string", "null"]},
                            "address": {"type": ["string", "null"]},
                            "main_menu": {"type": ["string", "null"]},
                        },
                        "required": ["restaurant_name","brand","address","main_menu"],
                        "additionalProperties": False,
                    },
                },
                "confidence": {"type": "string", "enum": ["high","medium","low"]},
                "evidence": {"type": "string"},
            },
            "required": ["restaurants","confidence","evidence"],
            "additionalProperties": False,
        },
    }
    body = {
        "model": "gpt-4o-mini",  # vision + structured outputs 지원
        "messages": [
            {"role": "system", "content": "한국 음식 영상 매장 정보 추출 전문가. 썸네일 이미지 분석. 정해진 JSON 스키마만 반환."},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_schema", "json_schema": json_schema},
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
        with urllib.request.urlopen(req, timeout=45) as r:
            res = json.loads(r.read().decode("utf-8"))
        content = res["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        # 새 형식: {"restaurants": [...], "confidence": ..., "evidence": ...}
        # 구 형식 호환: {"restaurant_name": ..., ...} → 1개짜리 list로 wrap
        if "restaurants" in parsed:
            restaurants = parsed.get("restaurants") or []
            conf = parsed.get("confidence", "low")
            ev = parsed.get("evidence", "")
            for r in restaurants:
                r["confidence"] = conf
                r["evidence"] = ev
            return restaurants
        else:
            # 단일 매장 응답 (구 형식)
            return [parsed]
    except Exception as e:
        print(f"    [LLM 실패: {type(e).__name__}: {str(e)[:120]}]")
        return []


def kakao_search_brand(brand: str, region: str = "", limit: int = 5) -> list:
    """브랜드명으로 Kakao Local 검색 (전국 매장 후보)"""
    if not KAKAO_REST or not brand: return []
    q = f"{region} {brand}" if region else brand
    params = {"query": q, "category_group_code": "FD6", "size": limit}
    url = "https://dapi.kakao.com/v2/local/search/keyword.json?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {KAKAO_REST}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode("utf-8")).get("documents", [])
    except: return []


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


def get_subtitle_via_api(vid_id: str) -> str:
    """youtube-transcript-api로 자막 받기 — yt-dlp 봇 차단 우회.
    별도 transcript endpoint 사용해서 GitHub IP에서도 작동."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return ""
    try:
        api = YouTubeTranscriptApi()
        # 한국어 우선, 자동 생성 자막 포함
        transcript_list = api.list(vid_id)
        # 수동 자막 한국어
        try:
            transcript = transcript_list.find_manually_created_transcript(['ko'])
        except Exception:
            # 자동 생성 자막 한국어
            try:
                transcript = transcript_list.find_generated_transcript(['ko'])
            except Exception:
                return ""
        snippets = transcript.fetch()
        text = " ".join(s.text for s in snippets if hasattr(s, 'text'))
        return text
    except Exception:
        return ""


def get_subtitle_text(vid_id: str) -> str:
    """자막 가져오기 — youtube-transcript-api 우선, yt-dlp 폴백.
    GitHub Actions IP에서 yt-dlp 봇 차단으로 자막 0자 되는 문제 해결."""
    # 1순위: youtube-transcript-api (봇 차단 우회)
    text = get_subtitle_via_api(vid_id)
    if text and len(text) > 200:
        return text

    # 폴백: yt-dlp
    vtt_path = SUB_DIR / f"{vid_id}.ko.vtt"
    if not (vtt_path.exists() and vtt_path.stat().st_size > 300):
        subprocess.run([
            "yt-dlp", "--skip-download", "--write-auto-subs",
            "--sub-lang", "ko", "--sub-format", "vtt",
            "-o", str(SUB_DIR / "%(id)s"), "--no-warnings",
            f"https://www.youtube.com/watch?v={vid_id}",
        ], capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    if not (vtt_path.exists() and vtt_path.stat().st_size > 300): return text or ""
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


def _build_entry_from_llm(video: dict, title: str, sub_text: str, desc_text: str,
                          region: str, food: str | None, web_snip: str,
                          llm_r: dict) -> dict | None:
    """LLM이 추출한 단일 매장 정보를 Naver/Kakao로 검증해서 완성된 entry로 변환.
    다중 매장 영상의 각 매장을 처리하기 위해 분리됨."""
    upload_date = date.today().strftime("%Y-%m-%d")
    address = None
    name = None
    lat = lng = None
    phone = ""
    place_url = ""
    kakao_category = ""

    llm_name = (llm_r.get("restaurant_name") or "").strip()
    llm_brand = (llm_r.get("brand") or "").strip()
    llm_addr = (llm_r.get("address") or "").strip()
    conf = llm_r.get("confidence", "?")
    ev = (llm_r.get("evidence") or "")[:120]

    # 일반명사 제거
    if llm_name in GENERIC_NAMES:
        llm_name = ""

    # LLM이 주소 줬으면 지오코딩
    if llm_addr:
        coords = kakao_geocode(llm_addr)
        if coords:
            lat, lng = coords
            address = llm_addr
            if not region: region = find_region(llm_addr) or region

    if llm_name:
        name = llm_name
    elif llm_brand:
        name = llm_brand

    print(f"    [LLM({conf}): {llm_name or llm_brand or '?'} @ {address or '?'} | {ev}]")

    # Naver 보조 검색 (이름은 있는데 주소 없을 때)
    if (llm_name or llm_brand) and not address:
        name_q = llm_name or llm_brand
        queries = []
        if region:
            queries.append(f"{name_q} {region} 주소")
            queries.append(f"쯔양 {name_q} {region}")
        queries.append(f"{name_q} 주소")
        queries.append(f"쯔양 {name_q}")
        for q in queries:
            naver_addr = naver_search_address(q)
            if naver_addr:
                coords = kakao_geocode(naver_addr)
                if coords:
                    lat, lng = coords
                    address = naver_addr
                    if not region: region = find_region(naver_addr) or region
                    print(f"    [Naver 보조 주소: '{q}' → {naver_addr}]")
                    break

    # Kakao 검증 (LLM 이름으로 재검색해서 실제 매장 매칭)
    if llm_name or llm_brand:
        candidate = llm_name or llm_brand
        kakao_results = kakao_search_brand(candidate, region or "", limit=5)
        best = None
        best_score = -1
        for c in kakao_results:
            try:
                clat = float(c["y"]); clng = float(c["x"])
                sim = name_similarity(candidate, c.get("place_name", ""))
                dist_km = 0
                if lat and lng:
                    dist_km = ((clat-lat)**2 + (clng-lng)**2)**0.5 * 111
                score = sim * 100 - (dist_km * 0.5)
                if score > best_score:
                    best_score = score
                    best = (c, sim, dist_km)
            except: continue
        ok = False
        if best:
            sim_v, dist_v = best[1], best[2]
            if sim_v >= 0.85: ok = True
            elif sim_v >= 0.5 and dist_v <= 30: ok = True
            elif sim_v >= 0.4 and dist_v <= 10: ok = True
            elif sim_v >= 0.3 and dist_v <= 5 and lat and lng: ok = True
        if ok:
            c, sim, dist_km = best
            try:
                lat = float(c["y"])
                lng = float(c["x"])
                address = c.get("road_address_name") or c.get("address_name", "") or address
                name = c.get("place_name", name)
                phone = c.get("phone", "") or phone
                place_url = c.get("place_url", "") or place_url
                kakao_category = c.get("category_name", "") or kakao_category
                print(f"    [Kakao 검증: {name} @ {address} (sim={sim:.2f}, dist={dist_km:.1f}km)]")
            except: pass

    if not lat or not lng: return None
    if not name:
        name = food or (region + "맛집" if region else "맛집")

    # 추가 cross-verify with food_hint
    food_hint = food or "음식점"
    nearby = kakao_search_nearby(lat, lng, query=food_hint, radius=100)
    if nearby:
        best_n = nearby[0]
        try:
            dist_n = ((lat - float(best_n["y"]))**2 + (lng - float(best_n["x"]))**2)**0.5 * 111000
            if dist_n < 80:
                k_name = best_n.get("place_name", "")
                k_sim = name_similarity(name, k_name)
                if (name in GENERIC_NAMES) or k_sim >= 0.4:
                    name = k_name or name
                address = best_n.get("road_address_name") or address
                if best_n.get("phone") and not phone: phone = best_n.get("phone", "")
                if best_n.get("place_url") and not place_url: place_url = best_n.get("place_url", "")
                if best_n.get("category_name") and not kakao_category: kakao_category = best_n.get("category_name", "")
        except: pass

    # 카테고리 매핑
    cat_map = {
        "떡볶이":"분식","냉면":"냉면","닭갈비":"닭갈비","게장":"해산물","국밥":"국밥",
        "갈비":"구이","곱창":"구이","순대":"분식","칼국수":"면류","돈까스":"일식",
        "초밥":"일식","짜장":"중식","짬뽕":"중식","삼겹살":"구이","치킨":"치킨",
        "라면":"면류","우동":"면류","만두":"분식","해산물":"해산물","구이":"구이",
        "회":"해산물","보쌈":"한식","족발":"한식","한우":"한식","비빔밥":"한식",
    }
    category = cat_map.get(food, "기타")

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
    if region_val == "기타" and address:
        for city, r in region_map.items():
            if city in address: region_val = r; break

    # 최종 품질 검증
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


def process_new_video(video: dict) -> list[dict]:
    """영상에서 매장(들)을 추출. 다중 매장 영상도 list로 반환.
    Returns: list of entry dicts (length 0~N)."""
    title = video["title"]

    # 해외 스킵
    if any(k in title.lower() for k in OVERSEAS_KW): return []

    # 자막 수집
    sub_text = get_subtitle_text(video["id"])
    region   = find_region(title + " " + sub_text[:500])
    upload_date = date.today().strftime("%Y-%m-%d")

    address = None
    name    = None
    lat = lng = None
    food = has_food_keyword(title)  # 함수 전반에서 사용 (category 매핑 등)

    # 추가 메타데이터
    phone = ""
    place_url = ""
    kakao_category = ""

    # ── 전략 0: 자막 + 설명 + 웹검색 + 썸네일을 LLM에 통합 분석 ──────────
    desc_text = get_video_description(video["id"])

    # description 정규식 주소 (LLM 없이도 작동)
    addr_from_desc = extract_address_from_text(desc_text)
    if addr_from_desc:
        coords = kakao_geocode(addr_from_desc)
        if coords:
            lat, lng = coords
            address = addr_from_desc
            if not region: region = find_region(addr_from_desc) or region
            print(f"    [description 주소: {addr_from_desc}]")

    # 웹 검색 (Naver) — 영상 제목 + 쯔양으로 블로그/뉴스 본문 수집
    web_snip = naver_search_snippets(f"쯔양 {title}")
    if web_snip:
        # 검색 결과에서 주소 패턴 직접 추출 시도 (보조)
        web_addr = extract_address_from_text(web_snip)
        if web_addr and not address:
            coords = kakao_geocode(web_addr)
            if coords:
                lat, lng = coords
                address = web_addr
                print(f"    [웹검색 주소: {web_addr}]")

    # 댓글 수집 — 매장 식별의 핵심 신호 (팬들이 지점/주소 언급)
    comments_text = get_all_top_comments(video["id"], max_n=100)

    # LLM 통합 분석 (제목 + 자막 + 설명 + 댓글전체 + 웹스니펫 + 썸네일) — list 반환
    llm_list = []
    if OPENAI_KEY:
        thumb = video.get("thumbnail") or f"https://i.ytimg.com/vi/{video['id']}/hqdefault.jpg"
        llm_list = llm_extract_restaurant(title, sub_text, desc_text, comments_text, web_snip, thumb) or []

    # ── 다중 매장 영상: LLM이 2개 이상 매장 반환했으면 각각 처리해서 list 반환 ──
    if len(llm_list) > 1:
        print(f"    [다중 매장 감지: {len(llm_list)}개]")
        entries = []
        for llm_r in llm_list:
            e = _build_entry_from_llm(video, title, sub_text, desc_text,
                                       region, food, web_snip, llm_r)
            if e:
                entries.append(e)
        print(f"    [다중 매장 결과: {len(entries)}/{len(llm_list)}개 추출 성공]")
        return entries

    # ── 단일 매장 (또는 LLM 결과 없음): 기존 흐름 ─────────────────────────
    llm_name = None
    llm_brand = None
    llm = llm_list[0] if llm_list else None
    if llm:
        nm    = (llm.get("restaurant_name") or "").strip()
        br    = (llm.get("brand") or "").strip()
        ad    = (llm.get("address") or "").strip()
        menu  = (llm.get("main_menu") or "").strip()
        conf  = llm.get("confidence", "?")
        ev    = (llm.get("evidence") or "")[:120]

        if nm and nm not in GENERIC_NAMES:
            llm_name = nm
        if br:
            llm_brand = br

        # 주소: LLM > web/desc regex > Kakao geocode
        if ad and not address:
            coords = kakao_geocode(ad)
            if coords:
                lat, lng = coords
                address = ad
                if not region: region = find_region(ad) or region

        if llm_name:
            name = llm_name
        elif llm_brand and not name:
            name = llm_brand  # 브랜드라도 placeholder

        print(f"    [LLM({conf}): {llm_name or llm_brand or '?'} @ {address or '?'} | {ev}]")

    # ── Strategy 1.5: LLM이 매장명 줬는데 주소 없으면 Naver 보조 검색 ─────
    # "고추명가", "우지커피" 같은 LLM이 정확히 잡은 이름을 Naver에서 직접 검색
    if (llm_name or llm_brand) and not address:
        name_q = llm_name or llm_brand
        # 여러 쿼리 시도
        queries = []
        if region:
            queries.append(f"{name_q} {region} 주소")
            queries.append(f"쯔양 {name_q} {region}")
        queries.append(f"{name_q} 주소")
        queries.append(f"쯔양 {name_q}")
        for q in queries:
            naver_addr = naver_search_address(q)
            if naver_addr:
                coords = kakao_geocode(naver_addr)
                if coords:
                    lat, lng = coords
                    address = naver_addr
                    if not region: region = find_region(naver_addr) or region
                    print(f"    [Naver 보조 주소: '{q}' → {naver_addr}]")
                    break

    # ── LLM 결과 Kakao 검증 ─────────────────────────────────────────────
    # LLM이 매장명을 주면 Kakao에서 그 이름으로 검색해서 실제 좌표/주소로 대체.
    # LLM 주소가 정확하면 유지, hallucination이면 실제 매장 주소로 교체.
    if llm_name or llm_brand:
        candidate = llm_name or llm_brand
        kakao_results = kakao_search_brand(candidate, region or "", limit=5)

        # 점수: 이름 유사도 + LLM 좌표 근접도
        best = None
        best_score = -1
        for c in kakao_results:
            try:
                clat = float(c["y"]); clng = float(c["x"])
                sim = name_similarity(candidate, c.get("place_name", ""))
                dist_km = 0
                if lat and lng:
                    dist_km = ((clat-lat)**2 + (clng-lng)**2)**0.5 * 111
                score = sim * 100 - (dist_km * 0.5)
                if score > best_score:
                    best_score = score
                    best = (c, sim, dist_km)
            except: continue

        # 정밀 임계값 — 이름 유사도와 거리 모두 고려해서 false positive 방지
        # - sim ≥ 0.85: 거리 무관 통과 (강한 이름 매칭)
        # - sim 0.5~0.85: 거리 30km 이내
        # - sim 0.4~0.5:  거리 10km 이내
        # - sim 0.3~0.4:  거리 5km 이내 + LLM 좌표 존재
        ok = False
        if best:
            sim_v, dist_v = best[1], best[2]
            if sim_v >= 0.85:
                ok = True
            elif sim_v >= 0.5 and dist_v <= 30:
                ok = True
            elif sim_v >= 0.4 and dist_v <= 10:
                ok = True
            elif sim_v >= 0.3 and dist_v <= 5 and lat and lng:
                ok = True
        if ok:
            c, sim, dist_km = best
            try:
                lat = float(c["y"])
                lng = float(c["x"])
                address = c.get("road_address_name") or c.get("address_name", "")
                name = c.get("place_name", llm_name or llm_brand)
                phone = c.get("phone", "") or phone
                place_url = c.get("place_url", "") or place_url
                kakao_category = c.get("category_name", "") or kakao_category
                print(f"    [Kakao 검증: {name} @ {address} (sim={sim:.2f}, dist={dist_km:.1f}km)]")
            except: pass

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
        if not food: return []
        query = f"쯔양 {region} {food} 맛집 주소" if region else f"쯔양 {food} 맛집 주소"
        address = naver_search_address(query)
        if not address: return []

        coords = kakao_geocode(address)
        if not coords: return []
        lat, lng = coords
        name = f"{region}{food}" if region else food

    if not lat or not lng: return []

    # 전략 0에서 주소만 얻고 이름 아직 못 채운 경우 → placeholder
    # (다음 cross-verify에서 정확한 매장명으로 교체됨)
    if not name:
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
        return []

    return [{
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
    }]


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
            entries = process_new_video(v)  # list[dict] 반환 (다중 매장 지원)
            if entries:
                new_entries.extend(entries)
                for entry in entries:
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
