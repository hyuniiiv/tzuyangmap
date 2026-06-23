"""빈 menus를 LLM(GPT-4o-mini)으로 보강.

입력: video_title + kakao_category + name
출력: 영상에서 먹은 실제 메뉴 1~5개 (JSON)
비용: 약 125건 × $0.0001 ≈ $0.015
"""
import json, sys, os, urllib.request
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

ROOT = Path(__file__).parent.parent
GEO = ROOT / "public" / "data" / "restaurants_geo.json"

# .env 읽기
ENV = ROOT / ".env"
if not ENV.exists() and (ROOT.parent / ".env").exists():
    ENV = ROOT.parent / ".env"
OPENAI_KEY = ""
if ENV.exists():
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("OPEN_AI_API_KEY") or line.strip().startswith("OPENAI_API_KEY"):
            OPENAI_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
if not OPENAI_KEY:
    OPENAI_KEY = os.getenv("OPEN_AI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
if not OPENAI_KEY:
    print("⚠️ OPENAI_KEY 없음 — 종료")
    sys.exit(1)


SCHEMA = {
    "name": "menus_extract",
    "schema": {
        "type": "object",
        "properties": {
            "menus": {
                "type": "array",
                "items": {"type": "string"},
                "description": "이 영상에서 쯔양이 먹은 실제 음식/메뉴 이름 1~5개. "
                               "카테고리어(한식/일식/분식 등)나 일반어(음식점/맛집/요리)는 절대 넣지 마세요. "
                               "구체적 음식명만 (예: 곰탕, 엽기떡볶이, 매운갈비찜, 칼국수, 평양냉면). "
                               "확실하지 않으면 빈 배열."
            }
        },
        "required": ["menus"],
        "additionalProperties": False,
    },
    "strict": True,
}


def llm_menus(title: str, name: str, kakao_cat: str) -> list:
    sys_msg = (
        "You extract Korean food/menu items from YouTube videos by 쯔양 (Korean mukbang YouTuber). "
        "Return ONLY actual specific food/menu names from the video title and store info. "
        "Never return category words like 한식/일식/분식/중식/양식/음식점/맛집."
    )
    user_msg = (
        f"영상 제목: {title}\n"
        f"매장명: {name}\n"
        f"카카오 카테고리: {kakao_cat}\n\n"
        "이 영상에서 먹은 구체적인 음식/메뉴를 1~5개 추출하세요. "
        "카테고리어나 일반어는 제외. 확실한 음식만."
    )
    payload = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        "response_format": {"type": "json_schema", "json_schema": SCHEMA},
        "temperature": 0,
        "max_tokens": 200,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read().decode("utf-8"))
        content = res["choices"][0]["message"]["content"]
        obj = json.loads(content)
        out = obj.get("menus", []) or []
        return [m.strip() for m in out if isinstance(m, str) and m.strip()]
    except Exception as e:
        print(f"    [LLM 실패: {e}]")
        return []


def main():
    data = json.load(open(GEO, encoding="utf-8"))
    print(f"전체: {len(data)}개")

    # video_id 기준 그룹화 (같은 영상은 한 번만 호출)
    empty_entries = [r for r in data if not (r.get("menus") or [])]
    by_vid = defaultdict(list)
    for r in empty_entries:
        by_vid[r.get("video_id", "")].append(r)
    print(f"빈 menus: {len(empty_entries)}건 / 유니크 영상: {len(by_vid)}개")
    print(f"예상 비용: 약 ${len(by_vid) * 0.0001:.3f}\n")

    filled = 0
    for i, (vid, entries) in enumerate(by_vid.items()):
        title = entries[0].get("video_title", "") or ""
        # 같은 영상 내 매장은 카테고리/이름 정보 합쳐서 1번 호출
        names = " / ".join(set(r.get("name", "") for r in entries if r.get("name")))[:80]
        cats  = " / ".join(set(r.get("kakao_category", "") for r in entries if r.get("kakao_category")))[:120]

        print(f"[{i+1}/{len(by_vid)}] {title[:55]}")
        menus = llm_menus(title, names, cats)
        if menus:
            print(f"    → {menus}")
            for r in entries:
                r["menus"] = menus
                filled += 1
        else:
            print(f"    (메뉴 추출 실패)")

    print(f"\nLLM으로 채운 entry: {filled}건")
    json.dump(data, open(GEO, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"저장 완료")


if __name__ == "__main__":
    main()
