#!/usr/bin/env bash
# Сборка декомпилированного дампа Roblox Delta-2.747.1486.
#
# Что делает:
#   1. проверяет инструменты (java/javac, curl, tar, unzip)
#   2. скачивает android.jar API 35 (если ещё нет)
#   3. распаковывает исходники и применяет 74 исправления синтаксиса
#   4. компилирует и складывает отчёт об ошибках
#
# Требуется: JDK 17+ (javac в PATH), curl, tar, unzip.
# Запуск:  bash build_kit/build.sh
# Результат: build_kit/out/  (классы) и build_kit/errors.txt
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
WORK="$HERE/work"
OUT="$HERE/out"
AJAR="$HERE/android35.jar"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { printf '\033[31mОШИБКА: %s\033[0m\n' "$*" >&2; exit 1; }

say "1/5 Проверка инструментов"
command -v javac >/dev/null || die "javac не найден в PATH. Установи JDK 17+ (например: sudo apt install openjdk-17-jdk)"
command -v java  >/dev/null || die "java не найден"
command -v curl  >/dev/null || die "curl не найден"
command -v tar   >/dev/null || die "tar не найден"
echo "javac: $(javac -version 2>&1)"
echo "java:  $(java -version 2>&1 | head -1)"

say "2/5 android.jar (API 35)"
if [ -f "$AJAR" ]; then
  echo "уже есть: $AJAR ($(du -h "$AJAR" | cut -f1))"
else
  TMP="$HERE/.dl.tgz"
  echo "качаю репозиторий android-platforms (~750 МБ tar.gz, из него нужен один файл)..."
  curl -L --fail --retry 3 -o "$TMP" \
    "https://codeload.github.com/Sable/android-platforms/tar.gz/refs/heads/master" \
    || die "не удалось скачать. Скачай вручную:
  https://codeload.github.com/Sable/android-platforms/tar.gz/refs/heads/master
  и положи android-35/android.jar как build_kit/android35.jar"
  tar -xzf "$TMP" --wildcards '*/android-35/android.jar' -C "$HERE" || die "android.jar не найден в архиве"
  mv "$HERE"/android-platforms-master/android-35/android.jar "$AJAR"
  rm -rf "$HERE"/android-platforms-master "$TMP"
  echo "готово: $AJAR"
fi

say "3/5 Исходники"
rm -rf "$WORK"; mkdir -p "$WORK"
( cd "$WORK" && unzip -q "$ROOT/Delta-2_sources.zip" ) || die "не удалось распаковать Delta-2_sources.zip"
SRC="$WORK/out/sources"
[ -d "$SRC" ] || die "в архиве нет out/sources"
echo "файлов: $(find "$SRC" -name '*.java' | wc -l)"

say "4/5 Применяю 78 исправленных файлов"
if [ -f "$ROOT/syntax_fixes.zip" ]; then
  ( cd "$WORK/out" && unzip -qo "$ROOT/syntax_fixes.zip" ) || echo "предупреждение: не удалось наложить патчи"
  echo "наложено 78 файлов из syntax_fixes.zip"
else
  echo "syntax_fixes.zip не найден — компилирую как есть (будет больше ошибок)"
fi

say "5/5 Компиляция"
mkdir -p "$OUT"
find "$SRC" -name '*.java' > "$HERE/sources.txt"
echo "передаю $(wc -l < "$HERE/sources.txt") файлов в javac (это займёт несколько минут)..."

cd "$SRC"
javac -nowarn -proc:none -Xmaxerrs 100000 -Xlint:none \
      -d "$OUT" \
      -cp "$AJAR" \
      -sourcepath . \
      @"$HERE/sources.txt" 2> "$HERE/errors.txt"
RC=$?

echo
echo "----------------------------------------"
if [ $RC -eq 0 ]; then
  echo "СБОРКА УСПЕШНА: $(find "$OUT" -name '*.class' | wc -l) классов"
else
  echo "javac завершился с кодом $RC"
  echo "классов собрано: $(find "$OUT" -name '*.class' 2>/dev/null | wc -l)"
  echo "файлов с ошибками: $(grep -c 'error:' "$HERE/errors.txt" 2>/dev/null || echo 0)"
  echo
  echo "ТОП-15 типов ошибок:"
  grep 'error:' "$HERE/errors.txt" 2>/dev/null \
    | sed 's/.*error: //' \
    | sed 's/[A-Za-z_][A-Za-z0-9_.]*/X/g' \
    | sort | uniq -c | sort -rn | head -15
fi
echo "----------------------------------------"
echo "полный лог: $HERE/errors.txt"
echo
echo "Отправь мне errors.txt — разберу ошибки по категориям."
