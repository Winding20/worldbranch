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

    app = Flask(__name__)
    app.config["WORLDBRANCH"] = cfg
    app.json.ensure_ascii = False

    CORS(app, resources={r"/api/*": {"origins": cfg.CORS_ORIGINS or "*"}})

    db = Database(cfg.DATABASE_URL, echo=cfg.SQL_ECHO)
    app.extensions["worldbranch_db"] = db

    from .api import register_blueprints

    register_blueprints(app)

    @app.get("/")
    def index():
        """默认入口：Vue 界面。"""
        from flask import redirect

        if (cfg.VUE_DIST / "index.html").exists():
            return redirect("/app/")
        return (
            "前端尚未构建。请先执行：cd frontend && node build.mjs"
            "（或用 start.bat / start.sh 启动，脚本会处理）",
            503,
        )

    # ---- Vue 3 新界面：构建产物由 Vite 输出到 frontend/dist ----
    vue_dist = cfg.VUE_DIST

    @app.get("/app/")
    @app.get("/app/<path:subpath>")
    def vue_app(subpath: str = ""):
        from flask import abort, send_from_directory

        if not (vue_dist / "index.html").exists():
            abort(404, "前端尚未构建：在 frontend 目录执行 node build.mjs")
        if not subpath or subpath == "index.html":
            return send_from_directory(vue_dist, "index.html")
        if not (vue_dist / subpath).is_file():
            # 单页应用：未知路径回落到 index.html
            return send_from_directory(vue_dist, "index.html")
        return send_from_directory(vue_dist, subpath)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "project": "WorldBranch"})

    @app.errorhandler(LookupError)
    def handle_lookup(err):
        return jsonify({"error": str(err)}), 404

    @app.errorhandler(ValueError)
    def handle_value(err):
        return jsonify({"error": str(err)}), 400

    from .ai import LLMError, ProviderNotConfigured
    from .engine.decisions import DecisionError

    @app.errorhandler(DecisionError)
    def handle_decision_error(err):
        return jsonify({"error": str(err)}), 400

    @app.errorhandler(ProviderNotConfigured)
    def handle_no_provider(err):
        return jsonify({"error": str(err)}), 400

    @app.errorhandler(LLMError)
    def handle_llm_error(err):
        # 错误信息里绝不会出现 API Key
        return jsonify({"error": str(err)}), 502

    from .cli import register_cli

    register_cli(app)

    return app