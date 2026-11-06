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
        sonuc.append({"url": url_temizle(link), "baslik": kisalt(baslik, 300),
                      "ozet": kisalt(ozet, 260), "tarih": iso(tarih), "tur": k.get("icerik_turu", "yazi")})
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
    ogeler = rss_oku(ist, k2, durum, yazar)
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


def yazar_kesfet(ist: Istemci, ad: str) -> tuple[list[dict], str]:
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
                                         "say": 0})
            s["say"] += 1
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
                if _yazar_sayfasi_mi(ist, aday, ad)[0]:
                    bulundu = aday
                    break
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
        kaynaklar, aciklama = yazar_kesfet(ist, ad)
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


OKUYUCULAR = {
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
    return True


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
                               or k.get("yazar_dizini") or k.get("rss_url") or k.get("site")))


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
                         "kesif": uyg.get("kesif") or {}}
    if (uyg.get("bildirim") or {}).get("ntfy_konu"):
        ayar["ayarlar"].setdefault("bildirim", {})
        ayar["ayarlar"]["bildirim"] = dict(ayar["ayarlar"]["bildirim"] or {},
                                           ntfy_konu=uyg["bildirim"]["ntfy_konu"])
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
                   "adres": k.get("url") or k.get("kanal") or k.get("kullanici") or k.get("yazar_dizini")})
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
                  not_=("Site doğrudan okunmaya izin vermiyor; Google Haberler üzerinden takip ediliyor"
                        if kd.get("yedek") else None))
        if sadece_kontrol:
            print(f"✓ {etiket}: {len(ogeler)} öğe" + (" (tahmini desen)" if kd.get("tahmini") else ""))
            for o in ogeler[:3]:
                print(f"      - {o['baslik'][:90]}  →  {o['url']}")
            continue

        ilk_kez = not kd["gorulen"]
        gorulen = set(kd["gorulen"])
        if ogeler and len(ogeler) == len([o for o in ogeler if o["url"] not in gorulen]) and not ilk_kez \
                and len(ogeler) > 8:
            # Sitenin adres yapısı değişmiş olabilir: hepsini yeni sayıp akışı doldurmayalım
            print(f"! {etiket}: sayfadaki her şey yeni görünüyor, adres yapısı değişmiş olabilir; "
                  f"ilk {ilk_gosterim} tanesi gösterilecek")
            ilk_kez = True
        taze = [o for o in ogeler if o["url"] not in gorulen and o["url"] not in mevcut_url]
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
            o.update(id=kimlik(o["url"]), yazar=y["ad"], kaynak=kd["etiket"], kaynak_id=anahtar,
                     bulunma=iso(simdi()), ilk=ilk_kez)
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

    # artık ayar dosyasında olmayan kaynakların kayıtlarını temizle
    for anahtar in list(durum["kaynaklar"]):
        if anahtar not in aktif_anahtarlar:
            del durum["kaynaklar"][anahtar]

    # yazarlar hâlâ aynı yerde mi yazıyor?
    denetim_mesajlari = adres_denetimi(ist, ayar, durum, zorla=zorla_denetim)

    # akışı güncelle ve buda
    sinir = simdi() - timedelta(days=int(a.get("akista_tutulacak_gun", 45)))
    tum = yeni_ogeler + durum["ogeler"]
    tum = [o for o in tum if (iso_oku(o.get("bulunma")) or simdi()) >= sinir]
    tum.sort(key=_siralama_anahtari, reverse=True)
    durum["ogeler"] = tum[: int(a.get("akista_en_fazla", 1500))]
    durum["son_calisma"] = iso(baslangic)
    durum["son_calisma_suresi_sn"] = round((simdi() - baslangic).total_seconds(), 1)

    veri_dir.mkdir(parents=True, exist_ok=True)
    gecici = durum_yolu.with_suffix(".tmp")
    gecici.write_text(json.dumps(durum, ensure_ascii=False, indent=1), encoding="utf-8")
    gecici.replace(durum_yolu)

    cikti_dir.mkdir(parents=True, exist_ok=True)
    sayfa_uret(ayar, durum, cikti_dir / "index.html")
    rss_uret(ayar, durum, cikti_dir / "akis.xml")

    gercek_yeni = [o for o in yeni_ogeler if not o.get("ilk")]
    print(f"\nBitti: {len(gercek_yeni)} yeni öğe, akışta toplam {len(durum['ogeler'])} öğe. "
          f"Sayfa: {cikti_dir / 'index.html'}")
    if gercek_yeni:
        bildirim_gonder(ist, a, gercek_yeni)
    if kesif_mesajlari:
        bildirim_gonder(ist, a, [], baslik="Yeni takip: arama sonucu", satirlar=kesif_mesajlari)
    if denetim_mesajlari:
        print("\nAdres denetimi:")
        for m in denetim_mesajlari:
            print("  • " + m)
        bildirim_gonder(ist, a, [], baslik="Takip listesi: kontrol et", satirlar=denetim_mesajlari)
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


def bildirim_gonder(ist: Istemci, a: dict, yeniler: list[dict], baslik: str | None = None,
                    satirlar: list[str] | None = None):
    """İsteğe bağlı: ntfy.sh üzerinden telefona anlık bildirim."""
    konu = (a.get("bildirim") or {}).get("ntfy_konu")
    if not konu:
        return
    sunucu = (a.get("bildirim") or {}).get("ntfy_sunucu", "https://ntfy.sh").rstrip("/")
    if satirlar is None:
        satirlar = [f"{o['yazar']}: {o['baslik']}" for o in yeniler[:8]]
        if len(yeniler) > 8:
            satirlar.append(f"…ve {len(yeniler) - 8} tane daha")
    baslik = baslik or f"{len(yeniler)} yeni içerik"
    basliklar = {"Title": baslik.encode("utf-8"), "Tags": "newspaper"}
    if a.get("site_adresi"):
        basliklar["Click"] = a["site_adresi"]
    try:
        ist.gonder(f"{sunucu}/{konu}", "\n".join(satirlar).encode("utf-8"), basliklar)
        print("→ telefona bildirim gönderildi")
    except Exception as e:
        print(f"! bildirim gönderilemedi: {e}")


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
        "yazarlar": yazarlar,
        "ogeler": [
            {k: o.get(k) for k in ("id", "url", "baslik", "ozet", "yazar", "kaynak", "tur", "tarih",
                                   "bulunma", "ilk")}
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
