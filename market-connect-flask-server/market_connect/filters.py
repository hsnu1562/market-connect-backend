from __future__ import annotations

import json

from flask import Flask
from markupsafe import Markup


def register_template_filters(app: Flask) -> None:
    @app.template_filter("date")
    def date_filter(value, fmt: str = "Y-m-d"):
        if value is None:
            return ""
        django_to_python = {
            "Y": "%Y",
            "m": "%m",
            "d": "%d",
            "H": "%H",
            "i": "%M",
            "M": "%b",
        }
        python_fmt = fmt
        for django_token, python_token in django_to_python.items():
            python_fmt = python_fmt.replace(django_token, python_token)
        return value.strftime(python_fmt) if hasattr(value, "strftime") else str(value)

    @app.template_filter("escapejs")
    def escapejs_filter(value):
        # Django's escapejs returns a JS-string-safe fragment, not a JSON string.
        escaped = json.dumps(str(value), ensure_ascii=False)[1:-1]
        return Markup(escaped)
