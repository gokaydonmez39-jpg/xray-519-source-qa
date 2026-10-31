# XRAY-519 — Public saatlik güvenilirlik sözleşmesi (31.10.2026)

Bu sözleşme yalnız public xray-519-source-qa içindir. NASDAQ, private P30, ücretli runner, gerçek emir, WSS ve bildirimler değişmez.

## Zamanlama (UTC)
- :01 — Cloudflare primary Cron, ilk güvenli GitHub dispatch denemesi.
- :04 — GitHub native schedule, best-effort.
- :06 — Cloudflare backup Cron. Yeni epoch rezervasyonu mümkünse ilk deneme; aksi halde yalnız kesin POST-öncesi başarısızlığı bir kez atomik CAS ile yeniden dene.
- :08 — GitHub native schedule ikinci best-effort tetikleme.

Cloudflare cron UTC kullanır; dağıtım propagasyonu 15 dakika sürebilir. Cron varlığı gerçek kaynak run başarısı anlamına gelmez.

## SQLite ve karar emniyeti
- Tek SourceDispatchLock / xray-519-singleton, mevcut dispatch_epoch tablosu ve özgün reserved_at korunur. Satır DELETE/lock reset yok.
- Yalnız GitHub dispatch POST'undan ÖNCE kesinleşen şu 5 ilk-attempt durumunda backup CAS izni var: SOURCE_RECEIPT_LOOKUP_UNAVAILABLE, GITHUB_RUNS_UNAVAILABLE, GITHUB_RUNS_INDETERMINATE, GITHUB_RUN_TIME_INVALID, GITHUB_PRE_DISPATCH_NETWORK_ERROR (GET/response parse hatası).
- Backup sahibi BACKUP_RESERVED_PREPOST ile işaretlenir. Sonraki durum BACKUP_ ile öneklenir; hiçbir BACKUP_ durumu üçüncü denemeye hak vermez.
- RESERVED, DISPATCH_REJECTED, GITHUB_NETWORK_OR_RESPONSE_UNKNOWN, POST_RESERVATION_AUDIT_FAILURE, DISPATCH_ACCEPTED_NOT_SOURCE_PASS veya başka belirsiz/POST-sonrası durumda backup dispatch YASAK.
- Github'da aynı UTC dönemin mevcut source run'ı veya receipt varsa her fırsat yeniden dispatch yapmadan durur.
- GitHub dispatch POST denemesi başlamışsa ağ hatası daima GITHUB_NETWORK_OR_RESPONSE_UNKNOWN kalır; güvenli GET sınıflandırmasına asla düşürülmez.

## Ölçülebilir canlı kabul
1. Her UTC döneminde gerçek ve benzersiz source workflow run ID (event=workflow_dispatch/schedule/push) ve 519 parite taraması.
2. source_qa_success=true, technical_scanned=519, technical_pass+technical_warmup+technical_failed=519, technical_failed=0, emir/bildirim=0.
3. Aynı dönem receipt ve bridge uzak main'den alınır; bağımsız SHA256 ve bridge/source canonical hash, epoch ve 519 kapsamı geçer.
4. Duplicate NOOP ikinci başarılı veri dönemi sayılmaz; geçen saatteki eksiklik geriye dönük kabul edilmez.
5. İki ardışık UTC döneminin ardından 48 saat kesintisiz ölçüm; private P30 maliyet ve tazelik ayrı kapı; WSS, APNs ve FULL FINAL START için ayrı uçtan uca kanıt gerekir.

## Bilinen belirsizlik ve rollback
- 31.10.2026 22:01 TS ekranında Cron çalışmış ve hata üretmiştir; kesin decision/httpStatus halen bilinmiyor. Bu onarım özel hata kodunun giderildiği iddiası değildir.
- Yalnız başarısız ilk GET/API listelemesinden kaynaklanan kalıcı kilit yolunu düzeltir. Permission veya auth 403 devam ederse kaynak yine HOLD olur.
- Yan etki/çakışma doğrulanırsa PR merge commit git revert yapılır; SQLite epoch veya makbuz silinmez.
