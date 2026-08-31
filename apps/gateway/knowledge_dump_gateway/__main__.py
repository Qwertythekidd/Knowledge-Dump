from __future__ import annotations

import os

from .server import create_server


def main() -> None:
    host = os.environ.get("KNOWLEDGE_DUMP_GATEWAY_HOST", "127.0.0.1")
    port = int(os.environ.get("KNOWLEDGE_DUMP_GATEWAY_PORT", "8787"))
    server = create_server(host=host, port=port)
    print(f"Knowledge Dump mock gateway listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
