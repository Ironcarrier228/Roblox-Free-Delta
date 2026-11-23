import javalang, glob, json, collections, re
ROOT='/tmp/x/02_sources/java'
idx=json.load(open('index.json'))
JDK_PREFIX=('java.','javax.','jdk.','sun.','org.w3c.','org.xml.','com.sun.')
ANNOT=('org.jetbrains.annotations','kotlin.','androidx.annotation','com.google.errorprone')
files=sorted(glob.glob(ROOT+'/**/*.java',recursive=True))
broken=set(open('/tmp/rwork/broken.txt').read().split())

stats=collections.Counter()
missing_external=collections.Counter()   # внешние (не JDK, не в дампе) корни
unresolved_sym=collections.Counter()
per_file=collections.Counter()
clean=[]
for f in files:
    rel=f[len(ROOT)+1:]
    if rel in broken: stats['файл с синтаксической ошибкой']+=1; continue
    try:
        src=open(f,encoding='utf-8',errors='replace').read(); cu=javalang.parse.parse(src)
    except Exception:
        stats['не распарсен']+=1; continue
    pkg=cu.package.name if cu.package else ''
    imported=set()
    wildcard=[]
    for im in cu.imports:
        if im.wildcard: wildcard.append(im.path)
        else: imported.add(im.path)
    ok=True
    # 1) импорты: JDK / в дампе / внешние
    for im in list(imported):
        if im.startswith(JDK_PREFIX) or im.startswith(ANNOT): continue
        if im in idx: continue
        # может быть вложенный класс: A.B -> ищем A
        parts=im.split('.')
        if any('.'.join(parts[:i]) in idx for i in range(len(parts),0,-1)): continue
        missing_external['.'.join(parts[:3])]+=1; ok=False
    if ok: stats['импорты полностью разрешимы']+=1; clean.append(rel)
    else: stats['есть неразрешимые импорты']+=1
json.dump(clean, open('clean_imports.json','w'))
print("=== по файлам ===")
for k,v in stats.most_common(): print(f"  {v:>6}  {k}")
print("\n=== неразрешимые внешние корни (топ-20) ===")
for k,v in missing_external.most_common(20): print(f"  {v:>5}  {k}")
