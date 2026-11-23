#!/usr/bin/env python3
"""F6: полная квалификация ссылок на вложенные классы, когда есть конфликт имён.

Заменяет подход F5 (удаление импорта). F5 был неверным: удалив
`import com.roblox.client.flags.a;` из `ci/a.java`, я лишил `a.d` смысла —
он стал указывать на несуществующий `ci.a.d`, и число ошибок не изменилось.

Правильно — оставить импорт и переписать ссылки на полное имя:
    public final a.d A2;   ->   public final com.roblox.client.flags.a.d A2;

Даже если внутри `flags.a` вложенный класс называется `d`, но в DEX он
`flags/a$d`, Java-имя вложенного класса — `flags.a.d` (точечная форма).

Источник истины — DEX: для каждого `X.Y` в файле проверяем
  1) `X` — тип в этом же пакете (файл-сосед)?
  2) `X` — импортированный тип?
  3) существует ли `pkg.X$Y` в DEX? -> ссылка неверна, квалифицируем
  4) существует ли `imported_pkg.X$Y` в DEX? -> квалифицируем как imported_pkg.X.Y

Использование:
    python3 fix_qualified_nested.py <sources_dir> <dex...> [--apply]
"""
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dexparse import Dex  # noqa: E402

IMPORT = re.compile(r'^import\s+(?:static\s+)?([\w.]+)\s*;\s*$', re.M)
NOISE = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"', re.S)


def split_noise(src):
    out, pos = [], 0
    for m in NOISE.finditer(src):
        if m.start() > pos:
            out.append((src[pos:m.start()], False))
        out.append((m.group(0), True))
        pos = m.end()
    if pos < len(src):
        out.append((src[pos:], False))
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    root, dexes = pathlib.Path(args[0]), args[1:]
    do = '--apply' in sys.argv

    types = set()
    for p in dexes:
        for t in Dex(p).types():
            if t.startswith('L') and t.endswith(';'):
                types.add(t[1:-1])

    # индексы
    files = {str(p.relative_to(root))[:-5] for p in root.rglob('*.java')}
    pkgs = {os.path.dirname(f) for f in files}

    # что реально объявлено внутри каждого файла (JADX переименовывает
    # X$X -> C0143a, поэтому одного DEX недостаточно)
    decl = re.compile(r'\b(?:class|interface|enum)\s+(\w+)')
    dump_nested = {}
    for rel in files:
        try:
            txt = (root / (rel + '.java')).read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        names = set(decl.findall(txt))
        top = rel.rsplit('/', 1)[-1]
        names.discard(top)
        dump_nested[rel] = names

    def in_dex(desc):
        return desc in types

    files_changed = 0
    refs = 0
    samples = []

    for p in sorted(root.rglob('*.java')):
        rel = str(p.relative_to(root))[:-5]
        pkg = os.path.dirname(rel)
        src = p.read_text(encoding='utf-8', errors='replace')

        imports = {}
        for m in IMPORT.finditer(src):
            fqn = m.group(1)
            imports[fqn.rsplit('.', 1)[-1]] = fqn

        # кандидаты: Base.Inner, где Base — импортированное простое имя
        targets = {}
        for simple_name, fqn in imports.items():
            imp_pkg, _, imp_cls = fqn.rpartition('.')
            if simple_name != imp_cls:
                continue
            if imp_pkg == pkg:
                continue          # свой пакет: коллизии нет
            # есть ли в файле объявление с этим именем? тогда конфликт
            if not re.search(r'\b(?:class|interface|enum)\s+' + re.escape(simple_name) + r'\b', src):
                continue
            targets[simple_name] = fqn

        if not targets:
            continue

        def fix_chunk(chunk):
            nonlocal refs
            def rep(m):
                nonlocal refs
                base, inner = m.group(1), m.group(2)
                if base not in targets:
                    return m.group(0)
                fqn = targets[base]
                imp_pkg = fqn.rpartition('.')[0]
                # существует ли настоящий pkg.Base$Inner?
                if in_dex(pkg + '/' + base + '$' + inner):
                    return m.group(0)          # ссылка верна, не трогаем
                target_rel = imp_pkg.replace('.', '/') + '/' + base
                if (in_dex(imp_pkg.replace('.', '/') + '/' + base + '$' + inner)
                        or inner in dump_nested.get(target_rel, ())):
                    refs += 1
                    return '%s.%s' % (fqn, inner)
                return m.group(0)              # ничего не знаем — оставляем
            return re.sub(r'(?<![\w.])' + '(' + '|'.join(map(re.escape, targets)) + r')\.(\w+)',
                          rep, chunk)

        parts = split_noise(src)
        new = ''.join(frag if is_noise else fix_chunk(frag) for frag, is_noise in parts)
        if new != src:
            files_changed += 1
            if len(samples) < 8:
                first = next((l.strip() for l in new.split('\n')
                              if targets.get(l.split('.')[0].strip()) or
                              any(t + '.' in l for t in targets)), '')
                samples.append((rel, first[:100]))
            if do:
                p.write_text(new, encoding='utf-8')

    print('файлов: %d, ссылок квалифицировано: %d' % (files_changed, refs))
    for f, s in samples:
        print('   %-50s %s' % (f, s))
    if not do:
        print('(отчёт; добавь --apply)')


if __name__ == '__main__':
    main()
