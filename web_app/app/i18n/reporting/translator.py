# app/i18n/reporting/translator.py
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional

from importlib import resources


@dataclass(frozen=True)
class LanguageSpec:
    code: str
    label: str
    locale: str
    icon: str
    file: str


class ReportingTranslator:
    """
    Report-only translator.

    - Reads manifest + catalogs from package resources (Git-tracked).
    - Fallback chain: requested lang -> default lang -> key
    - Logs missing keys via provided logger (optional).
    """

    def __init__(self, logger=None):
        self._logger = logger

        # IMPORTANT: RLock to avoid deadlocks from nested calls (t() -> normalize_lang()).
        self._lock = threading.RLock()

        self._manifest: Optional[Dict[str, Any]] = None
        self._languages: Dict[str, LanguageSpec] = {}
        self._default_lang: str = "en"

        # cache: lang -> catalog dict
        self._catalogs: Dict[str, Dict[str, str]] = {}

    def _load_manifest(self) -> None:
        if self._manifest is not None:
            return

        with resources.files("app.i18n.reporting").joinpath("manifest.json").open("rb") as f:
            manifest = json.load(f)

        default_lang = manifest.get("default_lang", "en")
        langs = manifest.get("languages", {})

        parsed: Dict[str, LanguageSpec] = {}
        for code, spec in langs.items():
            parsed[code] = LanguageSpec(
                code=code,
                label=str(spec.get("label", code)),
                locale=str(spec.get("locale", code)),
                icon=str(spec.get("icon", "")),
                file=str(spec.get("file", "")),
            )

        self._manifest = manifest
        self._languages = parsed
        self._default_lang = default_lang if default_lang in parsed else "en"

    def get_default_lang(self) -> str:
        with self._lock:
            self._load_manifest()
            return self._default_lang

    def get_language_specs(self) -> Dict[str, LanguageSpec]:
        with self._lock:
            self._load_manifest()
            return dict(self._languages)

    def normalize_lang(self, lang: Optional[str]) -> str:
        with self._lock:
            self._load_manifest()
            if not lang:
                return self._default_lang
            lang = lang.strip().lower()
            return lang if lang in self._languages else self._default_lang

    def _load_catalog(self, lang: str) -> Dict[str, str]:
        self._load_manifest()
        if lang in self._catalogs:
            return self._catalogs[lang]

        spec = self._languages.get(lang)
        if not spec or not spec.file:
            self._catalogs[lang] = {}
            return self._catalogs[lang]

        with resources.files("app.i18n.reporting").joinpath(spec.file).open("rb") as f:
            data = json.load(f)

        # enforce flat dict[str,str]
        catalog: Dict[str, str] = {}
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(k, str) and isinstance(v, str):
                    catalog[k] = v

        self._catalogs[lang] = catalog
        return catalog

    def t(self, key: str, lang: Optional[str] = None, **kwargs: Any) -> str:
        """
        Translate key in requested language with fallback to default.
        Supports simple {placeholders} via str.format.
        """
        if not isinstance(key, str) or not key:
            return ""

        with self._lock:
            self._load_manifest()

            # Avoid nested lock call: normalize manually here.
            lang_norm = (lang or self._default_lang).strip().lower() if isinstance(lang, str) else self._default_lang
            if lang_norm not in self._languages:
                lang_norm = self._default_lang

            default_lang = self._default_lang

            cat = self._load_catalog(lang_norm)
            text = cat.get(key)

            if text is None and lang_norm != default_lang:
                text = self._load_catalog(default_lang).get(key)

            if text is None:
                if self._logger:
                    self._logger.warning(f"[i18n] Missing key '{key}' (lang={lang_norm}, default={default_lang})")
                text = key

        # formatting outside lock
        try:
            return text.format(**kwargs) if kwargs else text
        except Exception:
            if self._logger:
                self._logger.warning(f"[i18n] Bad format for key '{key}' with kwargs={kwargs}")
            return text
