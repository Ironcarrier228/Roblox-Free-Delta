import javalang, glob, json
ROOT='/tmp/x/02_sources/java'
files=sorted(glob.glob(ROOT+'/**/*.java',recursive=True))
idx={}; pkg_of={}
for f in files:
    rel=f[len(ROOT)+1:]
    try: cu=javalang.parse.parse(open(f,encoding='utf-8',errors='replace').read())
    except Exception: continue
    pkg=cu.package.name if cu.package else ''
    pkg_of[rel]=pkg
    def walk(node,prefix):
        kids=getattr(node,'types',None)
        if kids is None: kids=getattr(node,'body',None)
        for t in (kids or []):
            if not hasattr(t,'name'): continue
            fqn=(prefix+'.'+t.name) if prefix else t.name
            idx.setdefault(fqn,rel)
            walk(t,fqn)
    walk(cu,pkg)
print("файлов:",len(pkg_of),"FQN:",len(idx))
json.dump(idx,open('index.json','w')); json.dump(pkg_of,open('pkg_of.json','w'))
