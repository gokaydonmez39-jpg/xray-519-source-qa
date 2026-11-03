# XRAY CRYPTO Ω — DexPaprika + maliyet stres testleri (araştırma dalı)

## Güvenlik sözleşmesi

- Yalnız `research_lab/external_sources_shadow.py` ve kendi testleri: mevcut 519 Binance SPOT USDT taraması, receipt/bridge, Cloudflare Worker, cron, SQLite kilitleri, P30 private stratejisi, WSS, bildirim, emir sistemleri değişmez.
- Varsayılan `dex_shadow(..., allow_public_rest=False)` hiçbir ağa bağlanmaz. Canlı HTTP GET ancak çağıran yazılımdan açıkça `allow_public_rest=True` ile; mevcut workflow tarafından çağrılmaz.
- **En fazla 10 önceden eşleştirilmiş EVM kontratı**, izinli beş zincir, sabit `api.dexpaprika.com` sunucusu, HTTPS, GET, 3 saniye istek zaman aşımı, 64 KiB yanıt limiti, yönlendirme takibi yok, erişim anahtarı yok. Ödeme / x402 / CEX emir API'si yok.
- Zincir ve kontrat adresi yanıtla birebir doğrulanır. Binance sembolünün bu kontrata gerçekten ait olduğu **henüz bağımsız doğrulanmadığından** her kayıt `contract_mapping_authenticated=False` taşır.
- Gerçek HTTP çağrısı, bağlantı kotası, yanıt gecikmesi ve sağlayıcı kredisi şu anda canlı test edilmedi; gözlem `EXTERNAL_RESEARCH_UNVERIFIED` durumundadır. 10 ardışık çağrıda API rate limit tetiklenirse fail-closed olabilir; otomatik tekrar yapılmaz.
- `cost_sensitivity_shadow()` sahte/haricî veriyle *senaryo değerlendirme yöntemidir*. İşlem komisyon ve kayması 0/10/20 bps eksenlerinde sınanır, aynı zaman aralığındaki BTC göreli proxy'si ile karşılaştırılır. Tarihsel uygunluk, gerçek fill, walk-forward OOS ve getiri kanıtı sayılmaz.
- Haricî lisanslı Python kodu, haricî MCP çalışma zamanı, ağ kütüphanesi veya ücretli araç yüklenmez. Python standart kütüphanesi yeterlidir.

## Kabul testleri

- 13 test normal ve `python -O` altında PASS (yerel çalışma); negatif senaryolar: yetkisiz ağ, URL/path enjeksiyonu, desteklenmeyen zincir, fazla/çift kayıt, yanlış adres/zincir, yanlış SHA, NaN, fazla maliyet, lookahead, tekrar işlem, tanınmayan alan.
- PR CI ile tüm kamu repo regresyonları ayrıca doğrulanmalı. PR merge yapılmadan 48 saatlik üretim kabulü etkilenmez.
- Private P30'da mevcut `phase10_p18_costed_pit_oos.py` ve `phase10_p11_pit_split_gate.py` korunur. Bu kamu araştırma modülü otomatik P30 yetkisi vermez.

## Geri dönüş

Bu araştırma dalı/PR kapatılır. Üretim dosyalarına veya özel P30'a müdahale gerekmez.

Resmî API: https://docs.dexpaprika.com/tutorials/fetch-token-price ; https://dexpaprika.com/api/pricing . Vektörleştirilmiş backtest metodolojisi: https://vectorbt.dev/getting-started/usage/ .
