#!/usr/bin/env bash
# Сборка декомпилированного дампа Roblox Delta-2.747.1486.
#
# Что делает:
#   1. проверяет инструменты (java/javac, curl, tar, unzip)
#   2. качает android.jar API 35 (27 МБ, с проверкой целостности)
#   3. распаковывает исходники и накладывает 157 исправлений
#   4. исключает 9 файлов, невосстановимых декомпиляцией (см. still_broken_9.txt)
#   5. компилирует и складывает отчёт об ошибках
#
# Требуется: JDK 17+, curl, tar, unzip.
# Запуск:  bash build_kit/build.sh
# Итог:    build_kit/out/ (классы), build_kit/errors.txt
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
WORK="$HERE/work"
OUT="$HERE/out"
AJAR="$HERE/android35.jar"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { printf '\033[31mОШИБКА: %s\033[0m\n' "$*" >&2; exit 1; }

say "1/5 Проверка инструментов"
command -v javac >/dev/null || die "javac не найден в PATH. Установи JDK 17+"
command -v java  >/dev/null || die "java не найден"
command -v unzip >/dev/null || die "unzip не найден (pkg install unzip / apt install unzip)"
echo "javac: $(javac -version 2>&1)"
echo "java:  $(java -version 2>&1 | head -1)"

say "2/5 android.jar (API 35)"
# Отдельный скрипт: проверяет целостность и падает с внятной ошибкой, если файл битый.
bash "$HERE/get_android_jar.sh" || die "android.jar не получен (см. сообщение выше)"

say "3/5 Исходники"
rm -rf "$WORK"; mkdir -p "$WORK"
( cd "$WORK" && unzip -q "$ROOT/Delta-2_sources.zip" ) || die "не удалось распаковать Delta-2_sources.zip"
SRC="$WORK/out/sources"
[ -d "$SRC" ] || die "в архиве нет out/sources"
TOTAL=$(find "$SRC" -name '*.java' | wc -l | tr -d ' ')
echo "файлов: $TOTAL"

say "4/5 Патчи (157 файлов) + исключение невосстановимых (9)"
if [ -f "$ROOT/syntax_fixes.zip" ]; then
  ( cd "$WORK/out" && unzip -qo "$ROOT/syntax_fixes.zip" ) || die "не удалось наложить syntax_fixes.zip"
  echo "наложено 157 исправленных файлов"
else
  echo "ВНИМАНИЕ: syntax_fixes.zip не найден — компилирую как есть"
fi

# Файлы, где JADX потерял конструкцию: чинить нечего, они ломают вывод javac
# каскадом. Исключаем из списка компиляции — на остальное они не влияют.
cd "$SRC"
find . -name '*.java' > "$HERE/all_sources.txt"
if [ -f "$HERE/still_broken_9.txt" ]; then
  grep -v -F -x -f <(sed 's|^|./|' "$HERE/still_broken_9.txt") "$HERE/all_sources.txt" \
    > "$HERE/sources.txt" || true
  EXCL=$(( $(wc -l < "$HERE/all_sources.txt") - $(wc -l < "$HERE/sources.txt") ))
  echo "исключено невосстановимых: $EXCL (их ошибки не пойдут в каскад)"
else
  cp "$HERE/all_sources.txt" "$HERE/sources.txt"
fi

say "4.5/5 Восстановление из DEX"
DEXDIR="$WORK/dex"
mkdir -p "$DEXDIR"
python3 "$ROOT/dex_recovery/extract_dex.py" "$ROOT" "$DEXDIR"
if ls "$DEXDIR"/*.dex >/dev/null 2>&1; then
  DEXLIST=$(ls "$DEXDIR"/*.dex | tr '\n' ' ')
  echo "dex: $(ls "$DEXDIR"/*.dex | wc -l | tr -d ' ') файлов"
  # F4: типы потерянных локальных переменных (?? name = ...)
  python3 "$ROOT/dex_recovery/fix_unknown_local.py" "$SRC" --apply || true
  # главное: вернуть пропавшие ВЛОЖЕННЫЕ классы по сигнатурам из DEX
  python3 "$ROOT/dex_recovery/inject_nested.py" "$SRC" "$SRC" $DEXLIST || true
else
  echo "ВНИМАНИЕ: dex не найден — восстановление из DEX пропущено"
fi

say "5/5 Компиляция"
mkdir -p "$OUT"; rm -rf "$OUT"/*
echo "передаю $(wc -l < "$HERE/sources.txt") файлов в javac (несколько минут)..."

javac -nowarn -proc:none -Xmaxerrs 100000 -Xlint:none \
      -d "$OUT" \
      -cp "$AJAR" \
      -sourcepath . \
      @"$HERE/sources.txt" 2> "$HERE/errors.txt"
RC=$?

NERR=$(grep -c '^[^ ].*: error:' "$HERE/errors.txt" 2>/dev/null || echo 0)
NFILE=$(grep '^[^ ].*: error:' "$HERE/errors.txt" 2>/dev/null | sed 's|:.*||' | sort -u | wc -l | tr -d ' ')
NCLS=$(find "$OUT" -name '*.class' 2>/dev/null | wc -l | tr -d ' ')

echo
echo "----------------------------------------"
if [ "$RC" -eq 0 ]; then
  echo "СБОРКА УСПЕШНА: $NCLS классов"
else
  echo "javac код возврата: $RC"
  echo "классов собрано:    $NCLS"
  echo "ошибок:             $NERR"
  echo "файлов с ошибками:  $NFILE"
  echo
  echo "ТОП-10 файлов по числу ошибок:"
  grep '^[^ ].*: error:' "$HERE/errors.txt" 2>/dev/null \
    | sed 's|:.*||' | sort | uniq -c | sort -rn | head -10 \
    | sed "s|$SRC/||"
fi
echo "----------------------------------------"
echo "лог: $HERE/errors.txt"
echo
echo "Разбор по категориям:"
echo "  python3 build_kit/analyze_errors.py build_kit/errors.txt"
