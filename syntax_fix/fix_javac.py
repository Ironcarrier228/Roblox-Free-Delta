#!/usr/bin/env python3
"""Правила, которые нашёл ТОЛЬКО javac (javalang их пропускал).

F1  int-литерал с 32-битной сигнатурой переполнения:
        0xffffffff87010000 -> 0x87010000
    ВАЖНО: применяется только в реальном коде, вне комментариев. JADX пишет
    внутри /* */ листинги байткода вида 'r2 = -2147483648(0xffffffff80000000)',
    их трогать нельзя — это читаемая документация, а не код.

F2  конструктор с именем анонимного класса (артефакт JADX):
        public AnonymousClass5(...) -> public void AnonymousClass5(...)
"""
import re
import sys
import pathlib

F1 = re.compile(r'0xffffffff([0-9a-f]{8})\b')
F2 = re.compile(r'\bpublic\s+(AnonymousClass\d+)\s*\(')
BLOCK = re.compile(r'/\*.*?\*/', re.S)
LINE = re.compile(r'//[^\n]*')


def split_comments(src):
    """Вернуть список (фрагмент, является_ли_комментарием)."""
    out = []
    pos = 0
    for m in BLOCK.finditer(src):
        if m.start() > pos:
            out.append((src[pos:m.start()], False))
        out.append((m.group(0), True))
        pos = m.end()
    if pos < len(src):
        out.append((src[pos:], False))
    # построчные комментарии внутри кода
    res = []
    for frag, is_com in out:
        if is_com:
            res.append((frag, True))
            continue
        p = 0
        for m in LINE.finditer(frag):
            if m.start() > p:
                res.append((frag[p:m.start()], False))
            res.append((m.group(0), True))
            p = m.end()
        if p < len(frag):
            res.append((frag[p:], False))
    return res


def fix_text(src):
    applied = []
    parts = split_comments(src)
    out = []
    n1 = n2 = 0
    for frag, is_com in parts:
        if is_com:
            out.append(frag)
            continue
        frag, a = F1.subn(r'0x\1', frag)
        n1 += a
        frag, b = F2.subn(r'public void \1(', frag)
        n2 += b
        out.append(frag)
    if n1:
        applied.append('F1:%d' % n1)
    if n2:
        applied.append('F2:%d' % n2)
    return ''.join(out), applied


def main():
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/x2/out/sources')
    apply = '--apply' in sys.argv
    changed = []
    for p in sorted(root.rglob('*.java')):
        src = p.read_text(encoding='utf-8', errors='replace')
        out, app = fix_text(src)
        if app and out != src:
            changed.append((str(p.relative_to(root)), app))
            if apply:
                p.write_text(out, encoding='utf-8')
    print('файлов изменено: %d' % len(changed))
    for f, a in changed:
        print('  %-52s %s' % (f, ','.join(a)))
    if not apply:
        print('\n(отчёт; добавь --apply чтобы записать)')


if __name__ == '__main__':
    main()
