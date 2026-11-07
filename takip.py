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
import base64
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
        ogeler = yedek_sonuclarini_suz(ist, ogeler, k, url, durum)
        return ogeler[: int(k.get("en_fazla", 25))]
    corba = BeautifulSoup(html_metin, "html.parser")

    desen = k.get("link_deseni")
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
    sorgu = quote(f'"{ad}" site:{site} when:30d')
    try:
        metin = ist.al(f"https://news.google.com/rss/search?q={sorgu}&hl=tr&gl=TR&ceid=TR:tr", deneme=1)
    except KaynakHatasi as e:
        raise KaynakHatasi(f"site bulut sunucularını engelliyor ve Google Haberler yedeği de açılamadı ({e})")
    sonuc = []
    for e in feedparser.parse(metin).entries:
        baslik = re.sub(r"\s+-\s+[^-]{1,40}$", "", e.get("title", "")).strip()
        # "Can Ataklı yazdı: ..." / "... | Can Ataklı" gibi ekleri at
        baslik = re.sub(r"^" + re.escape(ad) + r"\s*(yazdı)?\s*[:|-]\s*", "", baslik, flags=re.I)
        baslik = re.sub(r"\s*[|-]\s*" + re.escape(ad) + r"\s*$", "", baslik, flags=re.I).strip()
        if not baslik or not e.get("link"):
            continue
        tarih = datetime(*e["published_parsed"][:6], tzinfo=timezone.utc) if e.get("published_parsed") else None
        sonuc.append({"url": e["link"], "baslik": kisalt(baslik, 200), "tarih": iso(tarih), "tur": "yazi",
                      "_yedek": True})
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


def yedek_sonuclarini_suz(ist: Istemci, ogeler: list[dict], k: dict, sayfa_url: str, kd: dict) -> list[dict]:
    """Google Haberler yedeğinden gelenleri asıl adreslerine göre süzer: yalnızca yazarın kendi yazıları."""
    desen = re.compile(k["link_deseni"]) if k.get("link_deseni") else None
    on_ek = urlparse(sayfa_url).path.rstrip("/") + "/"

    def yazara_ait(u: str) -> bool:
        return bool(desen.search(u)) if desen else (urlparse(u).path.startswith(on_ek) and len(urlparse(u).path) > len(on_ek) + 3)

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
                o["gn_url"], o["url"] = o["url"], url_temizle(gercek)
                sonuc.append(o)
            else:
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
        tam = " ".join(c.get("value", "") for c in e.get("content", []) if isinstance(c, dict))
        tam = bosluk(BeautifulSoup(tam, "html.parser").get_text(" ")) if tam else ""
        if len(tam) > 600:
            oge["_metin"] = tam[:12000]
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
    return ogeler


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
            return {"tur": "youtube", "kanal": f"https://www.youtube.com/channel/{m.group(1)}",
                    "kanal_id": m.group(1), "etiket": "YouTube", "otomatik": True}
    return None


def _tek_yazi_adresi(u: str) -> bool:
    """Adres bir yazarın sayfası değil de tek bir haber/yazı gibi mi görünüyor? (ör. /haber/6008284/gazeteci-…)"""
    yol = urlparse(u).path.lower().rstrip("/")
    son = yol.rsplit("/", 1)[-1]
    return bool(re.search(r"/(haber|haberler|news|video|galeri|foto|gundem|makale|yazi)/", yol + "/")
                and not re.search(r"/(yazar|yazarlar|author)/", yol)) or son.count("-") >= 4


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


def yazar_kesfet(ist: Istemci, ad: str, youtube_ara_iste: bool = False) -> tuple[list[dict], str]:
    """Kişinin yazdığı yerleri bulur. (kaynaklar, açıklama) döner."""
    sorgu = quote(f'"{ad}" when:60d')
    alanlar: dict[str, dict] = {}
    try:
        akis = feedparser.parse(ist.al(f"https://news.google.com/rss/search?q={sorgu}&hl=tr&gl=TR&ceid=TR:tr",
                                       deneme=1))
        for e in akis.entries:
            kaynak = e.get("source") or {}
            href = kaynak.get("href") or ""
            alan = _alan_adi(href)
            if not alan or any(alan == g or alan.endswith("." + g) for g in GENEL_SITELER):
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
            bulunan.append({"tur": "sayfa", "url": bulundu, "etiket": s["ad"], "dogrula": True, "otomatik": True})
        elif any(k in ("403", "429", "503") for k in kodlar) and s["say"] >= 3:
            engelli.append({"tur": "google_haber", "site": s["alan"], "etiket": s["ad"], "otomatik": True})
    # site doğrudan açılmıyorsa ve başka yer bulunamadıysa: Google Haberler üzerinden izle
    if not any(b["tur"] in ("sayfa", "rss") for b in bulunan):
        bulunan.extend(engelli[:1])
    # 3) YouTube kanalı
    yt = _youtube_kanali_bul(ist, ad)
    if yt:
        bulunan.append(yt)
    # 4) başka kanallardaki programlar: istendiyse ya da köşe yazısı bulunamadıysa, adı başlıkta geçen videolar
    yazili = any(b["tur"] in ("sayfa", "rss", "google_haber") for b in bulunan)
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
    return bulunan, aciklama


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
        if kaynaklar:
            y = next((x for x in uyg["yazarlar"] if x.get("ad") == ad), None)
            if not y:
                y = {"ad": ad, "kaynaklar": []}
                uyg["yazarlar"].append(y)
            y.setdefault("kaynaklar", []).extend(kaynaklar)
            uyg["kapali_yazarlar"] = [x for x in _liste(uyg.get("kapali_yazarlar")) if x != ad]
            kesif[ad] = {"durum": "bulundu", "zaman": iso(simdi()), "aciklama": aciklama}
            mesajlar.append(f"{ad} eklendi: {aciklama}")
        else:
            kesif[ad] = {"durum": "bulunamadi", "zaman": iso(simdi()), "aciklama": aciklama}
            mesajlar.append(f"{ad}: {aciklama}")
        print(f"   → {aciklama}")
    islenen = {bosluk(a["ad"]) for a in aranacaklar[:8]}
    uyg["aranacaklar"] = [a for a in aranacaklar if bosluk(a["ad"]) not in islenen]
    yol.write_text(json.dumps(uyg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return mesajlar


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
        yazar_meta = sade(meta("author", "article:author", "dc.creator") or "")
        ld_metin = " ".join(s.get_text() for s in corba.find_all("script", type="application/ld+json"))
        if aranan not in yazar_meta and aranan not in sade(ld_metin) and aranan not in sade(corba.get_text(" ")[:20000]):
            return False

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
        dt = iso_oku(t)
        if dt:
            oge["tarih"] = iso(dt)
    govde = makale_metni(corba)
    if len(govde) > 600:
        oge["_metin"] = govde
    return True


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
    for y in ayar["yazarlar"]:
        y["kaynaklar"] = _liste(y.get("kaynaklar"))
        for k in y["kaynaklar"]:
            k.setdefault("_kok", "yaml")

    uyg_yol = Path(yol).with_name(UYGULAMA_DOSYASI)
    uyg = {}
    if uyg_yol.exists():
        try:
            uyg = json.loads(uyg_yol.read_text(encoding="utf-8")) or {}
        except Exception as e:
            print(f"! {UYGULAMA_DOSYASI} okunamadı, yok sayılıyor: {e}")
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
                         "konular": _liste(uyg.get("konular")),
                         "push": uyg.get("push") if isinstance(uyg.get("push"), dict) else {}}
    # telefondan yapılan bildirim ayarları (konu adı, sessiz saatler, susturulan yazarlar/türler…)
    uyg_bildirim = {k: v for k, v in (uyg.get("bildirim") or {}).items() if v not in (None, "")}
    if uyg_bildirim:
        ayar["ayarlar"]["bildirim"] = dict(ayar["ayarlar"].get("bildirim") or {}, **uyg_bildirim)
    if os.environ.get("NTFY_KONU"):
        ayar["ayarlar"]["bildirim"] = dict(ayar["ayarlar"].get("bildirim") or {},
                                           ntfy_konu=os.environ["NTFY_KONU"])
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


def calistir(ayar_yolu: Path, sadece_kontrol: bool = False, zorla_denetim: bool = False) -> int:
    ayar = ayar_oku(ayar_yolu)
    a = ayar["ayarlar"]
    ist = Istemci(bekleme=float(a.get("istekler_arasi_bekleme", 0.7)))
    kesif_mesajlari = [] if sadece_kontrol else kesif_calistir(ist, ayar_yolu)
    if kesif_mesajlari:
        ayar = ayar_oku(ayar_yolu)  # yeni bulunan kaynaklarla yeniden oku
        a = ayar["ayarlar"]
    a["_push"] = push_durumu(ayar)
    veri_dir = KOK / a.get("veri_klasoru", "veri")
    cikti_dir = KOK / a.get("cikti_klasoru", "docs")
    durum_yolu = veri_dir / "durum.json"
    durum = durum_oku(durum_yolu)
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
        if ilk_kez:
            taze = taze[:ilk_gosterim]
        dogrula = k.get("dogrula", bool(k.get("yazar_dizini")) or kd.get("tahmini", False))
        eklenen = 0
        for o in taze:
            if tur == "sayfa" and not o.pop("_yedek", False) and ayrinti_sayaci < ayrinti_siniri \
                    and k.get("ayrinti", True):
                ayrinti_sayaci += 1
                try:
                    if not ayrinti_getir(ist, o, (k.get("bul") or y["ad"]) if dogrula else None):
                        gorulen.add(o["url"])  # başka yazarın yazısı; bir daha bakma
                        continue
                except Exception as e:
                    print(f"   (ayrıntı alınamadı: {o['url']} — {e})")
            if _ayni_baslik_var(durum["ogeler"] + yeni_ogeler, y["ad"], o["baslik"]):
                gorulen.add(o["url"])
                continue
            o.update(id=kimlik(o["url"]), yazar=y["ad"], kaynak=o.pop("_kaynak", None) or kd["etiket"], kaynak_id=anahtar,
                     bulunma=iso(simdi()), ilk=ilk_kez or bool(o.pop("_eski", False)))
            yeni_ogeler.append(o)
            mevcut_url.add(o["url"])
            eklenen += 1
            _son_yaziyi_guncelle(durum, y["ad"], o)
        # Sayfada görünen her şeyi "görüldü" say ki ilk çalıştırmada eski yazılar akışa dolmasın
        simdiki = [o["url"] for o in ogeler]
        kd["gorulen"] = (simdiki + [u for u in kd["gorulen"] if u not in set(simdiki)])[:400]
        isaret = "★" if eklenen and not ilk_kez else "✓"
        print(f"{isaret} {etiket}: {len(ogeler)} öğe, {eklenen} {'ilk gösterim' if ilk_kez else 'yeni'}")

    if sadece_kontrol:
        return 0

    # takip edilen konular: haberlerde de aranması istenenler için Google Haberler taraması
    konular = konu_listesi(ayar)
    konu_kaydi = durum.setdefault("konular", {})
    for konu in konular:
        if not konu["haberler"]:
            continue
        kd = konu_kaydi.setdefault(konu["ad"], {})
        try:
            eklenen = 0
            for o in konu_haberleri(ist, konu, kd, ilk_gosterim):
                if o["url"] in mevcut_url or _ayni_baslik_var(durum["ogeler"] + yeni_ogeler, o["yazar"], o["baslik"]):
                    continue
                o.update(id=kimlik(o["url"]), kaynak_id="konu:" + konu["ad"], bulunma=iso(simdi()))
                yeni_ogeler.append(o)
                mevcut_url.add(o["url"])
                eklenen += 1
            kd.update(durum="tamam", son_hata=None)
            print(f"✓ Konu · {konu['ad']}: {eklenen} haber")
        except Exception as e:
            kd.update(durum="hata", son_hata=str(e)[:200])
            print(f"✗ Konu · {konu['ad']}: {e}")
    for ad in list(konu_kaydi):
        if ad not in {k["ad"] for k in konular if k["haberler"]}:
            del konu_kaydi[ad]

    # artık ayar dosyasında olmayan kaynakların kayıtlarını temizle
    for anahtar in list(durum["kaynaklar"]):
        if anahtar not in aktif_anahtarlar:
            del durum["kaynaklar"][anahtar]

    # kaldırılan/kapatılan kaynakların ve takipten çıkarılan kişilerin içerikleri akıştan da düşsün
    # (adres değişikliğinde aynı kişinin aynı türdeki geçmişi korunur)
    aktif_turler = {(y["ad"], k.get("icerik_turu") or KAYNAK_ICERIK_TURU.get(tur, "yazi"))
                    for y, k, tur, _ in kaynaklari_listele(ayar)}
    haberli_konular = {k["ad"] for k in konular if k["haberler"]}
    red_kumeleri = {a: set(kd.get("yedek_red") or []) for a, kd in durum["kaynaklar"].items() if kd.get("yedek_red")}
    red_tumu = set().union(*red_kumeleri.values()) if red_kumeleri else set()
    # adı her sayfada geçen sitelerde (ör. Oksijen) asıl adresi doğrulanmamış Google bağlantıları güvenilmez
    guvensiz = {a for y, k, tur, _ in kaynaklari_listele(ayar)
                for a in [kaynak_anahtari(y["ad"], k)]
                if k.get("yedek_dogrula") or (durum["kaynaklar"].get(a) or {}).get("ad_her_sayfada")}

    def akista_kalsin(o: dict) -> bool:
        if o.get("konu_haberi"):
            return o["konu_haberi"] in haberli_konular
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
    tum = [o for o in tum if (iso_oku(o.get("bulunma")) or simdi()) >= sinir]
    tum.sort(key=_siralama_anahtari, reverse=True)
    durum["ogeler"] = tum[: int(a.get("akista_en_fazla", 1500))]
    # isteğe bağlı: yeni köşe/blog yazılarına yapay zekâ özeti (GEMINI_ANAHTAR gizli ayarı varsa)
    yz_ozetle(ist, durum, os.environ.get("GEMINI_ANAHTAR") or a.get("gemini_anahtar"),
              sinir=int(a.get("yz_calisma_basina", 10)))

    # bildirimler: konu eşleşmeleri öne, susturulanlar hariç, sessiz saatlerde biriktir
    gercek_yeni = [o for o in yeni_ogeler if not o.get("ilk")]
    for o in gercek_yeni:
        o["konular"] = konulari_bul(o, konular)
    konulu, diger = bildirimleri_hazirla(a, gercek_yeni, konular)
    mesajlar = []
    if kesif_mesajlari:
        mesajlar.append(("Yeni takip: arama sonucu", kesif_mesajlari))
    if denetim_mesajlari:
        print("\nAdres denetimi:")
        for m in denetim_mesajlari:
            print("  • " + m)
        mesajlar.append(("Takip listesi: kontrol et", denetim_mesajlari))
    push_yeni_cihazlar(a)
    bildirimleri_gonder(ist, a, durum, konulu, diger, mesajlar)
    bulten_gonder(ist, a, durum, konular)
    push_kayitlarini_guncelle(ayar_yolu)

    for o in durum["ogeler"]:
        o.pop("_metin", None)  # tam metinler kayda girmesin (yalnızca özet için alındı)
    durum["son_calisma"] = iso(baslangic)
    durum["son_calisma_suresi_sn"] = round((simdi() - baslangic).total_seconds(), 1)

    veri_dir.mkdir(parents=True, exist_ok=True)
    gecici = durum_yolu.with_suffix(".tmp")
    gecici.write_text(json.dumps(durum, ensure_ascii=False, indent=1), encoding="utf-8")
    gecici.replace(durum_yolu)

    cikti_dir.mkdir(parents=True, exist_ok=True)
    sayfa_uret(ayar, durum, cikti_dir / "index.html")
    rss_uret(ayar, durum, cikti_dir / "akis.xml")

    print(f"\nBitti: {len(gercek_yeni)} yeni öğe, akışta toplam {len(durum['ogeler'])} öğe. "
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


# ───────────────────────── konular ─────────────────────────

def konu_listesi(ayar: dict) -> list[dict]:
    """kaynaklar.yaml'daki 'konular:' ile telefondan eklenen konuları birleştirir."""
    sonuc, gorulen = [], set()
    for x in _liste(ayar.get("konular")) + _liste((ayar.get("_uygulama") or {}).get("konular")):
        if isinstance(x, str):
            x = {"ad": x}
        if not isinstance(x, dict):
            continue
        ad = bosluk(x.get("ad"))
        if not ad or sade(ad) in gorulen:
            continue
        gorulen.add(sade(ad))
        kelimeler = [bosluk(k) for k in _liste(x.get("kelimeler")) if bosluk(k)] or [ad]
        sonuc.append({"ad": ad, "kelimeler": kelimeler, "haberler": bool(x.get("haberler")),
                      "bildirim": x.get("bildirim", True) is not False})
    return sonuc


def _konu_deseni(kelime: str) -> re.Pattern:
    # kelimenin başından eşleşir: "asgari ücret" → "asgari ücrete", "asgari ücretin" de tutar
    return re.compile(r"(?<![a-z0-9])" + re.escape(sade(kelime)))


def konulari_bul(o: dict, konular: list[dict]) -> list[str]:
    metin = sade(" ".join(str(o.get(k) or "") for k in ("baslik", "ozet", "yz_ozet")))
    bulunan = [k["ad"] for k in konular if any(_konu_deseni(w).search(metin) for w in k["kelimeler"])]
    if o.get("konu_haberi") and o["konu_haberi"] not in bulunan:
        bulunan.append(o["konu_haberi"])
    return bulunan


def konu_haberleri(ist: Istemci, konu: dict, kd: dict, ilk_gosterim: int) -> list[dict]:
    """Konunun kelimeleriyle Google Haberler'de son 2 günün haberlerini arar."""
    if feedparser is None:
        return []
    sorgu = " OR ".join(f'"{w}"' for w in konu["kelimeler"][:5]) + " when:2d"
    metin = ist.al(f"https://news.google.com/rss/search?q={quote(sorgu)}&hl=tr&gl=TR&ceid=TR:tr", deneme=1)
    ilk_kez = not kd.get("gorulen")
    gorulen = set(kd.get("gorulen") or [])
    sonuc, hepsi = [], []
    for e in feedparser.parse(metin).entries:
        link = e.get("link")
        if not link:
            continue
        hepsi.append(link)
        if link in gorulen:
            continue
        kaynak = bosluk((e.get("source") or {}).get("title")) if isinstance(e.get("source"), dict) else ""
        baslik = bosluk(e.get("title", ""))
        m = re.match(r"^(.*\S)\s+-\s+([^-]{1,60})$", baslik)
        if m:
            baslik, kaynak = m.group(1), kaynak or m.group(2).strip()
        tarih = datetime(*e["published_parsed"][:6], tzinfo=timezone.utc) if e.get("published_parsed") else None
        sonuc.append({"url": link, "baslik": kisalt(baslik, 300), "tarih": iso(tarih), "tur": "haber",
                      "yazar": kaynak or "Haber", "kaynak": "Google Haberler", "konu_haberi": konu["ad"],
                      "ilk": ilk_kez})
    sonuc.sort(key=lambda o: o.get("tarih") or "", reverse=True)
    kd["gorulen"] = (hepsi + [u for u in kd.get("gorulen") or [] if u not in set(hepsi)])[:500]
    kd["son"] = iso(simdi())
    return sonuc[:ilk_gosterim if ilk_kez else int(konu.get("en_fazla", 8))]


# ───────────────────────── bildirimler ─────────────────────────

def _dakika(s) -> int | None:
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})\s*$", str(s or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def sessiz_saatte_mi(b: dict, an: datetime | None = None) -> bool:
    bas, bit = _dakika(b.get("sessiz_bas")), _dakika(b.get("sessiz_bit"))
    if bas is None or bit is None or bas == bit:
        return False
    yerel = (an or simdi()).astimezone(TR_SAAT)
    t = yerel.hour * 60 + yerel.minute
    return bas <= t < bit if bas < bit else (t >= bas or t < bit)


def bildirimleri_hazirla(a: dict, yeniler: list[dict], konular: list[dict]) -> tuple[dict, list[dict]]:
    """Yeni öğeleri bildirim ayarlarına göre süzer → ({konu: [öğeler]}, [diğer öğeler])"""
    b = a.get("bildirim") or {}
    sessiz_yazar = set(_liste(b.get("sessiz_yazarlar")))
    sessiz_tur = set(_liste(b.get("sessiz_turler")))
    sadece_konular = b.get("kapsam") == "konular"
    bildirimli_konu = {k["ad"] for k in konular if k["bildirim"]}
    konulu: dict[str, list[dict]] = {}
    diger = []
    for o in yeniler:
        eslesen = [k for k in o.get("konular") or [] if k in bildirimli_konu]
        if eslesen:
            konulu.setdefault(eslesen[0], []).append(o)
        elif not (sadece_konular or b.get("anlik") is False or o.get("konu_haberi")
                  or o["yazar"] in sessiz_yazar or o.get("tur", "yazi") in sessiz_tur):
            diger.append(o)
    return konulu, diger


def site_adresi(a: dict) -> str:
    if a.get("site_adresi"):
        return a["site_adresi"]
    depo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in depo:
        sahip, ad = depo.split("/", 1)
        return f"https://{sahip}.github.io/{ad}/" if ad.lower() != f"{sahip.lower()}.github.io" else f"https://{ad}/"
    return ""


def bildirimleri_gonder(ist: Istemci, a: dict, durum: dict, konulu: dict, diger: list[dict],
                        mesajlar: list[tuple[str, list[str]]]):
    """Sessiz saatlerde biriktirir; sessiz saat bitince birikenleri tek bildirimde yollar."""
    b = a.get("bildirim") or {}
    if not bildirim_kanali_var(a):
        return
    bekleyen = durum.setdefault("bekleyen_bildirim", [])
    if sessiz_saatte_mi(b):
        for konu, ogeler in konulu.items():
            bekleyen.extend(f"🔖 {o['yazar']}: {o['baslik']}" for o in ogeler)
        if _dakika(b.get("bulten_saat")) is None:
            bekleyen.extend(f"{o['yazar']}: {o['baslik']}" for o in diger)
        for baslik, satirlar in mesajlar:
            bekleyen.extend(f"{baslik} — {x}" for x in satirlar)
        durum["bekleyen_bildirim"] = bekleyen[-60:]
        if konulu or diger or mesajlar:
            print("→ sessiz saatler: bildirim sabaha bırakıldı")
        return
    if bekleyen:
        satirlar = bekleyen[:10] + ([f"…ve {len(bekleyen) - 10} tane daha"] if len(bekleyen) > 10 else [])
        bildirim_gonder(ist, a, [], baslik=f"Sessiz saatlerde gelenler ({len(bekleyen)})", satirlar=satirlar)
        durum["bekleyen_bildirim"] = []
    for konu, ogeler in konulu.items():
        bildirim_gonder(ist, a, ogeler, baslik=f"{konu}: {len(ogeler)} yeni", oncelik="high", etiket="bookmark")
    if diger:
        bildirim_gonder(ist, a, diger)
    for baslik, satirlar in mesajlar:
        bildirim_gonder(ist, a, [], baslik=baslik, satirlar=satirlar)


def bildirim_gonder(ist: Istemci, a: dict, yeniler: list[dict], baslik: str | None = None,
                    satirlar: list[str] | None = None, oncelik: str | None = None, etiket: str = "newspaper",
                    tikla: str | None = None):
    """Telefona bildirim: uygulamanın kendi bildirimi (Web Push) ve/veya ntfy."""
    if not bildirim_kanali_var(a):
        return
    konu = (a.get("bildirim") or {}).get("ntfy_konu")
    sunucu = (a.get("bildirim") or {}).get("ntfy_sunucu", "https://ntfy.sh").rstrip("/")
    if satirlar is None:
        satirlar = [f"{o['yazar']}: {o['baslik']}" for o in yeniler[:8]]
        if len(yeniler) > 8:
            satirlar.append(f"…ve {len(yeniler) - 8} tane daha")
    baslik = baslik or f"{len(yeniler)} yeni içerik"
    basliklar = {"Title": baslik.encode("utf-8"), "Tags": etiket}
    if oncelik:
        basliklar["Priority"] = oncelik
    adres = site_adresi(a)
    if len(yeniler) == 1:  # tek yazıysa bildirime dokununca doğrudan yazı açılsın
        basliklar["Click"] = yeniler[0]["url"]
        if adres:
            basliklar["Actions"] = f"view, Akışı aç, {adres}"
    elif adres:
        basliklar["Click"] = adres
    if tikla:
        basliklar["Click"] = tikla
    if (a.get("_push") or {}).get("durum") == "hazir":
        simge = {"bookmark": "🔖 ", "sunny": "☀ "}.get(etiket, "")
        push_gonder(a, simge + baslik, "\n".join(satirlar), basliklar.get("Click") or adres or "./",
                    etiket={"bookmark": "takip-konu", "sunny": "takip-bulten"}.get(etiket, "takip-yeni"),
                    acil=bool(oncelik))
    if not konu:
        return
    try:
        ist.gonder(f"{sunucu}/{konu}", "\n".join(satirlar).encode("utf-8"), basliklar)
        print("→ telefona bildirim gönderildi (ntfy)")
    except Exception as e:
        print(f"! bildirim gönderilemedi: {e}")


# ───────────────────────── uygulama bildirimleri (Web Push) ─────────────────────────

PUSH_GECERSIZ: set[str] = set()   # süresi dolmuş / iptal edilmiş abonelikler
PUSH_ONAY: dict[str, str] = {}    # ilk deneme bildirimi ulaşan abonelikler


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _vapid_eslesir(gizli: str, acik: str) -> bool:
    try:
        from py_vapid import Vapid
        from cryptography.hazmat.primitives import serialization
        ham = Vapid.from_string(gizli).public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return _b64u(ham) == acik.strip().rstrip("=")
    except Exception:
        return False


def push_durumu(ayar: dict) -> dict:
    p = (ayar.get("_uygulama") or {}).get("push") or {}
    acik = (p.get("acik_anahtar") or "").strip()
    abone = [x for x in _liste(p.get("abonelikler"))
             if isinstance(x, dict) and x.get("endpoint") and isinstance(x.get("keys"), dict)]
    gizli = os.environ.get("VAPID_GIZLI", "").strip() or str(ayar["ayarlar"].get("vapid_gizli") or "")
    if not acik:
        d = "kapali"
    elif not gizli:
        d = "gizli_yok"
    elif not _vapid_eslesir(gizli, acik):
        d = "uyusmuyor"
    else:
        d = "hazir" if abone else "abone_yok"
    return {"acik_anahtar": acik, "abonelikler": abone, "gizli": gizli, "durum": d}


def _vapid_sub(a: dict) -> str:
    # bildirim servisleri gönderenin bir iletişim adresini ister; sitenin kök adresi yeterli
    u = urlparse(site_adresi(a) or "https://github.com")
    return f"https://{u.netloc}" if u.netloc else "https://github.com"


def bildirim_kanali_var(a: dict) -> bool:
    return bool((a.get("bildirim") or {}).get("ntfy_konu")) or (a.get("_push") or {}).get("durum") == "hazir"


def push_gonder(a: dict, baslik: str, metin: str, url: str, etiket: str = "takip", acil: bool = False,
                yalnizca: list[dict] | None = None) -> int:
    """Uygulamaya abone olan her cihaza bildirim gönderir; ulaşan cihaz sayısını döndürür."""
    p = a.get("_push") or {}
    try:
        from pywebpush import webpush, WebPushException
    except Exception:
        print("! uygulama bildirimi için pywebpush kurulu değil")
        return 0
    yuk = json.dumps({"baslik": baslik, "metin": metin[:1500], "url": url, "etiket": etiket}, ensure_ascii=False)
    ulasan = 0
    for ab in (yalnizca if yalnizca is not None else p.get("abonelikler") or []):
        if ab["endpoint"] in PUSH_GECERSIZ:
            continue
        try:
            webpush({"endpoint": ab["endpoint"], "keys": ab["keys"]}, yuk, vapid_private_key=p["gizli"],
                    vapid_claims={"sub": _vapid_sub(a)}, ttl=12 * 3600,
                    headers={"Urgency": "high" if acil else "normal"}, timeout=15)
            ulasan += 1
        except WebPushException as e:
            kod = getattr(getattr(e, "response", None), "status_code", None)
            if kod in (404, 410):
                PUSH_GECERSIZ.add(ab["endpoint"])
                print(f"– {ab.get('cihaz') or 'bir cihaz'}: bildirim aboneliği artık geçersiz, listeden çıkarılıyor")
            else:
                print(f"! uygulama bildirimi gönderilemedi ({ab.get('cihaz') or 'cihaz'}): HTTP {kod} {str(e)[:120]}")
        except Exception as e:
            print(f"! uygulama bildirimi gönderilemedi: {type(e).__name__}: {str(e)[:120]}")
    if ulasan:
        print(f"→ {ulasan} cihaza uygulama bildirimi gönderildi")
    return ulasan


def push_yeni_cihazlar(a: dict):
    """Yeni abone olan cihaza bir kez 'bildirimler açık' iletisi yollar; ulaşırsa onaylanmış sayılır."""
    p = a.get("_push") or {}
    if p.get("durum") != "hazir":
        return
    for ab in p["abonelikler"]:
        if ab.get("onay"):
            continue
        if push_gonder(a, "Takip bildirimleri açık ✓", "Yeni yazılar ve konuların bu cihaza bildirim olarak gelecek.",
                       site_adresi(a) or "./", etiket="takip-deneme", yalnizca=[ab]):
            PUSH_ONAY[ab["endpoint"]] = iso(simdi())


def push_kayitlarini_guncelle(ayar_yolu: Path):
    """Geçersiz abonelikleri siler, onaylananları işaretler (kaynaklar_uygulama.json)."""
    if not (PUSH_GECERSIZ or PUSH_ONAY):
        return
    yol = Path(ayar_yolu).with_name(UYGULAMA_DOSYASI)
    try:
        uyg = json.loads(yol.read_text(encoding="utf-8"))
        p = uyg.get("push") or {}
        yeni = []
        for ab in _liste(p.get("abonelikler")):
            if not isinstance(ab, dict) or ab.get("endpoint") in PUSH_GECERSIZ:
                continue
            if ab.get("endpoint") in PUSH_ONAY and not ab.get("onay"):
                ab["onay"] = PUSH_ONAY[ab["endpoint"]]
            yeni.append(ab)
        p["abonelikler"] = yeni
        uyg["push"] = p
        yol.write_text(json.dumps(uyg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as e:
        print(f"! bildirim abonelikleri güncellenemedi: {e}")


def bulten_icerigi(durum: dict, konular: list[dict], baslangic: datetime) -> tuple[int, list[str]]:
    """baslangic'tan beri gelen öğeleri kişiye göre gruplayıp bülten satırlarını üretir."""
    ogeler = [o for o in durum["ogeler"]
              if not o.get("ilk") and (iso_oku(o.get("bulunma")) or baslangic) > baslangic]
    if not ogeler:
        return 0, []
    satirlar = []
    konu_say: dict[str, int] = {}
    for o in ogeler:
        for k in konulari_bul(o, konular):
            konu_say[k] = konu_say.get(k, 0) + 1
    for k, n in sorted(konu_say.items(), key=lambda x: -x[1]):
        satirlar.append(f"🔖 {k}: {n} içerik")
    kisiler: dict[str, list[dict]] = {}
    for o in ogeler:
        if not o.get("konu_haberi"):
            kisiler.setdefault(o["yazar"], []).append(o)
    sirali = sorted(kisiler.items(), key=lambda x: (-len(x[1]), x[0]))
    for ad, liste in sirali[:14]:
        bas = kisalt(liste[0]["baslik"], 90)
        satirlar.append(f"• {ad}: {bas}" if len(liste) == 1 else f"• {ad} ({len(liste)}): {bas} …")
    if len(sirali) > 14:
        satirlar.append(f"…ve {len(sirali) - 14} kişiden daha")
    return len(ogeler), satirlar


def bulten_gonder(ist: Istemci, a: dict, durum: dict, konular: list[dict], an: datetime | None = None) -> bool:
    """Bülten saati geldiyse (günde bir kez) son bültenden beri gelenleri tek bildirimde yollar."""
    b = a.get("bildirim") or {}
    saat = _dakika(b.get("bulten_saat"))
    if saat is None or not bildirim_kanali_var(a):
        return False
    an = an or simdi()
    yerel = an.astimezone(TR_SAAT)
    bugun = yerel.date().isoformat()
    if durum.get("bulten_gun") == bugun or yerel.hour * 60 + yerel.minute < saat or sessiz_saatte_mi(b, an):
        return False
    son = iso_oku(durum.get("bulten_son"))
    baslangic = max(son, an - timedelta(days=2)) if son else an - timedelta(hours=24)
    sayi, satirlar = bulten_icerigi(durum, konular, baslangic)
    durum.update(bulten_gun=bugun, bulten_son=iso(an))
    if not sayi:
        print("☀ bülten: son bültenden beri yeni içerik yok, gönderilmedi")
        return False
    adres = site_adresi(a)
    bildirim_gonder(ist, a, [], baslik=f"Günün özeti: {sayi} yeni içerik", satirlar=satirlar,
                    etiket="sunny", tikla=(adres + "?bulten=1") if adres else None)
    return True


# ───────────────────────── yapay zekâ özetleri ─────────────────────────

YZ_TABAN = "https://generativelanguage.googleapis.com/v1beta"
YZ_ISTEM = ("Aşağıda {yazar} imzalı bir yazının metni var. Bu yazıyı Türkçe olarak en fazla üç cümleyle, "
            "tarafsız biçimde özetle: yazarın ana iddiası ve dayandığı başlıca olgular. Kendi yorumunu ve "
            "değerlendirmeni ekleme, \"Bu yazıda\" gibi girişler yapma; yalnızca özeti yaz.\n\n"
            "Başlık: {baslik}\n\nMetin:\n{metin}")


class YzHatasi(Exception):
    pass


def _yz_istek(yontem: str, yol: str, anahtar: str, govde: dict | None = None):
    basliklar = {"x-goog-api-key": anahtar, "Content-Type": "application/json"}
    r = http_std.request(yontem, YZ_TABAN + yol, headers=basliklar, json=govde, timeout=60)
    if r.status_code == 429:
        raise YzHatasi("kota")
    if r.status_code in (400, 401, 403) and "API key" in r.text:
        raise YzHatasi("Gemini anahtarı geçersiz ya da bu hesapta Gemini API açık değil")
    if r.status_code != 200:
        raise YzHatasi(f"Gemini HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def yz_model_sec(anahtar: str, yz: dict) -> str:
    """Anahtarın erişebildiği modellerden özet için uygun bir 'Flash' modeli seçer (haftada bir yenilenir)."""
    secim = iso_oku(yz.get("secim"))
    if yz.get("model") and secim and simdi() - secim < timedelta(days=7):
        return yz["model"]
    adlar, sayfa = [], ""
    for _ in range(5):
        j = _yz_istek("GET", f"/models?pageSize=200{'&pageToken=' + sayfa if sayfa else ''}", anahtar)
        adlar += [m["name"].split("/", 1)[-1] for m in j.get("models", [])
                  if "generateContent" in (m.get("supportedGenerationMethods") or [])]
        sayfa = j.get("nextPageToken") or ""
        if not sayfa:
            break
    for tercih in ("gemini-flash-lite-latest", "gemini-flash-latest"):
        if tercih in adlar:
            yz.update(model=tercih, secim=iso(simdi()))
            return tercih
    yasak = ("image", "tts", "audio", "live", "embedding", "native", "exp", "computer", "robotics", "thinking")
    adaylar = [a for a in adlar if a.startswith("gemini-") and "flash" in a and not any(y in a for y in yasak)]
    if not adaylar:
        raise YzHatasi("Gemini'de uygun model bulunamadı")

    def puan(a: str):
        surum = tuple(int(x) for x in re.findall(r"\d+", a.split("-flash")[0])) or (0,)
        return ("preview" not in a, surum, "lite" in a, not re.search(r"-\d{3}$|-\d{2}-\d{4}$", a))
    model = max(adaylar, key=puan)
    yz.update(model=model, secim=iso(simdi()))
    return model


def yz_ozetle(ist: Istemci, durum: dict, anahtar: str | None, sinir: int = 10, bekleme: float = 4.5) -> int:
    """Son iki günün özetlenmemiş köşe/blog yazılarına Gemini ile kısa özet ekler."""
    yz = durum.setdefault("yz", {})
    if not anahtar:
        yz.update(durum="kapali")
        return 0
    bugun = simdi().astimezone(TR_SAAT).date().isoformat()
    if yz.get("gun") != bugun:
        yz.update(gun=bugun, bugun=0)
    if yz.get("kota_gunu") == bugun and yz.get("kota_saati") and \
            simdi() - iso_oku(yz["kota_saati"]) < timedelta(hours=3):
        return 0  # kota doldu; üç saat sonra tekrar denenir
    sinir_zaman = simdi() - timedelta(days=2)
    adaylar = [o for o in durum["ogeler"]
               if o.get("tur", "yazi") == "yazi" and not o.get("yz_ozet") and o.get("yz_deneme", 0) < 2
               and "news.google.com" not in o["url"] and (iso_oku(o.get("bulunma")) or simdi()) >= sinir_zaman]
    adaylar.sort(key=lambda o: (bool(o.get("ilk")), not o.get("_metin")))
    yapilan = 0
    try:
        model = yz_model_sec(anahtar, yz)
        for o in adaylar[:sinir]:
            metin = o.get("_metin")
            if not metin:
                try:
                    metin = makale_metni(BeautifulSoup(ist.al(o["url"], deneme=1), "html.parser"))
                except Exception:
                    metin = ""
            if len(metin) < 600:
                o["yz_deneme"] = 2  # metni okunamıyor; bir daha deneme
                continue
            if yapilan:
                time.sleep(bekleme)
            o["yz_deneme"] = o.get("yz_deneme", 0) + 1
            try:
                j = _yz_istek("POST", f"/models/{model}:generateContent", anahtar, {
                    "contents": [{"role": "user", "parts": [{"text": YZ_ISTEM.format(
                        yazar=o["yazar"], baslik=o["baslik"], metin=metin[:12000])}]}],
                    "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048}})
            except YzHatasi as e:
                if "HTTP 404" in str(e):
                    yz.pop("model", None)  # model emekliye ayrılmış; bir dahaki sefere yenisini seç
                raise
            parcalar = ((j.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
            ozet = bosluk(" ".join(p.get("text", "") for p in parcalar if not p.get("thought")))
            if ozet:
                o["yz_ozet"] = kisalt(ozet, 700)
                yapilan += 1
        yz.update(durum="acik", son_hata=None, son_basari=iso(simdi()) if yapilan else yz.get("son_basari"))
    except YzHatasi as e:
        if str(e) == "kota":
            yz.update(durum="acik", kota_gunu=bugun, kota_saati=iso(simdi()),
                      son_hata="Günlük ücretsiz kullanım sınırı doldu; birkaç saat sonra devam edecek")
        else:
            yz.update(durum="hata", son_hata=str(e)[:300])
        print(f"! yapay zekâ özeti: {yz['son_hata']}")
    except Exception as e:
        yz.update(durum="hata", son_hata=f"{type(e).__name__}: {str(e)[:200]}")
        print(f"! yapay zekâ özeti: {yz['son_hata']}")
    yz["bugun"] = yz.get("bugun", 0) + yapilan
    if yapilan:
        print(f"✨ {yapilan} yazıya yapay zekâ özeti eklendi ({yz.get('model')})")
    return yapilan


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
        "ntfy_konu": (a.get("bildirim") or {}).get("ntfy_konu") or "",
        "yazar_listesi": _yazar_listesi(ayar, durum),
        "aranacaklar": (ayar.get("_uygulama") or {}).get("aranacaklar", []),
        "kesif": (ayar.get("_uygulama") or {}).get("kesif", {}),
        "konular": konu_listesi(ayar),
        "konu_durumu": {ad: {k: v for k, v in kd.items() if k != "gorulen"}
                        for ad, kd in (durum.get("konular") or {}).items()},
        "bildirim": {k: (a.get("bildirim") or {}).get(k) for k in (
            "sessiz_bas", "sessiz_bit", "kapsam", "sessiz_turler", "sessiz_yazarlar", "bulten_saat", "anlik")},
        "push": {"acik_anahtar": (a.get("_push") or {}).get("acik_anahtar") or "",
                 "durum": (a.get("_push") or push_durumu(ayar)).get("durum"),
                 "cihazlar": [{"kimlik": kimlik(x["endpoint"]), "cihaz": x.get("cihaz"), "zaman": x.get("zaman"),
                               "onay": x.get("onay") or PUSH_ONAY.get(x["endpoint"])}
                              for x in (a.get("_push") or push_durumu(ayar)).get("abonelikler", [])
                              if x["endpoint"] not in PUSH_GECERSIZ]},
        "yz": {k: (durum.get("yz") or {}).get(k) for k in (
            "durum", "model", "son_hata", "son_basari", "bugun")},
        "yazarlar": yazarlar,
        "ogeler": [
            {k: o.get(k) for k in ("id", "url", "baslik", "ozet", "yazar", "kaynak", "tur", "tarih",
                                   "bulunma", "ilk", "yz_ozet", "konu_haberi", "kaynak_id") if k in o or k in ("id", "url")}
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
