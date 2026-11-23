#!/usr/bin/env python3
"""Разбор errors.txt от javac: группирует ошибки по категориям и файлам.

Использование:  python3 build_kit/analyze_errors.py build_kit/errors.txt
"""
import re
import sys
import collections

path = sys.argv[1] if len(sys.argv) > 1 else 'build_kit/errors.txt'
try:
    text = open(path, encoding='utf-8', errors='replace').read()
except FileNotFoundError:
    sys.exit('нет файла %s — сначала запусти build.sh' % path)

# javac: "путь:строка: error: сообщение"
errs = re.findall(r'^(.+?):(\d+): error: (.*)$', text, re.M)
print('всего ошибок: %d\n' % len(errs))

cats = collections.Counter()
byfile = collections.Counter()
examples = collections.defaultdict(list)

for f, ln, msg in errs:
    if 'package ' in msg and 'does not exist' in msg:
        pkg = re.search(r'package (\S+) does not exist', msg).group(1)
        cat = 'нет пакета: %s' % pkg
        if pkg.startswith('androidx'):
            cat = 'НЕТ ЗАВИСИМОСТИ (androidx): ' + pkg
        elif pkg.startswith('kotlin'):
            cat = 'НЕТ ЗАВИСИМОСТИ (kotlin): ' + pkg
        elif pkg.startswith('android.'):
            cat = 'НЕТ В API 35: ' + pkg
        else:
            cat = 'нет пакета: %s' % pkg
    elif 'cannot find symbol' in msg:
        sym = re.search(r'symbol:\s+(?:class|variable|method) (\S+)', text[text.find(msg):text.find(msg) + 400])
        cat = 'cannot find symbol' + (' (%s)' % sym.group(1) if sym else '')
    elif 'is not abstract and does not override' in msg:
        cat = 'не реализованы абстрактные методы'
    elif 'incompatible types' in msg:
        cat = 'несовместимые типы'
    elif 'method does not override' in msg:
        cat = 'method does not override'
    elif 'cannot be applied to' in msg:
        cat = 'не подходит сигнатура метода'
    elif 'is already defined' in msg:
        cat = 'повторное объявление'
    else:
        cat = msg[:70]

    cats[cat] += 1
    byfile[f] += 1
    if len(examples[cat]) < 2:
        examples[cat].append('%s:%s' % (f, ln))

print('=== ТОП-25 КАТЕГОРИЙ ===')
for cat, n in cats.most_common(25):
    print('%6d  %s' % (n, cat))
    for ex in examples[cat]:
        print('        %s' % ex)

print('\n=== ФАЙЛЫ С НАИБОЛЬШИМ ЧИСЛОМ ОШИБОК ===')
for f, n in byfile.most_common(20):
    print('%6d  %s' % (n, f))

unq = len(byfile)
print('\nфайлов с ошибками: %d, уникальных категорий: %d' % (unq, len(cats)))
