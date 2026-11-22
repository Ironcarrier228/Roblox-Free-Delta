# Движок: как Java-оболочка поднимает Roblox

Разбор `libroblox.so` изнутри наружу — по тому, что вызывает и принимает Java.
Все пути ниже — из `02_sources/java/` архива.

## 1. Кто кого грузит

```java
// com/roblox/client/startup/a.java:61
public static String f9359d = "roblox";              // имя библиотеки
...
// a.java:532 — внутри t(), под synchronized
System.loadLibrary(f9359d);                          // -> libroblox.so
```

Никакого `System.load` по абсолютному пути и никакого `dlopen` из кода —
только `loadLibrary("roblox")`. Перед загрузкой:

```java
a.D();   // tuneMimalloc(): env-переменные для аллокатора
```

`D()` — единственное место, где Java настраивает нативный аллокатор **до**
загрузки библиотеки, через `Os.setenv`:

| переменная | условие |
|---|---|
| `MIMALLOC_RESERVE_OS_MEMORY` = `<N>M` | только 32-бит, N из флага (512/768/1024 МБ) |
| `MIMALLOC_DISALLOW_OS_ALLOC` / `MIMALLOC_LIMIT_OS_ALLOC` = `1` | `a10.X3()` |
| `MIMALLOC_EAGER_COMMIT` = `0` | `a10.k2()` |
| `MIMALLOC_ARENA_EAGER_COMMIT` = `0` | `a10.o3()` |

Затем `WebRtcLoader.initialize(...)`, если `k.b()` и есть путь к
`librobloxwebrtc.so` — WebRTC в этот APK не входит, он приходит модулем.

### Подгрузка нативных библиотек «по требованию»

`deobf/com/roblox/client/ai/b.java` — резолвер имён:

```java
ClassLoader cl = context.getClassLoader();
if (!(cl instanceof BaseDexClassLoader)) { /* telemetry: classloader_not_bdcl */ }
String path = ((BaseDexClassLoader) cl).findLibrary(libName);   // "robloxwebrtc"
if (path == null) { /* telemetry: findlibrary_null + abis/nativeLibDir/splitSourceDirs */ }
```

То есть библиотеки ищутся **только** через стандартный `findLibrary` в
`nativeLibraryDir` (или split-APK). Если библиотеку не нашли, напишут событие
`native_lib_resolve_path_failed` с полями `lib_name`, `reason`, `detail`,
`abis=…;nativeLibDir=…;splitSourceDirs=…`.

Практический вывод для любой пересборки APK: `libroblox.so` должен лежать
ровно в `lib/arm64-v8a/`, иначе оболочка дойдёт до `nativeGameGlobalInit()`
и упадёт с `UnsatisfiedLinkError` (обрабатывается в `a.t()` — просто пишется
в лог `AndroidAppSettings`). Никаких путей в обход `findLibrary` в коде нет.

## 2. Порядок инициализации (точный)

`deobf/com/roblox/client/ei/f.java` — это AppShell-менеджер. Его `F(Context)`:

```
a1.W0()                                  // настройки окружения -> движок
FMOD.init(context)                       // звук (org.fmod)
NativeGLInterface.nativeGameGlobalInit() // ГЛАВНЫЙ вход в движок
a1.V0()
NativeGLInterface.nativeUpdateAdapterInit()
```

Дальше два независимых потока:

**(а) Клиентские настройки** — `AsyncTaskC0263f.doInBackground()`:

```java
b.C0155b u8 = a.u();                      // закешированный ответ /v2/settings
String d10 = u8.d();                      // тело (JSON)
String e10 = u8.e();                      // заголовок X-Signature-Ed25519
...
if (h.a().e6())
    NativeGLInterface.nativeInitClientSettingsSigned(d10, e10, o10, a1.M());
else
    NativeGLInterface.nativeInitClientSettings(d10, o10, a1.M());
```

`a1.M()` = `"GoogleAndroidApp"` — имя приложения в терминах Roblox.

**(б) Старт приложения** — `G(Surface)`:

```java
StartAppParams.a h10 = StartAppParams.builder()
    .i(surface)            // SurfaceView
    .g(i10.b)              // PlatformParams
    .b(i10.d) .c(i10.e)    // строки окружения
    .d(i10.f) .e(i10.g)
    .j(i10.h) .f(i10.i) .h(i10.j);
NativeGLInterface.nativeAppBridgeV2StartAppWithParams(h10.a());
```

Вход в игру — `deobf/com/roblox/client/ei/j0.java:123`:

```java
NativeGLInterface.nativeAppBridgeV2StartGameWithParam(u8.b());   // StartGameParams
```

## 3. Что Java передаёт в C++

Четыре неизменяемых пакета параметров (`com/roblox/engine/jni/autovalue/`).
`StartGameParams` — весь контекст запуска игры:

| группа | поля |
|---|---|
| игра | `gameId`, `gameIdToExclude`, `launchData`, `accessCode`, `eventId` |
| join | `joinAttemptId`, `joinAttemptOrigin`, `joinRequestType`, `gameJoinContext`, `isoContext` |
| звонок | `callId`, `conversationId` |
| устройство | `DeviceParams` (см. ниже), `PlatformParams` |
| сессия | `Surface`, `Activity` |

`PlatformParams` (`jni/model/PlatformParams.java`) — плоский `@Keep`-класс,
ровно то, что движок читает напрямую через JNI:

```java
public String assetFolderPath;      // <apk>/assets — откуда грузить контент
public float  dpiScale;
public boolean isTouchDevice, isMouseDevice, isKeyboardDevice;
public int    viewportWidthMm, viewportHeightMm;
```

Вот почему шейдеры и модели из `04_assets/` работают: `assetFolderPath` — это
путь к распакованным ассетам, движок читает их сам, без Java.

## 4. Обратный канал: как движок зовёт Java

`NativeGLJavaInterface` — статический фасад, у которого C++ вызывает методы
напрямую через JNI. Это **полный список** того, что движок умеет попросить:

| метод | смысл |
|---|---|
| `promptNativePurchase*` (4 варианта) | показать нативную оплату Robux |
| `showKeyboard` / `hideKeyboard` / `syncTextboxTextAndCursorPosition2` | ввод текста в TextBox |
| `saveImageToAlbum(String)` | сохранить скриншот в галерею |
| `screenOrientationChanged(int)` | сменить ориентацию |
| `getMobileAdvertisingId()` / `getWebViewUserAgent()` | запросить данные у платформы (ответ — через callback-интерфейс) |
| `openNativeOverlay(String,String)` | показать нативный оверлей |
| `onDataModelNotificationCallback(String,String)` | событие из DataModel |
| `onExtendedAnalyticsRecvCallback(byte[],int)` | аналитика из движка |
| `onAppShellReloadNeeded()` | «перезапусти оболочку» |
| `onVrSessionStateUpdate(int)` | состояние VR-сессии |

Плюс `setDeviceStaticParams(...)` — Java отдаёт движку статические параметры
устройства один раз при старте.

`EngineJavaCallback2` — базовый класс на 40+ пустых методов (`a(int)`,
`e(String)`, `f(String,String)`…). Приложение подменяет реализацию:

```java
// ei/f.java:236
EngineJavaCallback2 impl = new e(engineJavaCallback2);
NativeGLJavaInterface.setImplementation(impl);
```

`e` переопределяет `f(String,String)`: если первый аргумент — `"APP_READY"`,
вызывается `q(str2)`. То есть **движок и оболочка общаются строковыми
событиями**, примерно как message bus. Отсюда `com/roblox/universalapp/messagebus/`
— 23 класса с контрактами запрос/ответ для таких же обменов Lua↔Java.

## 5. Клиентские настройки подписаны (главный вывод)

`com/roblox/client/startup/b.java` — загрузчик `/v2/settings`:

```java
// b.java:244 — читается заголовок ответа
c0155b = new C0155b(c(m10), m10.m("X-Signature-Ed25519", ""));

// b.java:170 — HTTPS с ZSTD
if (x.m().H(q2.ZSTD)) { aVar.a(new ni.b()); aVar.a(new ni.a()); }
```

Схема: тело ответа + заголовок `X-Signature-Ed25519`, оба уходят в
`nativeInitClientSettingsSigned`, проверка подписи происходит **в C++**.
Метод включается флагом `bi.h.a().e6()`; флаг `PassFlagSignatureToEngine`
регулирует передачу подписи флагов движку.

Формат тела: `C0155b.a(str)` берёт из JSON только объект
`"applicationSettings"` — это и есть список флагов. Второй аргумент
(`e()`) — подпись. Третий — `a1.M()` = `"GoogleAndroidApp"`.

Фолбэк: если запрос через ZSTD-клиент не удался, `b.k()` помечает соединение
битым (`f9374a.i()`) и **повторяет запрос без сжатия**, забирая тот же
подписанный ответ (`b.java:262-270`).

Практический смысл: подменить `v2/settings` (а это 346 флагов, см. §7) просто
так нельзя — подпись Ed25519 проверяется нативным кодом, ключ внутри
`libroblox.so`. При этом сам **базовый URL** переопределяется свободно
(`BaseApiUrl`, `roblox_channel_override`, `JNIBaseUrlSetter.setBaseUrl`) — то
есть клиент пустят на чужой хост, но настройки с него он примет только
подписанные.

## 6. OTA: движок сам патчит себя в рантайме

`com/roblox/client/scheduledwork/OtaConfigHandler.java` + `OtaPollingWorker.java`
(WorkManager, периодическая задача). Работает так:

1. Воркер скачивает **blob** (патч контента) по URL из настроек поведения.
2. `nativeVerifyAndPromoteBlob(path, assetId, assetVersion, behaviorName)` —
   проверка и «повышение» версии, **в C++**.
3. Если ок — `nativeCommitOtaConfig(patchStorageKey, perUserKeyJson)`.
4. Движок сообщает обратно: `onPatchLoadedFromNative(behaviorName, assetId, assetVersion)`.
5. `nativeGetEngineVersion()` — версия движка для логов.

Флаги, которые это включают: `EnableBackgroundOtaPolling2`,
`BackgroundOtaPolling*` (интервал, WIFI-only, retry), `EnableOtaWorker*`,
`DebugSkipOtaPatchVerification` (отладочный обход проверки).
Без `libroblox.so` шаги 2 и 3 не воспроизвести — проверка и патчинг живут
только в нативном коде.

## 7. Флаги: 346 в Java, остальное в C++

`deobf/unlinked/ci/a.java` (3702 строки) — реализация `bi.i`, где каждый флаг
объявлен как

```java
new a.C0143a("FFlagAppRatingTelemetry", bool, false);
h6("FFlagAppRatingTelemetry", c0143a);
```

346 имён. Разбивка по префиксам:

| префикс | что значит | примеры |
|---|---|---|
| `FFlag…` | булев флаг | `FFlagShouldDisableAdIds`, `FFlagEnableOrderedLibRobloxPrefetch` |
| `DFFlag…` | «dynamic» булев | `DFFlagSaveMicroProfileScreenshotsInExternalStorage` |
| `FInt`/`FString` | число/строка | `GmaSdkInitTimeoutInSeconds`, `EUDSAReportBaseUrlAndroid` |
| без префикса | Android-специфичные | `UseAndroidGooglePaymentsProtocol6`, `EnableGameActivity12` |

Часть имён прямо говорит, что уже включено и что тестируется:
`EnableGameActivity12`, `EnableEdgeToEdgeMigrationAndroid`,
`EarlyPlayIntegrityWarmup`, `EnableAppAgeSignalsOnAndroid`,
`EnableRecentlyPlayedWidgetAndroidShell6`, `DebugFeatureDeliveryUseFakeManager`.

Сами значения приходят из `v2/settings` (§5) и кешируются в трёх слоях:
`AndroidAppSettingsCache` (SharedPreferences), Version-B кеш
(`FlagCacheUtils`) и нативный слой (`FlagJniInterface`:
`nativeGetFFlag/FInt/FString`, `nativeRegisterFFlag`).

## 8. Что осталось только в нативном коде

Проверять по `06_native/libroblox.so_HOW_TO_GET_IT.md`:

```bash
nm -D --defined-only libroblox.so | grep Java_com_roblox | wc -l
```

Ожидаемо ~550 методов (`Java_com_roblox_engine_jni_*`,
`Java_com_roblox_client_flags_FlagJniInterface_*`,
`Java_com_roblox_client_scheduledwork_OtaConfigHandler_native*`).
Всё, что внутри этих функций — Lua VM, рендер (Vulkan/GLES3), физика,
проверка подписи, OTA-патчинг — в Java не отражается.

## Итог одной таблицей

| слой | где | можно ли изменить |
|---|---|---|
| точка входа движка | `a.t()` → `loadLibrary("roblox")` | да, имя библиотеки — переменная `f9359d` |
| настройки аллокатора | `a.D()` через `setenv` | да, до загрузки |
| глобальная инициализация | `nativeGameGlobalInit()` | вызов один, идемпотентен по флагу `b` |
| клиентские настройки | `nativeInitClientSettingsSigned` | только подписанные Ed25519 |
| запуск приложения | `nativeAppBridgeV2StartAppWithParams` | параметры в Java, поведение в C++ |
| запуск игры | `nativeAppBridgeV2StartGameWithParam` | `StartGameParams` целиком в Java |
| события движка | `NativeGLJavaInterface.*` | Java-обработчики подменяемы |
| OTA-патчи | `OtaConfigHandler` + 3 native-метода | проверка только в C++ |
| флаги | 346 в Java / остальное в C++ | значения — из подписанного ответа |
