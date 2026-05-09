import os

from waitress import serve

from app import app
from neeco_updates import apply as apply_neeco_updates


apply_neeco_updates(app)


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5000"))
    threads = int(os.getenv("WAITRESS_THREADS", "8"))
    serve(app, host=host, port=port, threads=threads)
