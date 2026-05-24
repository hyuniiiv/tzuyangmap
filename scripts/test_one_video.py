"""
단일 영상 ID로 process_new_video()를 드라이런해서 추출 결과를 확인.
- restaurants_geo.json 수정 없음
- LLM/description/comment/Kakao 각 단계 출력

사용법:
  python scripts/test_one_video.py <VIDEO_ID>

예시:
  python scripts/test_one_video.py xFGP21Xmn2w
"""
import sys, json
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import auto_update as au

if len(sys.argv) < 2:
    print("사용법: python scripts/test_one_video.py <VIDEO_ID>")
    sys.exit(1)

vid = sys.argv[1].strip()
print("=" * 60)
print(f"테스트: https://www.youtube.com/watch?v={vid}")
print(f"OpenAI 키: {'있음 (LLM 활성)' if au.OPENAI_KEY else '없음 (LLM 스킵, 기존 흐름만)'}")
print("=" * 60)

# 영상 정보 (제목) — YouTube oEmbed API로 가져오기 (봇 차단 없음)
import urllib.request, urllib.parse, json as _json
title = ""
try:
    oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json"
    with urllib.request.urlopen(oembed_url, timeout=10) as r:
        d = _json.loads(r.read().decode("utf-8"))
    title = d.get("title", "")
except Exception as e:
    print(f"oEmbed 실패: {e}")
    # 폴백: yt-dlp
    import subprocess
    r = subprocess.run(
        ["yt-dlp", "--print", "title", "--skip-download", "--no-warnings",
         f"https://www.youtube.com/watch?v={vid}"],
        capture_output=True, encoding="utf-8", errors="replace", timeout=20
    )
    title = (r.stdout or "").strip()

if not title:
    print("영상 제목 가져오기 실패")
    sys.exit(1)

thumbnail = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
print(f"\n[영상 제목] {title}\n")

video = {
    "id": vid,
    "title": title,
    "url": f"https://www.youtube.com/watch?v={vid}",
    "thumbnail": thumbnail,
    "channel": "tzuyang",
}

# process_new_video 실행
entry = au.process_new_video(video)

print()
print("=" * 60)
print("최종 결과")
print("=" * 60)
if entry:
    for k in ("name","address","category","region","lat","lng","phone","place_url","kakao_category","source"):
        v = entry.get(k, "")
        if v: print(f"  {k:<18}: {v}")
else:
    print("  (엔트리 생성 안 됨 — 거부됨 또는 정보 부족)")
