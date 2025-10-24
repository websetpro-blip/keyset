from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import quote

LOGGER = logging.getLogger(__name__)


def _allocate_port() -> int:
    """Return an ephemeral TCP port bound on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ProxyBridge:
    """
    Manage lightweight mitmdump processes that expose a local authenticated proxy.
    Chrome talks to 127.0.0.1 while mitmdump forwards traffic to the upstream proxy.
    """

    _processes: Dict[str, subprocess.Popen] = {}
    _ports: Dict[str, int] = {}
    _mitmdump_path: Optional[Path] = None

    @classmethod
    def _resolve_mitmdump(cls) -> Path:
        """Locate mitmdump executable, checking PATH and common virtualenv folders."""
        if cls._mitmdump_path and cls._mitmdump_path.exists():
            return cls._mitmdump_path

        candidates = []
        which_path = shutil.which("mitmdump")
        if which_path:
            candidates.append(Path(which_path))

        project_root = Path(__file__).resolve().parents[3]
        venv_dirs = [project_root / ".venv", project_root / "venv"]
        for venv_dir in venv_dirs:
            scripts_dir = venv_dir / "Scripts"
            candidates.append(scripts_dir / "mitmdump.exe")
            candidates.append(scripts_dir / "mitmdump")
            bin_dir = venv_dir / "bin"
            candidates.append(bin_dir / "mitmdump")

        for candidate in candidates:
            if candidate and candidate.exists():
                cls._mitmdump_path = candidate.resolve()
                LOGGER.debug("Resolved mitmdump executable at %s", cls._mitmdump_path)
                return cls._mitmdump_path

        raise RuntimeError(
            "mitmdump executable not found. Install mitmproxy (`pip install mitmproxy`) "
            "or ensure it is available in the active virtualenv."
        )

    @classmethod
    def start(
        cls,
        key: str,
        *,
        upstream_scheme: str,
        upstream_host: str,
        upstream_port: int,
        username: str,
        password: str,
    ) -> int:
        """Start (or reuse) a bridge dedicated to the given key and return its port."""
        existing = cls._processes.get(key)
        if existing is not None:
            if existing.poll() is None:
                return cls._ports[key]
            LOGGER.warning(
                "Proxy bridge for %s exited with code %s; restarting",
                key,
                existing.returncode,
            )
            cls.stop(key)

        mitmdump_path = cls._resolve_mitmdump()
        local_port = _allocate_port()

        upstream_url = f"{upstream_scheme}://{upstream_host}:{upstream_port}"

        args = [
            str(mitmdump_path),
            "--listen-host",
            "127.0.0.1",
            "--listen-port",
            str(local_port),
            "--mode",
            f"upstream:{upstream_url}",
            "--set",
            "upstream_cert=false",
            "--set",
            "connection_strategy=lazy",
            "--quiet",
        ]

        if username:
            quoted_user = quote(username, safe="")
            quoted_pass = quote(password or "", safe="")
            args.extend(
                [
                    "--set",
                    f"upstream_auth={quoted_user}:{quoted_pass}",
                ]
            )

        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        LOGGER.info("Starting mitmdump bridge for %s on 127.0.0.1:%s", key, local_port)
        LOGGER.debug("mitmdump command: %s", " ".join(args))
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

        try:
            cls._wait_until_ready(proc, local_port)
        except Exception:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
            raise

        cls._processes[key] = proc
        cls._ports[key] = local_port
        return local_port

    @classmethod
    def _wait_until_ready(cls, proc: subprocess.Popen, port: int) -> None:
        """Poll mitmdump process until the local port starts accepting connections."""
        deadline = time.time() + 5.0
        last_error: Optional[str] = None

        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(
                    f"mitmdump exited during startup (code {proc.returncode})."
                )
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    return
            except OSError as exc:
                last_error = str(exc)
                time.sleep(0.1)

        raise RuntimeError(
            f"mitmdump did not open 127.0.0.1:{port} in time (last error: {last_error})."
        )

    @classmethod
    def stop(cls, key: str) -> None:
        proc = cls._processes.pop(key, None)
        cls._ports.pop(key, None)
        if proc is None:
            return
        LOGGER.info("Stopping mitmdump bridge for %s", key)
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    @classmethod
    def stop_all(cls) -> None:
        for key in list(cls._processes.keys()):
            cls.stop(key)

    @classmethod
    def get_local_port(cls, key: str) -> Optional[int]:
        return cls._ports.get(key)


__all__ = ["ProxyBridge"]
