"""
채널 최근 N개 영상을 process_new_video()로 dry-run 처리.
- restaurants_geo.json 수정 없음
- 각 영상별 추출 결과/실패 사유 출력
- yt-dlp이 GitHub Actions에서 작동하는지도 검증

사용법:
  python scripts/test_recent_videos.py [N]   # default 10
"""
import sys, json, subprocess, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import auto_update as au

N = int(sys.argv[1]) if len(sys.argv) >= 2 else 10
CHANNEL = "https://www.youtube.com/@tzuyang6145/videos"

print("=" * 70)
print(f"최근 {N}개 영상 dry-run 테스트")
print(f"OpenAI: {'있음 (LLM 활성)' if au.OPENAI_KEY else '없음 (LLM 스킵)'}")
print(f"Kakao : {'있음' if au.KAKAO_REST else '없음'}")
print("=" * 70)

# 1) 채널 목록 (--flat-playlist)
print(f"\n[1] yt-dlp으로 최근 {N}개 영상 목록 가져오기...")
r = subprocess.run(
    ["yt-dlp", "--flat-playlist", "--dump-json", "--no-warnings",
     "--extractor-args", "youtube:lang=ko",
     "--playlist-end", str(N), CHANNEL],
    capture_output=True, encoding="utf-8", errors="replace", timeout=60
)
videos = []
for line in (r.stdout or "").splitlines():
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
            "thumbnail": thumb, "channel": "tzuyang",
        })
    except: continue

print(f"  → {len(videos)}개 가져옴")
if not videos:
    print(f"  stderr: {r.stderr[:400]}")
    sys.exit(1)

# 2) 각 영상 처리
results = []
for i, v in enumerate(videos):
    print()
    print("─" * 70)
    print(f"[{i+1}/{len(videos)}] {v['title'][:60]}")
    print(f"  id: {v['id']}")
    print("─" * 70)

    t0 = time.time()
    entry = au.process_new_video(v)
    elapsed = time.time() - t0

    if entry:
        print(f"  ✓ 성공 ({elapsed:.1f}s)")
        print(f"    name      : {entry.get('name')}")
        print(f"    address   : {entry.get('address')}")
        print(f"    phone     : {entry.get('phone') or '(없음)'}")
        print(f"    category  : {entry.get('category')} / {entry.get('region')}")
        print(f"    place_url : {entry.get('place_url') or '(없음)'}")
        results.append(("OK", v["title"][:40], entry.get("name"), entry.get("address")))
    else:
        print(f"  ✗ 거부됨 또는 추출 실패 ({elapsed:.1f}s)")
        results.append(("FAIL", v["title"][:40], None, None))

# 3) 요약
print()
print("=" * 70)
print("요약")
print("=" * 70)
ok = sum(1 for r in results if r[0] == "OK")
print(f"성공: {ok}/{len(results)}개\n")
for status, title, name, addr in results:
    mark = "✓" if status == "OK" else "✗"
    if name:
        print(f"  {mark} {title:<42} → {name} | {addr or ''}")
    else:
        print(f"  {mark} {title:<42} → (추출 실패)")
