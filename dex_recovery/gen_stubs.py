#!/usr/bin/env python3
"""Генерация Java-заглушек для классов, потерянных декомпилятором.

Источник истины — DEX (в нём сохранены типы, предки и сигнатуры). Для каждого
отсутствующего класса генерируется файл с тем же FQN, что нужен компилятору:

  * предок и интерфейсы — настоящие (из DEX);
  * поля — настоящих имён и типов, package-private (чтобы обращения из
    того же пакета компилировались);
  * методы — настоящих сигнатур, тело — `throw new UnsupportedOperationException`.

Заглушки НЕ претендуют на работоспособность: это то, что нужно, чтобы javac
проверил остальной код. Работоспособность упирается в нативный движок.

Использование:
    python3 gen_stubs.py <dex...> <sources_dir> <out_dir> [--only-existing]
        --only-existing : генерировать только вложенные классы тех внешних
                          классов, которые ЕСТЬ в дампе
"""
import os
import pathlib
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dexparse import Dex, ACC  # noqa: E402

JAVA_KW = {
    'abstract', 'assert', 'boolean', 'break', 'byte', 'case', 'catch', 'char',
    'class', 'const', 'continue', 'default', 'do', 'double', 'else', 'enum',
    'extends', 'final', 'finally', 'float', 'for', 'goto', 'if', 'implements',
    'import', 'instanceof', 'int', 'interface', 'long', 'native', 'new',
    'package', 'private', 'protected', 'public', 'return', 'short', 'static',
    'strictfp', 'super', 'switch', 'synchronized', 'this', 'throw', 'throws',
    'transient', 'try', 'void', 'volatile', 'while', 'true', 'false', 'null',
}

PRIM = {'V': 'void', 'Z': 'boolean', 'B': 'byte', 'S': 'short', 'C': 'char',
        'I': 'int', 'J': 'long', 'F': 'float', 'D': 'double'}


def jtype(desc):
    """Дескриптор DEX -> Java-тип."""
    arr = 0
    while desc.startswith('['):
        arr += 1
        desc = desc[1:]
    if desc in PRIM:
        base = PRIM[desc]
    elif desc.startswith('L') and desc.endswith(';'):
        base = desc[1:-1].replace('/', '.').replace('$', '.')
    else:
        base = 'Object'
    if arr:
        base += '[]' * arr
    return base


def jname(n):
    return n + '_' if n in JAVA_KW else n


def simple(fqn):
    return fqn.rsplit('/', 1)[-1].replace('$', '_')


class Repo:
    """Сводная информация по всем dex."""

    def __init__(self, paths):
        self.types = set()
        self.cls = {}       # name -> (access, super, ifaces)
        self.flds = {}      # (cls, name) -> type
        self.mths = {}      # cls -> [(name, ret, params)]
        for p in paths:
            d = Dex(p)
            for t in d.types():
                if t.startswith('L') and t.endswith(';'):
                    self.types.add(t[1:-1])
            for name, acc, sup, ifs in d.classes():
                n = name[1:-1] if name.startswith('L') else name
                if n in self.cls:
                    continue
                self.cls[n] = (acc, sup[1:-1] if sup and sup.startswith('L') else sup, ifs)

    def load_members(self, wanted):
        """Догрузить поля/методы только для нужных классов (экономия времени)."""
        wanted = set(wanted)
        for p in self.paths:
            d = Dex(p)
            for c, t, n in d.fields():
                if c.startswith('L'):
                    c = c[1:-1]
                if c in wanted:
                    self.flds[(c, n)] = t
            for c, n, ret, params in d.methods():
                if c.startswith('L'):
                    c = c[1:-1]
                if c in wanted:
                    self.mths.setdefault(c, []).append((n, ret, params))


def ancestors(repo, name, seen=None):
    """Все предки (для проверки, что они тоже будут в classpath)."""
    if seen is None:
        seen = set()
    info = repo.cls.get(name)
    if not info:
        return seen
    _acc, sup, ifs = info
    for p in ([sup] if sup else []) + list(ifs or []):
        if p and p.startswith('L'):
            p = p[1:-1]
        if p and p not in seen:
            seen.add(p)
            ancestors(repo, p, seen)
    return seen


def gen_class(repo, name, existing, stub_ancestors):
    """Сгенерировать исходник заглушки. Вернуть (path, text) или None."""
    info = repo.cls.get(name)
    if info is None:
        return None
    acc, sup, ifs = info
    is_iface = bool(acc & 0x0200)
    is_enum = bool(acc & 0x4000)
    pkg, _, clsname = name.replace('/', '.').rpartition('.')
    if not pkg:
        return None

    # предки: реальные, если есть в дампе; иначе тоже заглушки
    sup_j = None
    if sup and sup.startswith('L') and sup.endswith(';'):
        s = sup[1:-1]
        if s != 'Ljava/lang/Object;' and s != 'java/lang/Object':
            sup_j = jtype('L' + s + ';')
    ifaces_j = []
    for i in (ifs or []):
        if i.startswith('L') and i.endswith(';'):
            ifaces_j.append(jtype(i))

    # нельзя наследоваться от final-класса, которого нет — пропускаем такое
    extends = ''
    if sup_j and sup_j not in ('Object', 'java.lang.Object'):
        extends = ' extends %s' % sup_j
    implements = (' implements ' + ', '.join(ifaces_j)) if ifaces_j else ''
    if is_iface:
        extends, implements = '', (' extends ' + ', '.join(ifaces_j)) if ifaces_j else ''

    body = []
    # поля
    for (c, fn), ft in repo.flds.items():
        if c != name:
            continue
        jt = jtype(ft)
        if jt == 'void':
            continue
        if is_iface:
            body.append('    %s %s;' % (jt, jname(fn)) if not is_iface else
                        '    %s %s = %s;' % (jt, jname(fn), default_of(jt)))
        else:
            body.append('    %s %s;' % (jt, jname(fn)))
    # методы
    seen = set()
    for mn, ret, params in repo.mths.get(name, []):
        key = (mn, ret, params)
        if key in seen:
            continue
        seen.add(key)
        jr = jtype(ret)
        args = ', '.join('%s p%d' % (jtype(p), i) for i, p in enumerate(params))
        if mn == '<init>':
            body.append('    public %s(%s) { }' % (clsname, args))
            continue
        if mn in ('<clinit>',):
            continue
        stub = 'throw new UnsupportedOperationException("stub");'
        if is_iface and not (acc & 0x0400):
            # у интерфейса до Java 8 — без тела, но тогда класс не соберётся
            # как реализация; делаем default
            body.append('    default %s %s(%s) { %s }' % (jr, jname(mn), args, stub))
        elif jr == 'void':
            body.append('    public void %s(%s) { %s }' % (jname(mn), args, stub))
        else:
            body.append('    public %s %s(%s) { %s }' % (jr, jname(mn), args, stub))

    if not body:
        body.append('    private %s() { }' % clsname if not is_iface else '    // пусто')

    kw = ('interface' if is_iface else ('enum' if is_enum else 'class'))
    if is_enum:
        # enum нельзя extends; тела-заглушки для enum сложны — делаем class
        kw = 'class'
        if extends:
            extends = ''
    mods = 'public '
    if acc & 0x0400 and not is_iface:
        mods += 'abstract '
    if acc & 0x0010 and not is_iface:
        mods += 'final '
    text = 'package %s;\n\n// stub из DEX: настоящая сигнатура, тело отсутствует\n%s%s %s%s%s {\n%s\n}\n' % (
        pkg, mods, kw, clsname, extends, implements, '\n'.join(body))
    return '%s.java' % name, text


def default_of(jt):
    return {'boolean': 'false', 'char': "'\\0'", 'byte': '0', 'short': '0',
            'int': '0', 'long': '0L', 'float': '0f', 'double': '0d'}.get(jt, 'null')


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    only_existing = '--only-existing' in sys.argv
    dexes, src, out = args[:-2], args[-2], args[-1]
    src, out = pathlib.Path(src), pathlib.Path(out)

    repo = Repo(dexes)
    repo.paths = dexes
    have = set()
    for p in src.rglob('*.java'):
        have.add(str(p.relative_to(src))[:-5])

    missing = sorted(t for t in repo.types if t not in have)
    if only_existing:
        missing = [t for t in missing if t.split('$')[0] in have]
    print('нет в дампе: %d (генерирую %d)' % (len(repo.types - have), len(missing)))

    repo.load_members(missing)
    # предки тоже должны существовать -> генерируем и их
    need = set(missing)
    for t in missing:
        for a in ancestors(repo, t):
            if a not in have and a in repo.cls:
                need.add(a)
    repo.load_members(need - set(repo.mths))
    print('с предками к генерации: %d' % len(need))

    made = skipped = 0
    for t in sorted(need):
        r = gen_class(repo, t, have, None)
        if r is None:
            skipped += 1
            continue
        rel, text = r
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding='utf-8')
        made += 1
    print('сгенерировано: %d, пропущено: %d' % (made, skipped))


if __name__ == '__main__':
    main()
