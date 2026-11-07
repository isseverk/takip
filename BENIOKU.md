# Takip Akışı

Takip ettiğin yazarların yeni köşe yazılarını, YouTube videolarını, podcast bölümlerini, Bluesky ve Telegram paylaşımlarını, Ekşi Sözlük entry'lerini ve Instagram paylaşımlarını tek bir yerde toplar. Telefonuna uygulama olarak kurulur.

Uygulamanın üç ekranı var:
- **Akış:** Yeni içerikler en üstte, gün gün ayrılmış halde. Bir yazıyı sonra okumak için kartındaki ☆ işaretine dokun; **★ Sonra oku** çipinde toplanır. Bir yazarın adına dokununca o yazarın sayfası açılır. Yazar ve tür filtresi, arama ve okundu işareti var. Aşağı çekince yenilenir, internet yokken de son akışı gösterir. Kontroller 2 saatten uzun süredir yapılmadıysa en üstte uyarı çıkar.
- **Günün özeti (☀ düğmesi):** Son 24 saatte, 3 günde ya da 7 günde gelenler kişiye göre toplu halde, yapay zekâ özetleriyle.
- **Kaynaklar:** Yazar ya da kanal ekleyip çıkarırsın, bir kaynağın adresini değiştirirsin, takip ettiğin konuları yönetirsin. Telefonda YouTube'da ya da Chrome'da açtığın bir sayfayı **Paylaş → Takip** ile doğrudan ekleyebilirsin.
- **Ayarlar:** GitHub bağlantısı, bildirimler ve "şimdi kontrol et" düğmesi.

---

## Kurulum — bir kere yapılır, yaklaşık 15 dakika

Kontrolleri GitHub'ın sunucuları yarım saatte bir yapar, bilgisayarının açık olması gerekmez. Adımları **bilgisayardan** yapmak daha kolay. Son iki adım telefonda.

**A. Hesap ve depo (bilgisayarda)**
1. **github.com** adresinde ücretsiz bir hesap aç (**Sign up**). E-postana gelen kodla hesabı doğrula.
2. Sağ üstteki **+** menüsünden **New repository** seç.
   - **Repository name:** `takip`
   - **Public** seç. Ücretsiz sayfa yayını için gerekiyor. Depoda yalnızca zaten herkese açık yazıların bağlantıları ve takip listen bulunur.
   - **Create repository**'ye bas.
3. Açılan sayfada **uploading an existing file** bağlantısına tıkla. Zip'ten çıkardığın `takip` klasörünün **içindeki her şeyi** seç, sürükleyip bırak, sonra **Commit changes**'e bas. `.github` klasörünün de yüklendiğinden emin ol; otomatik çalışma onun içinde.

**B. İki ayar (bilgisayarda)**
4. Deponun **Settings** sekmesinden **Actions → General** sayfasına git. En alttaki **Workflow permissions** bölümünde **Read and write permissions**'ı seç, **Save**'e bas.
5. **Settings → Pages** sayfasına git. **Source** olarak **GitHub Actions** seç.

**C. İlk çalıştırma (bilgisayarda)**
6. **Actions** sekmesine git. Bir uyarı çıkarsa yeşil düğmeye basıp iş akışlarını etkinleştir. Soldan **Takip akışını güncelle**'yi seç, sağdaki **Run workflow → Run workflow**'a bas. 2–4 dakika sürer.
7. Bitince (yeşil ✓) uygulamanın adresi şu olur: `https://KULLANICIADIN.github.io/takip/`. Adres, çalışmanın özet sayfasında da yazar.

**D. Telefona kur (Android)**
8. Bu adresi telefonda **Chrome** ile aç. Altta "Takip'i yükle" önerisi çıkar. Çıkmazsa ⋮ menüsünden **Uygulamayı yükle** seç. Ana ekrana Takip simgesi gelir.
9. Uygulamada **Ayarlar → GitHub bağlantısı** bölümüne git. "Anahtar nasıl alınır?" adımlarını izleyip anahtarı yapıştır ve **Kaydet ve dene**'ye bas. Bu adım telefondan ekleme ve çıkarma yapabilmen için gerekli.
10. İstersen **Ayarlar → Bildirimler → Kuruluma başla**'ya bas ve üç adımı izle. Yeni yazılar Takip simgesiyle telefonuna bildirim olarak gelir (ayrıntısı aşağıda).

Bundan sonra akış her yarım saatte bir kendiliğinden güncellenir. GitHub zamanlanmış işleri bazen birkaç dakika geciktirebilir.

> GitHub, depoda 60 gün boyunca hiç değişiklik olmazsa zamanlanmış işleri durdurabilir. Program bunu önlemek için 50 günde bir depoya küçük bir "Canlı tut" kaydı atar. Yine de durursa GitHub e-posta atar; Actions sekmesinden tek tıkla yeniden açılır.
>
> Program, daha önce gördüğü yazıların kaydını depodaki ayrı bir **veri** dalında tutar. Bu dal ilk çalışmada kendiliğinden oluşur; silme. Böylece ana depo her yarım saatte büyümez.

## İsteğe bağlı — Kendi Windows bilgisayarında da çalıştırmak

1. **python.org** adresinden Python'u kur. Kurarken **"Add python.exe to PATH"** kutusunu işaretle.
2. Bu klasördeki **`calistir.bat`** dosyasına çift tıkla. İlk seferde gerekli parçaları kurar, kaynakları kontrol eder ve akış sayfasını açar.
3. Otomatik çalışsın istersen **`zamanlayici_kur.bat`** dosyasına çift tıkla. Bilgisayar açıkken her 30 dakikada bir arka planda, pencere açmadan çalışır. Sayfayı görmek için `docs\index.html` dosyasını aç.

Bu yol yalnızca bilgisayarda bakmak içindir; telefondaki uygulama GitHub'daki sürümü gösterir.

---

## Yazar / kaynak eklemek ve çıkarmak

**Sadece adıyla (en kolayı):** Uygulamada **Kaynaklar → + Ekle → İsimle bul**'a bas, kişinin adını yaz. Program haber sitelerindeki köşe sayfasını, kişisel blogunu ve YouTube kanalını kendisi arar, birkaç dakika içinde bulduklarını ekler. Birden fazla kişiyi aynı anda eklemek için her ismi ayrı satıra yaz (virgülle ayırmak da olur). Bir çalışmada en çok 8 kişi aranır, fazlası sonraki yarım saate kalır.

**Adresi biliyorsan:** **+ Ekle → Adresi biliyorum**'a bas ve adresi yapıştır. Türü uygulama kendisi tanır:

| Yapıştırdığın | Tanınan tür |
|---|---|
| Gazete yazar sayfası | Köşe |
| `youtube.com/@kanal` ya da bir video bağlantısı | YouTube |
| Blog, Substack, Medium ya da RSS adresi | Blog / RSS |
| `bsky.app/profile/…` ya da `kullanici.bsky.social` | Bluesky |
| `t.me/kanaladi` | Telegram (yalnızca herkese açık kanallar) |
| `podcasts.apple.com/…` ya da `open.spotify.com/show/…` | Podcast |
| `eksisozluk.com/biri/…` ya da bir başlık | Ekşi Sözlük |
| `instagram.com/hesap` ya da `@hesap` | Instagram |

Var olan bir yazarın adını seçersen kaynak onun altına eklenir.
- **Kısayol:** YouTube uygulamasında bir kanalı, ya da Chrome'da bir yazarın sayfasını açıp **Paylaş → Takip** de. Form adres dolu olarak açılır.
- **Çıkarmak:** Yazarın ya da kaynağın yanındaki **⋯** düğmesine bas, sonra **Takipten çıkar** / **Bu kaynağı kaldır** seç. O kaynaktan gelmiş içerikler de akıştan hemen kalkar. Kapattıkların "Kapatılanlar" bölümünde durur, oradan geri açabilirsin.
- **Adresi değişen yazar:** **⋯ → Adresini değiştir** seç.

Değişiklik birkaç dakika içinde akışa yansır. Telefondan yapılanlar `kaynaklar_uygulama.json` dosyasında tutulur.

**Bilgisayardan (gelişmiş):** `kaynaklar.yaml` dosyasını da düzenleyebilirsin. GitHub'da dosyaya tıklayıp ✏️ simgesine bas ve mevcut örneklerden birini kopyala:

```yaml
  - ad: Yeni Yazar
    kaynaklar:
      - tur: sayfa
        url: https://www.gazete.com/yazarlar/yeni-yazar
        dogrula: true
```

Yeni türlerle ilgili bilmen gerekenler:
- **Bluesky:** Yalnızca kişinin kendi paylaşımları gelir, başkalarına yazdığı yanıtlar atlanır.
- **Telegram:** Kanalın herkese açık önizlemesi okunur, bu yüzden son 20 kadar mesaj görülür. Yarım saatte 20'den fazla mesaj atan kanallarda arada kalanlar kaçabilir.
- **Podcast:** Apple Podcasts bağlantısı en sağlam yoldur. Spotify bağlantısında program aynı podcasti Apple'ın listesinde arar; yalnızca Spotify'da yayınlanan podcastler bulunamayabilir.

**Instagram**, giriş yapmadan otomatik okumayı çoğu zaman engeller. Kalıcı çözüm için **rss.app** gibi bir servisten hesabın RSS adresini alıp telefondan **Blog / RSS** türüyle ekle.

## Konular — bir konudaki her şeyi yakala

Uygulamada **Kaynaklar → Konular → + Konu**'ya bas ve bir konu yaz (ör. *asgari ücret*, *Kanal İstanbul*). Aynı konu için birden fazla kelimeyi virgülle ayırarak yazabilirsin. Kelimenin ekli halleri de bulunur: "asgari ücret" yazarsan "asgari ücrete" de eşleşir.

- Takip ettiğin kişilerin bu konudaki yazıları akışta 🔖 etiketiyle işaretlenir. Akışın üstündeki 🔖 çiplerine dokunarak yalnızca o konuyu görebilirsin.
- **Haberlerde de ara** kutusunu işaretlersen, takip ettiğin kişilerin dışında Google Haberler'de bu konuda çıkan yeni haberler de akışa **Haber** etiketiyle gelir.
- Konuna uyan yeni bir şey çıkınca ayrıca, öncelikli bir bildirim gelir. Bunu konu bazında kapatabilirsin.
- Bir konuyu kaldırınca, onun için gelen haberler de akıştan düşer.

## Bildirimler

**Uygulama bildirimleri (önerilen):** Yeni yazılar Takip simgesiyle doğrudan telefonunun bildirimlerine gelir; ayrı bir uygulama gerekmez. Takip'in telefona uygulama olarak kurulu olması gerekir. Bir kez ayarlanır:
1. **Ayarlar → Bildirimler → Kuruluma başla**'ya bas. Uygulama bir bildirim anahtarı oluşturur ve sana gizli bir anahtar gösterir.
2. **Kopyala**'ya bas, sonra **GitHub'da gizli ayar ekleme sayfasını aç** bağlantısına dokun. **Name** kutusuna `VAPID_GIZLI` yaz, **Secret** kutusuna kopyaladığın anahtarı yapıştır ve **Add secret**'e bas.
3. Uygulamaya dön ve **Bu cihazda bildirimleri aç**'a bas, izin istediğinde **İzin ver** de.

Sıradaki kontrolde telefonuna "Takip bildirimleri açık ✓" diye bir deneme bildirimi gelir. Bilgisayarında da Takip'i açıp 3. adımı yaparsan bildirimler oraya da gelir. Gizli anahtar yalnızca GitHub'ın gizli ayarlarında durur, depoda görünmez; kimseyle paylaşma.

**ntfy ile (alternatif yol):** Aynı bölümdeki **ntfy ile bildirim** kısmını aç ve **ntfy bildirimlerini aç**'a bas. Ücretsiz **ntfy** uygulamasını kurman ve **ntfy'de abone ol** düğmesine dokunman yeterli. İkisi birden açıksa her bildirim iki kez gelir; birini kapat.

Açtıktan sonra aynı bölümden ince ayar yapabilirsin, sonra **Bildirim ayarlarını kaydet**'e bas:
- **Ne zaman:** Her yeni içerikte ya da yalnızca konularına uyanlarda.
- **Türler:** Örneğin Ekşi entry'leri ya da YouTube videoları için bildirim gelmesin.
- **Sabah bülteni:** Her gün seçtiğin saatte (ör. 08:00) son bültenden beri gelenleri kişiye göre toplayan tek bir bildirim gelir. Dokununca Günün özeti ekranı açılır. İstersen **Anlık bildirimleri kapat** kutusunu da işaretle; o zaman gün içinde yalnızca konularına uyan içerikler anında bildirilir, gerisi bültende toplanır. Bülten, GitHub'ın zamanlaması nedeniyle seçtiğin saatten sonraki yarım saat içinde gelir.
- **Sessiz saatler:** Örneğin 23:00–07:30 arası bildirim gelmez. Arada gelenler, sessiz saat bitince tek bildirimde toplanır.
- **Kişi bazında:** Kaynaklar'da bir kişinin ⋯ menüsünden **Bildirimlerini kapat**'ı seç. Yazıları akışta görünmeye devam eder; adının yanında 🔕 görünür. Bu kişinin bir yazısı konularından birine uyarsa yine bildirim gelir.

Tek bir yazı için gelen bildirime dokununca doğrudan yazı açılır.

## Sonra oku ve cihazlar arası eşitleme

Bir yazıyı sonra okumak için kartının sağ üstündeki ☆ işaretine dokun. Akışın üstündeki **★ Sonra oku** çipinde toplanırlar. Kaydettiğin yazılar 45 gün sonra akıştan düşse de bu listede kalır; okuduktan sonra ★'e dokunup çıkarabilirsin.

Okundu işaretlerini ve Sonra oku listeni telefonunla bilgisayarın arasında eşitleyebilirsin:
1. Her iki cihazda da Takip'i aç ve **Ayarlar → GitHub bağlantısı** bölümüne anahtarı gir (telefonda kullandığın anahtarı bilgisayarda da kullanabilirsin).
2. Birinci cihazda **Ayarlar → Cihazlar arası eşitleme** bölümünde bir parola belirle ve **Eşitlemeyi aç**'a bas.
3. Diğer cihazda aynı parolayı gir.

Bundan sonra uygulama her açılışta ve bir yazıyı okuduğunda ya da kaydettiğinde birkaç saniye içinde eşitlenir. Bu bilgiler depodaki ayrı bir **okundu** dalında, senin parolanla şifrelenmiş olarak durur; depo herkese açık olsa da kimse okuyamaz. Parolayı unutursan aynı bölümden yeni parola belirleyip baştan başlayabilirsin; bu cihazdaki işaretlerin kaybolmaz.

## Yazar sayfası

Akışta, Günün özeti ekranında ya da Kaynaklar'da bir yazarın adına dokun. Açılan sayfada şunlar var:
- Son 30 günde kaç içerik geldiği ve haftada ortalama kaç yazdığı.
- Kaynaklarının durumu ve varsa adres denetimi uyarısı.
- Son içerikleri, yapay zekâ özetleriyle.
- **Akışta yalnızca bunu göster**, **Bildirimleri kapat/aç** ve **Kaynakları düzenle** düğmeleri.

## Yapay zekâ özetleri (isteğe bağlı, ücretsiz)

Yeni köşe ve blog yazılarına Google Gemini ile üç cümlelik özet eklenir. Akışta **✨ Özet** olarak görünür, dokununca tamamı açılır. Bir kez ayarlanır; bilgisayardan daha kolay:

1. **aistudio.google.com/apikey** adresine Google hesabınla gir, **Create API key**'e bas ve çıkan anahtarı kopyala.
2. GitHub'da deponun **Settings → Secrets and variables → Actions** sayfasına git, **New repository secret**'a bas.
3. **Name** kutusuna `GEMINI_ANAHTAR` yaz, **Secret** kutusuna anahtarı yapıştır ve **Add secret**'e bas.

Sıradaki kontrolden itibaren yeni yazılar özetlenir. Durumu **Ayarlar → Yapay zekâ özetleri** bölümünde görürsün.

- Anahtar yalnızca GitHub'ın gizli ayarlarında durur; depoda ya da telefonda görünmez.
- Program, anahtarın erişebildiği modeller arasından uygun bir "Flash" modelini kendisi seçer. Google bir modeli emekliye ayırırsa yenisine kendiliğinden geçer.
- Her kontrolde en çok 10 yazı özetlenir. Günlük ücretsiz sınır dolarsa özetler birkaç saat ara verip kaldığı yerden devam eder.
- Sitesi doğrudan okunamayan (Google Haberler üzerinden takip edilen) yazarların yazıları özetlenemez.
- Gemini'ye yalnızca zaten yayımlanmış yazıların metni gönderilir. Ücretsiz kullanımda Google bu metinleri hizmetini geliştirmek için kullanabilir.

## Adres denetimi — yazarlar hâlâ aynı yerde mi?

Gazeteciler yer değiştirdiğinde eski sayfaları açılmaya devam eder. Bu yüzden program her çalışmada ayrıca şunlara bakar:

- **Sessizlik:** Bir yazardan 10 gündür yeni yazı gelmediyse uyarır. Haftada bir yazanlar için bu süre 16 gün; `kaynaklar.yaml` içinde yazara özel `sessizlik_gun:` ile değiştirilebilir.
- **Erişim:** Yazarın sayfası 6 saattir açılmıyorsa, ya da açılıp hiç yazı vermiyorsa uyarır.
- **Haber taraması:** Haftada bir Google Haberler'de yazarın adını tarar. Son 30 günde hangi sitelerde "X yazdı" şeklinde imzalı yazısı göründüğünü kaydeder. Sessiz kalan yazarlar 2–3 günde bir taranır.

Yazar sessizken imzalı yazıları başka bir sitede görünüyorsa, sayfanın en üstünde şöyle bir uyarı çıkar: **"⚠ Can Ataklı: 20 gündür yeni yazı gelmedi; imzalı yazıları X sitesinde görünüyor — adresini değiştirmen gerekebilir"**. Yanında örnek yazının bağlantısı da olur. Telefon bildirimini açtıysan aynı uyarı telefonuna da gelir. Her sorun bir kez bildirilir, tekrar tekrar gelmez.

Program adresi kendiliğinden değiştirmez. Haberlerde adı geçmek her zaman o sitede yazdığı anlamına gelmediği için son karar sende. Değişiklik gerekiyorsa uyarıdaki **Düzelt** düğmesine bas, ardından **⋯ → Adresini değiştir** seç.

Tüm yazarların durumu sayfanın altındaki **"Yazar adres denetimi"** bölümünde görünür: son yazı tarihi, haberlerde göründüğü siteler ve son tarama zamanı. Taramayı hemen yaptırmak için bilgisayarında `python takip.py --denetle` komutunu çalıştırabilirsin.

## Bir kaynak çalışmıyorsa

Akış sayfasının en altındaki **"Kaynakların durumu"** bölümüne bak:

- ✗ işareti, sitenin açılamadığını ya da engellediğini gösterir.
- ! işareti, sayfanın açıldığını ama yazı bulunamadığını gösterir. Bu durumda site tasarımı ya da adresi değişmiş olabilir.

Bilgisayarında `python takip.py --kontrol` komutunu çalıştırırsan her kaynağın kaç öğe bulduğunu ve ilk birkaç başlığı listeler. Bu komut hiçbir şey kaydetmez.

## Dosyalar

| Dosya | Ne işe yarar |
|---|---|
| `takip.py` | Programın kendisi |
| `kaynaklar.yaml` | Takip listesi ve ayarlar |
| `kaynaklar_uygulama.json` | Telefondan yapılan ekleme/çıkarmalar (uygulama yazar, elle düzenlemen gerekmez) |
| `uygulama/` | Telefon uygulamasının simgeleri ve çevrimdışı çalışma dosyaları |
| `sablon.html` | Uygulamanın ekranları |
| `veri/durum.json` | Daha önce görülen yazıların kaydı. Bulutta depodaki **veri** dalında tutulur; o dalı silersen her şey "ilk çalıştırma" sayılır. |
| `okundu` dalı | Eşitleme açıksa okundu işaretleri ve Sonra oku listesi (şifreli). Silersen eşitleme baştan başlar, cihazlardaki kayıtlar kaybolmaz. |
| `docs/` | Üretilen akış sayfası ve RSS |
| `.github/workflows/takip.yml` | Bulutta yarım saatlik otomatik çalışma |
| `calistir.bat`, `zamanlayici_kur.bat` | Windows'ta çalıştırma ve otomatik zamanlama |
