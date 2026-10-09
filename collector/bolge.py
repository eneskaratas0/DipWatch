"""İçerikten bölge tahmini.

export._bolge_tahmini eskiden bölgeyi kaynağın (beslemenin) bölgesinden çıkarıyordu; bu yüzden "UK PM
Burnham's Labour..." gibi haberler kaynağın bölgesine göre Orta Doğu'ya, Japon-Fransız kimya Nobeli
Asya-Pasifik'e düşüyordu. Burada bölge başlık/özette geçen ülke, şehir ve lider adlarından (TR+EN)
çoğunluk oyuyla çıkarılır. Konu coğrafi değilse (Nobel, BM genel vb.) "kuresel" sayılır. Kaynağın
bölgesi yalnızca içerik oyu eşitlik verdiğinde son çare olarak kullanılır.
"""
import re
from collections import Counter

# Kaynak gruplarından hangileri coğrafi değil (kaynak_tahmini'nde son çare oyu için elenir)
COGRAFI_DEGIL = {"turkce", "analiz_ve_resmi", "kuresel"}

# bölge -> başlık/özette aranacak ülke, şehir, lider adları (küçük harf, TR+EN)
COGRAFYA = {
    "orta_dogu": [
        "iran", "israil", "israel", "filistin", "palestine", "gazze", "gaza", "lübnan", "lebanon",
        "suriye", "syria", "irak", "iraq", "suudi arabistan", "saudi arabia", "yemen", "husi", "houthi",
        "ürdün", "jordan", "katar", "qatar", "bae", "emirates", "bahreyn", "bahrain", "kuveyt", "kuwait",
        "umman", "oman", "mısır", "egypt", "tahran", "tehran", "beyrut", "beirut", "bağdat", "baghdad",
        "şam", "damascus", "riyad", "riyadh", "kudüs", "jerusalem", "tel aviv", "kahire", "cairo",
        "sana", "sanaa", "hamas", "hizbullah", "hezbollah", "cidde", "jeddah", "mekke", "makkah",
    ],
    "rusya_ukrayna_kafkasya": [
        "rusya", "russia", "ukrayna", "ukraine", "kiev", "kyiv", "moskova", "moscow", "belarus",
        "beyaz rusya", "gürcistan", "georgia", "ermenistan", "armenia", "azerbaycan", "azerbaijan",
        "çeçenistan", "chechnya", "putin", "zelensky", "zelenskiy", "kremlin", "donbas", "kırım", "crimea",
    ],
    "avrupa": [
        "fransa", "france", "almanya", "germany", "ingiltere", "britain", "united kingdom", "uk",
        "ispanya", "spain", "italya", "italy", "polonya", "poland", "hollanda", "netherlands",
        "belçika", "belgium", "isveç", "sweden", "norveç", "norway", "danimarka", "denmark",
        "finlandiya", "finland", "yunanistan", "greece", "portekiz", "portugal", "avusturya", "austria",
        "isviçre", "switzerland", "macaristan", "hungary", "romanya", "romania", "bulgaristan", "bulgaria",
        "sırbistan", "serbia", "hırvatistan", "croatia", "çekya", "czech", "slovakya", "slovakia",
        "irlanda", "ireland", "avrupa birliği", "european union", "brüksel", "brussels", "londra", "london",
        "paris", "berlin", "roma", "rome", "madrid", "varşova", "warsaw",
    ],
    "asya_pasifik": [
        "çin", "china", "japonya", "japan", "güney kore", "south korea", "kuzey kore", "north korea",
        "hindistan", "india", "pakistan", "tayvan", "taiwan", "hong kong", "vietnam",
        "filipinler", "philippines", "endonezya", "indonesia", "malezya", "malaysia",
        "avustralya", "australia", "yeni zelanda", "new zealand", "myanmar", "bangladeş", "bangladesh",
        "afganistan", "afghanistan", "pekin", "beijing", "tokyo", "seul", "seoul", "yeni delhi",
        "new delhi", "islamabad", "kabil", "kabul",
    ],
    "afrika": [
        "nijerya", "nigeria", "güney afrika", "south africa", "kenya", "etiyopya", "ethiopia", "sudan",
        "somali", "somalia", "libya", "cezayir", "algeria", "fas", "morocco", "tunus", "tunisia",
        "mali", "çad", "chad", "kongo", "congo", "ruanda", "rwanda", "darfur", "el fasher", "nairobi",
        "lagos", "addis ababa",
    ],
    "amerika": [
        "amerika birleşik devletleri", "united states", "u.s.", "usa", "kanada", "canada", "meksika",
        "mexico", "brezilya", "brazil", "arjantin", "argentina", "venezuela", "kolombiya", "colombia",
        "şili", "chile", "peru", "washington", "beyaz saray", "white house", "latin amerika",
        "latin america",
    ],
    "turkiye": ["türkiye", "turkey", "ankara", "istanbul", "erdoğan", "erdogan"],
}

# Konu belirli bir bölgeye ait değilse (Nobel, BM genel vb.) ülke adı geçse de "kuresel" sayılır.
KURESEL_ZORUNLU = re.compile(
    r"\bnobel\b|birleşmiş milletler|united nations|\bbm genel\b|un general assembly|"
    r"dünya sağlık örgütü|world health organization|dünya bankası|world bank|\bimf\b|"
    r"uluslararası para fonu|\bg7\b|\bg20\b|olimpiyat|\bolympic|dünya kupası|\bworld cup\b",
    re.IGNORECASE)

_DESENLER = {
    b: re.compile(r"\b(?:" + "|".join(re.escape(ad) for ad in adlar) + r")\b", re.IGNORECASE)
    for b, adlar in COGRAFYA.items()
}


def _icerik_oylari(metin: str) -> set[str]:
    return {b for b, desen in _DESENLER.items() if desen.search(metin)}


def kaynak_tahmini(haberler) -> str:
    """Eski yöntem: haberlerin geldiği kaynak gruplarının çoğunluğu. Yalnızca son çare olarak kullanılır."""
    c = Counter(h["bolge"] for h in haberler if h["bolge"] not in COGRAFI_DEGIL)
    return c.most_common(1)[0][0] if c else "kuresel"


def tahmin_et(haberler) -> str:
    """Başlık+özetteki ülke/şehir/lider adlarına göre çoğunluk oyu; konu coğrafi değilse (Nobel, BM
    genel) 'kuresel'; içerik oyu eşitse kaynağın bölgesi son çare olarak kullanılır."""
    metinler = [f"{h['baslik']} {h.get('ozet') or ''}" for h in haberler]
    if any(KURESEL_ZORUNLU.search(m) for m in metinler):
        return "kuresel"
    oylar = Counter()
    for m in metinler:
        oylar.update(_icerik_oylari(m))
    if not oylar:
        return "kuresel"
    en_cok = oylar.most_common()
    if len(en_cok) == 1 or en_cok[0][1] > en_cok[1][1]:
        return en_cok[0][0]
    return kaynak_tahmini(haberler)  # eşitlik: son çare kaynak bölgesi
