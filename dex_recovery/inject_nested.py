#!/usr/bin/env python3
"""Вставка потерянных ВЛОЖЕННЫХ классов в существующие файлы дампа.

Проблема: JADX сохранил внешний класс (`ci/a.java`), но потерял вложенные
(`ci/a$d`). Код обращается к `a.d` -> `cannot find symbol`.

Решение: взять сигнатуру `a$d` из DEX и вставить объявление
`static class d { ... }` в конец тела внешнего класса.

Использование:
    python3 inject_nested.py <sources_dir> <out_dir> <dex...> [--apply]
"""
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dexparse import Dex  # noqa: E402
from gen_stubs import jtype, jname, simple, PRIM  # noqa: E402


def find_class_end(src, clsname):
    """Индекс закрывающей скобки тела класса `clsname` (последняя `}` в файле)."""
    # надёжнее: идём от объявления класса, считая скобки
    m = re.search(r'\b(?:class|interface|enum)\s+' + re.escape(clsname) + r'\b', src)
    if not m:
        return -1
    i = src.index('{', m.end()) if '{' in src[m.end():] else -1
    if i < 0:
        return -1
    depth = 0
    j = i
    while j < len(src):
        c = src[j]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return j
        elif c == '"':
            j += 1
            while j < len(src) and src[j] != '"':
                if src[j] == '\\':
                    j += 1
                j += 1
        elif c == "'":
            j += 1
            while j < len(src) and src[j] != "'":
                if src[j] == '\\':
                    j += 1
                j += 1
        j += 1
    return -1


def build_nested(repo, name, inner_simple):
    inner_simple = inner_simple.rsplit('$', 1)[-1]   # a$a -> a
    acc, sup, ifs = repo.cls[name]
    is_iface = bool(acc & 0x0200)
    body = []
    for (c, fn), ft in repo.flds.items():
        if c != name:
            continue
        jt = jtype(ft)
        if jt == 'void':
            continue
        body.append('        %s %s;' % (jt, jname(fn)))
    seen = set()
    for mn, ret, params in repo.mths.get(name, []):
        key = (mn, ret, params)
        if key in seen:
            continue
        seen.add(key)
        jr = jtype(ret)
        args = ', '.join('%s p%d' % (jtype(p), i) for i, p in enumerate(params))
        stub = 'throw new UnsupportedOperationException("stub");'
        if mn == '<init>':
            body.append('        public %s(%s) { }' % (inner_simple, args))
        elif mn == '<clinit>':
            continue
        elif jr == 'void':
            body.append('        public void %s(%s) { %s }' % (jname(mn), args, stub))
        else:
            body.append('        public %s %s(%s) { %s }' % (jr, jname(mn), args, stub))

    # настоящий предок/интерфейсы, если они есть в этом же файле или в DEX
    def rel(t):
        """Тип с учётом вложенности: a5/k$b -> a5.k.b (если это внутри этого же файла)."""
        return jtype('L' + t + ';') if t else None

    sup_j = ''
    if sup and sup.startswith('L'):
        s = sup[1:-1]
        if s not in ('java/lang/Object',):
            sup_j = ' extends ' + rel(s)
    impl = ''
    ifs_j = [rel(i[1:-1]) for i in (ifs or []) if i.startswith('L')]
    if ifs_j:
        impl = (' extends ' if is_iface else ' implements ') + ', '.join(ifs_j)

    kw = 'interface' if is_iface else 'class'
    mods = 'public static '
    if acc & 0x0400 and not is_iface:
        mods += 'abstract '
    if not body:
        body = ['        // члены отсутствуют в DEX']
    return '\n\n    // --- восстановлено из DEX (%s) ---\n    %s%s %s%s%s {\n%s\n    }' % (
        name, mods, kw, inner_simple, sup_j, impl, '\n'.join(body))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    src, out = pathlib.Path(args[0]), pathlib.Path(args[1])
    dexes = args[2:]
    do = '--apply' in sys.argv

    repo_types = set()
    cls_info = {}
    for p in dexes:
        d = Dex(p)
        for t in d.types():
            if t.startswith('L') and t.endswith(';'):
                repo_types.add(t[1:-1])
        for name, acc, sup, ifs in d.classes():
            n = name[1:-1]
            cls_info.setdefault(n, (acc, sup, ifs))

    # какие вложенные нужны
    have = {str(p.relative_to(src))[:-5] for p in src.rglob('*.java')}
    todo = {}
    for t in repo_types:
        if '$' not in t or t in have:
            continue
        outer = t.split('$')[0]
        if outer in have:
            todo.setdefault(outer, []).append(t)
    print('внешних классов с потерянными вложенными: %d (вложенных %d)'
          % (len(todo), sum(len(v) for v in todo.values())))

    # загрузить члены
    flds, mths = {}, {}
    want = set()
    for v in todo.values():
        want.update(v)
    for p in dexes:
        d = Dex(p)
        for c, t, n in d.fields():
            c2 = c[1:-1] if c.startswith('L') else c
            if c2 in want:
                flds[(c2, n)] = t
        for c, n, ret, params in d.methods():
            c2 = c[1:-1] if c.startswith('L') else c
            if c2 in want:
                mths.setdefault(c2, []).append((n, ret, params))

    class R:
        pass
    repo = R()
    repo.cls = cls_info
    repo.flds = flds
    repo.mths = mths

    done = fail = 0
    for outer, inners in sorted(todo.items()):
        p = src / (outer + '.java')
        text = p.read_text(encoding='utf-8', errors='replace')
        base = outer.rsplit('/', 1)[-1]
        end = find_class_end(text, base)
        if end < 0:
            fail += 1
            continue
        # не дублировать уже объявленные
        add = []
        for t in sorted(inners):
            inner = t.split('$', 1)[1]
            if t not in repo.cls:
                continue          # тип известен, но класса в DEX нет — не наш случай
            if not re.match(r'^[A-Za-z_$][\w$]*$', inner.rsplit('$', 1)[-1]):
                continue          # синтетика (имя вида "1", "resultReceiver$1") — в Java невыразима
            if re.search(r'\b(?:class|interface|enum)\s+' + re.escape(inner) + r'\b', text):
                continue          # уже объявлен
            add.append(build_nested(repo, t, inner))
        if not add:
            continue
        new = text[:end] + ''.join(add) + '\n' + text[end:]
        dst = out / (outer + '.java')
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(new, encoding='utf-8')
        done += 1

    print('файлов дополнено: %d, не удалось разобрать: %d' % (done, fail))


if __name__ == '__main__':
    main()
