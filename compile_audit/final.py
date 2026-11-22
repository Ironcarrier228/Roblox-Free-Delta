import javalang, glob, json, collections
ROOT='/tmp/x/02_sources/java'
idx=json.load(open('index.json')); clean=set(json.load(open('clean_imports.json')))
files=sorted(glob.glob(ROOT+'/**/*.java',recursive=True))
members={}
for f in files:
    rel=f[len(ROOT)+1:]
    if rel not in clean: continue
    try: cu=javalang.parse.parse(open(f,encoding='utf-8',errors='replace').read())
    except Exception: continue
    pkg=cu.package.name if cu.package else ''
    def walk(node,prefix):
        kids=getattr(node,'types',None)
        if kids is None: kids=getattr(node,'body',None)
        for t in (kids or []):
            if not hasattr(t,'name'): continue
            fqn=(prefix+'.'+t.name) if prefix else t.name
            ms=set()
            for m in getattr(t,'methods',[]) or []: ms.add(m.name)
            for fl in getattr(t,'fields',[]) or []:
                for d in fl.declarators: ms.add(d.name)
            for c in getattr(t,'constructors',[]) or []: ms.add('<init>')
            members[fqn]=ms
            walk(t,fqn)
    walk(cu,pkg)
print("FQN с членами:",len(members))
ok=bad=0; badg=collections.Counter()
for f in files:
    rel=f[len(ROOT)+1:]
    if rel not in clean: continue
    try: cu=javalang.parse.parse(open(f,encoding='utf-8',errors='replace').read())
    except Exception: continue
    pkg=cu.package.name if cu.package else ''
    imp={im.path for im in cu.imports if not im.wildcard}
    for path,node in cu:
        if not isinstance(node,(javalang.tree.MemberReference,javalang.tree.MethodInvocation)): continue
        q=getattr(node,'qualifier',None); mem=getattr(node,'member',None)
        if not q or not mem or not q[0].isupper(): continue
        fqn=None
        for pre in ('',pkg+'.'):
            if pre+q in idx: fqn=pre+q; break
        if fqn is None:
            for im in imp:
                if im.endswith('.'+q): fqn=im; break
        if fqn is None: continue
        ms=members.get(fqn)
        if ms is None or mem in ms: ok+=1
        else: bad+=1; badg[(fqn,mem)]+=1
print(f"ссылок на классы дампа проверено: {ok+bad}")
print(f"  член найден: {ok}")
print(f"  член НЕ найден: {bad} (уникальных {len(badg)})")
print("\nтоп потерянных членов:")
for (c,m),v in badg.most_common(10): print(f"  {v:>4}  {c}.{m}")
