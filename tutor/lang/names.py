"""Language codes and names for the learner's own language (any language Whisper can recognise).

The native language is used three ways: the LLM writes translations and explanations in it (by name),
Whisper recognises questions asked in it (by code), and the review video needs a font for it.
"""

# Whisper's languages (code → English name)
WHISPER = {
    "en": "English", "zh": "Chinese", "de": "German", "es": "Spanish", "ru": "Russian", "ko": "Korean",
    "fr": "French", "ja": "Japanese", "pt": "Portuguese", "tr": "Turkish", "pl": "Polish", "ca": "Catalan",
    "nl": "Dutch", "ar": "Arabic", "sv": "Swedish", "it": "Italian", "id": "Indonesian", "hi": "Hindi",
    "fi": "Finnish", "vi": "Vietnamese", "he": "Hebrew", "uk": "Ukrainian", "el": "Greek", "ms": "Malay",
    "cs": "Czech", "ro": "Romanian", "da": "Danish", "hu": "Hungarian", "ta": "Tamil", "no": "Norwegian",
    "th": "Thai", "ur": "Urdu", "hr": "Croatian", "bg": "Bulgarian", "lt": "Lithuanian", "la": "Latin",
    "mi": "Maori", "ml": "Malayalam", "cy": "Welsh", "sk": "Slovak", "te": "Telugu", "fa": "Persian",
    "lv": "Latvian", "bn": "Bengali", "sr": "Serbian", "az": "Azerbaijani", "sl": "Slovenian", "kn": "Kannada",
    "et": "Estonian", "mk": "Macedonian", "br": "Breton", "eu": "Basque", "is": "Icelandic", "hy": "Armenian",
    "ne": "Nepali", "mn": "Mongolian", "bs": "Bosnian", "kk": "Kazakh", "sq": "Albanian", "sw": "Swahili",
    "gl": "Galician", "mr": "Marathi", "pa": "Punjabi", "si": "Sinhala", "km": "Khmer", "sn": "Shona",
    "yo": "Yoruba", "so": "Somali", "af": "Afrikaans", "oc": "Occitan", "ka": "Georgian", "be": "Belarusian",
    "tg": "Tajik", "sd": "Sindhi", "gu": "Gujarati", "am": "Amharic", "yi": "Yiddish", "lo": "Lao",
    "uz": "Uzbek", "fo": "Faroese", "ht": "Haitian Creole", "ps": "Pashto", "tk": "Turkmen", "nn": "Nynorsk",
    "mt": "Maltese", "sa": "Sanskrit", "lb": "Luxembourgish", "my": "Myanmar", "bo": "Tibetan", "tl": "Tagalog",
    "mg": "Malagasy", "as": "Assamese", "tt": "Tatar", "haw": "Hawaiian", "ln": "Lingala", "ha": "Hausa",
    "ba": "Bashkir", "jw": "Javanese", "su": "Sundanese", "yue": "Cantonese",
}
# Written variants that matter for explanations and fonts; Whisper hears them as the base language.
VARIANTS = {
    "zh-TW": ("Traditional Chinese (Taiwan)", "zh"), "zh-HK": ("Traditional Chinese (Hong Kong)", "zh"),
    "zh-CN": ("Simplified Chinese", "zh"), "pt-BR": ("Brazilian Portuguese", "pt"),
}
ALIASES = {"mandarin": "zh-CN", "taiwanese mandarin": "zh-TW", "traditional chinese": "zh-TW",
           "simplified chinese": "zh-CN", "farsi": "fa", "burmese": "my", "filipino": "tl", "javanese": "jw"}


def normalize(text: str) -> str | None:
    """'vi', 'Vietnamese', 'ZH-tw', 'traditional chinese' → a code; None if unknown."""
    t = text.strip()
    if not t:
        return None
    low = t.lower()
    for code in VARIANTS:
        if low == code.lower():
            return code
    if low in WHISPER:
        return low
    if low in ALIASES:
        return ALIASES[low]
    for code, name in WHISPER.items():
        if low == name.lower():
            return code
    for code, (name, _) in VARIANTS.items():
        if low == name.lower():
            return code
    return None


def name(code: str) -> str:
    """English name for prompts ("Traditional Chinese (Taiwan)"); unknown codes pass through."""
    return VARIANTS[code][0] if code in VARIANTS else WHISPER.get(code, code)


def whisper_code(code: str) -> str:
    return VARIANTS[code][1] if code in VARIANTS else code
