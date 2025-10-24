from __future__ import annotations

import asyncio
import base64
import threading
from contextlib import suppress
from typing import Optional


class LocalAuthProxy:
    """
    Простейший локальный HTTP-прокси, который пробрасывает запросы
    через удалённый прокси с авторизацией (Basic).

    Chrome подключается к localhost, а этот прокси добавляет заголовок
    Proxy-Authorization и взаимодействует с удалённым прокси.
    """

    def __init__(
        self,
        remote_host: str,
        remote_port: int,
        username: str,
        password: str,
    ) -> None:
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.username = username or ""
        self.password = password or ""

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._server: Optional[asyncio.AbstractServer] = None
        self._started = threading.Event()
        self.port: Optional[int] = None

        userpass = f"{self.username}:{self.password}".encode("utf-8")
        self._auth_header = base64.b64encode(userpass).decode("ascii")

    def start(self) -> int:
        """Запустить сервер и вернуть локальный порт."""
        if self._thread is not None:
            raise RuntimeError("Proxy already started")

        def runner() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            server = loop.run_until_complete(
                asyncio.start_server(self._handle_client, "127.0.0.1", 0)
            )
            self._server = server
            self.port = server.sockets[0].getsockname()[1]
            self._started.set()
            try:
                loop.run_forever()
            finally:
                server.close()
                loop.run_until_complete(server.wait_closed())
                loop.close()

        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()
        self._started.wait()
        if self.port is None:
            raise RuntimeError("Failed to start local proxy")
        return self.port

    def stop(self) -> None:
        if self._loop is None:
            return

        def stopper() -> None:
            if self._server:
                self._server.close()
            for task in asyncio.all_tasks(loop=self._loop):
                task.cancel()
            self._loop.stop()

        self._loop.call_soon_threadsafe(stopper)
        if self._thread:
            self._thread.join(timeout=5)

        self._loop = None
        self._thread = None
        self._server = None
        self.port = None

    async def _handle_client(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        try:
            header_data = await client_reader.readuntil(b"\r\n\r\n")
        except Exception:
            client_writer.close()
            return

        header_text = header_data.decode("latin1")
        request_line, *header_lines = header_text.split("\r\n")
        if not request_line:
            client_writer.close()
            return

        parts = request_line.split(" ")
        if len(parts) < 2:
            client_writer.close()
            return
        method = parts[0].upper()
        target = parts[1]

        try:
            remote_reader, remote_writer = await asyncio.open_connection(
                self.remote_host, self.remote_port
            )
        except Exception:
            client_writer.close()
            return

        if method == "CONNECT":
            request = (
                f"CONNECT {target} HTTP/1.1\r\n"
                f"Host: {target}\r\n"
                f"Proxy-Authorization: Basic {self._auth_header}\r\n"
                f"Proxy-Connection: Keep-Alive\r\n"
                "\r\n"
            )
            remote_writer.write(request.encode("latin1"))
            await remote_writer.drain()
            try:
                response = await remote_reader.readuntil(b"\r\n\r\n")
            except Exception:
                client_writer.close()
                remote_writer.close()
                return

            client_writer.write(response)
            await client_writer.drain()

            if not response.startswith(b"HTTP/1.1 200"):
                remote_writer.close()
                client_writer.close()
                return

            await asyncio.gather(
                self._pipe(client_reader, remote_writer),
                self._pipe(remote_reader, client_writer),
            )
            with suppress(Exception):
                remote_writer.close()
            with suppress(Exception):
                client_writer.close()
        else:
            filtered_headers = [
                line
                for line in header_lines
                if line and not line.lower().startswith("proxy-authorization:")
            ]
            filtered_headers.insert(
                0, f"Proxy-Authorization: Basic {self._auth_header}"
            )
            new_header = "\r\n".join([request_line, *filtered_headers, ""]).encode(
                "latin1"
            )
            remote_writer.write(new_header + b"\r\n")
            await remote_writer.drain()

        await asyncio.gather(
            self._pipe(client_reader, remote_writer),
            self._pipe(remote_reader, client_writer),
        )
        with suppress(Exception):
            remote_writer.close()
        with suppress(Exception):
            client_writer.close()

    async def _pipe(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()
        except Exception:
            pass


__all__ = ["LocalAuthProxy"]
