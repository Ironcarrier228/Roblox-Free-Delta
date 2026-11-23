#!/usr/bin/env python3
"""Достать classes*.dex из разрезанного APK (apk_part_aa..ad).

APK лежит в репозитории четырьмя частями; склеиваем в память и вынимаем dex.
Использование: python3 extract_dex.py <repo_root> <out_dir>
"""
import io
import sys
import zipfile

PARTS = ['apk_part_aa', 'apk_part_ab', 'apk_part_ac', 'apk_part_ad']


def main():
    root, out = sys.argv[1], sys.argv[2]
    buf = io.BytesIO()
    for p in PARTS:
        with open(root + '/' + p, 'rb') as f:
            buf.write(f.read())
    z = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    n = 0
    total = 0
    for name in z.namelist():
        if name.endswith('.dex'):
            data = z.read(name)
            with open(out + '/' + name, 'wb') as f:
                f.write(data)
            print('  %s: %d байт' % (name, len(data)))
            n += 1
            total += len(data)
    if not n:
        sys.exit('dex не найден в APK')
    print('  итого: %d dex, %.1f МБ' % (n, total / 1048576))


if __name__ == '__main__':
    main()
