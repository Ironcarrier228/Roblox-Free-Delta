import zipfile, re, glob, collections, json
jar=zipfile.ZipFile('/tmp/sdk/android35.jar')
classes={n[:-6].replace('/','.') for n in jar.namelist() if n.endswith('.class')}
ROOT='/tmp/x/out/sources'
files=sorted(glob.glob(ROOT+'/**/*.java',recursive=True))
res=collections.defaultdict(lambda: {'tot':0,'miss':collections.Counter(),'files':set()})
for f in files:
    rel=f[len(ROOT)+1:]
    src=open(f,encoding='utf-8',errors='replace').read()
    for im in re.finditer(r'^import\s+(?:static\s+)?([\w.]+);', src, re.M):
        path=im.group(1)
        if path.startswith('androidx.'): key='androidx (библиотеки)'
        elif path.startswith('android.'): key='android (framework)'
        elif path.startswith('com.google.android.'): key='com.google.android'
        else: continue
        res[key]['tot']+=1
        if key!='android (framework)': continue
        if path in classes: continue
        parts=path.split('.'); found=False
        for i in range(len(parts),0,-1):
            if '.'.join(parts[:i]) in classes: found=True; break
        if not found:
            res[key]['miss'][path]+=1; res[key]['files'].add(rel)
print(f"классов в android.jar API35: {len(classes)}\n")
for k,v in res.items():
    print(f"=== {k} ===")
    print(f"  импортов: {v['tot']}")
    if v['miss']:
        print(f"  НЕ найдено: {sum(v['miss'].values())} (уникальных {len(v['miss'])}), файлов {len(v['files'])}")
        for p,n in v['miss'].most_common(8): print(f"     {n:>4}  {p}")
    else:
        print("  все найдены в android.jar ✓")
    print()
json.dump({k:{'tot':v['tot'],'miss':dict(v['miss']),'files':sorted(v['files'])} for k,v in res.items()},
          open('/tmp/audit/sdk_audit.json','w'))
