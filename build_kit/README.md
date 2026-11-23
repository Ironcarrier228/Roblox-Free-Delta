# Набор для сборки — запусти у себя

У меня в песочнице нет компилятора Java (все зеркала заблокированы, см.
`sdk_audit/README.md`). У тебя JDK есть — значит финальную проверку сделаешь ты,
а я разберу результат. Ниже — что запустить и что прислать.

## Быстрый старт

Нужно: **JDK 17+** (`javac` в PATH), `curl`, `tar`, `unzip`.

```bash
git clone https://github.com/Ironcarrier228/Roblox-Free-Delta.git
cd Roblox-Free-Delta
bash build_kit/build.sh
```

Скрипт сам:
1. проверит инструменты;
2. скачает `android.jar` API 35 (~750 МБ tar.gz, из него берётся один файл 26 МБ);
3. распакует `Delta-2_sources.zip` во временный каталог;
4. наложит 74 исправленных файла из `syntax_fixes.zip`;
5. скомпилирует всё и соберёт `build_kit/errors.txt`.

Если `curl` не может скачать `android.jar` — скачай вручную
[отсюда](https://codeload.github.com/Sable/android-platforms/tar.gz/refs/heads/master),
достань из архива `android-35/android.jar` и положи как
`build_kit/android35.jar`, потом запусти скрипт снова (он увидит файл и
пропустит скачивание).

## Что мне прислать

```bash
python3 build_kit/analyze_errors.py build_kit/errors.txt
```

Пришли вывод этой команды (или сам `errors.txt`, если он небольшой). Я разберу
ошибки по категориям и скажу, какие из них чинятся механически.

## Прогноз: чего ждать

По аудиту с реальным `android.jar` (`sdk_audit/`) ожидаю такую картину:

| что | ожидание |
|---|---|
| **ошибки `package androidx.* does not exist`** | **основная масса** — реализации библиотек нет, только имена в `android.jar` |
| `package kotlin.* does not exist` | много — Kotlin-рантайма нет |
| `package android.* does not exist` | **мало** — только 26 внутренних классов `android.view.*`, 160 файлов |
| `cannot find symbol` | средне — Kotlin top-level функции (`CollectionsKt.firstOrNull` и т.п.) |
| синтаксис | **0** — 74 файла починены, 8 оставшихся можно исключить флагом (см. ниже) |

98% файлов имеют полностью разрешимый framework-контракт, так что **прикладной
код Roblox должен пройти** — упадут в основном библиотечные обёртки.

## Если хочется пойти дальше: только свой код Roblox

Самая осмысленная проверка — скомпилировать не весь дамп, а только то, что
написано Roblox (1 260 файлов). Меньше шума, быстрее, и сразу видно качество
именно приложения.

```bash
cd build_kit/work/out/sources
find com/roblox deobf/com/roblox -name '*.java' > /tmp/own.txt
javac -nowarn -proc:none -d /tmp/own-out -cp ../../../android35.jar \
      -sourcepath . @/tmp/own.txt 2> /tmp/own-errors.txt
wc -l /tmp/own-errors.txt
```

Пришли `/tmp/own-errors.txt` — это будет самый информативный результат.

## Если javac ругается на 8 файлов, которые я не смог починить

Они в `still_broken_8.txt`. Это места, где JADX потерял конструкцию (enum без
объявления, поле `default` в связке с `@Metadata` и т.п.). Исключить их:

```bash
grep -v -f <(sed 's|^|./|' build_kit/still_broken_8.txt) build_kit/sources.txt \
  > /tmp/sources_clean.txt
```

## Что уже готово в репозитории

| файл | что |
|---|---|
| `Delta-2_sources.zip` | исходный дамп, 13 392 файла |
| `syntax_fixes.zip` | 74 исправленных файла (99.94% дампа парсится) |
| `R_recovered/` | восстановленный `R.java` (6 191 ресурс) вместо сломанных стабов |
| `build_kit/build.sh` | этот скрипт |
| `build_kit/analyze_errors.py` | группировка ошибок javac |
| `sdk_audit/` | аудит импортов по реальному API 35 |

## Чего ждать в итоге (честно)

Даже если всё скомпилируется — **работающего приложения не будет**:
* 547 native-методов, из них 136 без парного экспорта в `.so`;
* `nativeStart` отсутствует во всех библиотеках → падение на старте;
* движок `libroblox.so` (108 МБ) — машинный код без исходников.

Так что цель этой сборки — **измерить качество дампа**, а не получить APK.
Это единственная проверка, которую нельзя сделать статически.
