"""GEO and language normalisation.

Real-world data uses three different conventions for "country":
  - ISO 2-letter code:  ES, DE, US
  - English name:       Spain, Germany, United States
  - Native or Russian:  España, Deutschland, Германия

Same for languages: "en" vs "English" vs "Английский".

The matcher needs to treat these as equivalent. This module collapses
everything to canonical forms (ISO 3166-1 alpha-2 for countries, ISO 639-1
for languages) so downstream code can compare with ==.

It also infers country / language from a URL's TLD when the source file
doesn't carry those columns — common with simple "domains list" exports.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse


# ----------------------------------------------------------------------------
# Country
# ----------------------------------------------------------------------------

# TLD → ISO-2.  Two-segment TLDs (co.uk, com.br) come first so the longer
# match wins.
TLD_TO_COUNTRY: dict[str, str] = {
    "co.uk": "GB", "org.uk": "GB",
    "com.br": "BR", "net.br": "BR",
    "com.mx": "MX",
    "com.ar": "AR",
    "com.au": "AU", "net.au": "AU",
    "com.cn": "CN", "net.cn": "CN",
    "co.jp": "JP", "ne.jp": "JP",
    "co.kr": "KR",
    "com.tw": "TW",
    "com.sg": "SG",
    "co.nz": "NZ",
    "co.za": "ZA",
    "co.in": "IN",
    "co.id": "ID",
    "com.my": "MY",
    "com.vn": "VN",
    "co.th": "TH", "in.th": "TH",
    "com.ph": "PH",
    "com.sa": "SA",
    "co.ae": "AE",
    "com.ua": "UA",
    "com.pk": "PK",
    "com.ng": "NG",
    "com.tr": "TR",
    "com.eg": "EG",
    # Single-segment TLDs
    "es": "ES", "de": "DE", "fr": "FR", "it": "IT", "pt": "PT",
    "uk": "GB", "us": "US", "ca": "CA", "au": "AU", "nz": "NZ",
    "br": "BR", "mx": "MX", "ar": "AR", "cl": "CL", "co": "CO",
    "pe": "PE", "ec": "EC", "uy": "UY", "ve": "VE", "bo": "BO",
    "ru": "RU", "ua": "UA", "by": "BY", "kz": "KZ", "uz": "UZ",
    "pl": "PL", "cz": "CZ", "sk": "SK", "hu": "HU", "ro": "RO",
    "bg": "BG", "hr": "HR", "rs": "RS", "si": "SI", "lt": "LT",
    "lv": "LV", "ee": "EE", "ie": "IE", "is": "IS", "gr": "GR",
    "tr": "TR", "il": "IL", "ae": "AE", "sa": "SA", "eg": "EG",
    "ng": "NG", "ke": "KE", "ma": "MA", "za": "ZA", "tn": "TN",
    "in": "IN", "pk": "PK", "bd": "BD", "lk": "LK", "id": "ID",
    "ph": "PH", "my": "MY", "th": "TH", "vn": "VN", "sg": "SG",
    "jp": "JP", "kr": "KR", "cn": "CN", "tw": "TW", "hk": "HK",
    "nl": "NL", "be": "BE", "ch": "CH", "at": "AT", "li": "LI",
    "lu": "LU", "se": "SE", "no": "NO", "dk": "DK", "fi": "FI",
    "mt": "MT", "cy": "CY", "al": "AL", "mk": "MK", "ba": "BA",
}

# Free-text → ISO-2. Cover English, native, Russian forms, and 2-letter codes.
COUNTRY_NAME_TO_CODE: dict[str, str] = {}


def _add(code: str, *names: str) -> None:
    COUNTRY_NAME_TO_CODE[code.lower()] = code
    for n in names:
        COUNTRY_NAME_TO_CODE[n.lower()] = code


_add("US", "united states", "usa", "america", "u.s.", "u.s.a", "сша", "соединённые штаты")
_add("GB", "united kingdom", "uk", "great britain", "britain", "england", "англия", "великобритания")
_add("DE", "germany", "deutschland", "германия", "немецкая", "немецкий")
_add("ES", "spain", "españa", "espana", "испания")
_add("FR", "france", "франция")
_add("IT", "italy", "italia", "италия")
_add("PT", "portugal", "португалия")
_add("NL", "netherlands", "nederland", "holland", "голландия", "нидерланды")
_add("BE", "belgium", "belgique", "бельгия")
_add("CH", "switzerland", "schweiz", "suisse", "швейцария")
_add("AT", "austria", "österreich", "австрия")
_add("SE", "sweden", "sverige", "швеция")
_add("NO", "norway", "norge", "норвегия")
_add("DK", "denmark", "danmark", "дания")
_add("FI", "finland", "suomi", "финляндия")
_add("PL", "poland", "polska", "польша")
_add("CZ", "czech republic", "czechia", "česká republika", "чехия")
_add("SK", "slovakia", "slovensko", "словакия")
_add("RO", "romania", "румыния")
_add("HU", "hungary", "magyarország", "венгрия")
_add("BG", "bulgaria", "българия", "болгария")
_add("HR", "croatia", "hrvatska", "хорватия")
_add("RS", "serbia", "srbija", "сербия")
_add("SI", "slovenia", "slovenija", "словения")
_add("LT", "lithuania", "lietuva", "литва")
_add("LV", "latvia", "latvija", "латвия")
_add("EE", "estonia", "eesti", "эстония")
_add("GR", "greece", "ελλάδα", "греция")
_add("TR", "turkey", "türkiye", "turkiye", "турция")
_add("IL", "israel", "ישראל", "израиль")
_add("RU", "russia", "russian federation", "россия")
_add("UA", "ukraine", "україна", "украина")
_add("BY", "belarus", "беларусь", "белоруссия")
_add("KZ", "kazakhstan", "казахстан")
_add("CA", "canada", "канада")
_add("MX", "mexico", "méxico", "mexico", "мексика")
_add("BR", "brazil", "brasil", "бразилия")
_add("AR", "argentina", "аргентина")
_add("CL", "chile", "чили")
_add("CO", "colombia", "колумбия")
_add("PE", "peru", "perú", "перу")
_add("VE", "venezuela", "венесуэла")
_add("UY", "uruguay", "уругвай")
_add("EC", "ecuador", "эквадор")
_add("BO", "bolivia", "боливия")
_add("JP", "japan", "日本", "япония")
_add("KR", "south korea", "korea", "republic of korea", "корея", "южная корея")
_add("CN", "china", "中国", "китай")
_add("TW", "taiwan", "台灣", "тайвань")
_add("HK", "hong kong", "香港", "гонконг")
_add("SG", "singapore", "сингапур")
_add("TH", "thailand", "ประเทศไทย", "таиланд")
_add("VN", "vietnam", "viet nam", "việt nam", "вьетнам")
_add("ID", "indonesia", "индонезия")
_add("MY", "malaysia", "малайзия")
_add("PH", "philippines", "филиппины")
_add("IN", "india", "индия", "bhārat")
_add("PK", "pakistan", "пакистан")
_add("BD", "bangladesh", "бангладеш")
_add("LK", "sri lanka", "шри-ланка")
_add("AU", "australia", "австралия")
_add("NZ", "new zealand", "новая зеландия")
_add("ZA", "south africa", "южная африка", "юар")
_add("NG", "nigeria", "нигерия")
_add("KE", "kenya", "кения")
_add("EG", "egypt", "egypt", "египет")
_add("MA", "morocco", "марокко")
_add("TN", "tunisia", "тунис")
_add("AE", "united arab emirates", "uae", "оаэ", "арабские эмираты")
_add("SA", "saudi arabia", "ksa", "саудовская аравия")
_add("IE", "ireland", "ирландия")
_add("IS", "iceland", "исландия")
# Balkans / Caucasus / Africa / Asia that were missing — these caused the
# "Bosnian donor on Austrian target" bug because they normalised to "".
_add("BA", "bosnia and herzegovina", "bosnia", "bosna i hercegovina", "босния и герцеговина", "босния")
_add("MK", "north macedonia", "macedonia", "северная македония", "македония")
_add("AL", "albania", "албания")
_add("ME", "montenegro", "черногория")
_add("XK", "kosovo", "косово")
_add("MD", "moldova", "молдова", "молдавия")
_add("GE", "georgia", "грузия", "сакартвело")
_add("AM", "armenia", "армения", "հայաստան")
_add("AZ", "azerbaijan", "азербайджан")
_add("ET", "ethiopia", "эфиопия")
_add("GH", "ghana", "гана")
_add("TZ", "tanzania", "танзания")
_add("UG", "uganda", "уганда")
_add("DZ", "algeria", "алжир")
_add("JO", "jordan", "иордания")
_add("LB", "lebanon", "ливан")
_add("IQ", "iraq", "ирак")
_add("IR", "iran", "иран")
_add("QA", "qatar", "катар")
_add("KW", "kuwait", "кувейт")
_add("BH", "bahrain", "бахрейн")
_add("OM", "oman", "оман")
_add("JM", "jamaica", "ямайка")
_add("DO", "dominican republic", "доминикана", "доминиканская республика")
_add("CR", "costa rica", "коста-рика")
_add("PA", "panama", "панама")
_add("GT", "guatemala", "гватемала")
_add("PY", "paraguay", "парагвай")
_add("CU", "cuba", "куба")
_add("NP", "nepal", "непал")
_add("KH", "cambodia", "камбоджа")
_add("MM", "myanmar", "burma", "мьянма")
_add("KZ", "kazakhstan", "казахстан")
_add("UZ", "uzbekistan", "узбекистан")
_add("AM", "armenia", "армения")
_add("LU", "luxembourg", "люксембург")
_add("MC", "monaco", "монако")


# ----------------------------------------------------------------------------
# Language
# ----------------------------------------------------------------------------

# TLD → ISO 639-1 language (best guess for the dominant language).
TLD_TO_LANG: dict[str, str] = {
    "co.uk": "en", "org.uk": "en", "uk": "en", "us": "en", "ca": "en",
    "au": "en", "com.au": "en", "nz": "en", "co.nz": "en",
    "ie": "en", "in": "en", "co.in": "en", "co.za": "en", "za": "en",
    "es": "es", "com.mx": "es", "mx": "es", "com.ar": "es", "ar": "es",
    "cl": "es", "pe": "es", "co": "es", "ec": "es", "uy": "es", "ve": "es",
    "de": "de", "at": "de", "li": "de",
    "fr": "fr", "be": "fr",
    "it": "it",
    "pt": "pt", "com.br": "pt", "br": "pt",
    "ru": "ru",
    "ua": "uk", "com.ua": "uk",
    "by": "be",
    "pl": "pl",
    "nl": "nl",
    "tr": "tr", "com.tr": "tr",
    "jp": "ja", "co.jp": "ja", "ne.jp": "ja",
    "kr": "ko", "co.kr": "ko",
    "cn": "zh", "com.cn": "zh", "tw": "zh", "com.tw": "zh", "hk": "zh",
    "th": "th", "co.th": "th",
    "vn": "vi", "com.vn": "vi",
    "id": "id", "co.id": "id",
    "my": "ms", "com.my": "ms",
    "ph": "tl", "com.ph": "tl",
    "il": "he",
    "ae": "ar", "co.ae": "ar", "sa": "ar", "com.sa": "ar", "eg": "ar", "com.eg": "ar",
    "se": "sv", "no": "no", "dk": "da", "fi": "fi",
    "gr": "el",
    "cz": "cs", "sk": "sk",
    "ro": "ro", "hu": "hu", "bg": "bg",
    "hr": "hr", "rs": "sr", "si": "sl",
    "lt": "lt", "lv": "lv", "ee": "et",
}

LANG_NAME_TO_CODE: dict[str, str] = {}


def _addl(code: str, *names: str) -> None:
    LANG_NAME_TO_CODE[code.lower()] = code
    for n in names:
        LANG_NAME_TO_CODE[n.lower()] = code


_addl("en", "english", "английский")
_addl("es", "spanish", "español", "espanol", "испанский", "castellano")
_addl("de", "german", "deutsch", "немецкий")
_addl("fr", "french", "français", "francais", "французский")
_addl("it", "italian", "italiano", "итальянский")
_addl("pt", "portuguese", "português", "portugues", "португальский")
_addl("ru", "russian", "русский")
_addl("uk", "ukrainian", "український", "украинский")
_addl("pl", "polish", "polski", "польский")
_addl("nl", "dutch", "nederlands", "голландский")
_addl("tr", "turkish", "türkçe", "turkce", "турецкий")
_addl("ja", "japanese", "日本語", "японский")
_addl("ko", "korean", "한국어", "корейский")
_addl("zh", "chinese", "中文", "китайский", "mandarin")
_addl("th", "thai", "тайский")
_addl("vi", "vietnamese", "tiếng việt", "вьетнамский")
_addl("id", "indonesian", "индонезийский", "bahasa")
_addl("ms", "malay", "малайский")
_addl("tl", "tagalog", "filipino", "тагальский")
_addl("hi", "hindi", "хинди")
_addl("mr", "marathi", "маратхи")
_addl("bn", "bengali", "бенгальский")
_addl("ar", "arabic", "العربية", "арабский")
_addl("he", "hebrew", "עברית", "иврит")
_addl("sv", "swedish", "svenska", "шведский")
_addl("no", "norwegian", "norsk", "норвежский")
_addl("da", "danish", "dansk", "датский")
_addl("fi", "finnish", "suomi", "финский")
_addl("el", "greek", "ελληνικά", "греческий")
_addl("cs", "czech", "čeština", "чешский")
_addl("sk", "slovak", "slovenčina", "словацкий")
_addl("ro", "romanian", "română", "румынский")
_addl("hu", "hungarian", "magyar", "венгерский")
_addl("bg", "bulgarian", "български", "болгарский")
_addl("hr", "croatian", "hrvatski", "хорватский")
_addl("sr", "serbian", "српски", "сербский")
_addl("sl", "slovenian", "slovenščina", "словенский")
_addl("lt", "lithuanian", "lietuvių", "литовский")
_addl("lv", "latvian", "latviešu", "латышский")
_addl("et", "estonian", "eesti", "эстонский")
_addl("be", "belarusian", "беларуская", "белорусский")
# Missing languages that normalised to "" → false wildcards in the matcher.
_addl("bs", "bosnian", "bosanski", "боснийский")
_addl("mk", "macedonian", "македонски", "македонский")
_addl("sq", "albanian", "shqip", "албанский")
_addl("hy", "armenian", "հայերեն", "армянский")
_addl("ka", "georgian", "ქართული", "грузинский")
_addl("az", "azerbaijani", "azərbaycan", "азербайджанский")
_addl("am", "amharic", "አማርኛ", "амхарский")
_addl("fa", "persian", "farsi", "فارسی", "персидский")
_addl("ur", "urdu", "اردو", "урду")
_addl("ta", "tamil", "தமிழ்", "тамильский")
_addl("te", "telugu", "телугу")
_addl("kk", "kazakh", "қазақ", "казахский")
_addl("uz", "uzbek", "oʻzbek", "узбекский")
_addl("km", "khmer", "кхмерский")
_addl("ne", "nepali", "непальский")
_addl("si", "sinhala", "сингальский")
_addl("sw", "swahili", "суахили")
_addl("af", "afrikaans", "африкаанс")


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

def _host_from_url(url: str) -> str:
    if not url:
        return ""
    raw = url.strip()
    if "://" not in raw:
        raw = "http://" + raw
    try:
        host = urlparse(raw).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _tail(host: str, segments: int) -> str:
    return ".".join(host.split(".")[-segments:]) if host else ""


def country_from_url(url: str) -> Optional[str]:
    host = _host_from_url(url)
    if not host:
        return None
    # Try two-segment TLD first (com.br, co.uk), then one-segment (es, de).
    two = _tail(host, 2)
    if two in TLD_TO_COUNTRY:
        return TLD_TO_COUNTRY[two]
    one = host.rsplit(".", 1)[-1]
    return TLD_TO_COUNTRY.get(one)


def language_from_url(url: str) -> Optional[str]:
    host = _host_from_url(url)
    if not host:
        return None
    two = _tail(host, 2)
    if two in TLD_TO_LANG:
        return TLD_TO_LANG[two]
    one = host.rsplit(".", 1)[-1]
    return TLD_TO_LANG.get(one)


def normalize_country(value: str) -> str:
    """Return the ISO-2 code or "" if we can't recognise the input."""
    if not value:
        return ""
    v = value.strip().lower()
    if not v:
        return ""
    return COUNTRY_NAME_TO_CODE.get(v, "")


def normalize_language(value: str) -> str:
    """Return the ISO 639-1 code or "" if unknown."""
    if not value:
        return ""
    v = value.strip().lower()
    if not v:
        return ""
    return LANG_NAME_TO_CODE.get(v, "")
