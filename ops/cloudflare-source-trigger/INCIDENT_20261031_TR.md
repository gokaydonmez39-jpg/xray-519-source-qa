# XRAY-519 public Cloudflare Cron arızası — 31 Ekim 2026

## Kanıt ve kök neden
- Cloudflare Observability'de `xray-519-source-qa`, sürüm `747e12ad-08a5-43d5-9add-82565a41438f` için UTC 16:01 Cron event görüldü.
- `XRAY_PUBLIC_DISPATCH` kararı `GITHUB_NETWORK_OR_RESPONSE_UNKNOWN`, stamp `20261031T1600Z`; bir önceki epoch kilidi `RESERVED`. Tek başına bu kod, canlı GitHub POST kabulü kanıtı değildir.
- PR #13'ün SQLite `INSERT ... RETURNING` rezervasyonundan sonra GitHub istemcisinde `redirect: 'error'` vardı.
- Cloudflare'ın resmî Request dokümantasyonuna göre Workers bu redirect modunu desteklemez; istek gönderilmeden `TypeError` oluşur: https://developers.cloudflare.com/workers/runtime-apis/request/
- Bu PR `manual` kullanır. 3xx HTTP durumları otomatik yönlendirme veya tekrar gönderim olmadan fail-closed kalır.
- Cloudflare gerçek script adı `xray-519-source-qa`; eski Wrangler adı `xray-519-public-source-trigger` ile farklıydı. PR, yapılandırmayı canlı script adıyla eşleştirir. Değişiklik yeni Worker oluşturmak için değildir.

## Test kanıtı (production değildir)
- Red: GitHub Actions 41220593788, eski Fetch ayarı üzerinde regresyon testi FAIL.
- Green: 41220674575, Fetch düzeltmesinden sonra PASS.
- İkinci red: 41220857831, eski Wrangler adı üzerinde isim eşleştirme testi FAIL.
- Son kabul için yeni green CI ve repo/main güncel durumunu PR #15 üzerinden doğrula. `node --test ops/cloudflare-source-trigger/*.test.mjs` ve `node --check` çalıştırılmalı.
- Hiçbir test Cloudflare'a canlı dispatch çağırmaz veya private ücretli run başlatmaz.

## Üretim geçiş kapıları (hepsi ayrı)
1. PR #15 ve ilgili GitHub CI gözden geçirilir. **Merge ve canlı deploy için ayrı kullanıcı onayı** gerekir. Başlangıç referansı `main=92f0d2eb83a0308b2f129089045287478837b904` korunur.
2. Cloudflare **mevcut** `xray-519-source-qa` Worker hedefini, `ops/cloudflare-source-trigger` kaynak dizinini, `wrangler.jsonc` ismini, Free planı ve mevcut DO/secret binding'lerini doğrula. Başka Worker/secret/plan oluşturma. Git bağlantısının otomatik deploy edip etmediğini doğrulamadan merge sonrası yayına çıktığını varsayma.
3. Dağıtımda yeni sürüm kimliği ve Cron `1 * * * *` kaydedilir. Eski `RESERVED` SQLite satırları **silinmez/sıfırlanmaz/yeniden denenmez**.
4. **Gelecekteki yeni UTC :01 epoch** için `XRAY_PUBLIC_DISPATCH` kararı doğrulanır. `DISPATCH_ACCEPTED_NOT_SOURCE_PASS` yalnız kabul aşamasıdır; run başarısı değildir. Mevcut receipt veya aktif run nedeniyle güvenli engelleme de ayrı raporlanır.
5. Ayrı GitHub `workflow_dispatch` run ID, branch `main`, `max_markets=519`, `completed/success`, aynı epoch 519 kaynak receipt + bridge, gzip/SHA256 uzaktan geri okuması kontrol edilir. Native GitHub `schedule :04` run'ı, Cloudflare dispatch yerine sayılamaz.
6. 519 piyasa kimliği, teknik PASS/WARMUP/FAIL, taze kapanmış 1H/4H/1D, <=1700 istek, <=720 s ve 15 dakikalık private tazelik kapısı ayrı ölçülür. WARMUP, AL sinyali değildir.
7. Private P30/CORE-18, özel AL/STOP/2R, WSS ve iPhone bildirimi ayrı HOLD kapılarıdır. Maliyet izni ve hesabın gerçek $0 kanıtı olmadan private çalıştırma yok. Önceden tanımlanan 48 ardışık saat kabul eşiği değiştirilmez.

## Risk, alternatif ve geri alma
- GitHub 401/403, limit/timeout, Cron gecikmesi, native :04 çakışması, eksik receipt, yetersiz geçmiş ve farklı Cloudflare Build root ayrı olası engellerdir. Bunlar üretim kanıtıyla elenir; varsayım üzerinden yeni bypass yazılmaz.
- Mevcut tekil kilit ve GitHub kaynak preflight korunur. 3xx/429/5xx veya belirsiz yanıt otomatik yeniden deneme yetkisi vermez.
- Yeni sürümde beklenmedik durum varsa **Cloudflare Cron trigger'ını devre dışı bırak** ve public GitHub native schedule'ı bağımsız incele. Kilit silme veya eski hatalı kodu otomatik tekrar dağıtma.
- NASDAQ, private strateji, emir, ücretli run ve hesap kimlik bilgileri kapsam dışıdır. `FINAL START = HOLD` ancak bütün kabul koşulları gerçek kanıtla sağlanınca değişir.
