"""HTTP API。"""

from __future__ import annotations

from flask import Blueprint, Flask

from . import ai, branches, worlds

BLUEPRINTS: tuple[Blueprint, ...] = (worlds.bp, branches.bp, ai.bp)


def register_blueprints(app: Flask) -> None:
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)


__all__ = ["register_blueprints", "BLUEPRINTS"]