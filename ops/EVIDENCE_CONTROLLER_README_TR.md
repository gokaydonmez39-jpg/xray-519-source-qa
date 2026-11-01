# XRAY-519 — Otomatik Kanıt Denetleyicisi, 1 Kasım 2026
**Durum:** Public CRYPTO PR #28 geliştirme dalında, üretime henüz alınmadı. NASDAQ, private P30, gerçek emir ve alarm servisiyle karıştırılmamalı.

## Mimari ve veri akışı
1. Kaynak motoru değişmez: Cloudflare Cron UTC :01/:06, GitHub native :04/:08, 519 SPOT USDT, immutable receipt+bridge ve SQLite SourceDispatchLock.
2. Yeni **GitHub native read-only workflow** `.github/workflows/xray-519-readonly-evidence-controller.yml` iki olaydan sonra tetiklenmek üzere tasarlandı: source workflow completed ve native denetim schedule UTC :17. Best-effort GitHub schedule garantili dakikada çalışmaz.
3. `ops/evidence_collector.py` son 48 UTC epoch için mevcut public main checkout'taki iki gerçek gzip dosyasını okur, compressed SHA256, limitli gzip/JSON, 519 durum muhasebesi, published canonical receipt hash ve bridge çapraz hash, runner ID ve epoch'u kontrol eder.
4. Public GitHub Actions workflow-run metadata'sını yalnız `GET /repos/gokaydonmez39-jpg/xray-519-source-qa/actions/runs/{id}` ile okur. Workflow ID, run ID, attempt, repo, main, conclusion=success ve UTC created_at zamanını doğrular. En fazla 48 farklı run GET; 7 saniye ağ timeout; cevap gövdesi/bearer token loglanmaz.
5. Salt-okunur `ops/autonomy_acceptance.py` içindeki 48 saat kabul kapısı tetikleme doğrulaması, eşleşen gerçek kayıt, NOOP olmayan eşsiz source ve zero-order kontrollerini uygular. Hiçbir koşulda private/WSS/OOS/ACK veya FULL FINAL START ilan etmez.
6. GitHub Actions job summary ve loglara ölçülen kanıt/eşik/boş epoch diagnostikleri yazılır. GitHub Actions sadece `contents:read`, `actions:read` kullanır; checkout `persist-credentials:false`, runner `ubuntu-24.04`. Kaynak tarama, order, dispatch, merge, issue-write, Cloudflare deploy veya veri overwrite yok.
7. Bağımsız kullanıcıya bildirilen otomasyonun 52 planlı saati, rapor yeniden başlarsa erken biteceği için **100 kontrol** olacak şekilde güncellendi. Bu ChatGPT raporu GitHub kontrol servisine denk değildir; anlık durumu ayrı doğrulanmalı.

## Kritik tutarlılık/sınır
- GitHub `event=workflow_dispatch` bilgisi, talimatı kimin verdiğini tek başına kanıtlamaz. Cloudflare canlı `XRAY_PUBLIC_DISPATCH` logu veya imzalı attestation yoksa `trigger_independently_verified=false`; kabul asla sahte PASS olmaz.
- Cloudflare Workers Observability REST API resmi olarak vardır: `POST /accounts/{account_id}/workers/observability/telemetry/query`; mevcut API dökümantasyonu sorgu için `Workers Observability Write` izni listeler. Salt-okunur asgari yetki güvenle doğrulanmadan GitHub'a böyle bir API token konulmaz. Cloudflare tokenı kodda veya sohbet mesajında paylaşılmaz.
- Mevcut GH standard public runner, GitHub dökümantasyonuna göre ücretsizdir, fakat hesap/organizasyon özel ücret ve GitHub cron gecikmesi ayrıca izlenir. Ücretli runner veya storage service kurulmaz.
- Github native `schedule` NOOP run `41309984339` completed/success ama ikinci source değil. 11Z kaynak boşluğu geçerli. PR #27'nin Cloudflare build'i başarılı ama canlı `selfHeal` tedavi edildi iddiası hâlâ ayrı kanıt gerektirir.
- Yeniden deneme yalnız halihazırdaki sınırlı Worker :06 CAS / 502/503/504 GET yoluna aittir. Denetleyici hiçbir hatada `POST /dispatches`, SQLite delete veya geçmiş kaynak backfill yapmaz.

## Bilimsel/test güvence
- Newton/Popper: eksik veya sahte olaylarda kabul reddedilir; pozitif/negatif UTC sınırları sabittir.
- Euler/Gauss: 48 saat, 519 kapsam, PASS+WARMUP+FAIL muhasebesi, tekrarsız run.
- Turing/Lamport: input provenance, idempotency ve olay saatleri bağımsız sınanır.
- Bayes/Shannon/Kahneman: yeşil workflow veya tek başarılı PR gerçek alpha/otonomi olarak sayılmaz.
- Thorp/Simons/Taleb: maliyet/kayma/likidite ve sürpriz kayıplar özel OOS/paper kabulü olmadan terfi edemez.
- Tüm testler Python stdlib/mock, gerçek Binance veya GitHub ağı olmadan CI'da çalıştırılır. `tests/test_evidence_collector.py` corrupt gzip, SHA mismatch, false run metadata, delayed schedule, 48/47 gün ve manual-vs-CF ambiguity hatalarını kapsar; workflow güvenlik sözleşmesi `tests/test_evidence_controller_workflow.py`.

## Kapanmamış kapılar
P0: Cloudflare API asgari yetkili canlı log ve Worker version attestation, bağımsız otomatik doğrulama.
P0: 48 gerçek ardışık source epoch. 489 PASS/30 WARMUP=0 FAIL geçmiş örnek, tam teknik olgunluk değil.
P1: Kaynak adayı keşif→lisans→PIT→OOS→shadow→paper testlerin gerçek otomatik çalıştırıcısı ve onaylı terfi.
P1: Arıza tanıyıp güvenli taslak PR üreten, izole ve onaylı bot kimliği.
P1: Private P30 önce sıfır ek ücret, sonra 15 dk tazelik ve gerçek başarı.
P2: 14 günlük native WSS, 60 günlük paper/OOS ve cihaz ACK.

**Rollback:** Yalnız bu PR değişikliklerini revert et. SQLite, makbuzlar, source script, private runner, NASDAQ asla değişmez. GitHub Actions controller'ı istenirse tek başına devre dışı bırakılabilir.
