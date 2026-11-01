# XRAY-519 SELF-HEALING ENGINE — Güvenli otomatik iyileşme sözleşmesi
**Durum: DRAFT / üretime alınmadı.** Yalnız public CRYPTO kaynak hattı; NASDAQ ve özel P30 sistemlerinden bütünüyle bağımsızdır.

## Problem ve başarı kriteri
Eski sistem Cron/REST hatasını logluyordu, fakat güvenli sınırlar dışında kendisini düzeltemiyordu. Hedef, bilinen POST-öncesi geçici hataları sistemin kendisinin gidermesi, bilinmeyen veya belirsiz hata durumlarında ise fail-closed ve kanıtlı inceleme sağlamasıdır. Kabul için yalnız yeşil CI yeterli değildir.

**Üretim öncesi kapılar:** Negatif/pozitif regresyonlar, mevcut CI tam PASS, izin ve maliyet sınırı, ayrı kullanıcı merge/deploy onayı. **Canlı kabul:** 48 ayrı kesintisiz UTC saat dönemi, 519/519, 0 FAIL, bağımsız receipt/bridge SHA256, 0 emir/bildirim, otomatik tetikleme provenansı. Geçmiş boş epoch sonradan doldurulamaz. Özel P30 <=15 dakika, 14 gün WSS, 60 gün paper/OOS ve iPhone ACK ayrı kapıdır.

## Seviye 1 — Kanıta bağlı otomatik teşhis
`self-heal-policy.mjs::classifyDecision`, yalnız izin verilen `decision`, sayısal `httpStatus` ve primary/backup bilgisine göre sabit kod döndürür. `dispatch-core.mjs` sonucuna `selfHeal` olarak eklenir ve mevcut Cloudflare `XRAY_PUBLIC_DISPATCH` logunda görünür. Secret, URL, hata response-body veya özel piyasa verisi kaydedilmez.

- `OBSERVE_ONLY`: Dispatch kabul edilmiş ya da mevcut run/receipt var. Bu yalnız işlem durumudur, kaynak başarısı değildir.
- `SAFE_BACKUP_CAS_ONCE`: Kesin POST-öncesi başarısızlık; mevcut :06 tek-kazananlı SQLite CAS ile yalnız bir ek fırsat.
- `HOLD_NO_RETRY`: POST belirsiz, hata sonrası backup tükenmiş, stale veya duplicate kilit; yeniden dispatch ve kilit temizliği yasak.
- `REVIEW_REQUIRED`: 401/403/429, bilinmeyen kod veya kanıtı belirsiz durum; önce gerçek HTTP yanıtı ve neden incelenir.
- Tüm durumlarda `automaticCodeChange=false`, `automaticLockReset=false`.

## Seviye 2 — Sınırlı otomatik toparlanma
Yalnız salt-okunur GitHub GET sorgusu HTTP **502, 503 veya 504** döndürürse *aynı URL ve aynı yetkiyle* en fazla bir kez GET tekrarlanabilir. Tek Worker invocation başına bu hak yalnız bir kez kullanılabilir ve **nominal 90 saniyelik Cron tazelik süresinden en az 7 saniye** kalmış olmalıdır. Ek GET çalışmasının ardından gerçek saat POST öncesinde tekrar kontrol edilir; 90 saniye aşılmışsa dispatch reddedilir.

**Otomatik tekrar yasağı:** 401/403/429, POST, belirsiz ağ sonucu, üçüncü deneme, tamamlama sonrası geri dönük tarama. Mevcut Cloudflare :01/:06, GitHub native :04/:08, Durable Object SQLite `dispatch_epoch`, `reserved_at` ve create-only receipt/bridge korunur. Daha fazla GitHub GET trafik/limit riskini artırabileceğinden otomatik retry yalnız tek geçici hata için sınırlıdır.

## Seviye 3 — Denetimli düzeltme (sınırı açık)
Yeni veya sürekli arızalar `REVIEW_REQUIRED` olarak işaretlenir ve kanıtlı olay/onarım incelemesine yönlendirilir. Otomatik rastgele kod üretip PR açan veya üretime otomatik merge/deploy yapan yetkili bir ajan **bu DRAFT kapsamında kurulmadı**. Bunun için ayrı ve en az yetkili GitHub bot kimliği, güvenilir hata kökeni, bağımsız test, maliyet kanıtı ve açık kullanıcı yetkilendirmesi gerekir. Bu sınır aşılmadan otomatik kod değişikliği varmış gibi davranılmayacak.

## Olumsuz senaryolar ve geri dönüş
| Durum | Güvenli davranış |
|---|---|
| 403 sürer | HOLD; API izin/rate-limit başlıklarını kontrol et, token yetkisini varsayma |
| GET 503 sürer | Sınırlı tek GET, varsa tek backup CAS; sonuç belirsizse dur |
| POST ağ hatası | Dispatch yapılmış olabilir: kesinlikle tekrar deneme |
| Duplicate veya RESERVED | SQLite satırını silme; rezervasyon ve run provenansını oku |
| 90 saniye veya UTC dönemi kaçırıldı | Kaynak taramasını engelle; geçmiş dönemi PASS sayma |
| Yanlış kod/maliyet | Bu özelliğin merge commit'ini revert et; veri ve kilitleri koru |

## Test ve üretim kabul
GitHub CI: `node --test ops/cloudflare-source-trigger/*.test.mjs`. Kontroller arasında 403/429 reddi; 502/503/504 tek GET; kalıcı 503 durdurma; backup sonrası üçüncü deneme yok; belirsiz POST durdurma; zaman aşımı hem geçilen hem tetiklenen eşikler; token/log gizliliği; tek POST; eski regresyonlar vardır. Üretim deploy onayı ayrıca alınmadıkça DRAFT kalır. Canlı Cron ve 48 saatlik kabul yapılmadığı sürece FULL FINAL START = HOLD.
