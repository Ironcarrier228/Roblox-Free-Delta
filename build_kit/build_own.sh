#!/usr/bin/env bash
# Компиляция ТОЛЬКО кода Roblox (1 260 файлов из 13 392).
#
# Это самый информативный тест: он показывает качество именно приложения,
# без шума библиотек. Быстро (секунды вместо минут).
#
# Требуется: JDK 17+, build_kit/android35.jar (его скачает build.sh).
# Запуск:  bash build_kit/build_own.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AJAR="$HERE/android35.jar"
SRC="$HERE/work/out/sources"
OUT="$HERE/out-own"

command -v javac >/dev/null || { echo "нужен javac (JDK 17+)"; exit 1; }
[ -f "$AJAR" ] || { echo "нет $AJAR — сначала запусти bash build_kit/build.sh"; exit 1; }
[ -d "$SRC" ]  || { echo "нет $SRC — сначала запусти bash build_kit/build.sh"; exit 1; }

cd "$SRC"
find com/roblox deobf/com/roblox -name '*.java' 2>/dev/null > "$HERE/own_sources.txt"
COUNT=$(wc -l < "$HERE/own_sources.txt")
echo "файлов кода Roblox: $COUNT"

mkdir -p "$OUT"
javac -nowarn -proc:none -Xmaxerrs 100000 -Xlint:none \
      -d "$OUT" -cp "$AJAR" -sourcepath . @"$HERE/own_sources.txt" \
      2> "$HERE/own_errors.txt"
RC=$?

echo "----------------------------------------"
echo "код возврата javac: $RC"
echo "классов собрано: $(find "$OUT" -name '*.class' 2>/dev/null | wc -l)"
echo "ошибок: $(grep -c 'error:' "$HERE/own_errors.txt" 2>/dev/null || echo 0)"
echo "----------------------------------------"
echo "лог: $HERE/own_errors.txt"
echo
echo "Разбор: python3 build_kit/analyze_errors.py build_kit/own_errors.txt"
