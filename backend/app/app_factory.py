"""应用工厂。"""

from __future__ import annotations

from flask import Flask, current_app, jsonify
from flask_cors import CORS

from .config import get_config
from .db import Database


def get_db() -> Database:
    return current_app.extensions["worldbranch_db"]


def create_app(overrides: dict | None = None) -> Flask:
    cfg = get_config(overrides)

    app = Flask(
        __name__,
        static_folder=str(cfg.WEB_DIR / "static"),
        static_url_path="/static",
        template_folder=str(cfg.WEB_DIR),
    )
    app.config["WORLDBRANCH"] = cfg
    app.json.ensure_ascii = False

    CORS(app, resources={r"/api/*": {"origins": cfg.CORS_ORIGINS or "*"}})

    db = Database(cfg.DATABASE_URL, echo=cfg.SQL_ECHO)
    app.extensions["worldbranch_db"] = db

    from .api import register_blueprints

    register_blueprints(app)

    @app.get("/")
    def index():
        from flask import render_template

        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "project": "WorldBranch"})

    @app.errorhandler(LookupError)
    def handle_lookup(err):
        return jsonify({"error": str(err)}), 404

    @app.errorhandler(ValueError)
    def handle_value(err):
        return jsonify({"error": str(err)}), 400

    from .cli import register_cli

    register_cli(app)

    return app