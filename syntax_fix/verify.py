import javalang, pathlib, sys, json
ROOT=pathlib.Path('/tmp/x/out/sources')
ok=bad=0; badlist=[]
for p in sorted(ROOT.rglob('*.java')):
    try:
        javalang.parse.parse(p.read_text(encoding='utf-8',errors='replace')); ok+=1
    except Exception: bad+=1; badlist.append(str(p.relative_to(ROOT)))
print(f"ИТОГО: {ok} OK / {bad} сломано  (было 13310 / 82)")
json.dump(badlist,open('/tmp/fix/still_broken.json','w'))
