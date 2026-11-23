import javalang, glob, json, collections, os
ROOT='/tmp/x/02_sources/java'
broken=set(open('/tmp/rwork/broken.txt').read().split())
files=sorted(glob.glob(ROOT+'/**/*.java',recursive=True))
cnt=collections.Counter(); examples=collections.defaultdict(list)
dup=collections.defaultdict(list)
for f in files:
    rel=f[len(ROOT)+1:]
    if rel in broken: cnt['пропущен (синтакс. ошибка)']+=1; continue
    try: cu=javalang.parse.parse(open(f,encoding='utf-8',errors='replace').read())
    except Exception: cnt['пропущен (не распарсен)']+=1; continue
    base=os.path.basename(rel)[:-5]
    tops=[t for t in cu.types]
    # 1) имя public-класса должно совпадать с именем файла
    pub=[t for t in tops if 'public' in (t.modifiers or set())]
    if len(pub)>1:
        cnt['>1 public класса в файле']+=1; examples['multi'].append(rel)
    if pub and pub[0].name!=base:
        cnt['public класс != имя файла']+=1; examples['mismatch'].append((rel,pub[0].name))
    if not pub and tops and tops[0].name!=base:
        cnt['единственный класс != имя файла']+=1; examples['mismatch2'].append((rel,tops[0].name))
    # 2) дубли FQN
    pkg=cu.package.name if cu.package else ''
    for t in tops:
        dup[f"{pkg}.{t.name}"].append(rel)
d=[(k,v) for k,v in dup.items() if len(v)>1]
cnt['дублирующихся FQN']=len(d)
print("=== жёсткие ошибки (без компилятора) ===")
for k,v in cnt.most_common(): print(f"  {v:>6}  {k}")
print("\nпримеры несовпадения имени:")
for e in examples['mismatch'][:5]: print("   ",e)
print("\nпримеры дублей FQN:")
for k,v in d[:5]: print("   ",k,"->",v)
json.dump({k:list(v)[:50] for k,v in examples.items()}, open('hard_examples.json','w'))
json.dump([[k,v] for k,v in d[:200]], open('dup_fqn.json','w'))
