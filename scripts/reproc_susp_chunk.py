"""의심 매장 청크 재처리. 결과 entry 형태로 저장."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import auto_update as au

idx = int(sys.argv[1])
ROOT = Path(__file__).parent.parent
items = json.loads((ROOT/'scripts'/f'.susp_chunk_{idx}.json').read_text(encoding='utf-8'))
print(f'[Chunk {idx}] {len(items)}개 재처리')

results = []
for i, r in enumerate(items):
    vid = r['video_id']; title = r.get('video_title','')
    old_name = r.get('name','')
    cat = r.get('_cat','?')
    print(f'  [{i+1}/{len(items)}] [{cat}] {title[:55]}')
    addr_str = (r.get('address') or '')[:40]
    print(f'    기존: {old_name} @ {addr_str}')
    v = {'id':vid,'title':title,'url':f'https://www.youtube.com/watch?v={vid}',
         'thumbnail':r.get('thumbnail') or f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg',
         'channel':r.get('channel','tzuyang')}
    try:
        entries = au.process_new_video(v) or []
    except Exception as e:
        entries = []
        print(f'    예외: {e}')
    if entries:
        for e in entries:
            print(f'    신규: {e.get("name")} @ {e.get("address")}')
        results.append({'video_id':vid, 'cat':cat, 'old_name':old_name, 'old_addr':r.get('address'),
                        'entries':entries, 'upload_date':r.get('upload_date'),
                        'video_title':title})
    else:
        print(f'    ✗ 추출 실패')
        results.append({'video_id':vid, 'cat':cat, 'old_name':old_name, 'old_addr':r.get('address'),
                        'entries':[], 'upload_date':r.get('upload_date'),
                        'video_title':title})

(ROOT/'scripts'/f'.susp_result_{idx}.json').write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'[Chunk {idx}] 저장 완료')
