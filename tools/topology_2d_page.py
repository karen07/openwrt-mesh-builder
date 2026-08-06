#!/usr/bin/env python3
# Python wrapper only. Keep all page markup in topology-2d-template.html.
import json
from html import escape
from pathlib import Path
from typing import Any

TEMPLATE_PATH = Path(__file__).with_name("topology-2d-template.html")


def clean_generated_html(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


def html_page(data: dict[str, Any]) -> str:
    data_json = json.dumps(data, ensure_ascii=False, indent=2)
    replacements = {
        "__TITLE__": escape(str(data["title"]), quote=True),
        "__DATA_JSON__": data_json,
    }

    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    for marker, value in replacements.items():
        text = text.replace(marker, value)
    return clean_generated_html(text)
