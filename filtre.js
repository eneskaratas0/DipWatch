// Liste sayfalarında arama + "/" kısayolu + göreli zaman + olay sayfasında dil filtresi + başa dön düğmesi.
// JS kapalıysa: arama kutusu/dil filtresi görünmez ama sayfa eksiksiz kalır, saatler kesin kalır.
(function () {
  "use strict";

  // Göreli zaman: <time class="zaman" datetime="ISO">son haber <span class="zaman-deger">14:32</span></time>
  // JS kapalıysa kesin saat (HH:MM) görünür kalır; burada metni "3 sa önce" gibi göreliye çevrilir,
  // kesin saat ise hover için title'a taşınır.
  function bagilZaman(ms) {
    var dk = Math.round(ms / 60000);
    if (dk < 1) return "az önce";
    if (dk < 60) return dk + " dk önce";
    var sa = Math.round(dk / 60);
    if (sa < 24) return sa + " sa önce";
    return Math.round(sa / 24) + " gün önce";
  }
  document.querySelectorAll("time.zaman[datetime]").forEach(function (t) {
    var d = new Date(t.getAttribute("datetime"));
    var deger = t.querySelector(".zaman-deger");
    if (!deger || isNaN(d.getTime())) return;
    var fark = Date.now() - d.getTime();
    if (fark < 0) return; // gelecekteki saat (saat dilimi tuhaflığı) - dokunma
    t.title = "Kesin saat: " + deger.textContent;
    deger.textContent = bagilZaman(fark);
  });

  // Arama: büyük/küçük harf ve ı/i farkı aramayı bozmasın (build.py'deki arama_metni ile aynı sadeleştirme)
  var ara = document.getElementById("ara");
  if (ara) {
    var sonucEl = document.getElementById("sonuc-sayisi");
    var yokEl = document.getElementById("sonuc-yok");
    var zamanlayici = null;

    function uygula() {
      var q = ara.value.trim().toLowerCase().replace(/̇/g, "").replace(/ı/g, "i");
      var gorunen = 0;
      document.querySelectorAll("section.gun").forEach(function (gun) {
        var n = 0;
        gun.querySelectorAll("li.olay").forEach(function (li) {
          var uyar = !q || li.dataset.ara.indexOf(q) !== -1;
          li.hidden = !uyar;
          if (uyar) n++;
        });
        gun.hidden = n === 0;
        gorunen += n;
      });
      if (yokEl) yokEl.hidden = gorunen > 0 || !q;
      if (sonucEl) {
        clearTimeout(zamanlayici);
        zamanlayici = setTimeout(function () {
          sonucEl.textContent = q ? gorunen + " olay bulundu" : "";
        }, 350); // çok sık duyuru okuyucuyu boğmasın diye yazarken küçük bir bekleme
      }
    }
    ara.addEventListener("input", uygula);
    uygula();

    // "/" ile arama kutusuna odaklan (başka bir alana yazarken tetiklenmesin)
    document.addEventListener("keydown", function (ev) {
      if (ev.key !== "/" || ev.metaKey || ev.ctrlKey || ev.altKey) return;
      var h = ev.target, dolu = h && (h.tagName === "INPUT" || h.tagName === "TEXTAREA" || h.isContentEditable);
      if (dolu) return;
      ev.preventDefault();
      ara.focus();
    });
  }

  // Başa dön: bir ekran boyu aşağı inilince belirir; tıklayınca yumuşakça başa kayar (hareket azaltma
  // tercihinde anında), klavye kullanıcısının yeri kaybolmasın diye odak logoya taşınır.
  var basaDon = document.querySelector(".basa-don");
  if (basaDon) {
    var bekliyor = false;
    function guncelle() {
      bekliyor = false;
      basaDon.classList.toggle("kapali", window.scrollY < window.innerHeight * 0.8);
    }
    // ilk durum animasyonsuz uygulanır, yoksa sayfa açılırken düğme bir an görünüp söner
    basaDon.style.transition = "none";
    guncelle();
    void basaDon.offsetWidth;
    basaDon.style.transition = "";
    window.addEventListener("scroll", function () {
      if (!bekliyor) { bekliyor = true; window.requestAnimationFrame(guncelle); }
    }, { passive: true });
    basaDon.addEventListener("click", function (ev) {
      ev.preventDefault();
      var azHareket = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      window.scrollTo({ top: 0, behavior: azHareket ? "auto" : "smooth" });
      var logo = document.querySelector(".logo");
      if (logo) logo.focus({ preventScroll: true });
    });
  }

  // Teknoloji sayfası: kategori düğmeleri + kaynak seçimi + arama birlikte uygulanır. Seçim adres
  // çubuğuna yazılır (?kategori=...&kaynak=...&q=...), böylece filtrelenmiş görünüm paylaşılabilir.
  var teknoAraclar = document.querySelector(".tekno-araclar");
  if (teknoAraclar) {
    teknoAraclar.hidden = false; // JS kapalıysa filtreler gizli kalır, tüm haberler görünür
    var tAra = document.getElementById("tekno-ara");
    var tKaynak = document.getElementById("tekno-kaynak");
    var tDugmeler = teknoAraclar.querySelectorAll("button[data-kategori]");
    var tSonuc = document.getElementById("sonuc-sayisi");
    var tYok = document.getElementById("sonuc-yok");
    var tKategori = "";
    var tZaman = null;

    var p = new URLSearchParams(window.location.search);
    tKategori = p.get("kategori") || "";
    if (p.get("kaynak")) tKaynak.value = p.get("kaynak");
    if (tKaynak.selectedIndex < 0) tKaynak.value = "";
    if (p.get("q")) tAra.value = p.get("q");

    function teknoUygula() {
      tDugmeler.forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.kategori === tKategori ? "true" : "false"); });
      var q = tAra.value.trim().toLowerCase().replace(/̇/g, "").replace(/ı/g, "i");
      var kaynak = tKaynak.value;
      var gorunen = 0;
      document.querySelectorAll("section.gun").forEach(function (gun) {
        var n = 0;
        gun.querySelectorAll("li.tekno-haber").forEach(function (li) {
          var uyar = (!tKategori || li.dataset.kategori === tKategori) &&
                     (!kaynak || li.dataset.kaynak === kaynak) &&
                     (!q || li.dataset.ara.indexOf(q) !== -1);
          li.hidden = !uyar;
          if (uyar) n++;
        });
        gun.hidden = n === 0;
        gorunen += n;
      });
      var filtreli = !!(tKategori || kaynak || q);
      if (tYok) tYok.hidden = gorunen > 0 || !filtreli;
      if (tSonuc) {
        clearTimeout(tZaman);
        tZaman = setTimeout(function () { tSonuc.textContent = filtreli ? gorunen + " haber bulundu" : ""; }, 350);
      }
      var yeni = new URLSearchParams();
      if (tKategori) yeni.set("kategori", tKategori);
      if (kaynak) yeni.set("kaynak", kaynak);
      if (q) yeni.set("q", tAra.value.trim());
      var s = yeni.toString();
      try { history.replaceState(null, "", window.location.pathname + (s ? "?" + s : "")); } catch (e) { /* file:// */ }
    }
    tDugmeler.forEach(function (b) {
      b.addEventListener("click", function () { tKategori = b.dataset.kategori; teknoUygula(); });
    });
    tKaynak.addEventListener("change", teknoUygula);
    tAra.addEventListener("input", teknoUygula);
    teknoUygula();

    document.addEventListener("keydown", function (ev) {
      if (ev.key !== "/" || ev.metaKey || ev.ctrlKey || ev.altKey) return;
      var h = ev.target;
      if (h && (h.tagName === "INPUT" || h.tagName === "TEXTAREA" || h.tagName === "SELECT" || h.isContentEditable)) return;
      ev.preventDefault();
      tAra.focus();
    });
  }

  // Olay sayfası: zaman çizelgesinde dil filtresi (Tümü / TR / EN)
  var dilDugmeleri = document.querySelectorAll(".dil-filtre button");
  if (dilDugmeleri.length) {
    var detay = document.querySelector(".cizelge-devam > details");
    dilDugmeleri.forEach(function (btn) {
      btn.addEventListener("click", function () {
        dilDugmeleri.forEach(function (b) { b.setAttribute("aria-pressed", b === btn ? "true" : "false"); });
        var dil = btn.dataset.dil;
        var acikGun = null;
        // ".cizelge > li": ana liste ve <details> içindeki devam listesi (ikisi de "cizelge" sınıflı);
        // gruplanmış haberin kendi iç listesi (.cizelge-ic) kapsanmaz, görünürlüğü üst öğeyle belirlenir.
        document.querySelectorAll(".cizelge > li").forEach(function (li) {
          if (li.classList.contains("cizelge-devam")) return;
          if (li.classList.contains("cizelge-gun")) { li.hidden = true; acikGun = li; return; }
          var uyar = !dil || li.dataset.dil === dil;
          li.hidden = !uyar;
          if (uyar && acikGun) { acikGun.hidden = false; acikGun = null; }
        });
        if (detay) detay.open = true; // filtrelenen haberler daralmışın içindeyse de görünsün
      });
    });
  }
})();
