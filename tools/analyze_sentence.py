#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json

from vocomipedia_nlp import analyze_sentence


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Vocomipedia offline sentence token/POS analysis.")
    ap.add_argument("--language", required=True)
    ap.add_argument("--sentence", required=True)
    ap.add_argument("--ruby-source", default=None, help="Bracketed Japanese sentence source, e.g. 山[やま]を見る。")
    args = ap.parse_args()
    result = analyze_sentence(args.language, args.sentence, ruby_source=args.ruby_source)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
