# Как вызывается «дельта»: цепочка запуска от иконки до движка

Короткий ответ: **это не кастомный лончер и не подмена клиента.** Это обычный
Roblox 2.747.1486, в который вшита нативная прослойка чужого автора —
`com.roblox.gloop.Loader`. Она стартует раньше Roblox и дальше не даёт
запуститься настоящему движку. Ниже — по шагам, с файлами.

## 0. Что это за APK (по подписи и структуре)

| признак | значение |
|---|---|
| подпись | самоподписанный сертификат: `CN=Gloopiest Man`, `O=Gloop`, `L=Berlin`, `C=DE`, срок 12.07.2024 — 12.07.2025 |
| схема подписи | v1 + v2 + v3 (`X-Android-APK-Signed: 2, 3`), но ключ свой → **обновления из Play не встанут** |
| DEX | 4 шт.; `classes4.dex` целиком состоит из 5 классов `com.roblox.gloop.Loader*` |
| assets | добавлен `assets/gloop/dlt.zip` (2 МБ картинок UI) |
| ванильный Roblox | весь остальной код на месте, ничего не вырезано |

То есть взяли официальный APK, добавили один пакет в отдельный DEX, картинки в
assets — и переподписали своим ключом.

## 1. Старт: две разные «первые» точки

`AndroidManifest.xml` объявляет три иконки-алиаса:

```xml
<activity-alias android:name=".startup.LauncherAliasMain"
    android:targetActivity=".startup.ActivitySplash"
    android:enabled="true" exported="true"/>
<activity-alias android:name=".startup.LauncherAliasClassic" ... enabled="false"/>
<activity-alias android:name=".startup.LauncherAliasHalloween2026" ... enabled="false"/>
```

Тап по иконке → `ActivitySplash` (`com/roblox/client/startup/ActivitySplash.java:212`):

```java
public void onCreate(Bundle bundle) {
    StartedForEnum y22 = y2(getIntent());
    if (h.a().Q1()) {                       // флаг "GameActivity = ON"
        super.onCreate(bundle);
        Intent i22 = MainGameActivity.i2(this, y22);
        ...
        startActivity(i22);
        finish();
        return;
    }
    ...
}
```

Дальше `MainGameActivity` (`com/roblox/client/startup/MainGameActivity.java:1038`):

```java
public void onCreate(@Nullable Bundle savedInstanceState) {
    Loader.get().startLib(this);            // ← ПЕРВАЯ строка, до всего Roblox
    q.h("MainGameActivity", "onCreate");
    ...
    super.onCreate(savedInstanceState);
    ...
}
```

`ActivityNativeMain.java:1269` — то же самое, для второго варианта активити.

## 2. Что делает `Loader.startLib()`

`com/roblox/gloop/Loader.java` (весь пакет — 5 классов, `classes4.dex`):

```java
public synchronized void startLib(Activity _activity) {
    this.activity = _activity;
    Window window = _activity.getWindow();
    window.addFlags(128);                                // FLAG_KEEP_SCREEN_ON
    window.getDecorView().addOnLayoutChangeListener(this); // ловит ресайз
    requestPermissions();                                 // MANAGE_EXTERNAL_STORAGE!
    int nativeStart = nativeStart(this.activity, this);   // ← ключевой вызов
    if (nativeStart != 0) showToast("Failed to start: ERROR " + nativeStart);
}
```

`nativeStart(Activity, Loader)` — `public static native int`, объявлен в этом же
классе. И вот главное:

> **В APK нет ни одной нативной библиотеки, которая реализует
> `Java_com_roblox_gloop_Loader_nativeStart`.**

Проверено разбором ELF: в `libroblox.so` 1189 динамических символов, из них 586
экспортированных `Java_*` — и ни одного с `gloop`. В остальных 7 `.so` символ
тоже отсутствует. `libroblox.so` вдобавок **stripped** (`.symtab` нет), так что
функция не может быть спрятана как локальная и найдена через `dlsym`.

Отсюда следует:

* `nativeStart` не слинкован → при вызове летит `UnsatisfiedLinkError`;
* вызов обёрнут в `try { … } catch (Exception e) { showToast("Failed to start lib."); }`
  — а `UnsatisfiedLinkError` это `Error`, не `Exception`, поэтому **не ловится**;
* исключение вылетает из `onCreate` → приложение падает с `FATAL EXCEPTION`.

Именно поэтому `dlt.zip` и `logo.png` лежат внутри: при живом `nativeStart`
прослойка должна была рисовать поверх игры свой оверлей. **Логика этой
прослойки в APK отсутствует** — есть только Java-обвязка и картинки.

## 3. Что должно было происходить (по обвязке)

Внутри `Loader` (помимо `nativeStart`) есть `nativeContext(Context)` и
`nativeResize(int,int)`, а также готовые Java-методы, которые нативный слой
зовёт обратно:

| метод `Loader` | что делает | кому |
|---|---|---|
| `openWebsite(String url)` | `Intent(ACTION_VIEW, url)` | открыть сайт во внешнем браузере |
| `setClipboard(String)`, `getClipboard()` | работа с буфером обмена (`text/plain`) | вставка/копирование скриптов |
| `showToast(String)` | тост на UI-потоке | уведомления оверлея |
| `getDownloadUrl()` (`native`) | отдаёт строку-URL | откуда качать контент |
| `attachContext(Context)` | `nativeContext` → `throw RuntimeException("context returned false.")` | проброс контекста |

Иконки в `assets/gloop/dlt.zip` (74 файла) — это букварь интерфейса:
`Console.png`, `Execute.png`, `AutoExecNotify.png`, `LocalFile.png`,
`Clipboard.png`, `Discord.png`, `Telegram.png`, `Website.png`, `Key.png`,
`Verified.png`/`Unverified.png`, `SheildNotify.png`, `NewUI.png`/`OldUI.png`.
Плюс `Poppins.rbxmx` и шрифты Montserrat (`f1`, `i1`…`i18`) — кастомный UI
внутри Roblox.

Складывая: это заготовка инжектора-оверлея с консолью, автоисполнением,
списком локальных файлов, буфером обмена и проверкой «верификации».
`dlt` — вероятно, и есть имя инструмента (Delta / Delta Executor).

## 4. Где в цепочке настоящий Roblox

Ванильная часть не тронута и до неё дело не доходит:

```
ActivitySplash.onCreate
  └─ MainGameActivity.onCreate
       ├─ Loader.get().startLib(this)        ← падение здесь
       └─ (дальше не выполняется)
            RobloxApplication.attachBaseContext → a.I("main")
            a.t() → System.loadLibrary("roblox")      // startup/a.java:532
            FMOD.init → nativeGameGlobalInit()        // ei/f.java:270
            nativeInitClientSettingsSigned(...)       // ei/f.java:174
            nativeAppBridgeV2StartAppWithParams(...)  // ei/f.java:287
            nativeAppBridgeV2StartGameWithParam(...)  // ei/j0.java:123
```

## 5. Проверить у себя за минуту

```bash
# 1) кто подписал
unzip -p Delta-2.747.1486.apk META-INF/KEY.RSA | openssl pkcs7 -inform DER -print_certs -noout

# 2) есть ли реализация nativeStart
python3 - <<'PY'
import zipfile, re
z = zipfile.ZipFile("Delta-2.747.1486.apk")
for n in z.namelist():
    if n.endswith(".so") and b"Java_com_roblox_gloop" in z.read(n):
        print("found in", n)
PY

# 3) что упадёт в логе (Android 11+)
adb logcat | grep -E "UnsatisfiedLinkError|gloop|Failed to start"
```

Ожидаемый лог: `java.lang.UnsatisfiedLinkError: No implementation found for int
com.roblox.gloop.Loader.nativeStart(android.app.Activity, com.roblox.gloop.Loader)`
и следом `FATAL EXCEPTION: main ... at com.roblox.gloop.Loader.startLib`.

## 6. Вывод

* «Дельта» вызывается **не отдельным приложением и не скриптом**, а из
  `onCreate` главной активити — первой же строкой.
* Сама прослойка в этом APK **не рабочая**: нативная часть (`libgloop*.so` или
  вшитая в другую `.so`) отсутствует, поэтому клиент падает при старте ещё до
  инициализации Roblox.
* Никакой модификации движка в APK нет: `libroblox.so` — оригинальный, все 586
  JNI-символов на месте. Менялся только `AndroidManifest` (иконки, разрешения),
  набор DEX и assets.
* Обновления из Play на эту сборку не встанут (другой ключ подписи), а
  `MANAGE_EXTERNAL_STORAGE`, который просит `Loader.requestPermissions()`,
  Google Play не пропускает — то есть распространяться через магазин она не может.
