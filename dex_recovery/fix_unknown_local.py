#!/usr/bin/env python3
"""F4: локальные переменные с потерянным типом (`?? name = ...`).

УТОЧНЕНИЕ ФАКТА (после проверки): правило R7 в fix_syntax.py уже заменяло
`??` на `var`, и для javac это РАБОТАЛО. Моя проверка парсером (javalang)
не понимает `var` и помечала такие файлы сломанными ЛОЖНО — то есть 36 из
52 «сломанных» файлов на самом деле компилируются.

Этот скрипт нужен только там, где `??` реально остался: объявление без
инициализатора (`?? x;`) — `var` в такой позиции запрещён даже в Java 10+.

JADX не смог вывести тип регистра и оставил `??`. Java такое не компилирует.
Тип берётся из того, что присваивается справа:

    ?? x = new MediaMuxer(...)           -> MediaMuxer x = ...
    ?? x = SomeClass.staticMethod(...)   -> ... (тип неизвестен, берём Object)
    ?? x = expr; x.foo()                 -> вывод невозможен, Object

Правила по убыванию надёжности:
  1) right после `new X(`            -> X
  2) right — литерал/приведение к    -> тип литерала
  3) явное объявление без значения
     (`?? x;`)                        -> Object
  4) иначе                            -> Object  (компилируется, но x.foo()
                                                   может не найтись; такие места
                                                   попадут в отчёт)

Использование:
    python3 fix_unknown_local.py <sources_dir> [--apply]
"""
import pathlib
import re
import sys

NEW = re.compile(r'^\s*new\s+([A-Za-z_][\w.]*)\s*[(<]')
CAST = re.compile(r'^\s*\(\s*([A-Za-z_][\w.]*)\s*\)')
LIT = [(re.compile(r'^\s*"[^"]*"'), 'String'),
       (re.compile(r'^\s*-?\d+L\b'), 'long'),
       (re.compile(r'^\s*-?\d+\.\d*[fF]?\b'), 'double'),
       (re.compile(r'^\s*-?\d+\b'), 'int'),
       (re.compile(r'^\s*(true|false)\b'), 'boolean'),
       (re.compile(r'^\s*\''), 'char')]

DECL = re.compile(r'^(\s*)\?\?\s+([A-Za-z_]\w*)\s*(=|;)(.*)$')


def infer(right):
    right = right.strip()
    m = NEW.match(right)
    if m:
        return m.group(1), 'new'
    m = CAST.match(right)
    if m:
        return m.group(1), 'cast'
    for rx, t in LIT:
        if rx.match(right):
            return t, 'literal'
    return None, None


def fix_text(src):
    out = []
    hits = []
    for line in src.split('\n'):
        m = DECL.match(line)
        if not m:
            out.append(line)
            continue
        indent, name, sep, rest = m.groups()
        if sep == ';':
            out.append('%sObject %s;' % (indent, name))
            hits.append((name, 'Object', 'no-init'))
            continue
        typ, how = infer(rest)
        if typ is None:
            typ = 'Object'
            how = 'fallback'
        out.append('%s%s %s =%s' % (indent, typ, name, rest))
        hits.append((name, typ, how))
    return '\n'.join(out), hits


def main():
    root = pathlib.Path(sys.argv[1])
    do = '--apply' in sys.argv
    files = 0
    total = 0
    fallback = 0
    for p in sorted(root.rglob('*.java')):
        src = p.read_text(encoding='utf-8', errors='replace')
        if '??' not in src:
            continue
        new, hits = fix_text(src)
        if not hits or new == src:
            continue
        files += 1
        total += len(hits)
        fallback += sum(1 for _n, _t, h in hits if h == 'fallback')
        if do:
            p.write_text(new, encoding='utf-8')
    print('файлов: %d, объявлений исправлено: %d (из них с типом Object: %d)'
          % (files, total, fallback))
    if not do:
        print('(отчёт; добавь --apply)')


if __name__ == '__main__':
    main()
