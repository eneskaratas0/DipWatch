// Liste sayfalarında arama ve "tek kaynaklı olayları göster" filtresi. JS kapalıysa her şey görünür.
(function () {
  var ara = document.getElementById("ara"), tek = document.getElementById("tek");
  if (!ara || !tek) return;
  try { tek.checked = localStorage.getItem("dipwatch-tek") === "1"; } catch (e) {}

  function uygula() {
    var q = ara.value.trim().toLowerCase().replace(/\u0307/g, "").replace(/ı/g, "i");
    document.body.classList.toggle("gizle-tek", !tek.checked);
    var gorunen = 0;
    document.querySelectorAll("section.gun").forEach(function (gun) {
      var n = 0;
      gun.querySelectorAll("li.olay").forEach(function (li) {
        var uyar = !q || li.dataset.ara.indexOf(q) !== -1;
        li.hidden = !uyar;
        if (uyar && (tek.checked || !li.classList.contains("tek"))) n++;
      });
      gun.hidden = n === 0;
      gorunen += n;
    });
    var yok = document.getElementById("sonuc-yok");
    if (yok) yok.hidden = gorunen > 0;
  }

  ara.addEventListener("input", uygula);
  tek.addEventListener("change", function () {
    try { localStorage.setItem("dipwatch-tek", tek.checked ? "1" : "0"); } catch (e) {}
    uygula();
  });
  uygula();
})();
