"""Render entry point for the Oliv Telegram bot.

Runs a tiny HTTP health endpoint in a daemon thread because Render Free
supports Web Services (not free Background Workers). The Telegram bot
continues to use long polling in the main process.
"""
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Fail closed: this bot handles private financial information.
_REQUIRED_ENV = (
    "TELEGRAM_TOKEN",
    "GEMINI_API_KEY",
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "ALLOWED_TELEGRAM_IDS",
)
_missing = [name for name in _REQUIRED_ENV if not os.environ.get(name, "").strip()]
if _missing:
    raise RuntimeError(
        "Missing required Render environment variable(s): "
        + ", ".join(_missing)
    )

_allowed_ids = [
    item.strip()
    for item in os.environ["ALLOWED_TELEGRAM_IDS"].split(",")
    if item.strip()
]
if not _allowed_ids or any(not item.isdigit() for item in _allowed_ids):
    raise RuntimeError(
        "ALLOWED_TELEGRAM_IDS must contain one or more numeric Telegram user IDs, "
        "separated by commas."
    )


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/health"):
            self.send_error(404)
            return

        body = json.dumps({"status": "ok", "service": "oliv-telegram-bot"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        # Keep health-check requests out of the deployment logs.
        return


def main():
    port = int(os.environ.get("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    server_thread = threading.Thread(
        target=server.serve_forever,
        name="render-health-server",
        daemon=True,
    )
    server_thread.start()
    logging.getLogger(__name__).info("Health endpoint listening on port %s", port)

    # main.py adds the bot/ folder to sys.path and imports the existing bot.
    from main import main as run_telegram_bot

    run_telegram_bot()


if __name__ == "__main__":
    main()
