"""미처리 영상 청크 처리 (병렬 에이전트용).
- 청크 파일에서 영상 목록 읽어 process_new_video 실행
- 성공한 entries를 결과 파일에 저장
사용: python scripts/process_unproc_chunk.py <chunk_idx>
"""
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import auto_update as au

idx = int(sys.argv[1])
ROOT = Path(__file__).parent.parent
CHUNK_FILE = ROOT / "scripts" / f".unproc_chunk_{idx}.json"
OUT_FILE = ROOT / "scripts" / f".unproc_entries_{idx}.json"

items = json.loads(CHUNK_FILE.read_text(encoding="utf-8"))
print(f"[Chunk {idx}] {len(items)}개 처리 시작")

all_entries = []
t_start = time.time()
pass_count = 0
fail_count = 0

for i, v in enumerate(items):
    vid = v["id"]; title = v["title"]
    print(f"  [{i+1}/{len(items)}] {title[:60]}")
    video = {
        "id": vid, "title": title,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        "channel": "tzuyang",
    }
    try:
        entries = au.process_new_video(video) or []
    except Exception as e:
        print(f"    예외: {type(e).__name__}: {str(e)[:80]}")
        entries = []

    if entries:
        pass_count += 1
        for e in entries:
            print(f"    ✓ {e.get('name')} @ {e.get('address')}")
        all_entries.extend(entries)
    else:
        fail_count += 1
        print(f"    ✗")

OUT_FILE.write_text(json.dumps(all_entries, ensure_ascii=False, indent=2), encoding="utf-8")
elapsed = time.time() - t_start
print(f"\n[Chunk {idx}] 완료 — 통과 {pass_count}/{len(items)}, 엔트리 {len(all_entries)}개, {elapsed/60:.1f}분")
