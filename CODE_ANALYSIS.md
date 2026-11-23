# Разбор клиента Delta-2.747.1486 (Roblox Android)

Разбор по архиву `Delta-2.747.1486_FULL_READABLE.zip`. Всё ниже — из кода, а не из
общих слов: в каждом разделе указан файл, который можно открыть.

## 1. Что это за сборка

| | |
|---|---|
| пакет | `com.roblox.client` |
| версия | 2.747.1486 (versionCode 21686) |
| sdk | min 26 (Android 8.0), target 35 (Android 15), compile 36 |
| ABI | только `arm64-v8a` (8 `.so`, все ELF64 AArch64) |
| каналы | `NativeShell_googleProdRelease` / `universalapp_googleProdRelease` |
| подпись | `debuggable` не выставлен, `allowBackup=true` |

Это обычный продакшн-клиент из Google Play, а не кастомная сборка: имена
менялись только обфускатором (R8), инфраструктура Roblox на месте.

## 2. Как поднимается приложение

Цепочка ровно такая (`02_sources/java/com/roblox/client/`):

```
AndroidManifest
 └─ LauncherAlias*  →  ActivitySplash        (2 штуки: Main / Classic / Halloween2026)
      └─ MainGameActivity                     (@Keep, exported=false)
           └─ NativeHelper                    (мост «Java → движок»)
                └─ libroblox.so               (System.loadLibrary, JNI)
```

`RobloxApplication` (`RobloxApplication.java`) — `Application`, в конструкторе
поднимает три синглтона (`startup.ik.x`), в `onCreate` инициализирует Appsflyer,
WorkManager, крэш-репортинг (Backtrace/Crashpad).

`NativeHelper` — самый интересный класс: 100+ методов вида
`gameActivity_onEngineInitialized`, `gameActivity_onDidLogInReceived`,
`gameActivity_showKeyboard`, `gameActivity_onScreenOrientationChanged`. Это
не «флаги», а **колбэки из C++ в Java** — движок зовёт их через JNI, когда
происходит событие в Lua-приложении. Список этих методов = карта того, что
движок умеет сообщать оболочке.

## 3. Сетевой слой: всё настраивается извне

`02_sources/java/deobf/com/roblox/client/bh/a1.java` — конфиг окружения:

```java
static { K0("www.roblox.com"); }              // базовый домен
public static String c()  { return "https://clientsettingscdn." + P(); }
public static String h()  { return "https://api." + P(); }
public static String i()  { return "https://auth." + P(); }
public static String D0() { return "https://ecsv2." + P() + "mobile/pbe"; }
```

`P()` = `b.b()` = базовый домен с заменой `www.` → `apis.`. Дальше — три
независимых способа переопределить окружение, и все три **читаются из
системных настроек, а не из кода**:

1. `Settings.Global.getString(cr, "roblox_channel_override")` — канал
   (`Production`, `Beta`, …) через `adb shell settings put global`.
2. `SharedPreferences.configure_dev_roblox → "BaseApiUrl"` — подмена базового URL.
3. `JNIBaseUrlSetter.setBaseUrl(str)` — `@Keep`-точка входа, движок может
   переставить URL на ходу (`a1.K0`).

Именно поэтому на GitHub гуляют «разблокированные» сборки Roblox: ломать
ничего не надо, достаточно вызвать `setBaseUrl`/прописать настройку — клиент
сам пойдёт на другой хост. Никакого сертификат-пиннинга в Java-слое для
`*.roblox.com` нет: `CertificatePinner` встречается только в Persona SDK
(`deobf/com/withpersona/sdk2/inquiry/mv/*`).

## 4. Что клиент реально отправляет на сервер

`com.roblox.platform.http.interfaces/*` — 16 интерфейсов API. Пути лежат
строками, например:

```
/v2/push-notifications/register-android-native
/v2/stream-notifications/unread-count
/platform-chat-api/v1/send-messages
/v1/platforms/android/purchases
/v2/verified-signup/challenge
/v1/users/avatar-headshot
```

Плюс счётчики: `https://ephemeralcounters.api.<domain>v1.1/Counters/Increment/?apiKey=76E5A40C-…`
(ключ лежит прямо в коде, это публичный клиентский счётчик Roblox).

## 5. Безопасность: что есть на самом деле

| проверка | где | что делает |
|---|---|---|
| root | `deobf/com/roblox/client/bh/u.java` | `Build.TAGS` содержит `test-keys`, либо существует один из 10 путей `/system/bin/su`, `/sbin/su`, `/system/xbin/su`, … |
| архитектура | там же | `NativeSettingsInterface.getRunningArchitecture()` → ARM64/X86_64 |
| Play Integrity | `com.google.android.play.core.integrity.*` | подключён, но в `com.roblox` коде не вызывается напрямую — работает через движок/SDK |
| anti-fraud | `com.appsflyer.internal.AFf1iSDK` | ищет строку `frida` в карте памяти (это Appsflyer, не Roblox) |
| биометрия | манифест | `USE_BIOMETRIC`, `USE_FINGERPRINT`, `assume_strong_biometrics_models` |
| скриншоты | манифест | `DETECT_SCREEN_CAPTURE` (Android 14+) |

Важно: **root-детект ничего не блокирует.** `u.g().h()` встречается всего в двух
местах — `purchase/nj/n.java` и `purchase/dj/g.java`, и оба просто пишут
`"Rooted": true` в телеметрию покупки. То есть клиент на рутованном устройстве
запускается и работает, а факт рута уходит в аналитику. Это не «защита», а
метрика.

## 6. JNI: где кончается Java

549 объявлений `native` в `com.roblox.*`. Всё остальное — в `libroblox.so`
(103 МБ, stripped ELF). Карта мостов:

```
com/roblox/engine/jni/
├── NativeGLInterface / NativeGLJavaInterface     — рендер, SurfaceView, GL-контекст
├── NativeInputInterface                          — тапы, пан, пинч, геймпад, гироскоп
├── NativeSettingsInterface                       — флаги, архитектура, конфиг
├── NativeAppBridgeInterface                      — жизненный цикл приложения
├── NativeVideoInterface / video/*                — MediaCodec, WebRTC-видео
├── memstorage/*                                  — быстрая память Java↔C++
├── reporter/*, locale/*, meta/*, user/*          — телеметрия, локаль, аттестация
└── autovalue/*                                   — 20 неизменяемых параметров (StartGameParams…)
```

Плюс `com/roblox/protocols/` — 23 «платформенных интерфейса»
(`designfoundations`, `calling`, `filepicker`, `nativeads`, `systemdialog`,
`webview`, `connectivityv2`, …). Это модульная шина: движок просит
«покажи системный диалог» или «дай файл», а Java-сторона реализует.

## 7. Фичи, которые видно прямо в манифесте

- **Deep links**: `roblox://`, `robloxmobile://`, `robloxglobal://`,
  `https://www.roblox.com/{games,join,share,catalog,bundles,communities}/…`,
  `https://ro.blox.com/Ebh5` (реферальные ссылки).
- **Три иконки-алиаса**: `LauncherAliasMain`, `LauncherAliasClassic`,
  `LauncherAliasHalloween2026` — сезонная смена иконки, переключается кодом.
- **Виджет** «Недавно играл»: `RecentlyPlayedWidgetProvider` (exported).
- **SMS-автозаполнение**: `SMSBroadcastReceiver` на
  `com.google.android.gms.auth.api.phone.SMS_RETRIEVED` (SMS Retriever API,
  читает только одноразовый код, не переписку).
- **Звонки**: `IncomingCallActivity`, `CallActionReceiver`, `RealtimeService`.
- **Камера + ML Kit**: баркоды и текст (`mlkit_vision_barcode`, `mlkit_vision_text`),
  это сканер QR для входа.
- **Реклама**: 4 активити/сервиса `gmasdk.*` в изолированном sandbox-процессе.
- **Persona**: верификация личности (`com.withpersona.sdk2.inquiry`),
  отдельный `PersonaInitProvider` и свой `resources`-пакет `0x87`.

## 8. Ассеты: что лежит рядом с движком

`04_assets/` (605 файлов, 88 МБ):

- `ExtraContent/models/*.rbxm` — 28 МБ готовых 3D-моделей интерфейса
  (универсальное приложение, контекстное меню аватара, редактор аксессуаров);
- `shaders/shaders_vulkan_mobile.pack`, `shaders_glsles3.pack` — 22 МБ
  предкомпилированных шейдеров (Vulkan и GLES3);
- `content/guac/defaultConfigs/GuacDefaultPolicy-*.json` — **feature-политики по
  регионам** (`GlobalDist`, `CJVDist`, `VNGGamesDist`): включают/выключают чат,
  поиск, рекомендации. Это то, чем Roblox различает рынки;
- `gloop/dlt.zip` — внутренние иконки UI-оверлея (`dlt` = debug/loading toolkit),
  внутри `Info.png`, `Wifi.png`, `Battery.png`, `Controller.png`;
- `ssl/cacert.pem` — корневые сертификаты для нативного стека;
- `android/shared_compression_dictionaries/*.dict` — словари zstd-сжатия;
- `fonts/`, `content/textures/`, `content/sky/` — шрифты и окружение.

## 9. Что было обфусцировано и как это восстановлено

843 пакета вида `ob`, `fb`, `n0`, `qr`. Имена у них не несут смысла, но
привязка восстанавливается по импортам: если `com.roblox.client.startup`
импортирует `bh.m0`, а `bh` больше никто не трогает — это его код. В архиве
такие пакеты лежат в `deobf/<владелец>/<пакет>/`, поэтому структура читается:

```
deobf/com/roblox/client/bh/       — оболочка: активити, конфиг, покупки
deobf/com/roblox/client/startup/  — запуск движка, колбэки
deobf/com/withpersona/sdk2/       — Persona SDK
deobf/com/google/android/gms/     — GMS
deobf/unlinked/                    — 383 пакета, которые никто не импортирует
```

383 «бесхозных» пакета — это либо reflection-код, либо мёртвый код после R8,
либо точки входа, которые вызывает только движок. Если нужно — можно пройти
по `07_dex/classes_without_java_source.csv` и доснять их smali.

## С чего начинать чтение

1. `RobloxApplication.java` → `MainGameActivity.java` → `NativeHelper.java` —
   весь путь запуска.
2. `deobf/com/roblox/client/bh/a1.java` — все URL и переключение окружения.
3. `com/roblox/engine/jni/` — граница Java/C++.
4. `com/roblox/universalapp/cookie/CookieProtocol.java` — как куки ходят
   между WebView и движком.
5. `com/roblox/client/flags/FlagJniInterface.java` — FFlag/FInt строки
   (в Java их всего 14, остальные ~тысячи живут в нативном слое).
