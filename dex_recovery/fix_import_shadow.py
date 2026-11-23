#!/usr/bin/env python3
"""F5: импорт класса с тем же простым именем, что объявленный в файле.

JLS 7.5.1: single-type-import с именем, совпадающим с типом верхнего уровня в
том же файле, — ошибка компиляции. javac не просто ругается: после неё имя
перестаёт резолвиться, и КАЖДОЕ обращение `a.d` в файле даёт
`cannot find symbol: class d, location: class a`.

Именно это давало 409 ошибок в `ci/a.java`:
    package ci;
    import com.roblox.client.flags.a;   // конфликт со своим class a
    public final class a extends c implements i {
        public final a.d A2;             // 197 таких полей

Решение: удалить конфликтующий импорт. Тогда `a` — свой класс своего пакета,
а `a.d` резолвится в `ci.a.d`. Если такого вложенного класса нет, добавит его
`inject_nested.py` (по сигнатуре из DEX).

Безопасно для самоссылок (`package x; import x.x;`) — они не конфликт,
но тоже удаляются как заведомо лишние.

Использование:
    python3 fix_import_shadow.py <sources_dir> [--apply]
"""
import os
import pathlib
import re
import sys

IMP = re.compile(r'^import\s+([\w.]+)\s*;\s*$', re.M)


def fix_text(src):
    pkg = ''
    m = re.search(r'^package\s+([\w.]+)\s*;', src, re.M)
    if m:
        pkg = m.group(1)

    # имя типа верхнего уровня = имя файла (проверяется вызывающим)
    body_names = set()
    for mm in re.finditer(r'^(?:public\s+)?(?:final\s+|abstract\s+)*(?:class|interface|enum)\s+(\w+)',
                          src, re.M):
        body_names.add(mm.group(1))

    removed = []

    def keep(mt):
        fqn = mt.group(1)
        mark = fqn.find('<')
        if mark >= 0:
            fqn = fqn[:mark]
        last = fqn.rsplit('.', 1)[-1]
        imp_pkg = fqn.rsplit('.', 1)[0] if '.' in fqn else ''
        if last in body_names:
            removed.append(fqn)
            return ''
        return mt.group(0)

    new = IMP.sub(keep, src)
    # схлопнуть пустые строки, оставшиеся от удалённых импортов
    new = re.sub(r'\n{3,}', '\n\n', new)
    return new, removed, pkg


def main():
    root = pathlib.Path(sys.argv[1])
    do = '--apply' in sys.argv
    files = 0
    total = 0
    listing = []
    for p in sorted(root.rglob('*.java')):
        src = p.read_text(encoding='utf-8', errors='replace')
        base = p.stem
        if not re.search(r'\b(?:class|interface|enum)\s+' + re.escape(base) + r'\b', src):
            # имя файла не совпадает с объявлением — правил не применяем
            continue
        new, removed, pkg = fix_text(src)
        if not removed:
            continue
        files += 1
        total += len(removed)
        listing.append((str(p.relative_to(root)), removed))
        if do:
            p.write_text(new, encoding='utf-8')
    print('файлов: %d, удалено конфликтующих импортов: %d' % (files, total))
    for f, r in listing[:20]:
        print('   %-52s %s' % (f, ', '.join(r)))
    if len(listing) > 20:
        print('   ... и ещё %d файлов' % (len(listing) - 20))
    if not do:
        print('(отчёт; добавь --apply)')


if __name__ == '__main__':
    main()
