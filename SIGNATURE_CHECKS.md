# Где проверяются ключи и подписи

Разбор по вопросу «где проверяется ключ». Проверок несколько и они про разное:
подпись **самого APK** не проверяется вообще, зато подписан контент (настройки,
кэш флагов, OTA-патчи, ассеты), и есть аппаратная аттестация. Ниже — точные
файлы, символы и что можно проверить руками.

## Сводка

| что проверяется | где | чем | последствия подмены |
|---|---|---|---|
| подпись APK `com.roblox.client` | **нигде** | — | не детектируется (эта сборка подписана ключом «Gloop») |
| подпись чужого пакета `com.android.vending` | 4 копии `PhoneskyVerificationUtils` | SHA-256 сертификата, зашит строкой | не влияет на запуск |
| доступ к конфигу ядра (`content://`) | `ShellConfigurationContentProvider` | `protectionLevel=signature` | чужое приложение не прочитает конфиг |
| подпись клиентских настроек (`/v2/settings`) | `libroblox.so` ← `startup/b.java` | Ed25519 (`X-Signature-Ed25519`) | настройки/флаги не применятся |
| подпись файла кэша флагов | `libroblox.so` | подпись в `flag_cache_vb.dat` | кэш отбрасывается |
| подпись OTA-патча / asset-пака | `libroblox.so` ← `OtaConfigHandler` | нативная проверка + revocation-списки | патч не «промоутится» |
| аттестация устройства | AndroidKeyStore + `NativeQuoteInterface` | challenge + сертификат ключа | проверка на стороне сервера |

## 1. Подпись самого приложения: не проверяется

Ни одного обращения к `GET_SIGNATURES` / `GET_SIGNING_CERTIFICATES` **для своего
пакета** в коде нет. Проверка `Decompiled`: `grep -rn "GET_SIGNATURES\|signingInfo\|getApkContentsSigners"`
даёт только библиотечные места:

* `com/appsflyer/sdk_base/util/AndroidExtensionsKt.java` — Appsflyer собирает хэш своей подписи для аналитики;
* `androidx/emoji2`, `google/mlkit` — служебные проверки чужих пакетов;
* `deobf/com/google/android/gms/ob/ff.java:534` — GMS ищет в чужом пакете отладочный сертификат `CN=Android Debug`.

**Вывод:** подмена ключа (как в этой сборке — `O=Gloop, CN=Gloopiest Man`) на
стороне клиента ничем не детектируется. Но её видят Google Play Services,
Google Sign-In и Billing — они сверяют подпись вызывающего приложения у себя,
поэтому на переподписанной сборке ломаются вход через Google и покупки.

### Единственное место, где подпись реально работает

`com/roblox/client/provider/ShellConfigurationContentProvider.java` — exported
content provider `content://com.roblox.client.ShellConfigurationProvider`,
защищён разрешением:

```xml
<permission android:name="com.roblox.client.permission.CONFIGURATION"
            android:protectionLevel="0x00000002"/>   <!-- signature -->
```

`protectionLevel=2` = доступ только приложениям, подписанным **тем же ключом**.
Внутри провайдера ещё и проверка имени вызывающего
(`ShellConfigurationContentProvider.a()`):

```java
return callingPackage.startsWith("com.roblox.client")
    || callingPackage.startsWith("com.tencent.roblox");
```

Через этот провайдер `deobf/com/roblox/client/provider/ph/d.java` читает:
`channel_param`, `base_url_param`, `settings_param`, `user_agent_param`,
`dev_rpc_ip_port_override`, `dev_branch`, `dev_commit`, `browser_tracker_id`.
То есть **подпись ключа here — это замок на конфиг окружения** (канал, базовый
URL, RPC-оверрайд), а не защита APK.

## 2. Подпись клиентских настроек: Ed25519, проверка в нативном коде

`com/roblox/client/startup/b.java`:

```java
// b.java:282 и :289
c0155b = new C0155b(c(m10), m10.m("X-Signature-Ed25519", ""));
```

Дальше `deobf/com/roblox/client/ei/f.java:174`:

```java
return h.a().e6()
    ? Integer.valueOf(NativeGLInterface.nativeInitClientSettingsSigned(d10, e10, o10, a1.M()))
    : Integer.valueOf(NativeGLInterface.nativeInitClientSettings(d10, o10, a1.M()));
```

`d10` — JSON (`applicationSettings`), `e10` — подпись из заголовка,
`o10` — оверрайды, `a1.M()` = `"GoogleAndroidApp"`.

Проверка целиком в C++: **символ экспортирован**, его видно в таблице
динамических символов:

```
Java_com_roblox_engine_jni_NativeGLInterface_nativeInitClientSettingsSigned
Java_com_roblox_engine_jni_NativeGLInterface_nativeInitClientSettings
```

В строках библиотеки подтверждение и алгоритм:

```
'X-Signature-Ed25519'
'SigEd25519 no Ed25519 collisions'     ← строка из BoringSSL/OpenSSL (Ed25519)
'[DFLog::FlagCache] {} Signature validated'
```

Публичный ключ в формате DER SPKI (`30 2a 30 05 06 03 2b 65 70 03 21 00`)
в бинарнике **не найден** (0 вхождений) — значит ключ лежит либо сырыми 32
байтами в `.data`, либо разбирается в коде. Найти его можно так: символ
экспортирован, ставим точку останова и смотрим, что передаётся в
`EVP_DigestVerify*`:

```bash
nm -D --defined-only libroblox.so | grep nativeInitClientSettingsSigned
# затем в Ghidra/IDA: xref от этой функции -> поиск 32-байтной константы рядом с вызовом verify
```

## 3. Кэш флагов подписан на диске

Файл `flag_cache_vb.dat` (путь в `com/roblox/client/startup/FlagCacheUtils.java`)
хранит не только JSON, но и подпись — в нативном коде это видно по строкам:

```
'[DFLog::FlagCache] {} writeFlagCache: Failed to write signature size to file: {}'
'[DFLog::FlagCache] {} Failed to read signature from file: {}, expected size: {}, read size: {}'
'[DFLog::FlagCache] {} Signature validated'
```

Плюс флаги `PassFlagSignatureToEngine` и поле `SerializedClientFieldsSignature`.
То есть подменить кэш руками нельзя: при чтении размер и подпись сверяются,
несовпадение → кэш отбрасывается и флаги тянутся заново по сети.

## 4. OTA-патчи и контент: проверка только в C++

`com/roblox/client/scheduledwork/OtaConfigHandler.java:283`:

```java
public static native boolean nativeVerifyAndPromoteBlob(
        String blobPath, long assetId, long assetVersion, String behaviorName);
```

Вызов — `OtaConfigHandler.java:151`, затем `nativeCommitOtaConfig(...)`.
Java **не проверяет ничего**: решает нативная функция.

Что именно проверяется — видно по строкам `libroblox.so`:

```
'[FLog::DataModelPatchConfigurer] Signature verification failed with error: {}'
'[FLog::DataModelPatcher] Post-TTI: ABORT - signature verification failed'
'[FLog::PreloadedCacheVerifier] Preload signature verification failed'
'Signature verification failed for asset loaded with bytecode'
'JoinTicketV2_SignatureInvalid'
'Asset signature failure.'
'ClientSignatureAlgorithms'      'invalid signature size'
'InvalidRevokedSignatureTypes'   'SignatureValidationFailureTelemetry'
```

Списки отзыва ключей/алгоритмов приходят флагами
(`deobf/unlinked/ci/a.java:1724`):

```java
new a.g("DataModelPatcherRevokedPublicKeyIds", "", false);
new a.g("DataModelPatcherRevokedSignatureTypes", "", false);
```

То есть у Roblox схема «ключ + список отозванных ключей, приходит с сервера» —
скомпрометированный ключ отзывается, не требуя обновления приложения.

## 5. Аттестация устройства: ключ генерируется в AndroidKeyStore

`com/roblox/engine/jni/NativeQuoteInterface.java` — не проверка подписи APK, а
доказательство «это настоящий девайс»:

```java
public static byte[] requestResponse(byte[] bArr) throws Exception {
    if (bArr.length != 32) throw new IOException("challenge length is wrong");
    KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore");
    keyStore.load(null);
    if (keyStore.containsAlias("rbx_keystore")) keyStore.deleteEntry("rbx_keystore");
    // ключ на кривой secp256r1, с attestation challenge
    a(b("rbx_keystore", 12, bArr, true).build());   // true = StrongBox, если есть
    return requestResponseContinue(bArr);          // ← native
}
```

* ключ `rbx_keystore` создаётся заново на каждый запрос (старый удаляется);
* `setAttestationChallenge(bArr)` — 32-байтный challenge от сервера;
* `setIsStrongBoxBacked(true)` на Android 9+ — аппаратный модуль;
* если StrongBox недоступен — `IOException` возвращается в виде
  `[0x01][0x00][текст ошибки]`, и код повторяет без StrongBox;
* сертификат цепочки проверяет **сервер**, не приложение.

Рядом — Play Integrity через JNI
(`com/roblox/universalapp/account/JNIAccountProtocol.java`):

```java
public static native String getGetIntegrityTokenMethodName();
public static native String getDeviceIntegrityAvailableMethodName();
```

и `NativeMetaInterface.getDeviceAttestationToken(String, DeviceAttestationCallback)`
(`com/roblox/engine/jni/meta/`). Все три — экспортированные JNI-функции в
`libroblox.so`.

## 6. Что ещё «ключевого» лежит в бинарнике (это не ключ приложения)

* 4 PEM `BEGIN PUBLIC KEY` (RSA-2048) — три уникальных (sha256: `92c1b286…`,
  `47c29264…`, `95bd4719…`), вероятно для пиннинга/подписи служебных ответов;
* ~150 встроенных CA-сертификатов (`BEGIN CERTIFICATE`) — trust store нативного
  TLS-стека, не имеет отношения к подписи APK;
* `assets/ssl/cacert.pem` в APK — тот же набор для Java/OkHttp-слоя.

## 7. У прослойки «дельта» ключей нет

`com/roblox/gloop/Loader.java` не содержит ни проверки подписи, ни хэшей:
единственный «удалённый» параметр — `getDownloadUrl()`. То есть подлинность
своего контента прослойка не проверяет вообще (проверять нечего — нативной
части в APK нет, см. `LAUNCH_CHAIN.md`).

## Проверить руками

```bash
APK=Delta-2.747.1486.apk

# 1) подпись APK (кто и когда)
unzip -p $APK META-INF/KEY.RSA | openssl pkcs7 -inform DER -print_certs -noout

# 2) есть ли проверка своей подписи в коде
grep -rn "GET_SIGNATURES\|GET_SIGNING_CERTIFICATES" 02_sources/java | grep -i roblox

# 3) хэши Play Store в утилитах
grep -rn "8P1sW0EPJcslw7UzRsiXL64w" 02_sources/java/deobf/unlinked

# 4) экспортированные JNI-функции, отвечающие за подпись/флаги
nm -D --defined-only libroblox.so \
  | grep -E "InitClientSettings|VerifyAndPromote|FlagJni|Attestation"

# 5) строки про проверку подписи
strings -n 12 libroblox.so | grep -iE "signature (verification|invalid)|Signature validated|Revoked"

# 6) подпись настроек в рантайме
adb logcat | grep -E "ClientSettingsRequest|FlagCache|X-Signature"
```

## Итог

1. **Ключ подписи APK не проверяется нигде** — переподпись проходит незамеченной
   для кода приложения.
2. Единственный функциональный замок на ключ — `protectionLevel=signature`
   у провайдера конфига (канал, базовый URL, dev-RPC).
3. Настоящая криптография — **не про APK**: Ed25519 на клиентские настройки,
   подпись файла кэша флагов, подпись OTA-патчей и ассетов с серверным списком
   отозванных ключей, плюс аппаратная аттестация (KeyStore/StrongBox) и
   Play Integrity.
4. Все эти проверки живут в `libroblox.so`; Java только передаёт байты.
   Символы экспортированы, поэтому точки для отладки известны:
   `nativeInitClientSettingsSigned`, `nativeVerifyAndPromoteBlob`,
   `FlagJniInterface_*`, `NativeQuoteInterface_requestResponseContinue`.
