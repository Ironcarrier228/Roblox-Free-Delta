#!/usr/bin/env bash
# Скачивание android.jar (API 35) без 750 МБ лишнего.
#
# Качает только сам файл 27 МБ через GitHub API (blob по SHA), без tar.gz.
# Проверяет результат и падает с ошибкой, если файл битый.
#
# Запуск:  bash build_kit/get_android_jar.sh
# Результат: build_kit/android35.jar (27 092 450 байт)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AJAR="$HERE/android35.jar"
EXPECTED_SIZE=27092450
BLOB_SHA="2d6652edf0fb6046a23638f3a2f2c6246c745b08"

die() { printf '\033[31mОШИБКА: %s\033[0m\n' "$*" >&2; exit 1; }
say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

say "1/3 Проверка уже скачанного"
if [ -f "$AJAR" ]; then
  SIZE=$(wc -c < "$AJAR" | tr -d ' ')
  # битый/фейковый jar ловим по сигнатуре ZIP
  MAGIC=$(head -c 2 "$AJAR" 2>/dev/null)
  if [ "$SIZE" = "$EXPECTED_SIZE" ] && [ "$MAGIC" = "PK" ]; then
    echo "android.jar уже на месте и валиден: $SIZE байт"
    exit 0
  fi
  echo "файл есть, но невалиден (размер $SIZE, ожидалось $EXPECTED_SIZE). Перекачиваю."
  rm -f "$AJAR"
fi

say "2/3 Скачивание (~27 МБ)"
echo "источник: api.github.com blob $BLOB_SHA"
curl -L --fail --retry 3 --progress-bar \
     -H "Accept: application/vnd.github.raw" \
     -o "$AJAR.part" \
     "https://api.github.com/repos/Sable/android-platforms/git/blobs/$BLOB_SHA" \
  || die "не удалось скачать. Проверь интернет или скачай вручную:
  https://codeload.github.com/Sable/android-platforms/tar.gz/refs/heads/master
  внутри: android-platforms-master/android-35/android.jar
  положи как build_kit/android35.jar"

say "3/3 Проверка"
SIZE=$(wc -c < "$AJAR.part" | tr -d ' ')
[ "$SIZE" = "$EXPECTED_SIZE" ] || die "размер $SIZE, ожидалось $EXPECTED_SIZE — файл битый, повтори запуск"
MAGIC=$(head -c 2 "$AJAR.part")
[ "$MAGIC" = "PK" ] || die "это не ZIP/JAR (первые байты: $MAGIC) — проверь, не отдал ли GitHub HTML"
mv "$AJAR.part" "$AJAR"

# содержимое
if command -v python3 >/dev/null; then
  python3 - "$AJAR" <<'PY'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
n = z.namelist()
classes = [x for x in n if x.startswith('android/') and x.endswith('.class')]
need = ['android/app/Activity.class', 'android/os/Bundle.class', 'android/view/View.class']
miss = [c for c in need if c not in n]
print('  классов android/: %d' % len(classes))
if miss:
    print('  ОТСУТСТВУЮТ: %s' % miss); sys.exit(1)
print('  ключевые классы на месте: Activity, Bundle, View')
if len(classes) < 4000:
    print('  ПОДОЗРИТЕЛЬНО МАЛО классов'); sys.exit(1)
PY
  [ $? -eq 0 ] || die "android.jar не содержит ожидаемых классов"
fi

echo
echo "готово: $AJAR ($(du -h "$AJAR" | cut -f1))"
