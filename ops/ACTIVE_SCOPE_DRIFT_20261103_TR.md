# Public SPOT evreni değişimi — 3 Kasım 2026

**Durum:** Üretim `main` dalına geçirilmemiş güvenli onarım taslağı. Binance Global Spot `exchangeInfo` sorgusunda 3 Kasım 08:xx UTC itibarıyla `TRADING && isSpotTradingAllowed == true && quoteAsset == USDT` evreni 518; 02:00 UTC döneminin önceki uzaktan doğrulanmış kaydı 519. 03:00–08:00 UTC kaynak çalışmalarında 518 tarama, `receipt-n519` ve `bridge-n518` yüzünden `INVALID_EVIDENCE_PATH` ile FAIL_CLOSED.

## Kesinleşmiş sembol kimliği ve bağımsız SHA256 doğrulaması

- Binance Global SPOT `exchangeInfo`, 2026-11-03T09:04:46.578Z: 518 `TRADING && isSpotTradingAllowed && quoteAsset=USDT`.
- `VELODROMEUSDT`: `status=BREAK`, `quoteAsset=USDT`, `baseAsset=VELODROME`, `isSpotTradingAllowed=true`. Bu durumdaki sembol aktif `TRADING` evreninin dışındadır.
- Python `instrument_scope()` ile aynı kanonik JSON sırası, UTF-8 ve SHA256 algoritması bağımsız JS hesaplamasıyla tekrarlandı; hesaplayıcının `abc` vektörü PASS.
- Güncel 518 sembolün SHA256 özeti `aa5fbb1c924a28a18d83009edb50ce7215ba00d421d9f859572f5e71ad90486d`: 03 Kasım 08Z kaynak çalışmasıyla **birebir aynı**.
- Aynı 518 listeye yalnız `VELODROMEUSDT` tekrar eklenince SHA256 `b3cf5f9bd206e0f5b96e456a5189f8394ad890107e93542d3bfa3012e98104ea`: 03 Kasım 02Z son başarılı n519 kaynak çalışmasıyla **birebir aynı**.
- Böylece 519→518 evren farkını yaratan tek kimliğin `VELODROMEUSDT` olduğu tarihsel ve güncel bağımsız digest ile kanıtlandı. Sembolün hangi nedenle BREAK'e geçtiği ve ne zaman yeniden TRADING olacağı bilinmiyor.
- Bu kanıt `FULL_FINAL_START=HOLD` kararını **değiştirmez**. 518 kayıtları 519/48 saat şartına yazılmaz.

## Güvenlik ilkeleri

1. Gerçek taranan kimlik sayısı değiştiğinde full-mode makbuz ve bridge aynı **gözlenen** `-nN` ekiyle, eski artefaktları değiştirmeden üretilir. 519 gibi görünmesi için hayali bir sembol eklenmez.
2. `publish_git.py` yalnız 250/400 pilot modunda tek makbuza, 401–564 aralığındaki tam kapsam modunda ise **aynı saat ve aynı gerçek N ile eşleşmiş bir makbuz + bridge çiftine** izin verir. İkinci yazma, SHA farklılığı ve kaynak kodu değişimi yine fail-closed.
3. Aynı UTC saatindeki farklı **N** kapsamlı birden fazla çift, preflight tarafından `CONFLICTING_SCOPE_SAME_HOUR` olarak reddedilir.
4. Uzak Git doğrulamasında tam çift varsa sonraki aynı saat çalışması yeni tarama yapmadan NOOP verir. 518 makbuzu `519_SOURCE_PASS` olarak sunulamaz.
5. Mevcut `verify_remote_pair.py`, `ops/evidence_collector.py` ve `ops/autonomy_acceptance.py` 519 tam kabulü için değiştirilmez. Bu nedenle 518 tarihli kayıtlar 519/48 saatin eksik saatlerini kapatmaz; **FULL_FINAL_START=HOLD** korunur.
6. `src.scan` içinde canlı emir, AL, bildirimi veya private kod bulunmaz. Bu dal yalnız araştırma amaçlı kaynak kapsamının dürüst ve tekil yayımlanmasını hedefler.

## Kabul ve geri dönüş

- Öncelikle `python3 -m unittest discover -s tests -q` ve `python3 -O -m unittest discover -s tests -q` PASS.
- 518 makbuz / bridge eşleşmesi, 518'e ait aynı-saat NOOP, bozuk SHA ve eksik bridge için negatif testler PASS.
- Taslak PR birleştirilmeden gerçek 518 publish PASS iddiası yoktur.
- `main` dalı değişmedikçe geri dönüş branch/PR kapatılmasıdır; main'e yetkili ileride birleştirme yapılırsa parent SHA'dan geri alma mümkündür.
- Gerçek üretim dağıtımı, Cloudflare köken 48h, P30, bağımsız CORE-18 host 24h, native WSS 14 gün, paper 60 gün ve APNs kabulü **ayrı kapılardır**; bu dal bunları tamamlamaz.

**Yasak:** eksik tarihsel saatleri backfill PASS, geçmiş olayları yeni PUSH, 519 yerine 518'i sayarak FINAL ve yeni gerçek emir.
