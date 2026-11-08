# Takip Akışı

Takip ettiğin yazarların yeni köşe yazılarını, YouTube videolarını, podcast bölümlerini, Bluesky ve Telegram paylaşımlarını, Ekşi Sözlük entry'lerini ve Instagram paylaşımlarını tek bir yerde toplar. Telefonuna uygulama olarak kurulur.

Uygulamanın üç ekranı var:
- **Akış:** Yeni içerikler en üstte, gün gün ayrılmış halde. Bir yazarın adına dokununca o yazarın sayfası açılır. Yazar filtresi, arama ve okundu işareti var. Yazar satırında **‹ ›** oklarıyla kayabilir ya da **☰ Yazar seç**'e dokunup listeden (isimle süzerek) seçebilirsin. Okunmuş bir yazının kartındaki **↺ Okunmadı yap** onu yeniden okunmamış yapar; Sağ üstteki **✓✓** görünenlerin hepsini okundu, yanındaki **◉** hepsini okunmadı sayar; ikisinden sonra da çıkan **Geri al** ile işlemi geri alabilirsin. Aşağı çekince yenilenir, internet yokken de son akışı gösterir. Kontroller 2 saatten uzun süredir yapılmadıysa en üstte uyarı çıkar.
- **Günün özeti (☀ düğmesi):** Son 24 saatte, 3 günde ya da 7 günde gelenler kişiye göre toplu halde, yapay zekâ özetleriyle.
- **Kaynaklar:** Yazar ya da kanal ekleyip çıkarırsın, bir kaynağın adresini değiştirirsin, bir kişinin adını düzeltirsin (⋯ → **Adını düzelt**). Telefonda YouTube'da ya da Chrome'da açtığın bir sayfayı **Paylaş → Takip** ile doğrudan ekleyebilirsin.
- **Ayarlar:** GitHub bağlantısı, cihazlar arası eşitleme ve "şimdi kontrol et" düğmesi.

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

**Sadece adıyla (en kolayı):** Uygulamada **Kaynaklar → + Ekle → İsimle bul**'a bas, kişinin adını yaz. Program haber sitelerindeki köşe sayfasını ve kişisel blogunu kendisi arar, birkaç dakika içinde bulduklarını ekler. Köşesi ya da blogu olan kişilerin YouTube kanalı eklenmez; yalnızca köşesi ya da blogu bulunamayanlar için YouTube kanalı aranır. Program, kişinin o sitede gerçekten kendi yazılarının çıktığını ve sayfanın son 4 ayda güncellendiğini doğrulamadan öneri yapmaz; önermediklerini gerekçesiyle yazar.

**Onay bekleyenler:** Program bulduklarını doğrudan takibe almaz. Kaynaklar'ın en üstündeki **Onay bekleyenler** bölümünde her öneri, neden önerildiği ve o kaynaktan gelen son 2-3 içeriğin başlığıyla görünür. Başlıklara dokunup kontrol edebilirsin. Doğru olanları işaretli bırakıp **Seçilenleri takip et**'e bas. Hiçbiri doğru değilse **Hiçbiri doğru değil**'e, adresi biliyorsan **Adresi elle ekle**'ye bas. Bekleyen öneri sayısı alttaki Kaynaklar simgesinde de görünür. Birden fazla kişiyi aynı anda eklemek için her ismi ayrı satıra yaz (virgülle ayırmak da olur). Bir çalışmada en çok 8 kişi aranır, fazlası sonraki yarım saate kalır.

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

**Başka kanallarda program yapan ya da konuk olan kişiler** (ör. futbol yorumcuları): **İsimle bul** ekranında **YouTube'da adının geçtiği programları da takip et** kutusunu işaretle. Program son bir haftanın YouTube videolarında kişinin adını arar; başlığında adı geçen yeni videolar, hangi kanalda olursa olsun akışa gelir ve kartta kanalın adı görünür. Zaten takip ettiğin biri için Kaynaklar'da adının yanındaki **⋯ → YouTube'da adının geçtiği programları ekle** de olur. İsimle bul köşe yazısı bulamazsa bu yolu kendiliğinden de dener. Kısa videolar (Shorts) alınmaz.
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

## Okundu işaretleri ve cihazlar arası eşitleme

Açtığın yazılar soluk görünür. Yanlışlıkla okundu sayılanı kartındaki **↺ Okunmadı yap** ile geri alabilirsin.

Okundu işaretlerini telefonunla bilgisayarın arasında eşitleyebilirsin:
1. Her iki cihazda da Takip'i aç ve **Ayarlar → GitHub bağlantısı** bölümüne anahtarı gir (telefonda kullandığın anahtarı bilgisayarda da kullanabilirsin).
2. Birinci cihazda **Ayarlar → Cihazlar arası eşitleme** bölümünde bir parola belirle ve **Eşitlemeyi aç**'a bas.
3. Diğer cihazda aynı parolayı gir.

Bundan sonra uygulama her açılışta ve bir yazıyı okuduğunda ya da okunmadı yaptığında birkaç saniye içinde eşitlenir. Bu bilgiler depodaki ayrı bir **okundu** dalında, senin parolanla şifrelenmiş olarak durur; depo herkese açık olsa da kimse okuyamaz. Parolayı unutursan aynı bölümden yeni parola belirleyip baştan başlayabilirsin; bu cihazdaki işaretlerin kaybolmaz.

## Yazar adını düzeltmek

Kaynaklar'da kişinin ⋯ menüsünden ya da yazar sayfasından **✏️ Adını düzelt**'e bas ve doğru yazılışı gir (ör. *ismail arı* → *İsmail Arı*). Sıradaki kontrolde ad her yerde değişir; geçmiş içerikler, okundu işaretleri ve kapattığın kaynaklar korunur. `kaynaklar.yaml`'daki kişilerde dosyanın kendisi değişmez; düzeltme `kaynaklar_uygulama.json` içinde `ad_esleme` altında saklanır. Başka birinin adını vermek engellenir.

## Yazar sayfası

Akışta, Günün özeti ekranında ya da Kaynaklar'da bir yazarın adına dokun. Açılan sayfada şunlar var:
- Son 30 günde kaç içerik geldiği ve haftada ortalama kaç yazdığı.
- Kaynaklarının durumu ve varsa adres denetimi uyarısı.
- Son içerikleri, yapay zekâ özetleriyle.
- **Kaynakları düzenle** ve **Adını düzelt** düğmeleri.

## Akışa hangi yazılar girer?

- Bir kaynak ilk eklendiğinde son **14 günün** yazıları (en az en yeni 3'ü) akışa konur ("yeni" sayılmaz).
- Sonraki her kontrolde yalnızca yeni yazılar eklenir. Yazının sayfasında tarih yoksa adresteki gün kullanılır (ör. `…/2026-10-23/…`); saati bilinmediği için kartta saat yazmaz.
- Sitenin listesinde sonradan beliren eski bir yazı ("çok okunanlar" kutusu gibi) 3 günden eskiyse "yeni" sayılmaz, 14 günden eskiyse hiç alınmaz.
- Akışta 45 günden eski içerik tutulmaz (yazının kendi tarihine bakılır).

## Doğrulama işareti (✓ / ?)

Kartlarda kaynağın yanında küçük bir işaret durur; dokununca açıklaması çıkar.
- **✓** — içeriğin o kişiye ait olduğu belli: yazının sayfasında imzası var, kişinin kendi yazı listesinden ya da kendi sitesi/kanalı/hesabından geldi, ya da Google Haberler üzerinden gelip adresi kişinin yazar klasöründe çıktı.
- **?** — emin değiliz: YouTube'da başlığında adı geçen program (konuk ya da konu olabilir), adresi doğrulanamayan Google Haberler sonucu, imza yerinde değil de yalnızca sayfanın bir yerinde adı geçen yazı, adresinde yazar adı olmayan bir sitede (ör. Dünya: `/kose-yazisi/…`) site açılmadığı için imzasına bakılamayan köşe yazısı.

Program, başlığında kişinin adının haber öznesi olarak geçtiği sayfaları ("X gözaltına alındı", "X adli kontrolle serbest bırakıldı") artık kişinin yazısı saymaz; "Ad Soyad | Başlık" ya da "… yorumladı" gibi imza kalıpları ise sorun değildir. Eski "İsimle bul" sürümünün yazar sayfası yerine tek bir haberi kaynak diye eklediği durumlar da kendiliğinden temizlenir; kişinin başka kaynağı kalmazsa yeniden aranır ve bulunanlar Onay bekleyenler'e düşer.

## Günlük kaynak taraması

Program her kişiyi günde bir kez yeniden arar (her kontrolde 2 kişi; yarım saatte bir çalıştığı için herkes gün içinde sırayla taranır). Takip ettiklerine ek olarak yeni bir köşe, blog ya da kanal bulursa onu doğrudan eklemez; son içerik örnekleriyle **Kaynaklar → Onay bekleyenler**'e koyar ve kartta "🔁 Günlük taramada bulundu" yazar.
- **Seçilenleri takip et** işaretlediklerini ekler; işaretlemediklerin bir daha önerilmez.
- **Hiçbirini ekleme** hepsini reddeder; mevcut kaynaklarına dokunmaz ve bunlar da bir daha önerilmez.
- Köşe yazısı ya da blogu takip edilen kişiler için YouTube kanalı önerilmez. Zaten takip edilen siteler yeniden denenmez.
- Ekşi başlıkları ve takipten çıkardığın kişiler taranmaz. Yazar sayfasında "yeni kaynak taraması … önce" satırı son taramanın ne zaman yapıldığını gösterir.
- Mevcut bağlantıların çalışıp çalışmadığı zaten her yarım saatte bir denetlenir; çalışmayanlar Kaynaklar'da uyarıyla görünür.

## Adres denetimi — yazarlar hâlâ aynı yerde mi?

Gazeteciler yer değiştirdiğinde eski sayfaları açılmaya devam eder. Bu yüzden program her çalışmada ayrıca şunlara bakar:

- **Sessizlik:** Bir yazardan 10 gündür yeni yazı gelmediyse uyarır. Haftada bir yazanlar için bu süre 16 gün; `kaynaklar.yaml` içinde yazara özel `sessizlik_gun:` ile değiştirilebilir.
- **Erişim:** Yazarın sayfası 6 saattir açılmıyorsa, ya da açılıp hiç yazı vermiyorsa uyarır.
- **Haber taraması:** Haftada bir Google Haberler'de yazarın adını tarar. Son 30 günde hangi sitelerde "X yazdı" şeklinde imzalı yazısı göründüğünü kaydeder. Sessiz kalan yazarlar 2–3 günde bir taranır.

Yazar sessizken imzalı yazıları başka bir sitede görünüyorsa, sayfanın en üstünde şöyle bir uyarı çıkar: **"⚠ Can Ataklı: 20 gündür yeni yazı gelmedi; imzalı yazıları X sitesinde görünüyor — adresini değiştirmen gerekebilir"**. Yanında örnek yazının bağlantısı da olur.

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
| `okundu` dalı | Eşitleme açıksa okundu işaretleri (şifreli). Silersen eşitleme baştan başlar, cihazlardaki kayıtlar kaybolmaz. |
| `docs/` | Üretilen akış sayfası ve RSS |
| `.github/workflows/takip.yml` | Bulutta yarım saatlik otomatik çalışma |
| `calistir.bat`, `zamanlayici_kur.bat` | Windows'ta çalıştırma ve otomatik zamanlama |
