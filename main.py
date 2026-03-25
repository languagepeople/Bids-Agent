"""
Bids Agent — Flask application entry point.

Run:
    python main.py

Then open http://localhost:5000 in your browser.
"""

import os
from flask import Flask, render_template, send_from_directory
from app.database import init_db
from app.routes import api


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "bids-agent-dev-key")

    # Initialize SQLite database
    init_db()

    # Register API blueprint
    app.register_blueprint(api)

    # Serve the SPA shell
    @app.route("/")
    def index():
        return render_template("index.html")

    # Allow download of exported files stored in data/
    @app.route("/data/<path:filename>")
    def serve_data(filename):
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        return send_from_directory(data_dir, filename, as_attachment=True)

    return app


if __name__ == "__main__":
    application = create_app()
    port = int(os.environ.get("PORT", 5000))
    print(f"\n🔎  Bids Agent running → http://localhost:{port}\n")
    application.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, debug=False)
