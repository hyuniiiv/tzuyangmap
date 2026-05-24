"""실패 재테스트용 청크 처리. 새 코드(Naver 재시도 + Kakao suffix)로."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import auto_update as au

idx = int(sys.argv[1])
ROOT = Path(__file__).parent.parent
items = json.loads((ROOT / 'scripts' / f'.retest_chunk_{idx}.json').read_text(encoding='utf-8'))
print(f"[Chunk {idx}] {len(items)}개 재테스트")

results = []
for i, r in enumerate(items):
    vid = r['video_id']; title = r['title']
    print(f"  [{i+1}/{len(items)}] {title[:55]}")
    v = {'id': vid, 'title': title,
         'url': f'https://www.youtube.com/watch?v={vid}',
         'thumbnail': f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg',
         'channel': 'tzuyang'}
    try:
        entries = au.process_new_video(v) or []
    except Exception as e:
        entries = []
        print(f"    예외: {e}")
    if entries:
        results.append({'video_id': vid, 'title': title, 'status': 'PASS',
                        'entries': [{'name': e.get('name'), 'address': e.get('address'),
                                      'phone': e.get('phone')} for e in entries]})
        for e in entries:
            print(f"    ✓ {e.get('name')} @ {e.get('address')}")
    else:
        results.append({'video_id': vid, 'title': title, 'status': 'FAIL'})
        print(f"    ✗")

(ROOT / 'scripts' / f'.retest_result_{idx}.json').write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
passed = sum(1 for r in results if r['status']=='PASS')
print(f"[Chunk {idx}] 완료: {passed}/{len(items)}")
