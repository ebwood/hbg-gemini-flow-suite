from __future__ import annotations

import argparse
import socket
import socketserver
import threading


ALLOWED_CLIENTS = {"127.0.0.1", "::1"}


def rewrite_host_header(payload: bytes, target_port: int) -> bytes:
    lines = payload.split(b"\r\n")
    replacement = f"Host: 127.0.0.1:{target_port}".encode()
    for index, line in enumerate(lines):
        if line.lower().startswith(b"host:"):
            lines[index] = replacement
            break
    return b"\r\n".join(lines)


class CdpBridgeHandler(socketserver.BaseRequestHandler):
    target_port = 0

    def handle(self) -> None:
        if self.client_address[0] not in ALLOWED_CLIENTS:
            return

        upstream = socket.create_connection(("127.0.0.1", self.target_port), timeout=10)
        try:
            initial = bytearray()
            while b"\r\n\r\n" not in initial:
                chunk = self.request.recv(65536)
                if not chunk:
                    return
                initial.extend(chunk)
                if len(initial) > 1024 * 1024:
                    raise RuntimeError("CDP request headers exceeded 1 MiB")
            upstream.sendall(rewrite_host_header(bytes(initial), self.target_port))

            def pump(source: socket.socket, destination: socket.socket) -> None:
                try:
                    while True:
                        data = source.recv(65536)
                        if not data:
                            break
                        destination.sendall(data)
                except OSError:
                    pass
                try:
                    destination.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

            outgoing = threading.Thread(
                target=pump, args=(self.request, upstream), daemon=True
            )
            incoming = threading.Thread(
                target=pump, args=(upstream, self.request), daemon=True
            )
            outgoing.start()
            incoming.start()
            outgoing.join()
            incoming.join()
        finally:
            upstream.close()


class ThreadingCdpBridge(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Temporarily bridge Docker Desktop to a localhost-only Chrome CDP port."
    )
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--target-port", type=int, required=True)
    args = parser.parse_args()

    handler = type(
        "ConfiguredCdpBridgeHandler",
        (CdpBridgeHandler,),
        {"target_port": args.target_port},
    )
    with ThreadingCdpBridge(("0.0.0.0", args.listen_port), handler) as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
