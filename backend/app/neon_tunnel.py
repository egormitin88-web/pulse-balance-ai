"""Local-only, TLS WebSocket transport when a network blocks PostgreSQL port 5432.

The database protocol and psycopg stay unchanged. Only the loopback hop is plain
TCP; traffic leaving this computer uses certificate-verified WSS to Neon.
Vercel uses the ordinary PostgreSQL connection and never starts this tunnel.
"""

from __future__ import annotations

import atexit
import logging
import socket
import socketserver
import threading

from sqlalchemy.engine import URL


logger = logging.getLogger(__name__)


def tcp_available(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def websocket_database_url(url: URL) -> URL:
    from websockets.sync.client import connect

    # Never send database traffic to an arbitrary WebSocket endpoint.
    if not url.host or not url.host.endswith(".neon.tech"):
        raise ValueError("The local WebSocket transport supports Neon hosts only")
    endpoint = "wss://" + url.host + "/v2"

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                with connect(endpoint, open_timeout=10, close_timeout=2, max_size=None) as ws:
                    def upload():
                        try:
                            while data := self.request.recv(65536):
                                ws.send(data)
                        except (OSError, RuntimeError):
                            pass
                        finally:
                            ws.close()

                    threading.Thread(target=upload, daemon=True).start()
                    for message in ws:
                        self.request.sendall(message if isinstance(message, bytes) else message.encode())
            except Exception as exc:
                # Connection failures may contain server details; never log the URL or credentials.
                logger.warning("Local Neon transport disconnected (%s)", type(exc).__name__)

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True

    tunnel = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=tunnel.serve_forever, daemon=True).start()

    def close():
        tunnel.shutdown()
        tunnel.server_close()

    atexit.register(close)
    logger.warning("Local Neon connection uses encrypted WebSocket transport (TCP port blocked)")
    return url.update_query_dict({
        "hostaddr": "127.0.0.1",
        "port": str(tunnel.server_address[1]),
        # The local hop is loopback only; the external hop is protected by WSS/TLS.
        "sslmode": "disable",
        "channel_binding": "disable",
    })
