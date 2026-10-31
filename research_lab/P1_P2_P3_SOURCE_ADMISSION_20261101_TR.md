# XRAY CRYPTO GODZILLA Ω — P1/P2/P3 kaynak kabul kaydı
Tarih: 2026-11-01. Yalnız **public XRAY-519** deposunda, taslak araştırma PR. NASDAQ tümüyle kapsam dışıdır.

## Önceden belirlenen başarı koşulları
- Yeni branch / draft PR; **main, 519 sayım mantığı, Cloudflare/GitHub workflow/cron, SQLite lock, receipt/bridge, private P30, WSS, bildirim, broker/AL, NASDAQ** değişmez.
- Yeni masraf/servis/API key/secret/LLM, otomasyon veya gerçek ağ çağrısı yok. Koda eklenen fonksiyonlar inert; üretim workflow'a bağlanmaz.
- Yeni offline modül normal ve `-O` Python'da pozitif + negatif testleri geçmeli; GitHub'da mevcut public repo regresyonları iki modda PASS olmalı.
- Ekonomik performans, makine öğrenmesi, private AL, gerçek fiyat/veri, maliyet veya bağımsız 48 saat kabulü hakkında hiçbir PASS iddiası yok.

## Önceden ilan edilen salt-okunur denetim eşiği
- **Tarihsel evren:** `spot_usdt_at_asof=true` ve önceki üyelik gözlemi, tam saat UTC karar, kapalı 1h candle; güncel 519 listesinden geçmiş üyelik türetilmez. Delist tarihi karardan önceyse RED.
- **Maliyet:** Sentetik/hypothetical ask-bid, 300 saniye azami quote yaşı, azami 30 bps spread, en az 10× küçük taraf depth/notional, 20 bps round-trip komisyon örnek testi; slip her tarafta, impact round-trip. Bunlar kanıtlanmış canlı strateji limitleri DEĞİL, yalnız araştırma testi poliçesi. `net_edge_bps = gross_edge_bps - spread_bps - roundtrip_commission_bps - 2*slippage_per_side_bps - roundtrip_impact_bps`. Başarı = sayısal formül ve monotonluk negatif testlerinin doğru işleyişi; net edge negatif çıkabilir.
- **Kaynak:** Saat adımı 3600000 ms, her dönemde tam 519 tarama, `pass + warmup + failed = 519`, `failed=0`, receipt/bridge canonical payload SHA256 alanları birebir ve epoch scope digest öncekiyle tutarlı olmalı. Değişen scope otomatik hata sayılıp manuel araştırma ister; doğal liste değişimi kanıtlandığında bu araştırma politikası yeniden ilan edilmeli. Eşit görünen hash *tek başına* gerçek SHA hesaplandığını veya imzayı kanıtlamaz.
- **İzolasyon:** Tüm fonksiyonlar dönen değerlerde `promotion_allowed=false`, `orders_sent=0`; 48 saatlik canlı kaynak başarısı, Cloudflare cron ve private onay asla üretilmez.

## P1 — Doğrulanan dış kaynaklar ve uygulanabilir bölüm
1. **Freqtrade**, https://github.com/freqtrade/freqtrade (GPL-3.0; develop @ `eea497b88a12e5c25acee6a9102df135ab01311b`). Resmî `lookahead-analysis` önce referans backtest, sonra sliced sinyal/indikatör karşılaştırması yapıyor; `recursive-analysis` farklı startup uzunluklarını denetliyor. Freqtrade *kurulmadı/çalıştırılmadı*. Zaten XRAY'de `freqtrade_causality_shadow.py`, `tests/test_freqtrade_causality_shadow.py` ve `research_lab/pit_audit.py` var; bunlar değiştirilmedi. Dry-run botu, çalıştırma motoru ve GPL kaynak kodu kopyalama YOK.
2. **AGIPro Claude Trading Skills**, https://github.com/agiprolabs/claude-trading-skills (MIT; main @ `981e1d736cdc02bdc1c55c74ec9224e956414706`). İlgili yöntemler: walk-forward, slippage, risk, position sizing, liquidity, regime, MEV. Kod otomatik çalıştırılmadı. `walk_forward.py` demo kodu, aynı kapanıştan üretilen sinyalle aynı return indeksini eşleyebilir; PBO örneği gerçek purge/embargo göstermiyor; OHLCV eğitim örneği forward-fill yapıyor. Kod/strateji kaynakları entegre edilmedi. MEV özellikle DEX ve Solana execution modeline bağlı; Binance Spot 519 için doğrudan ücret veya AL sinyali olamaz.

Yeni bağımsız `research_lab/p1_adversarial_risk.py`, salt-okunur metadata ve sentetik örnekler ile **tarihsel üyelik/survivorship, future data, ask-bid/slippage/fee, 10× likidite kapasitesi, duplicate/gap epoch, 519 accounting, receipt/bridge hash kayması ve değişen kaynak scope** olaylarını fail-closed denetler. `tests/test_p1_adversarial_risk.py` 21 standalone test barındırır. Upstream hiçbir çalışma zamanı, script veya bağımlılık alınmadı.

## P2 — Yalnız yöntem/araştırma (entegrasyon yok)
3. **Vibe-Trading**, https://github.com/HKUDS/Vibe-Trading (MIT; main @ `78fab6b3f998583f640820db60c155ffa5641a62`). `crypto_trading_desk` funding/basis + liquidation + flow içerir. Bunların çoğu **perpetual/futures** bağlamındadır; Binance Spot 519 filtrelerine futures funding veya liquidation otomatik katılamaz. Zaman eşleşmesi, finansman verisi, sembol, gerçek bedel/LLM gideri doğrulanmadan yalnız kavramsal referans.
4. **Hummingbot**, https://github.com/hummingbot/hummingbot (Apache-2.0; master @ `9af100d6822da7d2d0291a906c730ef172284ee2`). Spread, LOB/queue, fill ve capacity metodolojisi alınabilir; Hummingbot çalışma zamanı, borsa connection, paper-market canlı erişimi ve API key YASAK.
5. **TradingAgents**, https://github.com/TauricResearch/TradingAgents (Apache-2.0; main @ `c4544913a14ed3df5f1ed7b9e8483270ce20682a`). Boğa/ayı/risk bağımsız karşı tezleri araştırma raporu başlığı olabilir; ajan konsensüsü kanıtlanmış fiyat sinyali değildir. LLM sağlayıcısı, dış veriler, API maliyeti ve tarihsel veri saati belirsiz. Çalıştırma/kurulum yok.

## P3 — HOLD
6. **HKUDS/AI-Trader**, https://github.com/HKUDS/AI-Trader (main @ `d03ff6c056b32ced735adf7c19ed8175adb1c8df`). Yalnız paper-trade yaşam döngüsü incelenebilir. GitHub lisans tanıma alanı boş; README MIT iddia ediyor, yeniden kullanım için dosya ve hakkın ayrıca doğrulanması gerekir.
7. **Kronos**, https://github.com/shiyu-coder/Kronos (MIT kod; master @ `67b630e67f6a18c9e9be918d9b4337c960db1e9a`). Model/tokenizer ağırlıkları, lisans, CPU/GPU maliyeti, OOS ve veri kökeni olmadan gerçek tahmin değil. Mevcut `pit_audit.py` de model çalıştırıldığını iddia etmiyor.
8. **Fincept Terminal**, https://github.com/Fincept-Corporation/FinceptTerminal (main @ `7716ee8613249fb44c4d14036c5bc16ed6f34e97`). **LİSANS METNİ ÇELİŞKİSİ:** `docs/COMMERCIAL_LICENSE.md` v3, 11 Ağustos 2026 tarihinden itibaren yalnız AGPL-3.0-or-later, önceki dual-licensing kaldırıldı diyor; kök `LICENSE` metni hâlâ eski ticari lisans açıklamaları içeriyor. Hukuki uygulama ve API/LLM maliyeti belirsiz; herhangi bir kod/kütüphane/kopya entegre edilmedi.

## Kapsam dışı, kesin ret
AutoHedge canlı emir, Camofox anti-bot, LibreChat, Open Generative AI, Open-LLM-VTuber, Claude Ads, Agentic Inbox ve HyperFrames — entegrasyon, kurulum, secret veya araştırma çağrısı YOK. `virattt/ai-hedge-fund` yalnız önemsiz eğitimsel simülasyon adayı.

## Ölçülenler / ölçülemeyenler
- Yerelde `python -m unittest discover -s tests -q` ve `python -O -m unittest discover -s tests -q`, yalnız yeni 21-test örnek paketinde başarılı çalıştı. Tüm public repo testleri PR CI ile ayrıca doğrulanmalıdır.
- Büyük tam sayı maliyet girdisi ilk negatif testte yakalandı (`OverflowError`); sayısal kontrol düzeltildi ve aynı test yeniden PASS. Aynı input yanlışsa fail-closed davranış sürer.
- Bu modül sadece **kullanıcı tarafından sağlanan metadata doğruluğunu varsayarak** yapısal kapı kurar: gerçek receipt SHA, delisting archive, L2 orderbook/gerçek fill, risk/return, kesintisiz 48 saat ve harici maliyet bağımsız doğrulanmamıştır.
- Daha önce gözlenen `SOURCE_PREFLIGHT_FAIL_CLOSED PAIR_HASH_MISMATCH` bu araştırma PR'ı tarafından **onarılmaz**. Kaynak hatası varsa FULL FINAL START HOLD.

## Geri dönüş
Taslak PR birleştirilmeden kapatılabilir. `main` ve mevcut cron değişmediğinden üretim rollback gerekmez. İleride merge kararı, canlı kabul bitince ayrı bir onay, CI ve risk kontrolü gerektirir.
