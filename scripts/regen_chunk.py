"""제거된 협찬 영상 vid 재처리 (신 코드로 매장 정보 회복 시도)."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import auto_update as au

idx = int(sys.argv[1])
ROOT = Path(__file__).parent.parent
items = json.loads((ROOT/'scripts'/f'.regen_chunk_{idx}.json').read_text(encoding='utf-8'))
print(f"[Chunk {idx}] {len(items)}개")

# 임시: 협찬 거부 우회 — is_sponsored_video를 false로 패치
au.is_sponsored_video = lambda *a, **k: False

results = []
for i, item in enumerate(items):
    vid = item['video_id']; title = item['video_title']
    print(f"  [{i+1}/{len(items)}] {title[:55]}")
    print(f"    기존: {item['old_name']} @ {(item.get('old_addr') or '')[:40]}")
    v = {'id':vid,'title':title,'url':f'https://www.youtube.com/watch?v={vid}',
         'thumbnail':item.get('thumbnail') or f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg',
         'channel':'tzuyang'}
    try:
        entries = au.process_new_video(v) or []
    except Exception as e:
        entries = []
        print(f"    예외: {e}")
    if entries:
        # 메타데이터 + 구체적 이름만 유지
        valid = [e for e in entries
                 if (e.get('phone') or e.get('place_url'))
                 and e.get('name','') not in au.GENERIC_NAMES]
        for e in valid:
            print(f"    신규: {e.get('name')} @ {e.get('address')} | phone={e.get('phone')}")
        results.append({'video_id':vid, 'title':title, 'entries':valid})
    else:
        results.append({'video_id':vid, 'title':title, 'entries':[]})
        print(f"    ✗")

(ROOT/'scripts'/f'.regen_result_{idx}.json').write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"[Chunk {idx}] 완료")
