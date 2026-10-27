"""开发入口。

    python run.py

或使用 Flask CLI：

    flask --app run.py init-db
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5210"))
    app.run(host="127.0.0.1", port=port, debug=app.config["WORLDBRANCH"].DEBUG)