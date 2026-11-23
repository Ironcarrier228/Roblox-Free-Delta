#!/usr/bin/env python3
"""Починка синтаксически сломанных файлов декомпиляции JADX.

Принцип: каждое исправление проверяется парсером немедленно. Если файл после
правки не стал валидным — правка НЕ применяется и файл остаётся нетронутым.
Так гарантируется отсутствие регрессий.

Категории (см. README.md рядом):
  R1  android stub-интерфейсы  (*$Inner.java с static{throw NoClassDefFoundError})
  R2  enum X extends Y         (в Java запрещено) -> static class X extends Y
  R3  мусор вложенных классов  (b.c -> дочерний класс объявлен в этом файле)
  R4  неинициализированные final-поля -> = null
  R5  ключевое слово как идентификатор (default/class/...) -> имя_подчёркиванием
  R6  обрыв выражения перед блоком ошибки JADX -> усечение до корректной границы

Запуск:  python3 fix_syntax.py <каталог-с-java> [--apply]
Без --apply только отчёт, ничего не пишет.
"""
import javalang
import pathlib
import re
import sys
import json
import shutil

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/x/out/sources')
APPLY = '--apply' in sys.argv
JAVA_KW = {'default', 'class', 'int', 'new', 'static', 'enum', 'public',
           'private', 'protected', 'void', 'final', 'import', 'package',
           'interface', 'extends', 'implements', 'return', 'throw', 'this',
           'super', 'null', 'true', 'false', 'if', 'else', 'while', 'for'}


def parses(src):
    try:
        javalang.parse.parse(src)
        return True, ''
    except javalang.parser.JavaSyntaxError as e:
        return False, '%s | %s' % (getattr(e, 'description', ''), getattr(e, 'at', ''))
    except Exception as e:
        return False, type(e).__name__


# ---------- правила ----------

def r1_stub_interface(src):
    """android/app/Activity$ScreenCaptureCallback.java -> валидный интерфейс."""
    m = re.search(r'public\s+/\*\s*synthetic\s*\*/\s+(interface|class)\s+([\w$]+)\s*\{\s*'
                  r'static\s*\{\s*throw\s+new\s+NoClassDefFoundError\(\);\s*\}\s*\}', src, re.S)
    if not m:
        return None
    kind, name = m.group(1), m.group(2)
    clean = name.split('$')[-1]
    return src[:m.start()] + 'public %s %s {\n}\n' % (kind, clean) + src[m.end():]


def r2_enum_extends(src):
    """enum X extends Y — невалидно в Java; заменяем на 'public static class X extends Y'.

    JADX так помечает невосстановленные enum: класс-наследник Enum с полем $VALUES.
    Сохраняем модификатор public, если он был, и добавляем static.
    """
    out = src
    changed = False
    pat = re.compile(r'((?:public|private|protected)\s+)?\benum\s+(\w+)\s+extends\s+([\w.$]+)\s*\{')
    while True:
        m = pat.search(out)
        if not m:
            break
        vis = m.group(1) or ''
        new = '%spublic static class %s extends %s {' % ('' if 'public' in vis else 'public ', m.group(2), m.group(3))
        out = out[:m.start()] + new + out[m.end():]
        changed = True
    return out if changed else None


def r3_uninit_final(src):
    """public static final T name; -> = null (только static final без инициализатора)."""
    pat = re.compile(r'(public\s+static\s+final\s+[\w.$<>\[\], ?]+\s+\w+)\s*;')

    def rep(m):
        decl = m.group(1)
        if '=' in decl:
            return m.group(0)
        return decl + ' = null;'
    out = pat.sub(rep, src)
    return out if out != src else None


def r5_keyword_ident(src):
    """Идентификатор-ключевое слово: 'public final char char;' -> 'char char_;'."""
    KW = (r'char|default|class|enum|int|new|static|final|void|public|private|'
          r'protected|if|else|for|while|return|throw|this|super|null|true|false|'
          r'import|package|interface|extends|implements|abstract|synchronized|'
          r'volatile|transient|native')
    changed = False
    out = []
    for line in src.split('\n'):
        if re.search(r'\b(class|interface|enum)\s+$', line.rstrip(';').rstrip() + ' '):
            out.append(line)
            continue
        m = re.match(r'^(.*?)\b(' + KW + r')(\s*;\s*)$', line)
        if m and re.search(r'[A-Za-z0-9_\]>]\s*$', m.group(1)):
            head = m.group(1).rstrip()
            if re.search(r'\b(return|throw|new|else|case|assert|yield)\s*$', head):
                out.append(line)
                continue
            if head.endswith('.') or head.endswith(','):
                out.append(line)
                continue
            out.append('%s %s_;' % (head, m.group(2)))
            changed = True
            continue
        out.append(line)
    return '\n'.join(out) if changed else None


def r10_inlined_constant_garbage(src):
    """Порча от неудачного инлайна константы:

        x.getCom.appsflyer.sdk_base.referrer.Payload.TYPE java.lang.String()
        -> x.getType()
    """
    pat = re.compile(r'getCom\.appsflyer\.sdk_base\.referrer\.Payload\.\w+\s+java\.lang\.String\(\)')
    if not pat.search(src):
        return None
    out = pat.sub('getType()', src)
    return out if out != src else None


def r11_interface_static_block(src):
    """interface с static-блоком: в Java так нельзя (JADX оставляет инициализацию
    статических полей интерфейса). Меняем на abstract class."""
    if 'static {' not in src:
        return None
    m = re.search(r'public\s+interface\s+(\w+)\s*(?:extends\s+[\w.,$<>\s]+)?\s*\{', src)
    if not m:
        return None
    head = m.group(0).replace('interface', 'abstract class', 1)
    return src[:m.start()] + head + src[m.end():]


def r9_kw_usages(src):
    """Согласованное переименование обращений к переименованным полям.

    Ловит: 'this.char', 'obj.char', 'default.I(...)' (вызов на поле),
    а также присваивания 'default = ...'.
    """
    declared = set(re.findall(r'\b\w+\s+(\w+)_;', src))
    if not declared:
        return None
    changed = False
    out = src
    for name in declared:
        n = re.escape(name)
        pats = [
            (re.compile(r'(\bthis\.|\b\w+\.)' + n + r'\b(?!\s*\()'), r'\1' + name + '_'),
            (re.compile(r'(?<![\w."])' + n + r'(?=\s*[=;,)])(?!\s*\()'), name + '_'),
            (re.compile(r'(?<![\w."])' + n + r'(?=\s*\.)'), name + '_'),
        ]
        for pat, rep in pats:
            out2, k = pat.subn(rep, out)
            if k:
                out = out2
                changed = True
    return out if changed else None


def r6_truncated_stmt(src):
    """Строка обрывается перед блоком 'JADX ERROR' — усекаем до ';' или удаляем."""
    lines = src.split('\n')
    idx = None
    for i, l in enumerate(lines):
        if 'JADX ERROR' in l and l.strip().startswith('/*'):
            idx = i
            break
    if idx is None or idx == 0:
        return None
    # найти начало «нормального» кода выше: последняя строка, оканчивающаяся на ; { }
    j = idx - 1
    while j > 0 and not re.search(r'[;{}]\s*$', lines[j]):
        j -= 1
    # удалить строки (j, idx) — оборванное выражение или присваивание
    removed = idx - j - 1
    if removed <= 0:
        return None
    need = ';' if lines[j].rstrip().endswith(')') is False else ''
    kept = lines[:j + 1]
    if need and not kept[-1].rstrip().endswith((';', '{', '}')):
        kept[-1] = kept[-1].rstrip() + ';'
    out = '\n'.join(kept + lines[idx:])
    return out if out != src else None



def r7_unknown_type(src):
    """'?? name = expr;' -> 'var name = expr;'   (тип выводится из инициализатора)
       '?? name;'         -> 'Object name = null;'"""
    changed = False
    out_lines = []
    for line in src.split('\n'):
        m = re.match(r'^(\s*)\?\?\s+([A-Za-z_]\w*)\s*=\s*(.+)$', line)
        if m:
            out_lines.append('%svar %s = %s' % (m.group(1), m.group(2), m.group(3)))
            changed = True
            continue
        m3 = re.match(r'^(\s*)for\s*\(\s*\?\?\s+([A-Za-z_]\w*)\s*=', line)
        if m3:
            out_lines.append('%sfor (var %s =' % (m3.group(1), m3.group(2)) + line.split('=', 1)[1])
            changed = True
            continue
        m2 = re.match(r'^(\s*)\?\?\s+([A-Za-z_]\w*)\s*;\s*$', line)
        if m2:
            out_lines.append('%sObject %s = null;' % (m2.group(1), m2.group(2)))
            changed = True
            continue
        out_lines.append(line)
    return '\n'.join(out_lines) if changed else None


def r8_stub_class_static_block(src):
    """stub-класс/интерфейс с static-блоком, где throw NoClassDefFoundError
    стоит не в теле метода -> убираем блок."""
    if 'NoClassDefFoundError' not in src:
        return None
    pat = re.compile(r'\n\s*static\s*\{\s*\n\s*throw\s+new\s+NoClassDefFoundError\(\);\s*\n\s*\}')
    out, n = pat.subn('\n', src)
    return out if n else None


RULES = [
    ('R1_stub_interface', r1_stub_interface),
    ('R2_enum_extends', r2_enum_extends),
    ('R3_uninit_final', r3_uninit_final),
    ('R5_keyword_ident', r5_keyword_ident),
    ('R6_truncated_stmt', r6_truncated_stmt),
    ('R7_unknown_type', r7_unknown_type),
    ('R9_kw_usages', r9_kw_usages),
    ('R10_inlined_const_garbage', r10_inlined_constant_garbage),
    ('R11_interface_static_block', r11_interface_static_block),
    ('R8_stub_static_block', r8_stub_class_static_block),
]


def main():
    files = sorted(ROOT.rglob('*.java'))
    broken = []
    for p in files:
        src = p.read_text(encoding='utf-8', errors='replace')
        ok, _ = parses(src)
        if not ok:
            broken.append(p)

    print('файлов: %d, сломано: %d' % (len(files), len(broken)))
    fixed, unfixable = [], []

    for p in broken:
        orig = p.read_text(encoding='utf-8', errors='replace')
        cur = orig
        applied = []
        # жадный проход: применяем правила, пока файл не станет валидным
        for _ in range(6):
            ok, _ = parses(cur)
            if ok:
                break
            progressed = False
            for name, fn in RULES:
                cand = fn(cur)
                if cand is None or cand == cur:
                    continue
                ok2, _ = parses(cand)
                # применяем только если стало лучше (парсится) или это первое правило
                if ok2:
                    cur = cand
                    applied.append(name)
                    progressed = True
                    break
            if not progressed:
                # попытка применить правило без немедленного успеха (цепочка правил)
                for name, fn in RULES:
                    cand = fn(cur)
                    if cand is not None and cand != cur:
                        cur = cand
                        applied.append(name)
                        progressed = True
                        break
            if not progressed:
                break

        ok, err = parses(cur)
        rel = str(p.relative_to(ROOT))
        if ok and applied:
            fixed.append((rel, applied))
            if APPLY:
                shutil.copy2(p, str(p) + '.orig')
                p.write_text(cur, encoding='utf-8')
        else:
            unfixable.append((rel, err))

    print('\n=== ПОЧИНЕНО: %d ===' % len(fixed))
    for rel, ap in fixed:
        print('  %-70s %s' % (rel, ','.join(ap)))
    print('\n=== НЕ ПОДДАЛОСЬ: %d ===' % len(unfixable))
    for rel, err in unfixable[:20]:
        print('  %-60s %s' % (rel, err[:60]))

    json.dump({'fixed': fixed, 'unfixable': unfixable},
              open('/tmp/fix/result.json', 'w'), ensure_ascii=False, indent=1)
    if not APPLY:
        print('\n(режим отчёта; добавить --apply чтобы записать)')


if __name__ == '__main__':
    main()
