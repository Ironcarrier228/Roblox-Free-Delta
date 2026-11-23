import zipfile, re, glob, collections, json
jar=zipfile.ZipFile('/tmp/sdk/android35.jar')
classes={n[:-6].replace('/','.') for n in jar.namelist() if n.endswith('.class')}
print("классов в android.jar:", len(classes))
ROOT='/tmp/x/out/sources'
files=sorted(glob.glob(ROOT+'/**/*.java',recursive=True))
miss=collections.Counter(); missing_detail=[]; tot_imp=0; files_bad=set()
for f in files:
    rel=f[len(ROOT)+1:]
    src=open(f,encoding='utf-8',errors='replace').read()
    for im in re.finditer(r'^import\s+(?:static\s+)?(android[\w.]*);', src, re.M):
        path=im.group(1); tot_imp+=1
        if path in classes: continue
        # вложенный класс: android.view.View$OnClickListener -> android.view.View
        cand=None
        parts=path.split('.')
        for i in range(len(parts),0,-1):
            p='.'.join(parts[:i])
            if p in classes: cand=p; break
        if cand: continue
        miss[path]+=1; files_bad.add(rel)
        if len(missing_detail)<40: missing_detail.append((rel,path))
print(f"\nвсего android-импортов: {tot_imp}")
print(f"НЕ найдено в android.jar: {sum(miss.values())} (уникальных путей: {len(miss)})")
print(f"файлов затронуто: {len(files_bad)}")
print("\nтоп отсутствующих:")
for k,v in miss.most_common(15): print(f"  {v:>4}  {k}")
json.dump({'missing':dict(miss),'files':sorted(files_bad)},open('/tmp/audit/sdk_missing.json','w'))
