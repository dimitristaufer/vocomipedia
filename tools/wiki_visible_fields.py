#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

GLOSS_LANGUAGES: list[tuple[str, str]] = [
    ("en", "English"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("it", "Italian"),
    ("ko", "Korean"),
    ("zh-Hans", "Chinese (Simplified)"),
    ("yue", "Cantonese"),
    ("ru", "Russian"),
    ("pt", "Portuguese"),
    ("he", "Hebrew"),
    ("tr", "Turkish"),
    ("vi", "Vietnamese"),
    ("ar", "Arabic"),
    ("nl", "Dutch"),
    ("uk", "Ukrainian"),
    ("hu", "Hungarian"),
    ("hi", "Hindi"),
    ("pl", "Polish"),
    ("el", "Greek"),
    ("nb", "Norwegian Bokmal"),
    ("id", "Indonesian"),
    ("sv", "Swedish"),
    ("ro", "Romanian"),
    ("cs", "Czech"),
    ("da", "Danish"),
    ("fi", "Finnish"),
    ("ja", "Japanese"),
]
VISIBLE_GLOSS_LANGS = {lang for lang, _label in GLOSS_LANGUAGES}
VISIBLE_SENTENCE_TRANSLATION_LANGS = VISIBLE_GLOSS_LANGS
