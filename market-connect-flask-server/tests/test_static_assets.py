from __future__ import annotations

from app import create_app


def test_favicon_is_available_from_browser_and_static_urls():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    client = app.test_client()

    for path in ("/favicon.ico", "/static/favicon.svg"):
        response = client.get(path)

        assert response.status_code == 200
        assert response.mimetype == "image/svg+xml"
        assert b"SPACIS market stall" in response.data


def test_auth_dialog_assets_are_available():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    client = app.test_client()

    assert client.get("/static/auth-dialog.css").status_code == 200
    assert client.get("/static/auth-dialog.js").status_code == 200


def test_auth_dialog_offers_google_only():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})

    with app.app_context():
        template = app.jinja_env.get_template("_auth_dialog.html")
        source, _, _ = app.jinja_loader.get_source(app.jinja_env, "_auth_dialog.html")

    assert template is not None
    assert "auth-google-link" in source
    assert "auth-local-link" not in source
    assert "auth-register-link" not in source


def test_all_jinja_templates_compile():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})

    with app.app_context():
        for template_name in app.jinja_env.list_templates():
            app.jinja_env.get_template(template_name)
