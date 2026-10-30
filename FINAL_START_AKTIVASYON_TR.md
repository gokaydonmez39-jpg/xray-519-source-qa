# XRAY-519 — Public kaynak araştırması aktivasyonu

30 Ekim 2026. Bu paket yalnız halka açık Binance Spot/USDT piyasa verisini araştırır.
Özel AL/STOP/2R stratejisi, hesap erişimi, emir, WebSocket veya cihaz bildirimi içermez.

## Yayın sınırı

Tek hedef: `gokaydonmez39-jpg/xray-519-source-qa` adlı yeni ve bağımsız public depo.
Yayın, dosya denetiminden sonra depo sahibinin açık onayına bağlıdır.
Mevcut diğer depolar ve otomasyonlar bu işlemin kapsamı dışındadır.
Bu belge herhangi bir deponun oluşturulduğunu veya gerçek Actions çalıştırıldığını kanıtlamaz.

## Çalıştırma

Kaynak kod, testler ve `.github/workflows/hourly-519-public-source.yml` birlikte aktarılır.
Workflow standart `ubuntu-24.04` runner kullanır; ücretli runner, artifact/cache yükleme ve ödeme kurulumu içermez.
Planlı çalışmalar UTC `4 * * * *` zamanlamasını dener; GitHub geciktirebilir veya atlayabilir.
250 → 400 → 519 kapsam ilerlemesi yalnız geçerli makbuzlardan yapılır.
Elle başlatma aynı üç kapsamı destekler; arka arkaya başlatmalar iki ayrı saat kanıtı oluşturmaz.

## Kabul

Her çalışma için gerçek kapsam, 1H/4H/1D kapanmış mumlar, süre, istek sayısı ve kalite sonuçları incelenir.
HTTP 418/429 ve kaynak kesintisi taramayı durdurur. Bozuk veya stale kapanmış mumlar kalite hatasıdır.
Yeni veya eksik geçmiş WARMUP üretir; tam kalite geçişi değildir.
Stale ticker likidite ön filtresini geçemez; mum kalitesiyle ayrı değerlendirilir.
Spot/USDT kimliği ekonomik ürün sınıflandırması veya özel AL uygunluğu kanıtı değildir.
İki farklı run ID ve ardışık iki tam 519 kalite dönemi, uzaktan makbuz ve SHA256 kontrolü gereklidir.
`TWO_EPOCH_519_SOURCE_QUALITY_PASS` yalnız kaynak araştırmasına aittir.
Özel AL motoru, kesintisiz WebSocket ve cihaz bildirimleri için geçiş vermez.

## Birincil belgeler

- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md

## 30 Ekim 2026 — native GitHub schedule yeniden eşitleme denemesi

GitHub Actions native schedule denemelerinde 519/519 tam gerçek kaynak taraması elde edilmesine rağmen beş GitHub run'un tamamı `workflow_dispatch` idi; native `schedule` olayı gözlenmedi. GitHub'ın resmi Actions troubleshoot belgesinde bazı aktif workflow'larda cron değişikliğiyle scheduled actor kaydının tekrar etkinleştirilebildiği açıklanır. Bu nedenle yalnız cron dakikası UTC `23` yerine `17` olarak değiştirildi. Çalışan kaynak tarama kodu, testler, sınırlamalar, private strateji ve eski depolar değiştirilmedi. Kullanıcıya yeni maliyet veya yeni sunucu bağlanmadı. Bu commit bir `schedule` run'ının oluştuğunun kanıtı değildir. İlk gerçek `schedule` run kaydı ve buna bağlı yeni makbuz uzak GitHub üzerinde geri okunmadan `NATIVE_SCHEDULE_PASS` verilmez; GitHub'ın gecikme/atlama olasılığı devam eder. Saatlik ChatGPT denetim görevinde :35 TRT kontrolü korunur.

## 30 Ekim 2026 — public/private source bridge staging

An independently testable module is staged for a public-only Binance Spot source bridge: 100 closed 1H, 70 closed 4H, 60 closed daily bars, and 60 BTC daily bars. Existing source quality acceptance remains 100/40/40 and every instrument is still counted. A raw 15m USDT/15bps source subset may be exported to a compact immutable public gzip bound to the original source receipt SHA256. This **does not** run or publish private AL logic, open orders, or enable notifications.

The staged native workflow can trigger once on a reviewed code release via path-filtered `push` (receipt commits cannot recur). It still also has `schedule` UTC :17, which is not guaranteed and has not been accepted as reliable by deployment alone. The private compute handoff and its zero-fee GitHub budget safety remain separate HOLD gates. User approval is required before public/private live deployment and any change that could incur a charge.

## 30 Ekim 2026 — özel 15 dakikalık tazelik kapısı için erken kaynak çalıştırma

Public kaynak işi GH run 41123970185 üzerinde 519/519 Spot/USDT envanterini 1563 GET ile yaklaşık 237 saniyede doğruladı. Kaynak köprüsünün uzak SHA256 geri okuması PASS; 50 piyasa için 100 kapalı 1H, 70 kapalı 4H ve 60 kapalı 1D mum hazır. Bu bir AL sinyali DEĞİLDİR. UTC :17 planlaması, public taramanın ancak yaklaşık :21'de bitmesi nedeniyle özgün 15 dakika AL tazelik kapısıyla uyumlu değildi. Bu nedenle gelecek saatler için tek native schedule UTC :04 olarak değiştirildi; GitHub geciktirebilir/atlayabilir. Eski 17>4 değişikliği yalnız saat planlamasıdır; CORE-18 veya private strateji değişmez. Workflow push paths içinden workflow YML kendisi çıkarılmıştır; yalnız saat yenileme merge'i aynı saat kaynak makbuzunu tekrar taramak üzere tetiklemez. Public source release kod değişiklikleri ise ayrı ve kontrollü push tetikleme yolunu korur. İlk native :04 GitHub schedule çalışması ve private gölge hesaplaması gerçek run/makbuz ile kanıtlanana kadar HOLD'dur.

## 31 Ekim 2026 — İlk cron atlamasına karşı create-only public source kick

Gerçek GitHub repo kontrolünde public native schedule UTC :04 henüz gerçekleşmemiştir. Bu nedenle aynı ve değişmez 519/519 Spot kaynak tarayıcısına, yalnız public `main` dalındaki `ops/source-kicks/*.json` dosya oluşturma/değişiklikleri üzerinden denetlenebilir `push` tetiklemesi eklendi. Bu yeni algoritma değildir; mevcut read-only source-only GitHub job'ını, mevcut `select_scope.py` kapsamını, `SOURCE_PREFLIGHT` tekrarlı-epoch korumasını, 100/70/60 köprü geçmişini, SHA256 ve create-only makbuz davranışını kullanır. Yalnız beklenen UTC saat başı +04/+06 penceresinde, 519 source run aktif değilse ve henüz makbuz yoksa ilgili saat için tek `ops/source-kicks/YYYYMMDDTHH00Z.json` commit'ine izin verilir. Aynı epoch dosyası asla değiştirilmez; mevcut kaynak makbuzları korunur. Yedek çalışmanın `event=push` olması `event=schedule` diye raporlanmaz. İşlem sadece standard GitHub-hosted PUBLIC runner üzerinden gerçekleştirilebilir; private ücret veya özel strateji başlatma yetkisi içermez. Kilit testleri `tests/test_source_kick_fallback.py` ile eklenmiştir. İlk yedek kaynak run id, çalışma durumu, kendi benzersiz saatlik gzip dosyası ve uzak SHA256 doğrulanmadan native/backup süreklilik PASS verilmez. Private P30 çalışma ve maliyet HOLD kuralları aynen devam eder.
