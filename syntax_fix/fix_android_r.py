#!/usr/bin/env python3
"""F3: JADX спутал `R.*` (свой R) с `android.R.*` (framework).

Симптом в javac: `cannot find symbol: variable orientation / location R`.
Причина: в обфусцированном коде R-константы фреймворка пришли как `R.attr.id`,
`R.id.content` и т.п., а имя `R`, импортированное из другого пакета
(`com.roblox.client.personasdk.R`), таких полей не имеет.

Правило: обращение `R.<тип>.<имя>`, которого НЕТ в своём R, но которое ЕСТЬ в
`android.R`, переписать в `android.R.<тип>.<имя>`.

Проверка идёт по настоящему android.jar (имена полей читаются из .class),
поэтому ложных срабатываний нет: замена только там, где имя существует.

Использование:
    python3 fix_android_r.py <sources_dir> <android.jar> [--apply]

ВАЖНО: работает только вне комментариев и не трогает строковые литералы
и уже корректные `android.R.` (защита lookbehind).
"""
import re
import struct
import sys
import zipfile
import pathlib

TYPES = ['attr', 'id', 'style', 'color', 'anim', 'string', 'layout', 'drawable',
         'integer', 'dimen', 'bool', 'array', 'menu', 'xml', 'raw', 'animator',
         'interpolator', 'mipmap', 'plurals', 'fraction', 'transition']


# ---------- чтение имён полей из .class ----------
def parse_class(data):
    n = struct.unpack('>H', data[8:10])[0]
    i, utf, k = 10, {}, 1
    while k < n:
        tag = data[i]
        i += 1
        if tag == 1:
            L = struct.unpack('>H', data[i:i + 2])[0]
            i += 2
            utf[k] = data[i:i + L].decode('utf-8', 'replace')
            i += L
        elif tag in (7, 8, 16, 19, 20):
            i += 2
        elif tag == 15:
            i += 3
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            i += 4
        elif tag in (5, 6):
            i += 8
            k += 2
            continue
        k += 1
    i += 6
    ic = struct.unpack('>H', data[i:i + 2])[0]
    i += 2 + 2 * ic
    fc = struct.unpack('>H', data[i:i + 2])[0]
    i += 2
    out = set()
    for _ in range(fc):
        _acc, ni, _di = struct.unpack('>HHH', data[i:i + 6])
        i += 6
        ac = struct.unpack('>H', data[i:i + 2])[0]
        i += 2
        for _ in range(ac):
            i += 2
            L = struct.unpack('>I', data[i:i + 4])[0]
            i += 4 + L
        out.add(utf[ni])
    return out


def load_android_r(jar):
    z = zipfile.ZipFile(jar)
    names = set(z.namelist())
    out = {}
    for t in TYPES:
        c = 'android/R$%s.class' % t
        if c in names:
            out[t] = parse_class(z.read(c))
    return out


# ---------- разбор комментариев/строк ----------
NOISE = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S)


def apply_outside_noise(src, fn):
    """Применить fn к участкам вне комментариев/строк."""
    out, pos = [], 0
    for m in NOISE.finditer(src):
        if m.start() > pos:
            out.append(fn(src[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    if pos < len(src):
        out.append(fn(src[pos:]))
    return ''.join(out)


def own_r_packages(root):
    """Пакеты, в которых есть свой класс R (например com.roblox.client.personasdk)."""
    pkgs = set()
    for p in root.rglob('R.java'):
        txt = p.read_text(encoding='utf-8', errors='replace')[:400]
        m = re.search(r'^package\s+([\w.]+);', txt, re.M)
        if m:
            pkgs.add(m.group(1))
    return pkgs


def main():
    root = pathlib.Path(sys.argv[1])
    jar = sys.argv[2]
    do_apply = '--apply' in sys.argv

    ar = load_android_r(jar)
    print('android.R: ' + ', '.join('%s=%d' % (t, len(v)) for t, v in sorted(ar.items())))

    # 1) имена, определённые в своём R
    own = {}
    for p in root.rglob('R.java'):
        cur = None
        txt = p.read_text(encoding='utf-8', errors='replace')
        for line in txt.split('\n'):
            m = re.search(r'public static final class (\w+)', line)
            if m:
                cur = m.group(1).lower()
                own.setdefault(cur, set())
                continue
            m = re.search(r'public static final int (\w+)\s*=', line)
            if m and cur:
                own[cur].add(m.group(1))
    print('свой R: ' + ', '.join('%s=%d' % (t, len(v)) for t, v in sorted(own.items())))

    RREF = re.compile(r'(?<![.\w])R\.([a-z]+)\.(\w+)')
    stats = {}
    changed = []

    def make_fixer():
        hits = []

        def fix(chunk):
            def rep(m):
                t, n = m.group(1), m.group(2)
                if n in own.get(t, set()):
                    return m.group(0)          # есть в своём R — не трогаем
                if n in ar.get(t, set()):
                    hits.append((t, n))
                    return 'android.R.%s.%s' % (t, n)
                return m.group(0)              # неизвестно — оставляем как есть
            return RREF.sub(rep, chunk)
        return fix, hits

    for p in sorted(root.rglob('*.java')):
        src = p.read_text(encoding='utf-8', errors='replace')
        fix, hits = make_fixer()
        new = apply_outside_noise(src, fix)
        if hits:
            for t, n in hits:
                stats[t] = stats.get(t, 0) + 1
            changed.append((str(p.relative_to(root)), len(hits)))
            if do_apply:
                p.write_text(new, encoding='utf-8')

    total_hits = sum(stats.values())
    print('\nпереписано обращений: %d в %d файлах' % (total_hits, len(changed)))
    for t, c in sorted(stats.items(), key=lambda x: -x[1]):
        print('  %-10s %d' % (t, c))
    if not do_apply:
        print('\n(отчёт; добавь --apply чтобы записать)')
        for f, n in changed[:15]:
            print('  %-58s %d' % (f, n))


if __name__ == '__main__':
    main()
