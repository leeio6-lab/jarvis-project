import json
from pathlib import Path

from shared.constants import DEFAULT_LOCALE, SUPPORTED_LOCALES

_LOCALE_DIR = Path(__file__).resolve().parent.parent.parent / "locale"
_cache: dict[str, dict[str, str]] = {}


def _load(locale: str) -> dict[str, str]:
    if locale not in _cache:
        path = _LOCALE_DIR / f"{locale}.json"
        if path.exists():
            _cache[locale] = json.loads(path.read_text(encoding="utf-8"))
        else:
            _cache[locale] = {}
    return _cache[locale]


def t(key: str, locale: str | None = None) -> str:
    locale = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
    messages = _load(locale)
    if key in messages:
        return messages[key]
    if locale != DEFAULT_LOCALE:
        fallback = _load(DEFAULT_LOCALE)
        if key in fallback:
            return fallback[key]
    return key
