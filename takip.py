#!/usr/bin/env python3
"""
Takip Akışı — takip ettiğin yazarların yeni yazılarını, videolarını,
Ekşi Sözlük entry'lerini ve Instagram paylaşımlarını tek bir sayfada toplar.

Kullanım:
    python takip.py                 # kaynakları kontrol et, akış sayfasını üret
    python takip.py --kontrol       # her kaynağı dene, kaç öğe bulduğunu yaz (hiçbir şey kaydetmez)
    python takip.py --ayar dosya.yaml

Çıktılar:
    docs/index.html   → telefondan/bilgisayardan açacağın akış sayfası
    docs/akis.xml     → aynı akışın RSS hali (RSS okuyucu uygulamaları için)
    veri/durum.json   → daha önce görülenlerin kaydı (silme; silersen her şey "ilk çalıştırma" olur)
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse, quote

import yaml
from bs4 import BeautifulSoup

try:  # Tarayıcı taklidi yapan istemci: bot korumalarına daha az takılır
    from curl_cffi import requests as http_cffi  # type: ignore
except Exception:  # pragma: no cover
    http_cffi = None
import requests as http_std

try:
    import feedparser
except Exception:  # pragma: no cover
    feedparser = None

KOK = Path(__file__).resolve().parent
TR_SAAT = timezone(timedelta(hours=3))
TARAYICI_BASLIKLARI = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
}
TUR_ETIKETLERI = {
    "yazi": "Yazı",
    "video": "Video",
    "paylasim": "Paylaşım",
    "podcast": "Podcast",
    "eksi": "Ekşi",
    "instagram": "Instagram",
    "haber": "Haber",
}


# ───────────────────────── yardımcılar ─────────────────────────

def simdi() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds") if dt else None


_URL_TARIHI = re.compile(r"(?<!\d)(20\d\d)[-/_](0[1-9]|1[0-2])[-/_](0[1-9]|[12]\d|3[01])(?!\d)")


TERK_EDILMIS_GUN = 120   # en yeni yazısı bundan eskiyse kaynak "artık yazmıyor" uyarısı verir
ESKI_YAZI_GUN = 3   # bundan eski tarihli bir yazı ilk kez görülürse "yeni" sayılmaz
ILK_GOSTERIM_GUN = 14   # kaynak eklenince bu kadar günlük yazılar akışa (bildirimsiz) konur
PENCERE_EN_FAZLA = 12


def url_tarihi(url: str) -> datetime | None:
    """Adreste yazının günü varsa (…/2026-10-23/… ya da …/2026/10/23/…) onu döndürür (saat bilinmez)."""
    m = _URL_TARIHI.search(urlparse(url).path)
    if not m:
        return None
    try:
        dt = datetime(int(m[1]), int(m[2]), int(m[3]), 12, tzinfo=TR_SAAT)   # saat bilinmiyor: gün ortası
    except ValueError:
        return None
    return dt if dt <= simdi() + timedelta(days=1) else None


def iso_oku(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=TR_SAAT)
    except Exception:
        pass
    try:
        return parsedate_to_datetime(s)
    except Exception:
        return None


def sade(metin: str) -> str:
    """Türkçe karakterleri sadeleştirip küçük harfe çevirir (karşılaştırma için)."""
    metin = (metin or "").replace("İ", "i").replace("I", "ı").lower()
    metin = metin.translate(str.maketrans("ışğüöç", "isguoc"))
    metin = unicodedata.normalize("NFKD", metin)
    metin = "".join(c for c in metin if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", metin).strip()


def bosluk(metin: str | None) -> str:
    return re.sub(r"\s+", " ", metin or "").strip()


def kisalt(metin: str, n: int) -> str:
    metin = bosluk(metin)
    return metin if len(metin) <= n else metin[: n - 1].rsplit(" ", 1)[0] + "…"


def url_temizle(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc.lower(), p.path, p.params, p.query, ""))


def kimlik(*parcalar: str) -> str:
    return hashlib.sha1("|".join(parcalar).encode("utf-8")).hexdigest()[:12]


class KaynakHatasi(Exception):
    pass


# ───────────────────────── ağ ─────────────────────────

class Istemci:
    def __init__(self, bekleme: float = 0.7, zaman_asimi: int = 25):
        self.bekleme = bekleme
        self.zaman_asimi = zaman_asimi
        self._son_istek: dict[str, float] = {}
        self.oturum_cffi = http_cffi.Session(impersonate="chrome") if http_cffi else None
        self.oturum_std = http_std.Session()
        self.oturum_std.headers.update(TARAYICI_BASLIKLARI)

    def _nazik_ol(self, url: str):
        host = urlparse(url).netloc
        gecen = time.time() - self._son_istek.get(host, 0)
        if gecen < self.bekleme:
            time.sleep(self.bekleme - gecen)
        self._son_istek[host] = time.time()

    def al(self, url: str, basliklar: dict | None = None, deneme: int = 2) -> str:
        son_hata = None
        for i in range(deneme + 1):
            self._nazik_ol(url)
            try:
                if self.oturum_cffi is not None:
                    r = self.oturum_cffi.get(url, headers=basliklar or {}, timeout=self.zaman_asimi,
                                             allow_redirects=True)
                else:
                    r = self.oturum_std.get(url, headers=basliklar or {}, timeout=self.zaman_asimi)
                if r.status_code == 200 and r.content:
                    if not r.encoding or r.encoding.lower() == "iso-8859-1":
                        try:
                            return r.content.decode("utf-8")
                        except UnicodeDecodeError:
                            pass
                    return r.text
                son_hata = f"HTTP {r.status_code}"
                if r.status_code in (401, 403, 404, 410, 451):
                    break  # tekrar denemenin anlamı yok
            except Exception as e:  # bağlantı hataları
                son_hata = type(e).__name__ + ": " + str(e)[:150]
            time.sleep(2 * (i + 1))
        raise KaynakHatasi(f"{url} alınamadı ({son_hata})")

    def gonder(self, url: str, veri: bytes, basliklar: dict):
        return http_std.post(url, data=veri, headers=basliklar, timeout=15)

    def postala(self, url: str, veri: str, basliklar: dict) -> str:
        """Tarayıcı oturumuyla (aynı çerezlerle) POST isteği; yanıt metnini döndürür."""
        self._nazik_ol(url)
        oturum = self.oturum_cffi if self.oturum_cffi is not None else self.oturum_std
        r = oturum.post(url, data=veri, headers=basliklar, timeout=self.zaman_asimi)
        if r.status_code != 200:
            raise KaynakHatasi(f"{url} yanıt vermedi (HTTP {r.status_code})")
        return r.text


# ───────────────────────── okuyucular ─────────────────────────
# Her okuyucu şu sözlüklerin listesini döndürür:
#   {"url", "baslik", "ozet"?, "tarih"?, "tur"}

def sayfa_oku(ist: Istemci, k: dict, durum: dict, yazar: str) -> list[dict]:
    url = k.get("url")
    if k.get("yazar_dizini"):
        url = yazar_sayfasini_bul(ist, k["yazar_dizini"], k.get("bul") or yazar, durum)
    if not url:
        raise KaynakHatasi("sayfa adresi yok")
    durum.pop("yedek", None)
    try:
        html_metin = ist.al(url)
    except KaynakHatasi as e:
        # Bazı siteler (ör. Cloudflare arkasındakiler) bulut sunucularını engeller.
        # O zaman yazarın o sitedeki yazılarını Google Haberler üzerinden buluruz.
        if k.get("yedek", True) is False or not re.search(r"HTTP (403|429|503)", str(e)):
            raise
        ogeler = google_haber_oku(ist, k.get("bul") or yazar, _alan_adi(url))
        durum["yedek"] = "google_haber"
        ogeler = yedek_sonuclarini_suz(ist, ogeler, k, url, durum, ad=k.get("bul") or yazar)
        return ogeler[: int(k.get("en_fazla", 25))]
    corba = BeautifulSoup(html_metin, "html.parser")

    desen = k.get("link_deseni") or SITE_YAZI_DESENLERI.get(_alan_adi(url))
    tahmini = False
    if desen:
        rx = re.compile(desen)
        adaylar = _linkleri_topla(corba, url, lambda u: bool(rx.search(u)))
    else:
        yol = urlparse(url).path.rstrip("/")
        on_ek = yol + "/"
        adaylar = _linkleri_topla(
            corba, url,
            lambda u: urlparse(u).netloc == urlparse(url).netloc and urlparse(u).path.startswith(on_ek)
            and len(urlparse(u).path) > len(on_ek) + 3,
        )
        if not adaylar:
            adaylar = _linkleri_topla(corba, url, lambda u: _makaleye_benziyor(u, url))
            tahmini = True
    if tahmini:
        durum["tahmini"] = True
    for a in adaylar:
        a["tur"] = "yazi"
    return adaylar[: int(k.get("en_fazla", 25))]


def google_haber_oku(ist: Istemci, ad: str, site: str) -> list[dict]:
    """Google Haberler'de "<ad>" site:<site> aramasıyla son 30 günün yazılarını getirir."""
    if feedparser is None:
        raise KaynakHatasi("feedparser kurulu değil")
    # Google bir aramada en çok 100 sonuç verir. Kişinin adı sitenin her sayfasında geçiyorsa (ör. Medyascope)
    # 30 günlük aramanın ilk 100'üne yeni yazılar girmeyebilir; bu yüzden son 3 gün ayrıca aranır.
    girdiler, gorulen_link, hata = [], set(), None
    for sure in ("3d", "30d"):
        sorgu = quote(f'"{ad}" site:{site} when:{sure}')
        try:
            metin = ist.al(f"https://news.google.com/rss/search?q={sorgu}&hl=tr&gl=TR&ceid=TR:tr", deneme=1)
        except KaynakHatasi as e:
            hata = e
            continue
        for e in feedparser.parse(metin).entries:
            if e.get("link") and e["link"] not in gorulen_link:
                gorulen_link.add(e["link"])
                girdiler.append(e)
    if hata and not girdiler:
        raise KaynakHatasi(f"site bulut sunucularını engelliyor ve Google Haberler yedeği de açılamadı ({hata})")
    sonuc = []
    for e in girdiler:
        baslik = re.sub(r"\s+-\s+[^-]{1,40}$", "", e.get("title", "")).strip()
        ham_baslik = baslik          # imza kalıbına bakmak için ("Ruşen Çakır yorumladı: …")
        # "Can Ataklı yazdı: ..." / "... | Can Ataklı" gibi ekleri at
        baslik = re.sub(r"^" + re.escape(ad) + r"\s*(yazdı)?\s*[:|-]\s*", "", baslik, flags=re.I)
        baslik = re.sub(r"\s*[|-]\s*" + re.escape(ad) + r"\s*$", "", baslik, flags=re.I).strip()
        if not baslik or not e.get("link"):
            continue
        tarih = datetime(*e["published_parsed"][:6], tzinfo=timezone.utc) if e.get("published_parsed") else None
        sonuc.append({"url": e["link"], "baslik": kisalt(baslik, 200), "tarih": iso(tarih), "tur": "yazi",
                      "_yedek": True, "_gn_baslik": ham_baslik})
    sonuc.sort(key=lambda o: o.get("tarih") or "", reverse=True)
    return sonuc


# Google Haberler bağlantıları (news.google.com/rss/articles/…) asıl adresi gizler. Bazı sitelerde
# yazarın adı her sayfanın kenarında geçtiği için "<ad>" araması sitenin bütün haberlerini getirir
# (ör. Oksijen). Bu yüzden her bağlantının asıl adresini çözüp yalnızca yazarın kendi yazılarını alırız.
GN_COZUM_SINIRI = 40          # bir kaynak için bir çalışmada en çok kaç bağlantı çözülsün
_GN_DURDUR = {"evet": False}  # Google sınır koyarsa o çalışmada çözmeyi bırak


def _gn_kimlik(u: str) -> str | None:
    m = re.search(r"news\.google\.com/(?:rss/)?(?:articles|read)/([A-Za-z0-9_-]+)", u or "")
    return m.group(1) if m else None


def google_haber_adresi_coz(ist: Istemci, gn_url: str, onbellek: dict) -> str | None:
    """news.google.com bağlantısının gittiği asıl adresi bulur; bulamazsa None."""
    m = re.search(r"news\.google\.com/(?:rss/)?(?:articles|read)/([A-Za-z0-9_-]+)", gn_url)
    if not m:
        return gn_url
    kimlik_ = m.group(1)
    if onbellek.get(kimlik_):
        return onbellek[kimlik_]
    if _GN_DURDUR["evet"]:
        return None
    try:
        imza = zaman = None
        for adres in (f"https://news.google.com/articles/{kimlik_}?hl=tr&gl=TR&ceid=TR:tr",
                      f"https://news.google.com/rss/articles/{kimlik_}?hl=tr&gl=TR&ceid=TR:tr"):
            try:
                c = BeautifulSoup(ist.al(adres, deneme=0), "html.parser")
            except KaynakHatasi as e:
                if "HTTP 429" in str(e):
                    _GN_DURDUR["evet"] = True
                    return None
                continue
            d = c.select_one("c-wiz > div[jscontroller]") or c.select_one("[data-n-a-sg]")
            if d is not None and d.get("data-n-a-sg") and d.get("data-n-a-ts"):
                imza, zaman = d["data-n-a-sg"], d["data-n-a-ts"]
                break
        if not imza:
            return None
        istek = ["Fbv4je", '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
                           f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{kimlik_}",{zaman},"{imza}"]']
        yanit = ist.postala("https://news.google.com/_/DotsSplashUi/data/batchexecute",
                            "f.req=" + quote(json.dumps([[istek]])),
                            {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        gercek = _batchexecute_adresi(yanit)
        if isinstance(gercek, str) and gercek.startswith("http"):
            onbellek[kimlik_] = gercek
            return gercek
    except KaynakHatasi as e:
        if "HTTP 429" in str(e):
            _GN_DURDUR["evet"] = True
    except Exception:
        pass
    return None


def _yedek_notu(kd: dict) -> str:
    n = "Site doğrudan okunmaya izin vermiyor; Google Haberler üzerinden takip ediliyor"
    c = kd.get("yedek_cozum") or {}
    if c.get("cozulen", 0) >= 3 and not c.get("yazara_ait"):
        return (f"Bu sitede kişinin kendi yazısı bulunamadı (son taramada {c['cozulen']} sonucun hiçbiri onun değil); "
                "büyük olasılıkla yanlış eşleşme, bu kaynağı kaldırman önerilir")
    if c.get("cozulen"):
        diger = c["cozulen"] - c["yazara_ait"]
        n += f". Son taramada {c['yazara_ait']} yazı yazara ait" + (f", {diger} başka haber elendi" if diger else "")
    if c.get("atlanan"):
        n += f"; adresi çözülemeyen {c['atlanan']} sonuç güvenli olmadığı için alınmadı"
    return n


def _batchexecute_adresi(yanit: str) -> str | None:
    """Google'ın batchexecute yanıtından garturlres içindeki adresi çıkarır."""
    govde = yanit.split("\n\n", 1)[1] if "\n\n" in yanit else yanit
    i = govde.find("[")
    while i != -1:
        try:
            veri, _ = json.JSONDecoder().raw_decode(govde[i:])
        except ValueError:
            i = govde.find("[", i + 1)
            continue
        for satir in veri if isinstance(veri, list) else []:
            if isinstance(satir, list) and len(satir) > 2 and satir[0] == "wrb.fr" and isinstance(satir[2], str):
                ic = json.loads(satir[2])
                if isinstance(ic, list) and len(ic) > 1 and ic[0] == "garturlres":
                    return ic[1]
        i = govde.find("[", i + len(json.dumps(veri)))
    m = re.search(r'garturlres\\",\\"(https?://[^"\\]+)', yanit)
    return m.group(1) if m else None


# Köşe yazısı adresinde yazarın adı geçmeyen siteler: yazı adresinin biçimi (yazar sayfası okunurken ve
# Google Haberler yedeğinde kullanılır; yazının kime ait olduğuna sayfadaki imzayla bakılır)
SITE_YAZI_DESENLERI = {
    "dunya.com": r"dunya\.com/kose-yazisi/[^/?#]+/\d+",
}
# Diğer sitelerde de "köşe yazısı" klasöründeki adresler imza denetimine aday sayılır
GENEL_KOSE_YOLU = re.compile(r"/(kose-yazisi|kose-yazilari|kose-yazari|koseyazisi)/[^/?#]+")
IMZA_DENETIM_SINIRI = 6       # bir kaynak için bir çalışmada en çok kaç yazının imzasına bakılsın


def baslikta_imza_var(baslik: str, ad: str) -> bool:
    """Başlık kişinin imzasını taşıyor mu? "Ruşen Çakır yorumladı: …", "Can Ataklı yazdı | …", "… | Ruşen Çakır"."""
    b, a = sade(baslik), sade(ad)
    if not a or a not in b:
        return False
    return bool(re.search(r"(?:^|[|:\-\u2013\u2014]\s*)" + re.escape(a) + r"\s+(?:" + IMZA_EKLERI + r")\b", b)
                or re.search(r"[|\u2013\u2014]\s*" + re.escape(a) + r"\s*$", b))


def yedek_sonuclarini_suz(ist: Istemci, ogeler: list[dict], k: dict, sayfa_url: str, kd: dict,
                          ad: str | None = None) -> list[dict]:
    """Google Haberler yedeğinden gelenleri asıl adreslerine göre süzer: yalnızca yazarın kendi yazıları.
    Adresinde yazarın adı olmayan köşe yazılarında (ör. dunya.com/kose-yazisi/…) yazı açılıp imzaya bakılır;
    site açılmıyorsa yazı "?" (doğrulanamadı) işaretiyle alınır."""
    desen = re.compile(k["link_deseni"]) if k.get("link_deseni") else None
    on_ek = urlparse(sayfa_url).path.rstrip("/") + "/"
    site_deseni = SITE_YAZI_DESENLERI.get(_alan_adi(sayfa_url))
    kose_deseni = re.compile(site_deseni) if site_deseni else GENEL_KOSE_YOLU
    imza_kaydi = kd.setdefault("imza_cozum", {})
    imza_butce = [IMZA_DENETIM_SINIRI]

    def yazara_ait(u: str) -> bool:
        return bool(desen.search(u)) if desen else (urlparse(u).path.startswith(on_ek) and len(urlparse(u).path) > len(on_ek) + 3)

    def imza_karari(o: dict, gercek: str) -> str | None:
        """imza / ad_sayfada / belirsiz / baslik_imzasi (kabul) ya da red; bakılamadıysa None."""
        if ad and baslikta_imza_var(o.get("_gn_baslik") or "", ad):
            return "baslik_imzasi"   # adresinde adı yok ama başlığı "Ruşen Çakır yorumladı: …" biçiminde
        if not ad or not kose_deseni.search(gercek):
            return "red"
        karar = imza_kaydi.get(gercek)
        if karar is None:
            if imza_butce[0] <= 0:
                return None
            imza_butce[0] -= 1
            gecici = {"url": gercek, "baslik": o.get("baslik", "")}
            try:
                tamam = ayrinti_getir(ist, gecici, ad)
                ym = sade(gecici.get("_yazar_meta") or "")
                # yazar etiketinde bir kişi adı var mı (site/kurum adı değil)?
                kisi_adi = 2 <= len(ym.split()) <= 4 and not re.search(
                    r"gazete|haber|news|medya|ajans|\btv\b|editor|redaksiyon|dunya|\.com|\.tr", ym)
                baska_imza = kisi_adi and not gecici.get("_imza")
                # sayfada başka birinin imzası varsa (adı yalnızca metinde geçiyorsa) onun yazısı değildir
                karar = ("imza" if gecici.get("_imza") else "red" if baska_imza else "ad_sayfada") if tamam else "red"
                if tamam:
                    for alan in ("baslik", "ozet", "tarih"):
                        if gecici.get(alan):
                            o[alan] = gecici[alan]
            except Exception:
                karar = "belirsiz"          # site yazıyı da açtırmıyor: adıyla aranınca çıkan köşe yazısı
            imza_kaydi[gercek] = karar
            if len(imza_kaydi) > 300:
                for eski in list(imza_kaydi)[:-300]:
                    imza_kaydi.pop(eski, None)
        return karar

    onbellek = kd.setdefault("gn_cozum", {})
    red = list(kd.get("yedek_red") or [])
    sonuc, cozulemeyen = [], []
    cozulen = reddedilen = 0
    butce = GN_COZUM_SINIRI
    for o in ogeler:
        m = re.search(r"/articles/([A-Za-z0-9_-]+)", o["url"])
        onceden = bool(m and onbellek.get(m.group(1)))
        gercek = None
        if onceden or butce > 0:
            gercek = google_haber_adresi_coz(ist, o["url"], onbellek)
            if not onceden:
                butce -= 1
        if gercek:
            cozulen += 1
            if yazara_ait(gercek):
                gk = _gn_kimlik(o["url"])
                if gk in red:          # kural genişlediyse önceden elenmiş olan artık kabul edilir
                    red.remove(gk)
                    o["_kural_genisledi"] = True
                o["gn_url"], o["url"] = o["url"], url_temizle(gercek)
                son_parca = urlparse(gercek).path.rstrip("/").rsplit("/", 1)[-1]
                # ".../ad-soyad-yazdi-..." gibi başlık kalıbıyla mı, yazarın klasöründen mi tanındı
                o["_dogrulama"] = ("baslik_kalibi" if re.search(r"-(" + IMZA_EKLERI + r")(-|$)", son_parca) else "yazar_klasoru")
                sonuc.append(o)
            else:
                karar = imza_karari(o, gercek)
                if karar in ("imza", "ad_sayfada", "belirsiz", "baslik_imzasi"):
                    gk = _gn_kimlik(o["url"])
                    if gk in red:
                        red.remove(gk)
                        o["_kural_genisledi"] = True
                    o["gn_url"], o["url"] = o["url"], url_temizle(gercek)
                    o["_dogrulama"] = karar
                    sonuc.append(o)
                    continue
                if karar is None:      # bu çalışmada imzaya bakma hakkı bitti; sonra yeniden denenir
                    continue
                reddedilen += 1
                gk = _gn_kimlik(o["url"])
                if gk and gk not in red:
                    red.append(gk)
        else:
            cozulemeyen.append(o)
    # Çözülebilenlerin çoğu yazara ait değilse bu site "ad her sayfada" türündendir:
    # çözülemeyenleri de güvenilmez sayıp almayız (yaml'da yedek_dogrula: true ile de zorlanabilir).
    if cozulen >= 3:
        kd["ad_her_sayfada"] = reddedilen > cozulen / 2
    if "yedek_cozum" not in kd or kd.get("ad_her_sayfada"):   # geriye dönük bulunanlar bildirim yaratmasın
        esik = iso(simdi() - timedelta(days=2))
        for o in sonuc:
            if (o.get("tarih") or "") < esik:
                o["_eski"] = True
    guvenme = k.get("yedek_dogrula") or kd.get("ad_her_sayfada")
    if cozulemeyen and not guvenme:
        for o in cozulemeyen:
            o["_dogrulama"] = "belirsiz"
        sonuc += cozulemeyen
    kd["yedek_red"] = red[-400:]
    kd["gn_cozum"] = dict(list(onbellek.items())[-600:])
    kd["yedek_cozum"] = {"cozulen": cozulen, "yazara_ait": cozulen - reddedilen, "cozulemeyen": len(cozulemeyen),
                         "atlanan": len(cozulemeyen) if guvenme else 0}
    sonuc.sort(key=lambda o: o.get("tarih") or "", reverse=True)
    return sonuc


def _makaleye_benziyor(u: str, sayfa: str) -> bool:
    p, s = urlparse(u), urlparse(sayfa)
    if p.netloc != s.netloc or u.rstrip("/") == sayfa.rstrip("/"):
        return False
    son = p.path.rstrip("/").rsplit("/", 1)[-1]
    if not son or any(x in p.path for x in ("/etiket", "/kategori", "/tag/", "/uye", "/giris", "/arama")):
        return False
    return son.count("-") >= 3 or bool(re.search(r"\d{4,}$", son))


def _linkleri_topla(corba: BeautifulSoup, taban: str, uygun) -> list[dict]:
    sirali: list[str] = []
    bilgi: dict[str, dict] = {}
    for a in corba.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("javascript:", "mailto:", "#")):
            continue
        u = url_temizle(urljoin(taban, href))
        if not uygun(u):
            continue
        baslik = _baglanti_basligi(a)
        if u not in bilgi:
            sirali.append(u)
            bilgi[u] = {"url": u, "baslik": baslik}
        elif len(baslik) > len(bilgi[u]["baslik"]) and len(baslik) < 200:
            bilgi[u]["baslik"] = baslik
    return [bilgi[u] for u in sirali]


def _baglanti_basligi(a) -> str:
    for etiket in ("h1", "h2", "h3", "h4", "h5", "strong"):
        h = a.find(etiket)
        if h and len(bosluk(h.get_text())) > 3:
            return kisalt(h.get_text(" "), 180)
    if a.get("title") and len(a["title"].strip()) > 3:
        return kisalt(a["title"], 180)
    metin = bosluk(a.get_text(" "))
    metin = re.sub(r"\s*Devamını Oku.*$", "", metin, flags=re.I)
    return kisalt(metin, 180)


def yazar_sayfasini_bul(ist: Istemci, dizin: str, ad: str, durum: dict) -> str:
    ekstra = durum.setdefault("ekstra", {})
    if ekstra.get("yazar_sayfasi"):
        return ekstra["yazar_sayfasi"]
    corba = BeautifulSoup(ist.al(dizin), "html.parser")
    hedef = sade(ad)
    for a in corba.find_all("a", href=True):
        if hedef in sade(a.get_text(" ")) or hedef in sade(a.get("title", "")):
            u = url_temizle(urljoin(dizin, a["href"]))
            if u.rstrip("/") != dizin.rstrip("/"):
                ekstra["yazar_sayfasi"] = u
                return u
    raise KaynakHatasi(f"'{ad}' için yazar sayfası {dizin} içinde bulunamadı")


def rss_oku(ist: Istemci, k: dict, durum: dict, yazar: str) -> list[dict]:
    if feedparser is None:
        raise KaynakHatasi("feedparser kurulu değil")
    url = k.get("url")
    try:
        metin = ist.al(url)
        akis = feedparser.parse(metin)
        if not akis.entries:
            raise KaynakHatasi("akışta öğe yok")
    except KaynakHatasi:
        if not k.get("kesfet"):
            raise
        url = rss_kesfet(ist, k["kesfet"])
        akis = feedparser.parse(ist.al(url))
    filtre = [sade(x) for x in _liste(k.get("yazar_filtresi"))]
    sonuc = []
    for e in akis.entries:
        if filtre:
            yazan = sade(e.get("author", "") + " " + " ".join(a.get("name", "") for a in e.get("authors", [])))
            if not any(f in yazan for f in filtre):
                continue
        link = e.get("link")
        if not link:
            continue
        tarih = None
        for alan in ("published_parsed", "updated_parsed"):
            if e.get(alan):
                tarih = datetime(*e[alan][:6], tzinfo=timezone.utc)
                break
        ozet = bosluk(BeautifulSoup(e.get("summary", "") or "", "html.parser").get_text(" "))
        baslik = bosluk(e.get("title", ""))
        if not baslik or baslik == link:  # başlıksız paylaşımlar (Bluesky vb.): metnin kendisi başlık olur
            baslik, ozet = paylasim_bol(ozet) if ozet else (link, "")
        oge = {"url": url_temizle(link), "baslik": kisalt(baslik, 300),
               "ozet": kisalt(ozet, 260), "tarih": iso(tarih), "tur": k.get("icerik_turu", "yazi")}
        sonuc.append(oge)
    return sonuc


def paylasim_bol(metin: str) -> tuple[str, str]:
    """Başlıksız paylaşım metnini başlık + devamı olarak böler; aynı metin iki kez görünmesin."""
    metin = metin.strip()
    if len(metin) <= 300:
        return metin, ""
    kes = metin.rfind(" ", 0, 160)
    kes = kes if kes > 80 else 160
    return metin[:kes].rstrip(" ,;:") + "…", "…" + kisalt(metin[kes:].strip(), 300)


def bluesky_oku(ist: Istemci, k: dict, durum: dict, yazar: str) -> list[dict]:
    """Bluesky profilinin kendi RSS akışı: bsky.app/profile/<hesap>/rss"""
    hesap = (k.get("kullanici") or "").lstrip("@").strip()
    if not hesap:
        raise KaynakHatasi("Bluesky hesap adı yok")
    ogeler = rss_oku(ist, {"url": f"https://bsky.app/profile/{hesap}/rss", "icerik_turu": "paylasim"}, durum, yazar)
    if not k.get("yanitlar_dahil"):
        ogeler = [o for o in ogeler if not o["baslik"].startswith("@")]
    return ogeler


def telegram_oku(ist: Istemci, k: dict, durum: dict, yazar: str) -> list[dict]:
    """Herkese açık Telegram kanalının önizleme sayfası: t.me/s/<kanal> (son ~20 mesaj)"""
    kanal = (k.get("kullanici") or "").lstrip("@").strip()
    if not kanal:
        raise KaynakHatasi("Telegram kanal adı yok")
    corba = BeautifulSoup(ist.al(f"https://t.me/s/{quote(kanal)}"), "html.parser")
    sonuc = []
    for m in corba.select(".tgme_widget_message[data-post]"):
        no = m["data-post"].split("/")[-1]
        metin_el = m.select_one(".tgme_widget_message_text")
        metin = bosluk(metin_el.get_text(" ")) if metin_el else ""
        if not metin:
            onizleme = m.select_one(".link_preview_title")
            metin = bosluk(onizleme.get_text(" ")) if onizleme else ("(fotoğraf/video)" if m.select_one(
                ".tgme_widget_message_photo_wrap, video") else "")
        if not metin:
            continue
        zaman = m.select_one("time[datetime]")
        baslik, ozet = paylasim_bol(metin)
        sonuc.append({"url": f"https://t.me/{kanal}/{no}", "baslik": baslik, "ozet": ozet,
                      "tarih": iso(iso_oku(zaman["datetime"])) if zaman else None, "tur": "paylasim"})
    if not sonuc and not corba.select_one(".tgme_channel_info, .tgme_widget_message"):
        raise KaynakHatasi("kanal bulunamadı ya da herkese açık değil")
    sonuc.reverse()  # sayfa eskiden yeniye sıralı
    return sonuc


def podcast_oku(ist: Istemci, k: dict, durum: dict, yazar: str) -> list[dict]:
    """Apple Podcasts / Spotify bağlantısından ya da doğrudan RSS'ten podcast bölümleri."""
    ekstra = durum.setdefault("ekstra", {})
    akis = k.get("rss_url") or ekstra.get("akis")
    adres = k.get("url") or ""
    if not akis:
        m = re.search(r"podcasts\.apple\.com/.*?/id(\d+)", adres)
        if m:
            j = json.loads(ist.al(f"https://itunes.apple.com/lookup?id={m.group(1)}&entity=podcast"))
            akis = next((x.get("feedUrl") for x in j.get("results", []) if x.get("feedUrl")), None)
        elif "spotify.com/show/" in adres:
            corba = BeautifulSoup(ist.al(adres), "html.parser")
            og = corba.find("meta", attrs={"property": "og:title"})
            ad = bosluk(og["content"]) if og and og.get("content") else ""
            if not ad:
                raise KaynakHatasi("Spotify podcast adı okunamadı")
            j = json.loads(ist.al("https://itunes.apple.com/search?media=podcast&limit=10&term=" + quote(ad)))
            akis = next((x.get("feedUrl") for x in j.get("results", [])
                         if x.get("feedUrl") and sade(x.get("collectionName", "")) == sade(ad)), None)
            if not akis:
                raise KaynakHatasi(f"'{ad}' Spotify'a özel olabilir; Apple Podcasts'ta bulunamadı")
        else:
            akis = adres
        if not akis:
            raise KaynakHatasi("podcast akışı bulunamadı")
        ekstra["akis"] = akis
    return rss_oku(ist, {"url": akis, "icerik_turu": "podcast"}, durum, yazar)


def rss_kesfet(ist: Istemci, sayfa: str) -> str:
    corba = BeautifulSoup(ist.al(sayfa), "html.parser")
    for l in corba.find_all("link", rel=True, href=True):
        tip = (l.get("type") or "").lower()
        if "alternate" in [r.lower() for r in l["rel"]] and ("rss" in tip or "atom" in tip):
            return urljoin(sayfa, l["href"])
    raise KaynakHatasi(f"{sayfa} içinde RSS bağlantısı bulunamadı")


def youtube_oku(ist: Istemci, k: dict, durum: dict, yazar: str) -> list[dict]:
    ekstra = durum.setdefault("ekstra", {})
    kanal = k.get("kanal_id") or ekstra.get("kanal_id")
    if not kanal:
        adres = k.get("kanal") or k.get("url")
        if not adres:
            raise KaynakHatasi("YouTube kanal adresi yok")
        if not adres.startswith("http"):
            adres = "https://www.youtube.com/" + (adres if adres.startswith("@") else "@" + adres)
        sayfa = ist.al(adres, basliklar={"Cookie": "CONSENT=YES+1; SOCS=CAI"})
        m = (re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', sayfa)
             or re.search(r'"externalId":"(UC[\w-]{22})"', sayfa)
             or re.search(r'"channelId":"(UC[\w-]{22})"', sayfa))
        if not m:
            raise KaynakHatasi("YouTube kanal kimliği bulunamadı")
        kanal = m.group(1)
        ekstra["kanal_id"] = kanal
    k2 = {"url": f"https://www.youtube.com/feeds/videos.xml?channel_id={kanal}", "icerik_turu": "video"}
    durum.pop("yedek", None)
    try:
        ogeler = rss_oku(ist, k2, durum, yazar)
    except KaynakHatasi as e:
        # YouTube RSS akışlarını zaman zaman topluca kapatıyor (404). O zaman kanalın kendi sayfalarını oku.
        ogeler = youtube_kanal_sayfasi_oku(ist, kanal)
        if not ogeler:
            raise KaynakHatasi(f"{e}; kanal sayfası da okunamadı")
        durum["yedek"] = "youtube_sayfa"
    if k.get("kisa_videolari_atla", True):
        ogeler = [o for o in ogeler if "/shorts/" not in o["url"]]
    return ogeler


def eksi_yazar_oku(ist: Istemci, k: dict, durum: dict, yazar: str) -> list[dict]:
    nick = k.get("kullanici") or ""
    if not nick:
        raise KaynakHatasi("Ekşi kullanıcı adı yok")
    profil = "https://eksisozluk.com/biri/" + quote(nick)
    adres = "https://eksisozluk.com/son-entryleri?nick=" + quote(nick) + "&p=1"
    metin = ist.al(adres, basliklar={"X-Requested-With": "XMLHttpRequest", "Referer": profil})
    return _eksi_entryleri(metin, varsayilan_baslik=None)


def eksi_baslik_oku(ist: Istemci, k: dict, durum: dict, yazar: str) -> list[dict]:
    url = k.get("url")
    if not url:
        raise KaynakHatasi("Ekşi başlık adresi yok")
    temel = url.split("?")[0]
    metin = ist.al(temel)
    corba = BeautifulSoup(metin, "html.parser")
    baslik = ""
    h1 = corba.find(id="title") or corba.find("h1")
    if h1:
        baslik = h1.get("data-title") or bosluk(h1.get_text(" "))
    pager = corba.find(attrs={"data-pagecount": True})
    if pager:
        try:
            son = int(pager["data-pagecount"])
            if son > 1:
                metin = ist.al(f"{temel}?p={son}")
        except ValueError:
            pass
    ogeler = _eksi_entryleri(metin, varsayilan_baslik=baslik)
    return list(reversed(ogeler))  # en yenisi önce


def _eksi_entryleri(metin: str, varsayilan_baslik: str | None) -> list[dict]:
    corba = BeautifulSoup(metin, "html.parser")
    sonuc = []
    for li in corba.find_all("li", attrs={"data-id": True}):
        eid = li["data-id"]
        icerik = li.find(class_="content")
        baslik = varsayilan_baslik
        if not baslik:
            h = li.find_previous(["h1", "h2"])
            baslik = bosluk(h.get_text(" ")) if h else "Ekşi Sözlük"
        tarih_a = li.find("a", class_=re.compile("entry-date"))
        sonuc.append({
            "url": f"https://eksisozluk.com/entry/{eid}",
            "baslik": kisalt(baslik, 160),
            "ozet": kisalt(icerik.get_text(" ") if icerik else "", 260),
            "tarih": iso(_eksi_tarihi(tarih_a.get_text() if tarih_a else "")),
            "tur": "eksi",
        })
    if not sonuc:  # yapı değiştiyse kaba yedek
        for eid in dict.fromkeys(re.findall(r'/entry/(\d+)', metin)):
            sonuc.append({"url": f"https://eksisozluk.com/entry/{eid}",
                          "baslik": varsayilan_baslik or f"entry #{eid}", "tur": "eksi"})
    return sonuc


def _eksi_tarihi(s: str) -> datetime | None:
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?", s or "")
    if not m:
        return None
    g, a, y, sa, dk = m.groups()
    return datetime(int(y), int(a), int(g), int(sa or 0), int(dk or 0), tzinfo=TR_SAAT)


def instagram_oku(ist: Istemci, k: dict, durum: dict, yazar: str) -> list[dict]:
    if k.get("rss_url"):  # en güvenilir yol: RSS.app vb. bir servisin verdiği akış
        return [dict(o, tur="instagram") for o in rss_oku(ist, {"url": k["rss_url"]}, durum, yazar)]
    kullanici = (k.get("kullanici") or "").lstrip("@")
    if not kullanici:
        raise KaynakHatasi("Instagram kullanıcı adı yok")
    adres = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={quote(kullanici)}"
    try:
        metin = ist.al(adres, basliklar={"x-ig-app-id": "936619743392459", "Accept": "application/json"},
                       deneme=1)
        veri = json.loads(metin)
        kenarlar = veri["data"]["user"]["edge_owner_to_timeline_media"]["edges"]
    except Exception as e:
        raise KaynakHatasi("Instagram okumaya izin vermedi (giriş istiyor ya da sınırladı). "
                           "Kalıcı çözüm: kaynağa rss_url ekle. Ayrıntı: " + str(e)[:120])
    sonuc = []
    for kenar in kenarlar:
        n = kenar["node"]
        yazi = ""
        try:
            yazi = n["edge_media_to_caption"]["edges"][0]["node"]["text"]
        except (KeyError, IndexError):
            pass
        sonuc.append({
            "url": f"https://www.instagram.com/p/{n['shortcode']}/",
            "baslik": kisalt(yazi.split("\n")[0], 140) or f"@{kullanici} yeni paylaşım",
            "ozet": kisalt(yazi, 260),
            "tarih": iso(datetime.fromtimestamp(n.get("taken_at_timestamp", 0), tz=timezone.utc))
            if n.get("taken_at_timestamp") else None,
            "tur": "instagram",
        })
    return sonuc


def google_haber_kaynak_oku(ist: Istemci, k: dict, durum: dict, yazar: str) -> list[dict]:
    """Doğrudan okunamayan bir sitedeki yazıları Google Haberler aramasıyla izler."""
    ogeler = google_haber_oku(ist, k.get("bul") or yazar, k["site"])
    for o in ogeler:
        o.pop("_yedek", None)
    # Haber derleyen siteler (ör. gazeteoku.com) kişinin adının geçtiği her haberi getirir. Asıl adresi çözüp
    # yalnızca yolunda kişinin adı bir bölüm olarak geçenleri al: …/yazarlar/deniz-zeyrek/yazi-basligi
    durum["yedek"] = "google_haber"
    k2 = dict(k, link_deseni=k.get("link_deseni") or _yazar_yolu_deseni(k.get("bul") or yazar), yedek_dogrula=True)
    return yedek_sonuclarini_suz(ist, ogeler, k2, f"https://{k['site']}/", durum, ad=k.get("bul") or yazar)


# Adreste kişinin adından hemen sonra gelince içeriğin ona ait olduğunu gösteren ekler
# (medyascope.tv/…/rusen-cakir-yorumladi-…, …-rusen-cakir-video/, …-rusen-cakir-izleyicilerle-yorumladi/)
IMZA_EKLERI = "yazdi|yorumladi|video|izleyicilerle|anlatiyor|degerlendirdi|soruyor|cevapliyor"


def _yazar_yolu_deseni(ad: str) -> str:
    """Kişinin kendi yazısı mı? Adreste yazar klasörü olsun (…/yazar/deniz-zeyrek/…) ya da adres
    "<ad>-yazdi" / "<ad>-yorumladi" / "<ad>-video" biçiminde olsun, ya da "…-<ad>a-konustu" (onun söyleşisi)."""
    s = re.escape(_slug(ad))
    return (r"https?://[^/]+/(?:(?:[^?#]*/)?[^/?#]*" + s + r"[^/?#]*/[^?#]+"
            r"|[^?#]*(?:^|/|-)" + s + r"-(?:" + IMZA_EKLERI + r")(?:-|/|$)[^?#]*"
            r"|[^?#]*(?:^|/|-)" + s + r"(?:a|e|ya|ye)-konustu(?:-|/|$)[^?#]*)")


# ───────────────────────── isimden kaynak bulma ─────────────────────────
# Uygulamada "İsimle bul" seçilince ad, kaynaklar_uygulama.json'daki "aranacaklar" listesine yazılır.
# Burada o kişinin nerede yazdığını bulup kaynaklarını kendimiz ekleriz.

YAZAR_YOLLARI = ["/yazarlar/{s}", "/yazar/{s}", "/kose-yazarlari/{s}", "/author/{s}", "/yazarlar/{s}/"]
YAZAR_DIZINLERI = ["/yazarlar", "/kose-yazarlari", "/yazarlar/tum-yazarlar"]
GENEL_SITELER = {"youtube.com", "x.com", "twitter.com", "instagram.com", "facebook.com", "wikipedia.org",
                 "eksisozluk.com", "news.google.com", "google.com", "msn.com", "yandex.com.tr"}


def _slug(ad: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", sade(ad)).strip("-")


def _yazar_sayfasi_mi(ist: Istemci, url: str, ad: str) -> tuple[bool, str | None]:
    """(geçerli mi, hata kodu). Sayfa açılıyor, kişinin adı geçiyor ve en az 2 yazı bağlantısı varsa geçerli."""
    try:
        metin = ist.al(url, deneme=0)
    except KaynakHatasi as e:
        m = re.search(r"HTTP (\d+)", str(e))
        return False, m.group(1) if m else "hata"
    corba = BeautifulSoup(metin, "html.parser")
    bas = sade(" ".join(x.get_text(" ") for x in corba.find_all(["title", "h1", "h2"])[:8]))
    if sade(ad) not in bas:
        return False, None
    on_ek = urlparse(url).path.rstrip("/") + "/"
    linkler = _linkleri_topla(corba, url, lambda u: urlparse(u).path.startswith(on_ek)
                              and len(urlparse(u).path) > len(on_ek) + 3)
    if len(linkler) < 2:
        linkler = _linkleri_topla(corba, url, lambda u: _makaleye_benziyor(u, url))
    return len(linkler) >= 2, None


# ───────────────────────── YouTube'da adı geçen videolar ─────────────────────────
# Kendi kanalı olmayan, başka kanallarda program yapan ya da konuk olan kişiler için (ör. futbol yorumcuları):
# YouTube'da son bir haftanın videolarını kişinin adıyla arar, başlığında adı geçenleri alır.

_GORELI_SURE = {"saniye": 1, "second": 1, "dakika": 60, "minute": 60, "saat": 3600, "hour": 3600,
                "gün": 86400, "gun": 86400, "day": 86400, "hafta": 604800, "week": 604800,
                "ay": 2592000, "month": 2592000, "yıl": 31536000, "yil": 31536000, "year": 31536000}


def _goreli_tarih(metin: str) -> datetime | None:
    m = re.search(r"(\d+)\s*(saniye|dakika|saat|gün|gun|hafta|ay|yıl|yil|second|minute|hour|day|week|month|year)",
                  metin or "", re.I)
    return simdi() - timedelta(seconds=int(m.group(1)) * _GORELI_SURE[m.group(2).lower()]) if m else None


def _yt_metin(t) -> str:
    if not isinstance(t, dict):
        return ""
    return t.get("simpleText") or t.get("content") or "".join(r.get("text", "") for r in t.get("runs") or [])


def _yt_baslangic_verisi(metin: str):
    m = re.search(r"(?:var ytInitialData|window\[\"ytInitialData\"\])\s*=\s*", metin)
    if not m:
        return None
    try:
        return json.JSONDecoder().raw_decode(metin[m.end():])[0]
    except ValueError:
        return None


def _yt_arama_videolari(veri) -> list[dict]:
    """YouTube arama sayfasının verisinden videoları çıkarır: {id, baslik, kanal, zaman, kisa}."""
    bulunan, yigin = [], [veri]
    while yigin:
        x = yigin.pop()
        if isinstance(x, list):
            yigin.extend(reversed(x))
            continue
        if not isinstance(x, dict):
            continue
        v = x.get("videoRenderer")
        if isinstance(v, dict) and v.get("videoId"):
            yol = (((v.get("navigationEndpoint") or {}).get("commandMetadata") or {}).get("webCommandMetadata") or {}).get("url", "")
            bulunan.append({"id": v["videoId"], "baslik": _yt_metin(v.get("title")),
                            "kanal": _yt_metin(v.get("ownerText") or v.get("longBylineText")),
                            "zaman": _yt_metin(v.get("publishedTimeText")), "kisa": yol.startswith("/shorts/")})
            continue
        l = x.get("lockupViewModel")
        if isinstance(l, dict) and l.get("contentId") and "VIDEO" in str(l.get("contentType", "")):
            md = ((l.get("metadata") or {}).get("lockupMetadataViewModel") or {})
            satirlar = json.dumps(md.get("metadata") or {}, ensure_ascii=False)
            parcalar = re.findall(r'"content":\s*"([^"]+)"', satirlar)
            bulunan.append({"id": l["contentId"], "baslik": _yt_metin(md.get("title")),
                            "kanal": parcalar[0] if parcalar else "",
                            "zaman": next((p for p in parcalar if _goreli_tarih(p)), ""), "kisa": False})
            continue
        yigin.extend(reversed(list(x.values())))
    return bulunan


def youtube_kanal_sayfasi_oku(ist: Istemci, kanal_id: str) -> list[dict]:
    """Kanalın 'Videolar' ve 'Canlı yayınlar' sekmelerinden son videolar (RSS çalışmadığında)."""
    sonuc, gorulen, hata = [], set(), None
    for sekme in ("videos", "streams"):
        try:
            metin = ist.al(f"https://www.youtube.com/channel/{kanal_id}/{sekme}?hl=tr&gl=TR", deneme=1,
                           basliklar={"Cookie": "CONSENT=YES+1; SOCS=CAI", "Accept-Language": "tr-TR,tr;q=0.9"})
        except KaynakHatasi as e:
            hata = e
            continue
        veri = _yt_baslangic_verisi(metin)
        for v in _yt_arama_videolari(veri) if veri is not None else []:
            if v["kisa"] or v["id"] in gorulen or not v["baslik"]:
                continue
            gorulen.add(v["id"])
            zaman = _goreli_tarih(v["zaman"])
            sonuc.append({"url": f"https://www.youtube.com/watch?v={v['id']}", "baslik": kisalt(v["baslik"], 200),
                          "tarih": iso(zaman) if zaman else None, "tur": "video"})
    if not sonuc and hata:
        raise hata
    # yayın tarihi bilinmeyenler (ör. şu an canlı) en üste; sonra yeniden eskiye
    sonuc.sort(key=lambda o: o.get("tarih") or "9999", reverse=True)
    return sonuc[:20]


def youtube_ara(ist: Istemci, arama: str) -> list[dict]:
    # sp=EgQIAxAB → yalnızca videolar, son bir hafta
    url = ("https://www.youtube.com/results?search_query=" + quote(f'"{arama}"') + "&sp=EgQIAxAB&hl=tr&gl=TR")
    metin = ist.al(url, basliklar={"Cookie": "CONSENT=YES+1; SOCS=CAI", "Accept-Language": "tr-TR,tr;q=0.9"})
    veri = _yt_baslangic_verisi(metin)
    if veri is None:
        raise KaynakHatasi("YouTube arama sayfası okunamadı (yapı değişmiş olabilir)")
    return _yt_arama_videolari(veri)


def youtube_ara_oku(ist: Istemci, k: dict, durum: dict, yazar: str) -> list[dict]:
    """Başlığında kişinin adı geçen son bir haftanın YouTube videoları (hangi kanalda olursa olsun)."""
    arama = bosluk(k.get("arama") or yazar)
    hedef = sade(arama)
    haric = {sade(x) for x in _liste(k.get("haric_kanallar"))}
    sonuc, gorulen = [], set()
    for v in youtube_ara(ist, arama):
        if v["kisa"] or v["id"] in gorulen or sade(v["kanal"]) in haric:
            continue
        if hedef not in sade(v["baslik"]) and hedef != sade(v["kanal"]):
            continue
        gorulen.add(v["id"])
        zaman = _goreli_tarih(v["zaman"])
        sonuc.append({"url": f"https://www.youtube.com/watch?v={v['id']}", "baslik": kisalt(v["baslik"], 200),
                      "tarih": iso(zaman) if zaman else None, "tur": "video", "_kaynak": v["kanal"] or None})
    sonuc.sort(key=lambda o: o.get("tarih") or "", reverse=True)
    return sonuc[: int(k.get("en_fazla", 20))]


def _youtube_kanali_bul(ist: Istemci, ad: str) -> dict | None:
    try:
        metin = ist.al("https://www.youtube.com/results?search_query=" + quote(ad) + "&sp=EgIQAg%253D%253D",
                       basliklar={"Cookie": "CONSENT=YES+1; SOCS=CAI"}, deneme=0)
    except KaynakHatasi:
        return None
    hedef = sade(ad)
    for m in re.finditer(r'"channelRenderer":\{"channelId":"(UC[\w-]{22})","title":\{"simpleText":"([^"]+)"', metin):
        baslik = json.loads('"' + m.group(2) + '"')
        if hedef == sade(baslik) or (hedef in sade(baslik) and len(sade(baslik)) <= len(hedef) + 12):
            kanal = {"tur": "youtube", "kanal": f"https://www.youtube.com/channel/{m.group(1)}",
                     "kanal_id": m.group(1), "etiket": "YouTube", "otomatik": True}
            # adı aynı ama artık kullanılmayan (ya da başka birine ait eski) kanalları önerme
            try:
                videolar = youtube_oku(ist, {"kanal_id": m.group(1)}, {}, ad)
            except Exception:
                return kanal          # kontrol edilemedi; kanalı yine de öner
            tarihler = [iso_oku(v.get("tarih")) for v in videolar if v.get("tarih")]
            en_yeni = max(tarihler) if tarihler else None
            if en_yeni is None or simdi() - en_yeni > timedelta(days=120):
                ne_zaman = en_yeni.astimezone(TR_SAAT).strftime("%Y") if en_yeni else "hiç"
                return {"_elendi": f"YouTube kanalı ({baslik}) {ne_zaman}'den beri video yüklemiyor"
                        if en_yeni else f"YouTube kanalında ({baslik}) video yok"}
            return kanal
    return None


def _tek_yazi_adresi(u: str) -> bool:
    """Adres bir yazarın sayfası değil de tek bir haber/yazı gibi mi görünüyor? (ör. /haber/6008284/gazeteci-…)"""
    yol = urlparse(u).path.lower().rstrip("/")
    son = yol.rsplit("/", 1)[-1]
    return bool(re.search(r"/(haber|haberler|news|video|galeri|foto|gundem|makale|yazi)/", yol + "/")
                and not re.search(r"/(yazar|yazarlar|author)/", yol)) or son.count("-") >= 4


def _sitede_kendi_yazisi_var(ist: Istemci, linkler: list[str], ad: str, alan: str) -> bool:
    desen = re.compile(_yazar_yolu_deseni(ad))
    onbellek: dict = {}
    for gn in linkler[:4]:
        gercek = google_haber_adresi_coz(ist, gn, onbellek)
        if gercek and _alan_adi(gercek) == alan and desen.search(gercek):
            return True
    return False


def _son_yazi_yasi(ist: Istemci, sayfa_url: str) -> int | None:
    """Yazar sayfasındaki en yeni yazının kaç gün önce yayımlandığı (bulunamazsa None)."""
    try:
        corba = BeautifulSoup(ist.al(sayfa_url, deneme=0), "html.parser")
    except Exception:
        return None
    on_ek = urlparse(sayfa_url).path.rstrip("/") + "/"
    linkler = _linkleri_topla(corba, sayfa_url, lambda u: urlparse(u).path.startswith(on_ek)
                              and len(urlparse(u).path) > len(on_ek) + 3)
    if len(linkler) < 2:
        linkler = _linkleri_topla(corba, sayfa_url, lambda u: _makaleye_benziyor(u, sayfa_url))
    tarihler = []
    for l in linkler[:2]:
        o = {"url": l["url"]}
        try:
            ayrinti_getir(ist, o, None)
        except Exception:
            continue
        if iso_oku(o.get("tarih")):
            tarihler.append(iso_oku(o["tarih"]))
    return (simdi() - max(tarihler)).days if tarihler else None


def _haberden_yazar_sayfasi(ist: Istemci, linkler: list[str], slug: str, alan: str) -> str | None:
    onbellek: dict = {}
    for gn in linkler[:3]:
        gercek = google_haber_adresi_coz(ist, gn, onbellek)
        if not gercek or _alan_adi(gercek) != alan:
            continue
        p = urlparse(gercek)
        parcalar = [x for x in p.path.split("/") if x]
        for i, parca in enumerate(parcalar[:-1]):          # son parça yazının kendisi, ona bakma
            if slug in parca.lower():
                return f"{p.scheme}://{p.netloc}/" + "/".join(parcalar[: i + 1])
        try:
            corba = BeautifulSoup(ist.al(gercek, deneme=0), "html.parser")
        except Exception:
            continue
        for a in corba.find_all("a", href=True):
            h = urljoin(gercek, a["href"]).split("#")[0].split("?")[0].rstrip("/")
            if _alan_adi(h) == alan and slug in urlparse(h).path.lower() and not _tek_yazi_adresi(h):
                return h
    return None


def yazar_kesfet(ist: Istemci, ad: str, youtube_ara_iste: bool = False, atla_alanlar: set[str] | None = None,
                 yazili_var: bool = False) -> tuple[list[dict], str]:
    """Kişinin yazdığı yerleri bulur. (kaynaklar, açıklama) döner.
    atla_alanlar: zaten takip edilen siteler (yeniden denenmez); yazili_var: kişinin köşesi/blogu zaten takipte."""
    atla = atla_alanlar or set()
    sorgu = quote(f'"{ad}" when:60d')
    alanlar: dict[str, dict] = {}
    try:
        akis = feedparser.parse(ist.al(f"https://news.google.com/rss/search?q={sorgu}&hl=tr&gl=TR&ceid=TR:tr",
                                       deneme=1))
        for e in akis.entries:
            kaynak = e.get("source") or {}
            href = kaynak.get("href") or ""
            alan = _alan_adi(href)
            if not alan or any(alan == g or alan.endswith("." + g) for g in GENEL_SITELER) or alan in atla:
                continue
            s = alanlar.setdefault(alan, {"alan": alan, "kok": href.rstrip("/"), "ad": kaynak.get("title") or alan,
                                         "say": 0, "linkler": []})
            s["say"] += 1
            if e.get("link") and len(s["linkler"]) < 4:
                s["linkler"].append(e["link"])
    except Exception as e:
        print(f"   (Google Haberler araması yapılamadı: {e})")

    slug = _slug(ad)
    bulunan: list[dict] = []
    engelli: list[dict] = []
    elenen: list[str] = []      # neden eklenmediğini açıklamak için
    # 1) kişisel site: alan adında kişinin adı geçiyorsa (ör. farukbildirici.com)
    for s in alanlar.values():
        if slug.replace("-", "") in s["alan"].replace("-", "").replace(".", ""):
            try:
                rss = rss_kesfet(ist, s["kok"] + "/")
                bulunan.append({"tur": "rss", "url": rss, "kesfet": s["kok"] + "/", "etiket": s["alan"],
                                "otomatik": True})
            except Exception:
                pass
    # 2) haber siteleri: yazar sayfasını tahmin et ya da yazarlar listesinden bul
    for s in sorted(alanlar.values(), key=lambda x: -x["say"])[:6]:
        if len([b for b in bulunan if b["tur"] == "sayfa"]) >= 2:
            break
        if any(_alan_adi(b.get("url") or b.get("kesfet")) == s["alan"] for b in bulunan):
            continue
        kok = s["kok"] if s["kok"].startswith("http") else "https://" + s["alan"]
        bulundu, kodlar = None, []
        for yol in YAZAR_YOLLARI:
            aday = kok + yol.format(s=slug)
            gecerli, kod = _yazar_sayfasi_mi(ist, aday, ad)
            kodlar.append(kod)
            if gecerli:
                bulundu = aday
                break
            if kod in ("403", "429", "503"):
                break
        if not bulundu and not any(k in ("403", "429", "503") for k in kodlar):
            for dizin in YAZAR_DIZINLERI:
                try:
                    aday = yazar_sayfasini_bul(ist, kok + dizin, ad, {})
                except Exception:
                    continue
                if aday and not _tek_yazi_adresi(aday) and _yazar_sayfasi_mi(ist, aday, ad)[0]:
                    bulundu = aday
                    break
        # tahmin tutmadıysa: o sitedeki yazılarından birinin adresinden ya da içindeki bağlantıdan yazar sayfasını çıkar
        # (ör. t24.com.tr/yazarlar/tolga-sardan-buyutec/… → t24.com.tr/yazarlar/tolga-sardan-buyutec;
        #      dunya.com'daki yazının içindeki /yazar/prof-dr-selva-demiralp/1508 bağlantısı)
        if not bulundu and not any(k in ("403", "429", "503") for k in kodlar):
            aday = _haberden_yazar_sayfasi(ist, s.get("linkler") or [], slug, s["alan"])
            if aday and _yazar_sayfasi_mi(ist, aday, ad)[0]:
                bulundu = aday
        if bulundu:
            yas = _son_yazi_yasi(ist, bulundu)
            if yas is not None and yas > 120:
                elenen.append(f"{s['alan']} sayfası var ama son yazısı {yas} gün önce")
                bulundu = None
        if bulundu:
            bulunan.append({"tur": "sayfa", "url": bulundu, "etiket": s["ad"], "dogrula": True, "otomatik": True})
        elif any(k in ("403", "429", "503") for k in kodlar) and s["say"] >= 2:
            # adın geçmesi yazdığı anlamına gelmez (haber derleyen siteler); asıl adreste yazar klasörü arıyoruz
            if _sitede_kendi_yazisi_var(ist, s.get("linkler") or [], ad, s["alan"]):
                engelli.append({"tur": "google_haber", "site": s["alan"], "etiket": s["ad"], "otomatik": True})
            else:
                elenen.append(f"{s['alan']} (adı geçiyor ama orada yazmıyor)")
    # site doğrudan açılmıyorsa ve başka yer bulunamadıysa: Google Haberler üzerinden izle
    if not any(b["tur"] in ("sayfa", "rss") for b in bulunan):
        bulunan.extend(engelli[:1])
    # 3) YouTube kanalı
    # (köşe yazarı ya da kendi blogu olan kişilerin YouTube kanalı eklenmez; yalnızca yazıları takip edilir)
    yazili = yazili_var or any(b["tur"] in ("sayfa", "rss", "google_haber") for b in bulunan)
    yt = None if yazili else _youtube_kanali_bul(ist, ad)
    if yt and yt.get("_elendi"):
        elenen.append(yt["_elendi"])
    elif yt:
        bulunan.append(yt)
    # 4) başka kanallardaki programlar: açıkça istendiyse ya da köşe yazısı bulunamadıysa, adı başlıkta geçen videolar
    if youtube_ara_iste or not yazili:
        try:
            deneme = youtube_ara_oku(ist, {"arama": ad}, {}, ad)
        except Exception as e:
            deneme = []
            print(f"   (YouTube araması yapılamadı: {e})")
        if youtube_ara_iste or len(deneme) >= 2:
            bulunan.append({"tur": "youtube_ara", "arama": ad, "etiket": "YouTube'da adı geçen", "otomatik": True})

    if bulunan:
        aciklama = ", ".join(b["etiket"] for b in bulunan)
    elif alanlar:
        aciklama = ("Adı haberlerde geçiyor (" + ", ".join(list(alanlar)[:3]) +
                    ") ama köşe sayfası bulunamadı; adresi elle ekle")
    else:
        aciklama = "Son 2 ayda haberlerde adı geçmiyor; adresi elle ekle"
    if elenen:
        aciklama += " · Önerilmeyenler: " + "; ".join(elenen[:3])
    return bulunan, aciklama


def oneri_kaniti(ist: Istemci, ad: str, k: dict) -> dict:
    """Önerilen kaynağı bir kez okur: son birkaç içerik ve neden önerildiği (onay ekranında gösterilir)."""
    okuyucu = OKUYUCULAR.get(k.get("tur"))
    if okuyucu is None:
        return {"gerekce": "bu tür denenemedi"}
    kd: dict = {}
    try:
        ogeler = okuyucu(ist, {x: v for x, v in k.items() if x not in ("kanit", "otomatik")}, kd, ad)
    except Exception as e:
        return {"gerekce": f"denenemedi ({str(e)[:80]})"}
    ogeler = [o for o in ogeler if o.get("baslik")]
    if not ogeler:
        return {"gerekce": "içerik bulunamadı"}
    ogeler.sort(key=lambda o: o.get("tarih") or "", reverse=True)
    son = iso_oku(ogeler[0].get("tarih"))
    gun = (simdi() - son).days if son else None
    ne_zaman = "" if gun is None else ", en yenisi bugün" if gun <= 0 else ", en yenisi dün" if gun == 1 else f", en yenisi {gun} gün önce"
    n = len(ogeler)
    tur = k.get("tur")
    if tur == "sayfa":
        gerekce = f"{_alan_adi(k.get('url') or k.get('yazar_dizini'))} sitesindeki yazar sayfası; {n} yazı{ne_zaman}"
    elif tur == "rss":
        gerekce = f"kişinin kendi sitesi/blogu ({_alan_adi(k.get('kesfet') or k.get('url'))}); {n} yazı{ne_zaman}"
    elif tur == "google_haber":
        c = kd.get("yedek_cozum") or {}
        gerekce = (f"{k.get('site')} sitesinde kendi imzalı yazıları (site doğrudan açılmıyor, Google Haberler "
                   f"üzerinden; adresi yazar klasöründe olanlar: {c.get('yazara_ait', n)}){ne_zaman}")
    elif tur == "youtube":
        gerekce = f"adı birebir tutan YouTube kanalı; {n} video{ne_zaman} — kanalın gerçekten o kişiye ait olduğunu örneklerden kontrol et"
    elif tur == "youtube_ara":
        gerekce = f"başlığında adı geçen son bir haftanın videoları (farklı kanallardan); {n} video"
    else:
        gerekce = f"{n} içerik{ne_zaman}"
    ornekler = [{"baslik": kisalt(o["baslik"], 120), "url": o["url"], "tarih": o.get("tarih"),
                 "kanal": o.get("_kaynak")} for o in ogeler[:3]]
    return {"gerekce": gerekce, "ornekler": ornekler, "sayi": n}


def kesif_calistir(ist: Istemci, ayar_yolu: Path) -> list[str]:
    """kaynaklar_uygulama.json'daki 'aranacaklar' listesini işler. Bildirim mesajları döner."""
    yol = Path(ayar_yolu).with_name(UYGULAMA_DOSYASI)
    if not yol.exists():
        return []
    try:
        uyg = json.loads(yol.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    aranacaklar = [a for a in _liste(uyg.get("aranacaklar")) if isinstance(a, dict) and bosluk(a.get("ad"))]
    if not aranacaklar:
        return []
    uyg.setdefault("yazarlar", [])
    kesif = uyg.setdefault("kesif", {})
    mesajlar = []
    for a in aranacaklar[:8]:  # bir çalışmada en fazla 8 kişi; kalanlar sonraki kontrolde
        ad = bosluk(a["ad"])
        print(f"🔍 {ad} için kaynak aranıyor…")
        kaynaklar, aciklama = yazar_kesfet(ist, ad, bool(a.get("youtube")))
        # Bulunanlar doğrudan takibe alınmaz: her biri bir kez okunur, örnek yazılarıyla onaya sunulur.
        oneriler, bos = [], []
        for k in kaynaklar:
            kanit = oneri_kaniti(ist, ad, k)
            if kanit.get("ornekler"):
                oneriler.append(dict(k, kanit=kanit, kimlik=oneri_kimligi(k)))
            else:
                bos.append(f"{k.get('etiket')}: {kanit.get('gerekce')}")
        if bos:
            aciklama += " · İçerik gelmediği için önerilmeyenler: " + "; ".join(bos[:3])
        if oneriler:
            uyg.setdefault("oneriler", {})[ad] = {"zaman": iso(simdi()), "kaynaklar": oneriler, "aciklama": aciklama}
            kesif[ad] = {"durum": "onay_bekliyor", "zaman": iso(simdi()), "aciklama": aciklama}
            mesajlar.append(f"{ad}: {len(oneriler)} kaynak önerisi onayını bekliyor (Kaynaklar → Onay bekleyenler)")
        else:
            kesif[ad] = {"durum": "bulunamadi", "zaman": iso(simdi()), "aciklama": aciklama}
            mesajlar.append(f"{ad}: {aciklama}")
        print(f"   → {aciklama}")
    islenen = {bosluk(a["ad"]) for a in aranacaklar[:8]}
    uyg["aranacaklar"] = [a for a in aranacaklar if bosluk(a["ad"]) not in islenen]
    yol.write_text(json.dumps(uyg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return mesajlar


# ───────────────────────── günlük kaynak taraması ─────────────────────────
# Her kişi günde bir kez yeniden aranır; takip edilenlere ek yeni bir köşe, blog ya da kanal bulunursa
# doğrudan eklenmez, örnek içerikleriyle "Onay bekleyenler"e konur. Reddedilenler bir daha önerilmez.

GUNLUK_TARAMA_SAAT = 24
GUNLUK_TARAMA_KISI = 2      # bir çalışmada en fazla bu kadar kişi (yarım saatte bir çalışınca herkes günde bir kez)


def _kaynak_alani(k: dict) -> str:
    adres = str(k.get("url") or k.get("kesfet") or k.get("yazar_dizini") or k.get("rss_url") or k.get("site") or "")
    if "://" not in adres and "." in adres:
        adres = "https://" + adres
    return _alan_adi(adres)


def oneri_kimligi(k: dict) -> str:
    """Aynı yerin farklı adreslerle tekrar önerilmemesi için kaba kimlik (site bazında)."""
    tur = k.get("tur", "sayfa")
    if tur in ("sayfa", "rss", "google_haber"):
        return "site|" + _kaynak_alani(k)
    if tur == "youtube":
        return "youtube|" + str(k.get("kanal_id") or k.get("kanal") or "").lower().rstrip("/")
    if tur == "youtube_ara":
        return "youtube_ara|" + sade(str(k.get("arama") or ""))
    return f"{tur}|" + str(k.get("kullanici") or k.get("url") or "").lower().rstrip("/")


def oneri_kimlikleri(k: dict, kd: dict | None = None) -> set[str]:
    """Aynı kaynağın olası tüm kimlikleri (YouTube'da kanal adresi ve kanal kimliği ayrı yazılabiliyor)."""
    kimlikler = {oneri_kimligi(k)}
    if k.get("tur") == "youtube":
        adres = re.sub(r"^https?://(www\.|m\.)?", "", str(k.get("kanal") or k.get("url") or "").lower()).rstrip("/")
        if adres:
            kimlikler.add("youtube|" + adres)
        for kid in (k.get("kanal_id"), ((kd or {}).get("ekstra") or {}).get("kanal_id"),
                    (re.search(r"/channel/(uc[\w-]{22})", adres) or [None, None])[1]):
            if kid:
                kimlikler.add("youtube|" + kid.lower())
    return kimlikler


def gunluk_tarama(ist: Istemci, ayar: dict, ayar_yolu: Path, durum: dict,
                  en_fazla: int = GUNLUK_TARAMA_KISI) -> list[str]:
    yol = Path(ayar_yolu).with_name(UYGULAMA_DOSYASI)
    try:
        uyg = json.loads(yol.read_text(encoding="utf-8")) if yol.exists() else {}
    except Exception:
        return []
    kayit = durum.setdefault("gunluk_tarama", {})
    aranacak = set((ayar.get("_uygulama") or {}).get("aranacaklar") or [])
    reddedilen = uyg.get("reddedilen") if isinstance(uyg.get("reddedilen"), dict) else {}
    sinir = simdi() - timedelta(hours=GUNLUK_TARAMA_SAAT)
    adaylar = []
    for y in ayar.get("yazarlar", []):
        kaynaklar = y.get("kaynaklar") or []
        if y.get("aktif") is False or y["ad"] in aranacak:
            continue
        if kaynaklar and all(k.get("tur") == "eksi_baslik" for k in kaynaklar):
            continue                        # bir kişi değil, bir Ekşi başlığı
        son = iso_oku(kayit.get(y["ad"]))
        if not son or son < sinir:
            adaylar.append((son or datetime(2000, 1, 1, tzinfo=timezone.utc), y))
    adaylar.sort(key=lambda x: x[0])
    mesajlar, degisti = [], False
    for _, y in adaylar[:en_fazla]:
        ad = y["ad"]
        kaynaklar = y.get("kaynaklar") or []
        bilinen = set().union(*[oneri_kimlikleri(k, (durum.get("kaynaklar") or {}).get(kaynak_anahtari(ad, k)))
                                for k in kaynaklar]) if kaynaklar else set()
        alanlar = {_kaynak_alani(k) for k in kaynaklar} - {""}
        yazili_var = any(k.get("tur") in ("sayfa", "rss", "google_haber") for k in kaynaklar)
        bekleyen = (uyg.get("oneriler") or {}).get(ad) or {}
        bilinen |= {x.get("kimlik") or oneri_kimligi(x) for x in bekleyen.get("kaynaklar") or []}
        bilinen |= set(reddedilen.get(ad) or [])
        print(f"🔁 {ad}: günlük kaynak taraması…")
        try:
            bulunan, _ = yazar_kesfet(ist, ad, False, atla_alanlar=alanlar, yazili_var=yazili_var)
        except Exception as e:
            print(f"   (tarama yapılamadı: {e})")
            continue
        kayit[ad] = iso(simdi())
        yeni = []
        for k in bulunan:
            kim = oneri_kimligi(k)
            if oneri_kimlikleri(k) & bilinen or (yazili_var and k.get("tur") in ("youtube", "youtube_ara")):
                continue
            kanit = oneri_kaniti(ist, ad, k)
            if kanit.get("ornekler"):
                yeni.append(dict(k, kanit=kanit, kimlik=kim))
                bilinen.add(kim)
        if not yeni:
            print("   → yeni kaynak yok")
            continue
        o = uyg.setdefault("oneriler", {}).setdefault(ad, {"kaynaklar": []})
        o["kaynaklar"] = (o.get("kaynaklar") or []) + yeni
        o.update(zaman=iso(simdi()), gunluk=True,
                 aciklama="Günlük taramada takip ettiklerine ek olarak bulundu: " + ", ".join(k.get("etiket") or k["tur"] for k in yeni))
        degisti = True
        mesajlar.append(f"{ad}: günlük taramada {len(yeni)} yeni kaynak bulundu (Kaynaklar → Onay bekleyenler)")
        print("   → " + o["aciklama"])
    if degisti:
        yol.write_text(json.dumps(uyg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ayar.setdefault("_uygulama", {})["oneriler"] = uyg["oneriler"]   # bu çalışmanın sayfasında da görünsün
    return mesajlar


def eski_ozellik_kayitlarini_temizle(ayar_yolu: Path) -> None:
    """Kaldırılan özelliklerin (bildirimler, konular, alanlar) kayıtlarını depodan siler."""
    yol = Path(ayar_yolu).with_name(UYGULAMA_DOSYASI)
    try:
        uyg = json.loads(yol.read_text(encoding="utf-8"))
    except Exception:
        return
    silinen = [x for x in ("push", "konular", "kategoriler", "bildirim") if x in uyg]
    if silinen:
        for x in silinen:
            uyg.pop(x, None)
        yol.write_text(json.dumps(uyg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("– kaldırılan özelliklerin kayıtları silindi: " + ", ".join(silinen))


# Kaynak türü → ürettiği içerik türü (akış temizliğinde kullanılır)
KAYNAK_ICERIK_TURU = {"sayfa": "yazi", "rss": "yazi", "google_haber": "yazi", "youtube": "video", "youtube_ara": "video",
                      "bluesky": "paylasim", "telegram": "paylasim", "podcast": "podcast",
                      "eksi_yazar": "eksi", "eksi_baslik": "eksi", "instagram": "instagram"}

OKUYUCULAR = {
    "youtube_ara": youtube_ara_oku,
    "google_haber": google_haber_kaynak_oku,
    "bluesky": bluesky_oku,
    "telegram": telegram_oku,
    "podcast": podcast_oku,
    "sayfa": sayfa_oku,
    "rss": rss_oku,
    "youtube": youtube_oku,
    "eksi_yazar": eksi_yazar_oku,
    "eksi_baslik": eksi_baslik_oku,
    "instagram": instagram_oku,
}


# ───────────────────────── makale ayrıntısı ─────────────────────────

def ayrinti_getir(ist: Istemci, oge: dict, yazar_adi: str | None) -> bool:
    """Yeni bir yazının sayfasını açıp başlık/özet/tarih bilgisini tamamlar.
    yazar_adi verilirse sayfada bu ad geçmiyorsa False döner (başka yazarın yazısı)."""
    metin = ist.al(oge["url"], deneme=1)
    corba = BeautifulSoup(metin, "html.parser")

    def meta(*adlar):
        for ad in adlar:
            m = corba.find("meta", attrs={"property": ad}) or corba.find("meta", attrs={"name": ad})
            if m and m.get("content"):
                return m["content"].strip()
        return None

    if yazar_adi:
        aranan = sade(yazar_adi)
        oge["_yazar_meta"] = meta("author", "article:author", "dc.creator") or ""
        imza = _imza_yerinde_mi(corba, aranan, oge["_yazar_meta"])
        if not imza:
            if aranan not in sade(corba.get_text(" ")[:20000]):
                return False
            # adı yalnızca metinde geçiyor: başlığında da adı varsa büyük olasılıkla onun hakkında bir haber
            if baslik_onun_hakkinda(meta("og:title", "twitter:title") or oge.get("baslik") or "", yazar_adi):
                return False
        oge["_imza"] = imza

    baslik = meta("og:title", "twitter:title")
    if baslik:
        oge["baslik"] = kisalt(_site_adini_at(baslik, oge["url"]), 200)
    ozet = meta("og:description", "description", "twitter:description")
    if ozet and not oge.get("ozet"):
        oge["ozet"] = kisalt(ozet, 260)
    if not oge.get("tarih"):
        t = meta("article:published_time", "og:published_time", "datePublished", "pubdate")
        if not t:
            m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', metin)
            t = m.group(1) if m else None
        if not t:
            z = corba.find("time", attrs={"datetime": True})
            t = z["datetime"] if z else None
        dt = iso_oku(t)
        if dt:
            oge["tarih"] = iso(dt)
    return True


def baslik_onun_hakkinda(baslik: str, ad: str) -> bool:
    """Başlıkta kişinin adı haber öznesi olarak mı geçiyor? ("Bahadır Özgür adli kontrolle serbest bırakıldı")
    "Ad Soyad | Başlık", "Ad Soyad: ..." gibi imza ön ekleri ve "... yazdı/yorumladı" kalıpları sayılmaz."""
    b, a = sade(baslik), sade(ad)
    if not a or a not in b:
        return False
    ayrac = r"[|:\-\u2013\u2014/·•]"
    if re.search(r"(?:^|" + ayrac + r")\s*" + re.escape(a) + r"\s*(?:$|" + ayrac + ")", b):
        return False
    return not re.search(re.escape(a) + r"\s+(yazdi|yorumladi|yaziyor|anlatiyor|soruyor|cevapliyor|degerlendirdi)\b", b)


_IMZA_SINIFI = re.compile(r"author|yazar|byline|writer|muhabir|editor", re.I)


def _imza_yerinde_mi(corba: BeautifulSoup, aranan: str, yazar_meta: str | None) -> bool:
    """Ad, sayfanın imza yerinde mi (yazar meta etiketi, yapılandırılmış veri ya da imza kutusu)?
    Yalnızca metnin bir yerinde geçmesi yetmez: o kişi hakkında bir haber de olabilir."""
    if aranan in sade(yazar_meta or ""):
        return True
    for sc in corba.find_all("script", type="application/ld+json"):
        for m in re.finditer(r'"(?:author|creator)"\s*:\s*(\[[^\]]{0,800}\]|\{[^}]{0,500}\}|"[^"]{0,120}")', sc.string or sc.get_text() or ""):
            if aranan in sade(m.group(1)):
                return True
    for e in corba.find_all(attrs={"rel": "author"}) + corba.find_all(attrs={"itemprop": "author"}):
        if aranan in sade(e.get_text(" "))[:300]:
            return True
    for e in corba.find_all(class_=_IMZA_SINIFI, limit=60):
        t = e.get_text(" ", strip=True)
        if len(t) < 200 and aranan in sade(t):
            return True
    return False


def makale_metni(corba: BeautifulSoup) -> str:
    """Haber/köşe yazısı sayfasından yazının gövde metnini çıkarır (en fazla 12.000 karakter)."""
    for s in corba.find_all("script", type="application/ld+json"):
        m = re.search(r'"articleBody"\s*:\s*"((?:[^"\\]|\\.)*)"', s.string or s.get_text() or "")
        if m:
            try:
                metin = bosluk(BeautifulSoup(json.loads('"' + m.group(1) + '"'), "html.parser").get_text(" "))
            except Exception:
                metin = ""
            if len(metin) > 600:
                return metin[:12000]
    corba = BeautifulSoup(str(corba), "html.parser")  # aslını bozmamak için kopya
    for t in corba(["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "figure", "iframe"]):
        t.decompose()
    adaylar = corba.select('article, [itemprop="articleBody"], [class*="article-body"], [class*="content-text"], '
                           '[class*="post-content"], [class*="entry-content"], [class*="news-content"], '
                           '[class*="detail-content"], [class*="yazi-icerik"], [class*="makale"]') or [corba]
    en_iyi = ""
    for a in adaylar:
        metin = " ".join(bosluk(p.get_text(" ")) for p in a.find_all("p") if len(bosluk(p.get_text(" "))) > 40)
        if len(metin) > len(en_iyi):
            en_iyi = metin
    return en_iyi[:12000]


def _site_adini_at(baslik: str, url: str) -> str:
    """'Yazının başlığı | Gazete Adı' → 'Yazının başlığı'"""
    baslik = bosluk(baslik)
    site = sade(urlparse(url).netloc.replace("www.", "").split(".")[0])
    for _ in range(2):
        m = re.match(r"^(.{10,}?)\s+([|–—-])\s+([^|–—]{2,60})$", baslik)
        if not m:
            break
        bas, ayrac, kuyruk = m.groups()
        k = sade(kuyruk)
        if ayrac == "|" or site in k.replace(" ", "") or "gazete" in k or k.endswith((".com", ".net", ".tr")):
            baslik = bas
        else:
            break
    return baslik


# ───────────────────────── ana akış ─────────────────────────

UYGULAMA_DOSYASI = "kaynaklar_uygulama.json"


def kaynak_anahtari(ad: str, k: dict) -> str:
    tur = k.get("tur", "sayfa")
    return kimlik(ad, tur, str(k.get("url") or k.get("kanal") or k.get("kullanici")
                               or k.get("yazar_dizini") or k.get("rss_url") or k.get("site") or k.get("arama")))


def ayar_oku(yol: Path) -> dict:
    """kaynaklar.yaml'ı okur; telefondaki uygulamanın yaptığı değişiklikleri
    (kaynaklar_uygulama.json) üzerine ekler."""
    with open(yol, encoding="utf-8") as f:
        ayar = yaml.safe_load(f) or {}
    ayar.setdefault("ayarlar", {})
    ayar.setdefault("yazarlar", [])
    uyg_yol = Path(yol).with_name(UYGULAMA_DOSYASI)
    uyg = {}
    if uyg_yol.exists():
        try:
            uyg = json.loads(uyg_yol.read_text(encoding="utf-8")) or {}
        except Exception as e:
            print(f"! {UYGULAMA_DOSYASI} okunamadı, yok sayılıyor: {e}")
    esleme = uyg.get("ad_esleme") if isinstance(uyg.get("ad_esleme"), dict) else {}
    for y in ayar["yazarlar"]:
        y["ad"] = _ad_esle(esleme, bosluk(y.get("ad")))      # telefondan düzeltilen adlar
        y["kaynaklar"] = _liste(y.get("kaynaklar"))
        for k in y["kaynaklar"]:
            k.setdefault("_kok", "yaml")
    ad_ile = {y["ad"]: y for y in ayar["yazarlar"]}
    for uy in _liste(uyg.get("yazarlar")):
        ad = bosluk(uy.get("ad"))
        if not ad:
            continue
        kaynaklar = [dict(k, _kok="uygulama") for k in _liste(uy.get("kaynaklar")) if isinstance(k, dict)]
        if ad in ad_ile:
            mevcut = {kaynak_anahtari(ad, k) for k in ad_ile[ad]["kaynaklar"]}
            ad_ile[ad]["kaynaklar"].extend(k for k in kaynaklar if kaynak_anahtari(ad, k) not in mevcut)
            if uy.get("sessizlik_gun"):
                ad_ile[ad]["sessizlik_gun"] = uy["sessizlik_gun"]
        else:
            yeni = {k: v for k, v in uy.items() if k != "kaynaklar"}
            yeni.update(ad=ad, kaynaklar=kaynaklar, _kok="uygulama")
            ayar["yazarlar"].append(yeni)
            ad_ile[ad] = yeni
    kapali = set(_liste(uyg.get("kapali")))
    kapali_yazar = set(_liste(uyg.get("kapali_yazarlar")))
    for y in ayar["yazarlar"]:
        if y["ad"] in kapali_yazar:
            y["aktif"] = False
            y["_uygulamada_kapali"] = True
        for k in y["kaynaklar"]:
            if kaynak_anahtari(y["ad"], k) in kapali:
                k["aktif"] = False
                k["_uygulamada_kapali"] = True
    ayar["_uygulama"] = {"aranacaklar": [a.get("ad") for a in _liste(uyg.get("aranacaklar")) if isinstance(a, dict)],
                         "kesif": uyg.get("kesif") or {},
                         "oneriler": uyg.get("oneriler") if isinstance(uyg.get("oneriler"), dict) else {}}
    return ayar


def durum_oku(yol: Path) -> dict:
    if yol.exists():
        try:
            return json.loads(yol.read_text(encoding="utf-8"))
        except Exception:
            yedek = yol.with_suffix(".bozuk.json")
            yol.replace(yedek)
            print(f"! durum dosyası okunamadı, {yedek.name} olarak saklandı; sıfırdan başlıyorum")
    return {"kaynaklar": {}, "ogeler": []}


def _liste(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def kaynaklari_listele(ayar: dict):
    for y in ayar["yazarlar"]:
        if y.get("aktif") is False:
            continue
        for k in _liste(y.get("kaynaklar")):
            if k.get("aktif") is False:
                continue
            yield y, k, k.get("tur", "sayfa"), kaynak_anahtari(y["ad"], k)


def icerik_dogrulamasi(tur: str, k: dict, imza_dogrulandi: bool) -> str:
    """İçeriğin gerçekten o kişiye ait olduğunu neye dayanarak söylüyoruz?"""
    if imza_dogrulandi:
        return "imza"                 # yazının sayfasında kişinin adı (imza) bulundu
    if tur == "sayfa":
        return "yazar_sayfasi"        # kişinin kendi yazı listesi sayfasından
    if tur == "rss":
        return "imza" if k.get("yazar_filtresi") else "kendi_sitesi"
    if tur == "youtube":
        return "kanal"
    if tur in ("bluesky", "telegram", "instagram", "eksi_yazar", "podcast"):
        return "hesap"
    if tur == "youtube_ara":
        return "ad_geciyor"           # başlığında adı geçiyor: konuk ya da konu da olabilir
    if tur == "eksi_baslik":
        return "baslik"
    return "belirsiz"


def gec_gelen_eskileri_ayikla(durum: dict) -> None:
    """Önceki sürümün "yeni" diye aldığı, listede iki haftadan fazla gecikmeyle beliren eski yazıları akıştan çıkarır
    (ör. 23 Ekim yazısının 7 Kasım'da "çok okunanlar" kutusundan gelmesi). Bunlar artık hiç alınmıyor."""
    once = len(durum.get("ogeler", []))
    def gec_mi(o):
        t, b = iso_oku(o.get("tarih")), iso_oku(o.get("bulunma"))
        return bool(not o.get("ilk") and not o.get("konu_haberi") and t and b
                    and b - t > timedelta(days=ILK_GOSTERIM_GUN))
    durum["ogeler"] = [o for o in durum.get("ogeler", []) if not gec_mi(o)]
    if len(durum["ogeler"]) < once:
        print(f"– listede geç belirmiş {once - len(durum['ogeler'])} eski yazı akıştan çıkarıldı")


def dogrulama_isaretini_tamamla(ayar: dict, durum: dict) -> None:
    """Bu özellikten önce akışa girmiş öğelere de (bilinen kadarıyla) doğrulama bilgisi ekler."""
    bilgi = {anahtar: (tur, k) for _y, k, tur, anahtar in kaynaklari_listele(ayar)}
    for o in durum.get("ogeler", []):
        if not o.get("tarih") and url_tarihi(o.get("url", "")):
            o["tarih"], o["tarih_gun"] = iso(url_tarihi(o["url"])), True
        if o.get("dogrulama") or o.get("konu_haberi"):
            continue
        if o.get("gn_url"):
            son = urlparse(o["url"]).path.rstrip("/").rsplit("/", 1)[-1]
            o["dogrulama"] = "baslik_kalibi" if re.search(r"-(yazdi|yorumladi)(-|$)", son) else "yazar_klasoru"
        elif "news.google.com" in o.get("url", ""):
            o["dogrulama"] = "belirsiz"
        elif o.get("kaynak_id") in bilgi:
            tur, k = bilgi[o["kaynak_id"]]
            if tur == "sayfa" and baslik_onun_hakkinda(o.get("baslik") or "", o.get("yazar") or ""):
                o["dogrulama"] = "ad_sayfada"     # başlığında kendi adı geçiyor: onun hakkında bir haber olabilir
            else:
                o["dogrulama"] = icerik_dogrulamasi(tur, k, False)   # eski kayıtlarda imza denetiminin sonucu bilinmiyor


def kose_yazarlarinin_youtubeunu_cikar(ayar_yolu: Path, durum: dict) -> list[str]:
    """Köşe yazısı ya da blogu düzgün takip edilen kişilerden, otomatik bulunmuş YouTube kanallarını çıkarır.
    Köşe kaynağı henüz denenmemişse ya da yanlış eşleşme çıkmışsa (ör. haber derleyen site) dokunmaz."""
    yol = Path(ayar_yolu).with_name(UYGULAMA_DOSYASI)
    try:
        uyg = json.loads(yol.read_text(encoding="utf-8"))
    except Exception:
        return []

    def saglikli(ad: str, k: dict) -> bool:
        # köşe kaynağından gerçekten kişinin kendi yazıları geliyor mu?
        kd = durum["kaynaklar"].get(kaynak_anahtari(ad, k)) or {}
        c = kd.get("yedek_cozum")
        if c is not None:                      # Google Haberler üzerinden: en az bir yazısı doğrulanmış olmalı
            return c.get("yazara_ait", 0) > 0
        return kd.get("durum") == "tamam"

    cikarilan = []
    kapali = set(_liste(uyg.get("kapali")))
    for y in _liste(uyg.get("yazarlar")):
        kaynaklar = _liste(y.get("kaynaklar"))
        kose = [k for k in kaynaklar if k.get("tur") in ("sayfa", "rss", "google_haber")
                and kaynak_anahtari(y["ad"], k) not in kapali and saglikli(y["ad"], k)]
        if not kose:
            continue
        kalan = [k for k in kaynaklar if not (k.get("tur") == "youtube" and k.get("otomatik"))]
        if len(kalan) < len(kaynaklar):
            y["kaynaklar"] = kalan
            cikarilan.append(y["ad"])
    if cikarilan:
        yol.write_text(json.dumps(uyg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"– köşe yazısı takip edilen {len(cikarilan)} kişiden otomatik eklenmiş YouTube kanalı çıkarıldı: "
              + ", ".join(cikarilan))
    return cikarilan


def _ad_esle(esleme: dict, ad: str) -> str:
    """kaynaklar.yaml'daki bir adın telefondan düzeltilmiş hâli (zincirleme düzeltmeler dahil)."""
    gorulen = set()
    while ad in esleme and ad not in gorulen:
        gorulen.add(ad)
        ad = esleme[ad]
    return ad


def ad_degisikliklerini_uygula(ayar_yolu: Path, durum: dict) -> bool:
    """Telefondan istenen ad düzeltmelerini (kaynaklar_uygulama.json → ad_degisiklikleri) uygular.
    Kaynak kimlikleri addan türetildiği için kayıtlar yeni ada taşınır; geçmiş, okundu işaretleri ve kapalı
    kaynaklar korunur. kaynaklar.yaml'daki kişiler için düzeltme 'ad_esleme' altında saklanır."""
    yol = Path(ayar_yolu).with_name(UYGULAMA_DOSYASI)
    try:
        uyg = json.loads(yol.read_text(encoding="utf-8"))
    except Exception:
        return False
    istekler = [d for d in _liste(uyg.get("ad_degisiklikleri")) if isinstance(d, dict)]
    if not istekler:
        return False
    uygulanan = False
    for d in istekler:
        eski, yeni = bosluk(d.get("eski")), bosluk(d.get("yeni"))
        if not eski or not yeni or eski == yeni:
            continue
        yol.write_text(json.dumps(uyg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ayar = ayar_oku(ayar_yolu)
        y = next((x for x in ayar["yazarlar"] if x["ad"] == eski), None)
        if not y:
            print(f"! ad düzeltme: '{eski}' bulunamadı")
            continue
        if any(x is not y and x["ad"].casefold() == yeni.casefold() for x in ayar["yazarlar"]):
            print(f"! ad düzeltme: '{yeni}' adında başka biri zaten var; '{eski}' değiştirilmedi")
            continue
        anahtar = {kaynak_anahtari(eski, k): kaynak_anahtari(yeni, k) for k in y["kaynaklar"]}
        for uy in _liste(uyg.get("yazarlar")):
            if isinstance(uy, dict) and bosluk(uy.get("ad")) == eski:
                uy["ad"] = yeni
        if y.get("_kok") != "uygulama":          # kaynaklar.yaml'daki kişi: dosyaya dokunmadan eşleme tut
            esleme = uyg.setdefault("ad_esleme", {})
            asil = next((o for o in esleme if _ad_esle(esleme, o) == eski), eski)
            esleme[asil] = yeni
            if asil == yeni:
                esleme.pop(asil)
        uyg["kapali"] = [anahtar.get(x, x) for x in _liste(uyg.get("kapali"))]
        uyg["kapali_yazarlar"] = [yeni if x == eski else x for x in _liste(uyg.get("kapali_yazarlar"))]
        for alan in ("kesif", "oneriler", "reddedilen"):
            if isinstance(uyg.get(alan), dict) and eski in uyg[alan]:
                uyg[alan][yeni] = uyg[alan].pop(eski)
        for a in _liste(uyg.get("aranacaklar")):
            if isinstance(a, dict) and a.get("ad") == eski:
                a["ad"] = yeni
        kayitlar = durum.setdefault("kaynaklar", {})
        for e, n in anahtar.items():
            if e in kayitlar:
                kayitlar[n] = dict(kayitlar.pop(e), yazar=yeni)
        for o in durum.get("ogeler", []):
            if o.get("yazar") == eski and not o.get("konu_haberi"):
                o["yazar"] = yeni
                o["kaynak_id"] = anahtar.get(o.get("kaynak_id"), o.get("kaynak_id"))
        for alan in ("yazarlar", "gunluk_tarama"):
            if isinstance(durum.get(alan), dict) and eski in durum[alan]:
                durum[alan][yeni] = durum[alan].pop(eski)
        print(f"✏ ad düzeltildi: {eski} → {yeni}")
        uygulanan = True
    uyg.pop("ad_degisiklikleri", None)
    yol.write_text(json.dumps(uyg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return uygulanan


def tek_yazi_kaynaklarini_cikar(ayar_yolu: Path) -> list[str]:
    """Eski "İsimle bul" sürümünün yazar sayfası yerine tek bir haberi kaynak diye eklediği durumları temizler.
    Kişinin başka kaynağı kalmazsa yeniden aranır (bulunanlar onayına sunulur)."""
    yol = Path(ayar_yolu).with_name(UYGULAMA_DOSYASI)
    try:
        uyg = json.loads(yol.read_text(encoding="utf-8"))
    except Exception:
        return []
    cikarilan = []
    for y in _liste(uyg.get("yazarlar")):
        kaynaklar = _liste(y.get("kaynaklar"))
        kalan = [k for k in kaynaklar if not (k.get("otomatik") and k.get("tur") == "sayfa"
                                               and k.get("url") and _tek_yazi_adresi(k["url"]))]
        if len(kalan) < len(kaynaklar):
            y["kaynaklar"] = kalan
            cikarilan.append(y["ad"])
            if not kalan:
                ar = _liste(uyg.get("aranacaklar"))
                if not any((x.get("ad") if isinstance(x, dict) else x) == y["ad"] for x in ar):
                    ar.append({"ad": y["ad"], "zaman": iso(simdi())})
                uyg["aranacaklar"] = ar
                (uyg.get("kesif") or {}).pop(y["ad"], None)
    if cikarilan:
        yol.write_text(json.dumps(uyg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("– yazar sayfası yerine tek bir haber olarak eklenmiş kaynak çıkarıldı: " + ", ".join(cikarilan))
    return cikarilan


def calistir(ayar_yolu: Path, sadece_kontrol: bool = False, zorla_denetim: bool = False) -> int:
    if not sadece_kontrol:
        tek_yazi_kaynaklarini_cikar(ayar_yolu)   # yeniden aranacaklar varsa hemen aşağıda aranır
        eski_ozellik_kayitlarini_temizle(ayar_yolu)
    ayar = ayar_oku(ayar_yolu)
    a = ayar["ayarlar"]
    ist = Istemci(bekleme=float(a.get("istekler_arasi_bekleme", 0.7)))
    kesif_mesajlari = [] if sadece_kontrol else kesif_calistir(ist, ayar_yolu)
    if kesif_mesajlari:
        ayar = ayar_oku(ayar_yolu)  # yeni bulunan kaynaklarla yeniden oku
        a = ayar["ayarlar"]
    veri_dir = KOK / a.get("veri_klasoru", "veri")
    cikti_dir = KOK / a.get("cikti_klasoru", "docs")
    durum_yolu = veri_dir / "durum.json"
    durum = durum_oku(durum_yolu)
    if not sadece_kontrol and ad_degisikliklerini_uygula(ayar_yolu, durum):
        ayar = ayar_oku(ayar_yolu)  # yeni adlarla yeniden oku
        a = ayar["ayarlar"]
    if not sadece_kontrol and kose_yazarlarinin_youtubeunu_cikar(ayar_yolu, durum):
        ayar = ayar_oku(ayar_yolu)  # çıkarılan kanallar olmadan yeniden oku
        a = ayar["ayarlar"]
    dogrulama_isaretini_tamamla(ayar, durum)
    gec_gelen_eskileri_ayikla(durum)
    if not sadece_kontrol:
        kesif_mesajlari = kesif_mesajlari + gunluk_tarama(ist, ayar, ayar_yolu, durum)
    akis_siniri = simdi() - timedelta(days=int(a.get("akista_tutulacak_gun", 45)))
    ilk_gosterim = int(a.get("ilk_calistirmada_goster", 3))
    ayrinti_siniri = int(a.get("calisma_basina_ayrinti_siniri", 40))
    baslangic = simdi()

    mevcut_url = {o["url"] for o in durum["ogeler"]}
    yeni_ogeler: list[dict] = []
    ayrinti_sayaci = 0
    aktif_anahtarlar = set()

    for y, k, tur, anahtar in kaynaklari_listele(ayar):
        aktif_anahtarlar.add(anahtar)
        okuyucu = OKUYUCULAR.get(tur)
        kd = durum["kaynaklar"].setdefault(anahtar, {"gorulen": []})
        kd.update({"yazar": y["ad"], "tur": tur, "etiket": k.get("etiket") or _etiket_tahmin(k, tur),
                   "adres": k.get("url") or k.get("kanal") or k.get("kullanici") or k.get("yazar_dizini")
                   or (f"YouTube araması: {k.get('arama') or y['ad']}" if tur == "youtube_ara" else None)})
        etiket = f"{y['ad']} · {kd['etiket']}"
        if not okuyucu:
            kd.update(son_hata=f"bilinmeyen kaynak türü: {tur}", durum="hata")
            print(f"✗ {etiket}: bilinmeyen tür '{tur}'")
            continue
        try:
            ogeler = okuyucu(ist, k, kd, y["ad"])
        except Exception as e:
            kd["hata_sayisi"] = kd.get("hata_sayisi", 0) + 1
            kd.update(son_hata=str(e)[:300], son_deneme=iso(simdi()), durum="hata")
            print(f"✗ {etiket}: {e}")
            continue

        kd.update(son_deneme=iso(simdi()), son_basari=iso(simdi()), hata_sayisi=0, son_hata=None,
                  son_bulunan=len(ogeler), durum="uyari" if not ogeler else "tamam",
                  not_=(_yedek_notu(kd) if kd.get("yedek") == "google_haber"
                        else "YouTube RSS akışı şu an kapalı; kanal sayfasından okunuyor" if kd.get("yedek") == "youtube_sayfa"
                        else None))
        if sadece_kontrol:
            print(f"✓ {etiket}: {len(ogeler)} öğe" + (" (tahmini desen)" if kd.get("tahmini") else ""))
            for o in ogeler[:3]:
                print(f"      - {o['baslik'][:90]}  →  {o['url']}")
            continue

        ilk_kez = not kd["gorulen"]
        gorulen = set(kd["gorulen"])
        if ogeler and len(ogeler) == len([o for o in ogeler if o["url"] not in gorulen and o.get("gn_url") not in gorulen]) \
                and not ilk_kez \
                and len(ogeler) > 8:
            # Sitenin adres yapısı değişmiş olabilir: hepsini yeni sayıp akışı doldurmayalım
            print(f"! {etiket}: sayfadaki her şey yeni görünüyor, adres yapısı değişmiş olabilir; "
                  f"ilk {ilk_gosterim} tanesi gösterilecek")
            ilk_kez = True
        # yedekten gelen yazının asıl adresi çözülmüşse eski Google bağlantısıyla da karşılaştır (tekrar "yeni" sayılmasın)
        # (adı her sayfada geçen sitelerde eski "görüldü" kaydı yanlış eşleşmelerle dolu olduğundan yalnızca akışa bakılır)
        bakilan = mevcut_url if kd.get("ad_her_sayfada") else (gorulen | mevcut_url)
        taze = [o for o in ogeler if o["url"] not in bakilan and (o.get("gn_url") or o["url"]) not in bakilan]
        # Son ILK_GOSTERIM_GUN günün yazıları: kaynak ilk eklendiğinde en yeni birkaç yazıyla yetinmeyip
        # bu süredeki hepsini (bildirimsiz) göster; eskiden atlananları da bir kez tamamla
        if ilk_kez:
            pencere = taze[ilk_gosterim:ilk_gosterim + PENCERE_EN_FAZLA]
            taze = taze[:ilk_gosterim]
        elif not kd.get("bosluk_tamam") and not kd.get("ad_her_sayfada"):
            pencere = [o for o in ogeler if o not in taze and o["url"] not in mevcut_url
                       and o.get("gn_url") not in mevcut_url][:PENCERE_EN_FAZLA]
            gerek = sum(1 for o in pencere if tur == "sayfa" and not o.get("_yedek") and k.get("ayrinti", True))
            if ayrinti_sayaci + gerek <= ayrinti_siniri // 2:   # yeni yazılara da sayfa açma hakkı kalsın
                kd["bosluk_tamam"] = True
            else:
                pencere = []          # bu çalışmada sayfa açma hakkı yetmez; sonraki çalışmada
        else:
            pencere = []
        for o in pencere:
            o["_pencere"] = True
        taze += pencere
        dogrula = k.get("dogrula", bool(k.get("yazar_dizini")) or kd.get("tahmini", False))
        eklenen = 0
        for o in taze:
            yedekten = bool(o.pop("_yedek", False))
            imza_dogrulandi = False
            if tur == "sayfa" and not yedekten and ayrinti_sayaci < ayrinti_siniri \
                    and k.get("ayrinti", True):
                ayrinti_sayaci += 1
                try:
                    if not ayrinti_getir(ist, o, (k.get("bul") or y["ad"]) if dogrula else None):
                        gorulen.add(o["url"])  # başka yazarın yazısı; bir daha bakma
                        continue
                    imza_dogrulandi = bool(o.pop("_imza", False)) if dogrula else False
                    if dogrula and not imza_dogrulandi:
                        # imza kutusu bulunamadı; adres kişinin klasöründeyse yine de onun yazısıdır
                        o["_dogrulama"] = ("yazar_klasoru" if _slug(k.get("bul") or y["ad"]) in urlparse(o["url"]).path.lower()
                                           else "ad_sayfada")
                except Exception as e:
                    print(f"   (ayrıntı alınamadı: {o['url']} — {e})")
            o["dogrulama"] = o.pop("_dogrulama", None) or icerik_dogrulamasi(tur, k, imza_dogrulandi)
            if not o.get("tarih") and url_tarihi(o["url"]):
                o["tarih"], o["tarih_gun"] = iso(url_tarihi(o["url"])), True   # sayfada tarih yoktu; adresteki gün
            yazi_tarihi = iso_oku(o.get("tarih"))
            if yazi_tarihi and (not iso_oku(kd.get("en_yeni_yazi")) or yazi_tarihi > iso_oku(kd["en_yeni_yazi"])):
                kd["en_yeni_yazi"] = iso(yazi_tarihi)    # bu kaynakta görülen en yeni yazının tarihi
            if yazi_tarihi and yazi_tarihi < akis_siniri:
                gorulen.add(o["url"])      # akışta tutulandan da eski bir yazı; yeni değil
                continue
            pencere_siniri = simdi() - timedelta(days=ILK_GOSTERIM_GUN)
            tamamlama = bool(o.pop("_pencere", False))
            # önceden yanlışlıkla elenmiş, tanıma kuralı genişleyince kabul edilen yazı: akış süresi içindeyse
            # kendi tarihiyle (yeni sayılmadan) eklenir
            geri_kazanilan = bool(o.pop("_kural_genisledi", False))
            if tamamlama and (not yazi_tarihi or yazi_tarihi < pencere_siniri):
                continue                   # tamamlama adayıydı ama son iki haftadan değil (ya da tarihi bilinmiyor)
            if not ilk_kez and not geri_kazanilan and yazi_tarihi and yazi_tarihi < pencere_siniri:
                gorulen.add(o["url"])      # listede geç beliren iki haftadan eski yazı ("çok okunanlar" kutusu vb.)
                continue
            # listede geç beliren eski bir yazı (ör. "çok okunanlar" kutusu ya da arama yedeği):
            # akışa gerçek tarihiyle girer ama "yeni" sayılmaz, bildirim gitmez
            gec_kalmis = bool(yazi_tarihi and yazi_tarihi < simdi() - timedelta(days=ESKI_YAZI_GUN))
            if _ayni_baslik_var(durum["ogeler"] + yeni_ogeler, y["ad"], o["baslik"]):
                gorulen.add(o["url"])
                continue
            o.update(id=kimlik(o["url"]), yazar=y["ad"], kaynak=o.pop("_kaynak", None) or kd["etiket"], kaynak_id=anahtar,
                     bulunma=iso(simdi()), ilk=ilk_kez or bool(o.pop("_eski", False)) or gec_kalmis or tamamlama or geri_kazanilan)
            yeni_ogeler.append(o)
            mevcut_url.add(o["url"])
            eklenen += 1
            _son_yaziyi_guncelle(durum, y["ad"], o)
        # Sayfada görünen her şeyi "görüldü" say ki ilk çalıştırmada eski yazılar akışa dolmasın
        simdiki = [o["url"] for o in ogeler]
        kd["gorulen"] = (simdiki + [u for u in kd["gorulen"] if u not in set(simdiki)])[:400]
        # Sayfa açılıyor ama en yeni yazısı çok eski: kişi orada artık yazmıyor (ör. 2018'de ayrılmış)
        if not kd.get("en_yeni_yazi"):
            # önceki sürümden kalan kaynak: akıştaki yazılarından, yoksa listedeki ilk yazıyı bir kez açıp öğren
            tarihler = [t for o in durum["ogeler"] + yeni_ogeler if o.get("kaynak_id") == anahtar
                        for t in [iso_oku(o.get("tarih"))] if t]
            tarihler += [t for o in ogeler for t in [iso_oku(o.get("tarih"))] if t]   # akış/RSS listesindeki tarihler
            if not tarihler and ogeler and tur == "sayfa" and ayrinti_sayaci < ayrinti_siniri and not kd.get("yedek"):
                ayrinti_sayaci += 1
                ilk_oge = {"url": ogeler[0]["url"], "baslik": ogeler[0].get("baslik", "")}
                try:
                    ayrinti_getir(ist, ilk_oge, None)
                except Exception:
                    pass
                t = iso_oku(ilk_oge.get("tarih")) or url_tarihi(ilk_oge["url"])
                if t:
                    tarihler.append(t)
            if tarihler:
                kd["en_yeni_yazi"] = iso(max(tarihler))
        en_yeni = iso_oku(kd.get("en_yeni_yazi"))
        if en_yeni and en_yeni < simdi() - timedelta(days=TERK_EDILMIS_GUN) and kd.get("durum") == "tamam":
            kd.update(durum="uyari", not_=f"Bu sayfadaki en yeni yazı {en_yeni.astimezone(TR_SAAT):%d.%m.%Y} tarihli; "
                                          "kişi burada artık yazmıyor görünüyor. Kaynağı kaldırabilir ya da yeni adresini ekleyebilirsin")
        isaret = "★" if eklenen and not ilk_kez else "✓"
        print(f"{isaret} {etiket}: {len(ogeler)} öğe, {eklenen} {'ilk gösterim' if ilk_kez else 'yeni'}")

    if sadece_kontrol:
        return 0

    durum.pop("konular", None)   # konu takibi kaldırıldı

    # artık ayar dosyasında olmayan kaynakların kayıtlarını temizle
    for anahtar in list(durum["kaynaklar"]):
        if anahtar not in aktif_anahtarlar:
            del durum["kaynaklar"][anahtar]

    # kaldırılan/kapatılan kaynakların ve takipten çıkarılan kişilerin içerikleri akıştan da düşsün
    # (adres değişikliğinde aynı kişinin aynı türdeki geçmişi korunur)
    aktif_turler = {(y["ad"], k.get("icerik_turu") or KAYNAK_ICERIK_TURU.get(tur, "yazi"))
                    for y, k, tur, _ in kaynaklari_listele(ayar)}
    red_kumeleri = {a: set(kd.get("yedek_red") or []) for a, kd in durum["kaynaklar"].items() if kd.get("yedek_red")}
    red_tumu = set().union(*red_kumeleri.values()) if red_kumeleri else set()
    # adı her sayfada geçen sitelerde (ör. Oksijen) asıl adresi doğrulanmamış Google bağlantıları güvenilmez
    guvensiz = {a for y, k, tur, _ in kaynaklari_listele(ayar)
                for a in [kaynak_anahtari(y["ad"], k)]
                if k.get("yedek_dogrula") or (durum["kaynaklar"].get(a) or {}).get("ad_her_sayfada")}

    def akista_kalsin(o: dict) -> bool:
        if o.get("konu_haberi"):
            return False   # konu takibi kaldırıldı
        kid = o.get("kaynak_id")
        if red_tumu and _gn_kimlik(o["url"]) in red_kumeleri.get(kid, red_tumu):
            return False   # Google Haberler yedeğinden gelmiş ama yazara ait olmadığı anlaşılmış
        if kid in guvensiz and _gn_kimlik(o["url"]):
            return False   # yazara ait olduğu doğrulanamamış
        return not kid or kid in aktif_anahtarlar or (o["yazar"], o.get("tur", "yazi")) in aktif_turler

    once = len(durum["ogeler"])
    durum["ogeler"] = [o for o in durum["ogeler"] if akista_kalsin(o)]
    if len(durum["ogeler"]) < once:
        print(f"– kaldırılan kaynaklara ya da yanlış eşleşmelere ait {once - len(durum['ogeler'])} içerik akıştan çıkarıldı")

    # yazarlar hâlâ aynı yerde mi yazıyor?
    denetim_mesajlari = adres_denetimi(ist, ayar, durum, zorla=zorla_denetim)

    # akışı güncelle ve buda
    sinir = simdi() - timedelta(days=int(a.get("akista_tutulacak_gun", 45)))
    tum = yeni_ogeler + durum["ogeler"]
    # yazının kendi tarihi biliniyorsa ona, bilinmiyorsa bulunduğu zamana bakılır
    tum = [o for o in tum if (iso_oku(o.get("tarih")) or iso_oku(o.get("bulunma")) or simdi()) >= sinir]
    tum.sort(key=_siralama_anahtari, reverse=True)
    durum["ogeler"] = tum[: int(a.get("akista_en_fazla", 1500))]
    durum.pop("yz", None)

    for m in kesif_mesajlari:
        print("🔎 " + m)
    if denetim_mesajlari:
        print("\nAdres denetimi:")
        for m in denetim_mesajlari:
            print("  • " + m)
    for x in ("bekleyen_bildirim", "bulten_gun", "bulten_son"):   # bildirimler kaldırıldı
        durum.pop(x, None)

    for o in durum["ogeler"]:
        o.pop("_metin", None)
        o.pop("_yazar_meta", None)
        o.pop("_gn_baslik", None)
        o.pop("yz_ozet", None)     # yapay zekâ özetleri kaldırıldı
        o.pop("yz_deneme", None)
        o.pop("konular", None)
    durum["son_calisma"] = iso(baslangic)
    durum["son_calisma_suresi_sn"] = round((simdi() - baslangic).total_seconds(), 1)

    veri_dir.mkdir(parents=True, exist_ok=True)
    gecici = durum_yolu.with_suffix(".tmp")
    gecici.write_text(json.dumps(durum, ensure_ascii=False, indent=1), encoding="utf-8")
    gecici.replace(durum_yolu)

    cikti_dir.mkdir(parents=True, exist_ok=True)
    sayfa_uret(ayar, durum, cikti_dir / "index.html")
    rss_uret(ayar, durum, cikti_dir / "akis.xml")

    print(f"\nBitti: {len([o for o in yeni_ogeler if not o.get('ilk')])} yeni öğe, akışta toplam {len(durum['ogeler'])} öğe. "
          f"Sayfa: {cikti_dir / 'index.html'}")
    return 0


# ───────────────────────── adres denetimi ─────────────────────────
# Amaç: bir yazar gazete değiştirdiğinde eski sayfası açılmaya devam ettiği için akış sessizce kurur.
# Bunu üç işaretle yakalarız:
#   1) Yazarın kaynaklarından uzun süredir yeni yazı gelmiyor (sessizlik),
#   2) Kaynak sayfası saatlerdir açılmıyor ya da açılıp yazı vermiyor,
#   3) Google Haberler'de yazarın adıyla son 30 günde hangi sitelerde imzalı yazı göründüğü
#      (haftada bir taranır; sessiz yazarlar daha sık).

def _son_yaziyi_guncelle(durum: dict, ad: str, o: dict):
    yd = durum.setdefault("yazarlar", {}).setdefault(ad, {})
    alan = "son_yazi" if o.get("tur", "yazi") == "yazi" else "son_diger"
    t = _siralama_anahtari(o)
    eski = iso_oku(yd.get(alan))
    if not eski or t > eski:
        yd[alan] = iso(t)


def _alan_adi(url: str | None) -> str:
    if not url or "://" not in url:
        return ""
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def haber_taramasi(ist: Istemci, ad: str) -> list[dict]:
    """Google Haberler'de yazarın adının son 30 günde geçtiği siteleri çıkarır."""
    if feedparser is None:
        raise KaynakHatasi("feedparser kurulu değil")
    sorgu = quote(f'"{ad}" when:30d')
    metin = ist.al(f"https://news.google.com/rss/search?q={sorgu}&hl=tr&gl=TR&ceid=TR:tr", deneme=1)
    akis = feedparser.parse(metin)
    hedef = sade(ad)
    imza_rx = re.compile(re.escape(hedef) + r"('?\w{0,3})?\s+(yazdi|yaziyor|kaleme aldi)|^" + re.escape(hedef) + r"\s*:")
    siteler: dict[str, dict] = {}
    for e in akis.entries:
        baslik = e.get("title", "")
        kaynak = e.get("source") or {}
        alan = _alan_adi(kaynak.get("href"))
        if not alan:
            continue
        # Google başlığın sonuna " - Kaynak Adı" ekler; onu at
        temiz = re.sub(r"\s+-\s+[^-]+$", "", baslik)
        st = sade(temiz)
        if hedef not in st:
            continue
        s = siteler.setdefault(alan, {"alan": alan, "ad": kaynak.get("title") or alan, "gecen": 0, "imzali": 0,
                                       "ornek_baslik": temiz, "ornek_link": e.get("link")})
        s["gecen"] += 1
        if imza_rx.search(st):
            if s["imzali"] == 0:
                s["ornek_baslik"], s["ornek_link"] = temiz, e.get("link")
            s["imzali"] += 1
    return sorted(siteler.values(), key=lambda s: (s["imzali"], s["gecen"]), reverse=True)[:6]


def adres_denetimi(ist: Istemci, ayar: dict, durum: dict, zorla: bool = False) -> list[str]:
    a = ayar["ayarlar"]
    da = a.get("adres_denetimi") or {}
    if da.get("acik") is False:
        return []
    sessiz_esik = int(da.get("sessizlik_gun", 10))
    tarama_gun = float(da.get("tarama_gun", 7))
    tarama_siniri = int(da.get("calisma_basina_tarama", 4))
    hata_esigi = int(da.get("hata_esigi", 12))  # 12 ardışık hata ≈ yarım saatlik çalışmada 6 saat

    aktif = [y for y in ayar["yazarlar"] if y.get("aktif") is not False]
    yd_hepsi = durum.setdefault("yazarlar", {})
    for ad in list(yd_hepsi):
        if ad not in {y["ad"] for y in aktif}:
            del yd_hepsi[ad]

    mesajlar: list[str] = []
    taranan = 0
    sirali = sorted(aktif, key=lambda y: yd_hepsi.get(y["ad"], {}).get("son_tarama") or "")
    for y in sirali:
        ad = y["ad"]
        yd = yd_hepsi.setdefault(ad, {})
        yd.setdefault("izlemeye_baslama", iso(simdi()))
        kaynaklar = [kd for kd in durum["kaynaklar"].values() if kd.get("yazar") == ad]
        yazi_var = any(kd.get("tur") in ("sayfa", "rss", "google_haber") for kd in kaynaklar)
        son = iso_oku(yd.get("son_yazi")) if yazi_var else iso_oku(yd.get("son_yazi") or yd.get("son_diger"))
        referans = son or iso_oku(yd["izlemeye_baslama"])
        gun = max(0, (simdi() - referans).days)
        esik = int(y.get("sessizlik_gun", sessiz_esik))
        sessiz = gun >= esik

        son_tarama = iso_oku(yd.get("son_tarama"))
        aralik = timedelta(days=max(1.0, tarama_gun / 3) if sessiz else tarama_gun)
        if zorla or (taranan < tarama_siniri and (not son_tarama or simdi() - son_tarama >= aralik)):
            taranan += 1
            try:
                yd["haberlerde"] = haber_taramasi(ist, ad)
                yd.pop("tarama_hatasi", None)
            except Exception as e:
                yd["tarama_hatasi"] = str(e)[:200]
            yd["son_tarama"] = iso(simdi())

        bilinen = {_alan_adi(kd.get("adres")) for kd in kaynaklar} | {
            _alan_adi(k.get("url") or k.get("yazar_dizini")) for k in _liste(y.get("kaynaklar"))}
        oneriler = [h for h in yd.get("haberlerde", []) if h["imzali"] >= 2 and h["alan"] not in bilinen]
        bilinen_imzali = any(h["imzali"] >= 1 and h["alan"] in bilinen for h in yd.get("haberlerde", []))

        erisilemeyen = [kd for kd in kaynaklar if kd.get("durum") == "hata" and kd.get("hata_sayisi", 0) >= hata_esigi]
        bos = [kd for kd in kaynaklar if kd.get("durum") == "uyari"]
        if erisilemeyen and len(erisilemeyen) == len(kaynaklar):
            kod, aciklama = "erisilemiyor", f"{erisilemeyen[0]['etiket']} sayfası saatlerdir açılmıyor"
        elif sessiz and oneriler and not bilinen_imzali:
            o = oneriler[0]
            kod = "tasinmis_olabilir"
            aciklama = (f"{gun} gündür yeni yazı gelmedi; son 30 günde imzalı yazıları "
                        f"{o['ad']} ({o['alan']}) sitesinde görünüyor — adresini değiştirmen gerekebilir")
        elif bos and bos[0].get("yedek") == "google_haber":
            kod, aciklama = "bos", (f"{bos[0]['etiket']} sitesi bulut sunucularından gelen istekleri engelliyor; "
                                    "Google Haberler üzerinden de kişinin yazıları bulunamadı")
        elif bos:
            kod, aciklama = "bos", f"{bos[0]['etiket']} sayfası açılıyor ama yazı bulunamıyor (site tasarımı/adresi değişmiş olabilir)"
        elif sessiz:
            kod, aciklama = "sessiz", f"{gun} gündür yeni yazı gelmedi (ara vermiş ya da yer değiştirmiş olabilir)"
        elif erisilemeyen:
            kod, aciklama = "kismen", f"{erisilemeyen[0]['etiket']} kaynağı saatlerdir açılmıyor"
        else:
            kod, aciklama = "tamam", "güncel"

        yd.update(durum=kod, aciklama=aciklama, son_denetim=iso(simdi()), sessiz_gun=gun,
                  esik_gun=esik, oneriler=oneriler[:3])
        if kod == "tamam":
            yd.pop("bildirilen", None)
        elif yd.get("bildirilen") != kod:
            mesajlar.append(f"{ad}: {aciklama}")
            yd["bildirilen"] = kod
    return mesajlar


def _etiket_tahmin(k: dict, tur: str) -> str:
    if tur == "youtube":
        return "YouTube"
    if tur == "youtube_ara":
        return "YouTube'da adı geçen"
    if tur.startswith("eksi"):
        return "Ekşi Sözlük"
    if tur == "instagram":
        return "Instagram"
    if tur == "google_haber":
        return (k.get("site") or "") + " (Google Haberler)"
    if tur == "bluesky":
        return "Bluesky"
    if tur == "telegram":
        return "Telegram"
    if tur == "podcast":
        return "Podcast"
    adres = k.get("url") or k.get("yazar_dizini") or ""
    host = urlparse(adres).netloc.replace("www.", "")
    return host.split(".")[0].capitalize() if host else tur


def _ayni_baslik_var(ogeler: list[dict], yazar: str, baslik: str) -> bool:
    b = sade(baslik)
    if len(b) < 12:
        return False
    return any(o["yazar"] == yazar and sade(o["baslik"]) == b for o in ogeler[:600])


def _siralama_anahtari(o: dict):
    # Yayın tarihi varsa onu, yoksa bulunma zamanını kullan; ileri tarihli saçma değerleri bulunmaya çek
    bulunma = iso_oku(o.get("bulunma")) or simdi()
    tarih = iso_oku(o.get("tarih")) or bulunma
    if tarih > bulunma + timedelta(hours=6):
        tarih = bulunma
    return tarih


# ───────────────────────── çıktılar ─────────────────────────

def rss_uret(ayar: dict, durum: dict, yol: Path):
    a = ayar["ayarlar"]
    ogeler = []
    for o in durum["ogeler"][:200]:
        dt = _siralama_anahtari(o)
        ogeler.append(
            "<item>"
            f"<title>{html.escape(o['yazar'] + ': ' + o['baslik'])}</title>"
            f"<link>{html.escape(o['url'])}</link>"
            f"<guid isPermaLink=\"false\">{o['id']}</guid>"
            f"<pubDate>{format_datetime(dt)}</pubDate>"
            f"<category>{html.escape(TUR_ETIKETLERI.get(o.get('tur', 'yazi'), 'Yazı'))}</category>"
            f"<description>{html.escape(o.get('ozet') or '')}</description>"
            "</item>"
        )
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
           f"<title>{html.escape(a.get('site_basligi', 'Takip Akışım'))}</title>"
           f"<link>{html.escape(a.get('site_adresi', ''))}</link>"
           "<description>Takip edilen yazarların yeni içerikleri</description>"
           f"<lastBuildDate>{format_datetime(simdi())}</lastBuildDate>"
           + "".join(ogeler) + "</channel></rss>\n")
    yol.write_text(xml, encoding="utf-8")


def _yazar_listesi(ayar: dict, durum: dict) -> list[dict]:
    """Uygulamanın 'Kaynaklar' ekranı için: kapalılar dahil tüm yazarlar ve kaynakları."""
    sonuc = []
    for y in ayar["yazarlar"]:
        kayitlar = []
        for k in y["kaynaklar"]:
            anahtar = kaynak_anahtari(y["ad"], k)
            kd = durum["kaynaklar"].get(anahtar) or {}
            tur = k.get("tur", "sayfa")
            kayitlar.append({
                "anahtar": anahtar, "tur": tur,
                "etiket": k.get("etiket") or _etiket_tahmin(k, tur),
                "adres": k.get("url") or k.get("kanal") or k.get("kullanici") or k.get("rss_url")
                or (f"YouTube araması: {k.get('arama') or y['ad']}" if k.get("tur") == "youtube_ara" else None)
                or k.get("yazar_dizini") or k.get("site"),
                "otomatik": bool(k.get("otomatik")),
                "kok": k.get("_kok", "yaml"),
                "kapali": k.get("aktif") is False,
                "durum": kd.get("durum") or ("bekliyor" if k.get("aktif") is not False else None),
                "son_hata": kd.get("son_hata"),
                "son_basari": kd.get("son_basari"),
                "not_": kd.get("not_") or ("Site doğrudan okunamıyor; Google Haberler üzerinden takip ediliyor"
                                           if tur == "google_haber" else None),
                "yedek": "google_haber" if tur == "google_haber" else kd.get("yedek"),
            })
        sonuc.append({"ad": y["ad"], "kok": y.get("_kok", "yaml"), "kapali": y.get("aktif") is False,
                      "kaynaklar": kayitlar})
    return sonuc


def sayfa_uret(ayar: dict, durum: dict, yol: Path):
    a = ayar["ayarlar"]
    sablon = (KOK / "sablon.html").read_text(encoding="utf-8")
    kaynaklar = []
    for anahtar, kd in durum["kaynaklar"].items():
        kaynaklar.append(dict({k: kd.get(k) for k in ("yazar", "tur", "etiket", "adres", "durum", "son_basari",
                                                       "son_deneme", "son_hata", "son_bulunan", "hata_sayisi", "not_")},
                              anahtar=anahtar))
    kaynaklar.sort(key=lambda x: (x["durum"] == "tamam", x["yazar"] or ""))
    yazarlar = [y["ad"] for y in ayar["yazarlar"] if y.get("aktif") is not False]
    veri = {
        "baslik": a.get("site_basligi", "Takip Akışım"),
        "olusturma": iso(simdi()),
        "yenileme_dk": a.get("yenileme_dakika", 30),
        "depo": os.environ.get("GITHUB_REPOSITORY") or a.get("github_depo") or "",
        "yazar_listesi": _yazar_listesi(ayar, durum),
        "aranacaklar": (ayar.get("_uygulama") or {}).get("aranacaklar", []),
        "kesif": (ayar.get("_uygulama") or {}).get("kesif", {}),
        "oneriler": (ayar.get("_uygulama") or {}).get("oneriler", {}),
        "gunluk_tarama": durum.get("gunluk_tarama", {}),
        "yazarlar": yazarlar,
        "ogeler": [
            {k: o.get(k) for k in ("id", "url", "baslik", "ozet", "yazar", "kaynak", "tur", "tarih",
                                   "bulunma", "ilk", "konu_haberi", "kaynak_id", "dogrulama", "tarih_gun") if k in o or k in ("id", "url")}
            for o in durum["ogeler"]
        ],
        "kaynaklar": kaynaklar,
        "denetim": [
            dict({k: (durum.get("yazarlar", {}).get(ad) or {}).get(k) for k in (
                "durum", "aciklama", "son_yazi", "son_diger", "sessiz_gun", "esik_gun", "son_tarama",
                "haberlerde", "oneriler", "tarama_hatasi")}, ad=ad)
            for ad in yazarlar
        ],
    }
    gomulu = json.dumps(veri, ensure_ascii=False).replace("</", "<\\/")
    cikti = (sablon.replace("__BASLIK__", html.escape(veri["baslik"]))
             .replace("__VERI__", gomulu))
    yol.write_text(cikti, encoding="utf-8")
    # Uygulama açıkken yenilemek için aynı veri ayrı dosya olarak da yazılır
    (yol.parent / "veri.json").write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
    # Telefona kurulum için gereken dosyalar (simgeler, manifest, çevrimdışı çalışma)
    kaynak_dir = KOK / "uygulama"
    if kaynak_dir.is_dir():
        for f in kaynak_dir.iterdir():
            if f.is_file():
                hedef = yol.parent / f.name
                if not hedef.exists() or hedef.read_bytes() != f.read_bytes():
                    shutil.copyfile(f, hedef)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    p = argparse.ArgumentParser(description="Yazar/sayfa takip akışı")
    p.add_argument("--ayar", default=str(KOK / "kaynaklar.yaml"))
    p.add_argument("--kontrol", action="store_true", help="kaynakları dene, hiçbir şey kaydetme")
    p.add_argument("--denetle", action="store_true",
                   help="tüm yazarların adres denetimini (haber taraması dahil) şimdi yap")
    arg = p.parse_args()
    os.chdir(KOK)
    sys.exit(calistir(Path(arg.ayar), sadece_kontrol=arg.kontrol, zorla_denetim=arg.denetle))


if __name__ == "__main__":
    main()
