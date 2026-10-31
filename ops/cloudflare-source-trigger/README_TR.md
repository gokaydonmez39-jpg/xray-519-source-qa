# XRAY-519 — Cloudflare Free kaynak tetikleyicisi (STAGED, henüz DEPLOY edilmedi)

Bu dosyalar **mevcut public** `gokaydonmez39-jpg/xray-519-source-qa` deposunun içindedir; yeni kripto stratejisi, yeni private depo veya broker bağlantısı oluşturmaz.

## Neden?

GitHub'ın yerel `cron: '4 * * * *'` saati 2026-10-31 00:22 ve 06:37 UTC'de başladı; 15 dakikalık private araştırma tazelik kapısına yetişemedi. Cloudflare Workers Free üzerinde UTC `:01`'de saat başından sonra public workflow `workflow_dispatch` çağrısı hedefleniyor. GitHub Actions'ın runner kuyruğu ve Cloudflare Cron kesin zaman garantili değildir. Bu çözüm gecikme riskini azaltır, garanti etmez.

## Kaynak ve güvenlik

- Worker: `worker.mjs`, test edilebilir durum motoru `dispatch-core.mjs`, `wrangler.jsonc`.
- `1 * * * *`: UTC saat başından bir dakika sonra çalış.
- `SourceDispatchLock` SQLite Durable Object `INSERT OR IGNORE` ile **her saat yalnız bir kez** dispatch rezervasyonu yapar. Ağ hatası, belirsiz GitHub yanıtı ve diğer hatalarda rezervasyon korunur; otomatik tekrar yoktur. Manuel inceleme gerekir.
- İşlem öncesinde aynı saat `receipts/YYYY/MM/DD/YYYYMMDDTHH00Z-n519.json.gz` ve public GitHub Actions run listesi okunur. Mevcut kaynak makbuzu, aynı saat run'ı, önceki aktif source işi veya API belirsizliği varsa **HOLD**.
- Tetikleme sonrası `DISPATCH_ACCEPTED_NOT_SOURCE_PASS` yalnız GitHub isteğinin kabulü demektir; source PASS, özel P30, AL sinyali veya 7/24 başarı değildir.
- UTC :01 cron gerçek çalışmaya 90 saniyeden fazla gecikirse aynı saate ait source dispatch **yasak**. Bu, tazelik kuralını korumak içindir.
- REST çağrısı yalnız **public** GitHub reposunda `hourly-519-public-source.yml` ve `max_markets=519` ile yapılır. Cloudflare'ın `fetch()` HTTP arayüzü 404; public Web endpoint ile iş başlatılamaz.
- GitHub PAT'ini **kaynak koduna, GitHub Issues'a, sohbetlere veya düz metin dosyalarına koyma**. Cloudflare üzerinde Worker `GITHUB_ACTIONS_DISPATCH_TOKEN` secret olarak sakla. Fine-grained PAT yalnız public `xray-519-source-qa` reposu için Actions: write olmalı. Belli süre sonra token yenile. Private repo erişimi verme.
- `workers_dev:false` = dış HTTP endpoint yok. Sadece Cron ve sınırlı içeride Durable Object çağrısı.
- Worker kaynak ve strateji hesaplamaz, piyasa emri, STOP, 2R veya NASDAQ sistemlerine dokunmaz.

## Dağıtım kapısı (Work Cloud Browser / Cloudflare hesap oturumu gerekli)

1. Cloudflare hesabının **Workers Free** planında kaldığını, ücretli kaynak tanımı olmadığını gerçek hesap ekranından doğrula. Free sınırı aşımı fail/limit olmalı; asla Paid plan açma.
2. GitHub public repo'ya dar kapsamlı Actions:write fine-grained token oluştur; token'ı kimseyle paylaşmadan Cloudflare Worker Secret `GITHUB_ACTIONS_DISPATCH_TOKEN` olarak gir. Bu sohbet veya GitHub kodunu secret deposu olarak kullanma.
3. Var olan **bu repo** altındaki `ops/cloudflare-source-trigger` klasörünü Worker kaynak kökü olarak bağla; `wrangler.jsonc` ile deploy et. Cloudflare Workers > Cron Events/Logs üzerinden ilk UTC :01 olayı ve `XRAY_PUBLIC_DISPATCH` kararını doğrula.
4. GitHub'da yeni run id'nin `workflow_dispatch` olduğunu, 519 spot kaynak taramasını, gerçek saatli receipt + bridge, uzak SHA256, GitHub sonuç `completed/success` kayıtlarını denetle. `DISPATCH_ACCEPTED` tek başına PASS değildir.
5. Başlangıçta GitHub native `:04` cron'u devre dışı bırakma. Worker başarılı iki saat ve tekrar yok kanıtı verirken eski cron yedek kalır; mevcut `concurrency` ve `DUPLICATE_EPOCH_NO_SCAN` ikinci taramayı fail-close engeller. Gereksiz/çakışan kuyruk kanıtlanırsa native cron'un bakımı ayrı inceleme ve geri dönüş planıyla yapılır.
6. Public kaynak güncel ve koşulları sağladıktan sonra **ayrı private P30** real AL/STOP/2R araştırması gerekir. Bu Worker private workflow dispatch yetkisi taşımaz. Private başlangıç otomatikleşmiş sayılmaz. Private maliyet ve model kabulü ayrı.
7. Önceden belirlenmiş kalıcı kabul: 48 ayrı ardışık UTC saat döneminde birer tekrarsız source sonucu, her dönemde gerçek receipt+bridge SHA ve private değerlendirme <=15dk, sıfır emir, sıfır ek ücret. Cloudflare veya GitHub süreklilik garantisi sayılmaz.

## Test ve geri alma

- Test: `node --test dispatch-core.test.mjs worker.test.mjs` (lokal ve public CI, **API çağrıları mock**).
- İptal/geri alma: Cloudflare Cron trigger'ı devre dışı bırak veya Worker'ı deploy'dan kaldır; public GitHub veri motoru olduğu gibi kalır. GitHub PAT'i revoke et. Şifreyi log'a yazma.
- Bilinen engeller: Bu repo üzerinden Cloudflare hesabına giriş/deploy gerçekleştirilmedi. Wrangler gerçek Cloudflare ortamı test edilmedi. Token/canlı dispatch/sağlık makbuzu/private P30/WSS/APNs ACK **henüz PASS değildir**.
- İki veri hattı aynı değildir: 519 public source QA yalnız kaynak doğrulamasıdır; CORE-18 Google Sheets ve özel 519 P30 AL sinyali birbirinin yerine kabul edilemez.

Resmî API ve limit kaynakları: https://developers.cloudflare.com/workers/configuration/cron-triggers/ ; https://developers.cloudflare.com/durable-objects/platform/pricing/ ; https://docs.github.com/en/rest/actions/workflows
