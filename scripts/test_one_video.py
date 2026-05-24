"""
단일 영상 ID로 추출 단계별 결과를 확인 (드라이런).
- restaurants_geo.json 수정 없음
- 자막/설명/댓글/LLM/Kakao 각 단계 출력
사용법:
  python scripts/test_one_video.py <VIDEO_ID> [TITLE]
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import auto_update as au

if len(sys.argv) < 2:
    print("사용법: python scripts/test_one_video.py <VIDEO_ID> [TITLE]")
    sys.exit(1)

vid = sys.argv[1].strip()
override_title = sys.argv[2].strip() if len(sys.argv) >= 3 else ""

print("=" * 60)
print(f"테스트: https://www.youtube.com/watch?v={vid}")
print(f"OpenAI 키: {'있음 (LLM 활성)' if au.OPENAI_KEY else '없음 (LLM 스킵)'}")
print(f"Kakao 키 : {'있음' if au.KAKAO_REST else '없음'}")
print("=" * 60)

# 제목
title = override_title
if not title:
    import urllib.request, json as _json
    try:
        with urllib.request.urlopen(
            f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json",
            timeout=10) as r:
            title = _json.loads(r.read().decode("utf-8")).get("title", "")
    except Exception as e:
        print(f"[oEmbed 실패] {e} — CLI/workflow에서 title 직접 전달하세요")
        sys.exit(1)

print(f"\n[제목] {title}\n")

# 단계 1: 자막
print("─" * 60)
print("[1] 자막 (yt-dlp --write-auto-subs)")
print("─" * 60)
sub_text = au.get_subtitle_text(vid)
print(f"자막 길이: {len(sub_text)}자")
if sub_text:
    print(f"앞부분: {sub_text[:200]}...")
else:
    print("(빈 결과 — YouTube 자막 비활성 or yt-dlp 차단)")

# 단계 2: 영상 설명
print()
print("─" * 60)
print("[2] 영상 설명 (yt-dlp --print description)")
print("─" * 60)
desc_text = au.get_video_description(vid)
print(f"설명 길이: {len(desc_text)}자")
if desc_text:
    print(f"내용:\n{desc_text[:500]}")
else:
    print("(빈 결과)")

# 단계 3: description regex로 주소 추출 시도
print()
print("─" * 60)
print("[3] description regex 주소 추출")
print("─" * 60)
addr_re = au.extract_address_from_text(desc_text)
print(f"추출된 주소: {addr_re or '(없음)'}")

# 단계 4: 댓글 전체 (top + replies)
print()
print("─" * 60)
print("[4] 댓글 전체 (top 40 + replies 20)")
print("─" * 60)
comments_text = au.get_all_top_comments(vid, max_n=50)
print(f"댓글 총 길이: {len(comments_text)}자")
if comments_text:
    # 앞 600자만 미리보기
    print(f"앞부분 미리보기:\n{comments_text[:800]}...")

# 단계 5: 웹 검색 스니펫
print()
print("─" * 60)
print("[5] Naver 웹검색 스니펫 (쯔양 + 영상 제목)")
print("─" * 60)
web_snip = au.naver_search_snippets(f"쯔양 {title}")
print(f"스니펫 길이: {len(web_snip)}자")
if web_snip:
    print(f"앞부분: {web_snip[:400]}...")
    web_addr = au.extract_address_from_text(web_snip)
    print(f"\n  → 추출된 주소: {web_addr or '(없음)'}")

# 단계 6: LLM (vision + comments + web)
print()
print("─" * 60)
print("[6] LLM 추출 (GPT-4o-mini + Vision + 댓글 + 웹검색)")
print("─" * 60)
thumb_url = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
print(f"썸네일 URL: {thumb_url}")
if not au.OPENAI_KEY:
    print("OpenAI 키 없음 — 스킵")
    llm = None
else:
    llm_list = au.llm_extract_restaurant(title, sub_text, desc_text, comments_text, web_snip, thumb_url) or []
    print(f"\n결과: {len(llm_list)}개 매장 추출")
    for i, llm in enumerate(llm_list):
        print(f"\n  [매장 {i+1}/{len(llm_list)}]")
        for k, val in llm.items():
            print(f"    {k}: {val}")

# 단계 7: 전체 파이프라인 실행
print()
print("─" * 60)
print("[7] process_new_video() 전체 실행")
print("─" * 60)
video = {
    "id": vid, "title": title,
    "url": f"https://www.youtube.com/watch?v={vid}",
    "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
    "channel": "tzuyang",
}
entries = au.process_new_video(video) or []

print()
print("=" * 60)
print(f"최종 결과 — {len(entries)}개 매장")
print("=" * 60)
if entries:
    for i, entry in enumerate(entries):
        print(f"\n[매장 {i+1}/{len(entries)}]")
        for k in ("name","address","category","region","lat","lng","phone","place_url","kakao_category","source"):
            val = entry.get(k, "")
            if val: print(f"  {k:<18}: {val}")
else:
    print("  (엔트리 생성 안 됨)")
