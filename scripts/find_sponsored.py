"""데이터의 모든 unique video_id description 확인해서 협찬 영상 색출.
병렬 5청크."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import auto_update as au

idx = int(sys.argv[1])
total = int(sys.argv[2]) if len(sys.argv) >= 3 else 5
import math

ROOT = Path(__file__).parent.parent
data = json.loads((ROOT/'public'/'data'/'restaurants_geo.json').read_text(encoding='utf-8'))

# unique video_ids
seen=set(); vids=[]
for r in data:
    v = r.get('video_id')
    if v and v not in seen:
        seen.add(v); vids.append({'id':v, 'title':r.get('video_title','')})

ch = math.ceil(len(vids)/total)
chunk = vids[idx*ch:(idx+1)*ch]
print(f"[Chunk {idx}/{total}] {len(chunk)}개 video description 확인")

sponsored = []
for i, v in enumerate(chunk):
    if (i+1) % 20 == 0:
        print(f"  진행 {i+1}/{len(chunk)}...", flush=True)
    desc = au.get_video_description(v['id'])
    if au.is_sponsored_video(desc, v['title']):
        sponsored.append({'video_id':v['id'], 'title':v['title'], 'desc':desc[:200]})
        print(f"  [협찬] {v['title'][:50]}")

(ROOT/'scripts'/f'.sponsored_{idx}.json').write_text(
    json.dumps(sponsored, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"[Chunk {idx}] 협찬 {len(sponsored)}개 발견")
