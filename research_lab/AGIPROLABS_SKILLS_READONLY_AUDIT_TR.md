# XRAY CRYPTO GODZILLA Ω — agiprolabs trading-skills kaynak denetimi

## Amaç, karar ve kaynak sabitlemesi

- Tarih: 2026-11-01; kapsam: **yalnız public research-only taslak PR #22**.
- Üst kaynak: https://github.com/agiprolabs/claude-trading-skills
- İncelenen upstream **main**: `981e1d736cdc02bdc1c55c74ec9224e956414706`.
- GitHub deposu MIT lisanslı ve 68 `SKILL.md`, 119 Python dosyası barındırıyor. Bu sayılar **işleyen 68 entegrasyon** veya **119 doğrulanmış modül** anlamına gelmez.
- `.claude-plugin/plugin.json` açıklamasında hâlâ 67 skill yazıyor; README 68 yazıyor. Depo kökünde yalnız `tests/test_drawdown_analyzer.py` görüldü (iki unittest metodu); bu, bütün örnek kodun test edilmiş olduğunu kanıtlamaz.
- **Karar:** Metodoloji ve olumsuz örnekleri araştırma sözleşmesine al; upstream kodunu **kopyalama / kurma / çalıştırma**. Haricî API, paket veya yeni MCP/ajan yetkisi ekleme. Gerçek piyasa veya kârlılık kanıtı yok.

## Yararlı beceriler, XRAY gereksinimi ve karar

| Upstream skill | Yarar | XRAY kararı |
| --- | --- | --- |
| `walk-forward-validation` | Zaman sıralı train/test, purge/embargo, rejim ve multiple-trial denetimi | **Yöntem referansı**, mevcut `research_lab/pit_audit.py` ve private P11/P18'i kaldırmaz |
| `slippage-modeling` | İşlem büyüklüğüne göre artan impact, toplam fee/slippage ve başa baş maliyet | **Yöntem referansı**; Solana Jupiter quote verisi Binance Spot 519'un gerçekleşebilir fiyatı değildir |
| `risk-management` / `position-sizing` | Drawdown, exposure ve kayıp senaryoları | **Private kapı HOLD**; bu public proje gerçek para/AL yetkisi vermez |
| `liquidity-analysis` / `market-microstructure-traditional` | Depth, spread, kapasite ve anlık likidite şokları | Ek araştırma; ölçülen kitap görüntüsü olmadan sonuç iddiası yok |
| `regime-detection` / `volatility-modeling` | Rejimler arası sağlamlık, volatilite stress | **Yalnız geçmişte bilinen veriye fit**; mevcut canlı filtreleri değiştirme |
| `ohlcv-processing` | Bozuk OHLC, eksik bar, zaman damgası ve tekrar denetimi | **Gap yalnız fail-closed/WARMUP**, strateji için fiyat ileri doldurma yasak |
| `signal-classification` | Walk-forward ML, kalibrasyon ve çoklu deneme bilinci | Aşırı uyum ve maliyet kanıtı yok; gerçek model/AL için **HOLD** |
| `prediction-market-live-ops` | Önceden tanımlı falsification, tek değişkenli deney, bağımsız risk/kayıt denetimi | **Yöntem referansı**; gerçek emir/1-lot smoke test önerileri XRAY'de **YASAK** |

## Kod okumasında doğrulanan riskler

1. **Kritik — aynı barın getirisi:** `skills/walk-forward-validation/scripts/walk_forward.py`, `run_walk_forward` bölümünde `sma_crossover_signals(...)` mevcut kapanış fiyatını dahil ediyor; daha sonra aynı indeksin `returns` serisiyle `test_signals * test_returns` çarpıyor. Aynı barın kapanışı bilindiği anda aynı barın getirisi işlemsel olarak elde edilemez. **Öncelikli lookahead/attribution kusuru**; kodu XRAY'ye taşımıyoruz.
2. **Yüksek — CPCV'de eksik purge:** `skills/walk-forward-validation/scripts/overfit_detector.py`, `probability_of_backtest_overfitting` contiguous kombinasyon gruplarını ayırıyor; ancak eğitim etiketlerinin test aralığıyla çakışmasını kaldıran gerçek purge/embargo kontrolü görünmüyor. Açıklamada CPCV olarak adlandırılması tek başına leakage güvenliği kanıtı değildir.
3. **Yüksek — OHLCV gap doldurma:** `skills/ohlcv-processing/SKILL.md` kayıp barlara forward-fill / interpolate örneği veriyor. XRAY'nin kaynak QA, 519 identity ve P30 admission kanıtında bu tür üretilmiş barlar kabul edilemez; **WARMUP / veri eksikliği** korunmalı.
4. **Orta — API/dokümantasyon drift:** `skills/walk-forward-validation/SKILL.md` örneğindeki `purge_horizon` parametresi, gerçek `WalkForwardConfig` tanımındaki `purge_size` ile uyuşmuyor; örnek doğrudan çalışırlık kanıtı değil.
5. **Orta — rejim geleceğe sızması:** `skills/regime-detection/SKILL.md` örnek CUSUM kodu standartlaştırmada tüm getirilerin `mean()`/`std()` değerini kullanıyor. Karar anında yalnız tarihsel pencere kullanılabilir.
6. **Yüksek — yetki/yanlış mimari:** Solana/Jupiter işlem kurma, Kalshi gerçek emir, wallet/DEX execution becerileri ayrı bir izin düzeyi gerektirir. Bu depoda olması XRAY 519 source-only kapsamı için kullanma izni vermez.
7. **Orta — test kapsamı:** README'deki `production-ready` ifadesi, bütün 119 Python dosyasının normal/optimized, negatif, ağ ve ekonomik doğrulamalarının geçtiği anlamına gelmiyor. Upstream paket bütün olarak **test edilmedi**.

## Kilitli kabul sözleşmesi — yöntem entegrasyonu

- **Causality:** `feature_available_ms <= decision_ms`; sinyal üretiminde kullanılan kapalı mum ve gerçek fill/getiri dönemi zaman bakımından ayrılmalı. Gelecek kapanıştan geçmişe pozisyon getirisi yazılamaz.
- **Purge/embargo:** Eğitim etiketinin erişilebilirliği test başlangıcından önce gelmeli; epoch'lar bölünemez; train/validation/test birlikte mevcut olmalı. Mevcut `pit_audit.py` bu disiplinin yalnız araştırma sürümüdür.
- **OHLCV:** Eksik/bozuk/sahte bar = fail-closed ya da WARMUP; otomatik sentetik fiyat/volume oluşturma yasak.
- **Model selection:** Kaç aday denendiği tam sayılmalı; önceden açıklanmış family-wise kontrol, rejim kırılımları ve bağımsız OOS kanıtı olmadan Sharpe/accuracy artışı AL değildir.
- **Ekonomi:** Referansla aynı dönemde BTC/buy-and-hold karşılaştırması, çift taraflı ücret, spread, kayma, gecikme, fill ve kapasite; yalnız senaryo grid'i **gerçek fill veya kârlılık kanıtı değildir**.
- **Sıfır maliyet:** Hiçbir Solana RPC, Birdeye, Jupiter, Kalshi, ücretli API veya LLM agent işlem hattı devreye alınmaz.
- **Yetki:** Emir, swap, cüzdan, private P30 job, WSS, iPhone push, üretim promotion **yok**. SOURCE QA veya test PASS asla FULL FINAL START değildir.

## Uygulama ve test kanıtının sınırı

Bu dosyanın eklenmesi **yalnız dokümantasyon/metodoloji entegrasyonudur**; bir Python runtime, upstream skill veya yeni test çalıştırmaz. Upstream kaynak kodu bu görevde okunup denetlendi; upstream test suite'i ya da canlı API **çalıştırılmadı**. PR #22'nin daha önceki Python test PASS'leri bu yeni kaynağın algoritmalarını doğrulamaz. Gelecekte kod entegrasyonu istenirse izole modül, negatif lookahead testi, input-bound test, lisans provenansı ve maliyet testiyle ayrıca PR gerekir.

## İzolasyon ve geri dönüş

Yalnız taslak `research/dexpaprika-cost-shadow-20261101` dalında bu rapor dosyası bulunur. `main`, mevcut 48-saat/COUNT=52 denetim görevi, Binance 519 evreni, receipt/bridge, Cloudflare Worker/Cron, Durable Object SQLite kilidi, private P30 ve NASDAQ **değişmez**. Risk görürsen taslak PR içindeki bu doküman değişikliğini geri al; üretim rollback gerekmez.
