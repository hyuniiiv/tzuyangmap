"""기존 데이터의 upload_date를 영상 실제 게시일로 백필.
- 병렬 처리 (subprocess 동시 실행)
- yt-dlp batch URL 호출로 효율화

사용: python scripts/backfill_upload_dates.py [chunk_idx] [chunk_total]
- chunk_idx 없으면 전체 처리
"""
import sys, json, subprocess
from pathlib import Path
import math

ROOT = Path(__file__).parent.parent
GEO_FILE = ROOT / "public" / "data" / "restaurants_geo.json"

data = json.loads(GEO_FILE.read_text(encoding="utf-8"))

# unique video_id 추출
vids = []
seen = set()
for r in data:
    v = r.get("video_id")
    if v and v not in seen:
        seen.add(v)
        vids.append(v)

# chunk 처리
if len(sys.argv) >= 3:
    idx = int(sys.argv[1])
    total = int(sys.argv[2])
    ch = math.ceil(len(vids)/total)
    vids = vids[idx*ch:(idx+1)*ch]
    print(f"[Chunk {idx}/{total}] {len(vids)}개 처리")

# yt-dlp batch — 한 번에 여러 URL 처리
BATCH = 30
results = {}  # vid → date
for i in range(0, len(vids), BATCH):
    chunk = vids[i:i+BATCH]
    urls = [f"https://www.youtube.com/watch?v={v}" for v in chunk]
    print(f"  진행 {i+1}~{i+len(chunk)}/{len(vids)}...", flush=True)
    try:
        r = subprocess.run(
            ["yt-dlp", "--print", "%(id)s|%(upload_date)s",
             "--skip-download", "--no-warnings", "--ignore-errors"] + urls,
            capture_output=True, encoding="utf-8", errors="replace", timeout=300
        )
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if "|" not in line: continue
            vid, raw = line.split("|", 1)
            if len(raw) == 8 and raw.isdigit():
                results[vid] = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    except Exception as e:
        print(f"  에러: {e}")

# 결과 저장 (chunk별)
suffix = f"_{sys.argv[1]}_{sys.argv[2]}" if len(sys.argv) >= 3 else ""
out = ROOT / "scripts" / f".upload_dates{suffix}.json"
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n저장: {out.name} — {len(results)}개 매핑 / 시도 {len(vids)}개")
