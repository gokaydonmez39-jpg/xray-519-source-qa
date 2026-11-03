# XRAY CRYPTO Ω — AGIPro yöntem kapıları V1 (offline / fail-closed)

Kaynak: https://github.com/agiprolabs/claude-trading-skills ; incelenen commit: 981e1d736cdc02bdc1c55c74ec9224e956414706 (MIT). Yalnız yöntemlerden yararlanıldı, kaynak algoritma kopyalanmadı. Bu modül MCP, canlı veri sağlayıcı, model, emir/AL, cüzdan veya bildirim entegrasyonu değildir.

## Önceden sabitlenmiş hedef ve sınırlar

1. Aynı barın kapanışından türetilen sinyalin aynı barın getirisine uygulanması her durumda RED. Sinyal kararından sonra gözlenen entry ve bundan sonra kapanacak tam 1H return barı gerekir.
2. Purge/embargo: Her training label test başlangıcından en az 1H önce elde edilmiş olmalı; cutoff'lar UTC tam saat. Daha geç erişilen örnekler purged olarak sayılır, train'e sızmaz. Split yoksa RED.
3. OHLCV: Her bar 1H hizalı, ardışık, gerçekten gözlenmiş ve kapanmış olmalı; boşluk, tekrar, sıfır hacim, geçersiz OHLC ve sentetik/forward-fill = RED.
4. Çoklu deneme: declared_trials değerinin sağlanan test sonuçlarıyla eşleşmesi zorunlu; Holm-Bonferroni yalnız metodoloji örneği, bağımsız p-değerlerinin gerçekliği doğrulanmadı.
5. Pozitif kazanç yoğunlaşması: Top-N/pozitif PnL oranını hesapla; gerçekleşmiş portföy getirisi veya fill doğrulaması iddia etme.
6. Bütün çıktılarda promotion_allowed=false, orders_sent=0; sıfır yeni bağımlılık ve sıfır ağ.

## Açık varsayımlar ve sınırlamalar

- Özellikle validate_attribution() sonraki tamamen kapanmış 1H bar modelini zorunlu kılar: entry saat içinde gözlense bile aynı saatin kalan getirisi burada kullanılmaz. Bu koşul mevcut P30 stratejisini değiştirmez.
- purged_temporal_split() bir tek split tanılama aracı; tam CPCV, yeniden eğitim, gerçek OOS, rejim bağımsızlığı veya ileriye dönük ölçüm değildir.
- holm_research_gate() öznel/uydurma p-değerlerini ayırt edemez; tüm denemeler sayılmadan istatistiksel veya ekonomik kabul veremez.
- positive_gain_concentration() kazananların yoğunluğunu ölçer, maksimum drawdown ve portfolio PnL değil.
- Testler sentetik/veri-yapısı bazlıdır; gerçek Binance emir defteri, DexPaprika, private P30, WSS ve telefon ACK doğrulaması değildir.

## Geri dönüş, entegrasyon ve kabul kanıtı

Bu ekleme sadece research_lab/agipro_research_guard.py, tests/test_agipro_research_guard.py ve bu dokümandır. Çalışma zamanlayıcılarına/hook'larına otomatik bağlanmaz. Mevcut research_lab/pit_audit.py, DexPaprika taslak adaptörü ve P30 değişmez. Normal ve -O unit testleri, negatif örneği RED ve pozitif örneği PASS göstermek zorundadır. Başarısız CI durumunda taslak dalda kalır, main etkilenmez.

FULL FINAL START: HOLD. 48 gerçek ardışık kaynak epoch, maliyet, private/market OOS, WSS ve bildirim ACK ayrı kapılardır.
