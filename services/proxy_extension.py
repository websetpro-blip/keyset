from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Dict, Optional


EXTENSIONS_ROOT = Path(__file__).resolve().parents[2] / "runtime" / "proxy_extensions"


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def build_proxy_extension(account: str, proxy: Dict[str, str], disable_webrtc: bool = True) -> Path:
    """
    Создаёт MV3-расширение для авторизации на прокси и (опционально)
    отключает WebRTC утечки. Возвращает путь к каталогу расширения.
    """
    if not proxy or not proxy.get("server"):
        raise ValueError("Proxy configuration is empty")

    EXTENSIONS_ROOT.mkdir(parents=True, exist_ok=True)
    ext_dir = EXTENSIONS_ROOT / f"{account}_{int(time.time() * 1000)}"
    if ext_dir.exists():
        shutil.rmtree(ext_dir, ignore_errors=True)
    ext_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "manifest_version": 3,
        "name": f"KeySet Proxy Auth ({account})",
        "version": "1.0",
        "permissions": [
            "proxy",
            "storage",
            "declarativeNetRequest",
            "webRequest",
            "webRequestAuthProvider",
            "webRequestBlocking",
            "privacy",
        ],
        "host_permissions": ["<all_urls>"],
        "background": {"service_worker": "background.js"},
        "minimum_chrome_version": "109",
    }
    _write_text(ext_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    username = proxy.get("username", "")
    password = proxy.get("password", "")
    privacy_snippet = (
        "chrome.privacy.network.webRTCIPHandlingPolicy.set({value: 'disable_non_proxied_udp'});\n"
        "chrome.privacy.network.webRTCMultipleRoutesEnabled.set({value: false});\n"
        "chrome.privacy.network.webRTCNonProxiedUdpEnabled.set({value: false});"
        if disable_webrtc
        else ""
    )

    server = (proxy.get("server") or "").strip()
    scheme = "http"
    host = ""
    port = "80"
    if "://" in server:
        scheme, rest = server.split("://", 1)
    else:
        rest = server
    if ":" in rest:
        host, port = rest.rsplit(":", 1)
    else:
        host = rest
    try:
        port_int = int(port)
    except ValueError:
        port_int = 0
    host_json = json.dumps(host)
    scheme_json = json.dumps(scheme)

    background = f"""
const CREDS = {{
  username: {json.dumps(username)},
  password: {json.dumps(password)}
}};

const PROXY_CONFIG = {{
  mode: "fixed_servers",
  rules: {{
    singleProxy: {{
      scheme: {scheme_json},
      host: {host_json},
      port: {port_int}
    }}
  }}
}};

function applyPrivacy() {{
  {privacy_snippet}
}}

function applyProxy() {{
  chrome.proxy.settings.set({{ value: PROXY_CONFIG, scope: "regular" }});
}}

chrome.runtime.onInstalled.addListener(applyPrivacy);
chrome.runtime.onStartup.addListener(applyPrivacy);

chrome.runtime.onInstalled.addListener(applyProxy);
chrome.runtime.onStartup.addListener(applyProxy);

chrome.webRequest.onAuthRequired.addListener(
  () => {{
    return {{ authCredentials: CREDS }};
  }},
  {{ urls: ["<all_urls>"] }},
  ["blocking"]
);
""".strip()

    _write_text(ext_dir / "background.js", background + "\n")
    return ext_dir


def cleanup_extensions(older_than: Optional[float] = None) -> None:
    """Удаляет временные расширения (опционально старше указанного таймштампа)."""
    if not EXTENSIONS_ROOT.exists():
        return
    for entry in EXTENSIONS_ROOT.iterdir():
        try:
            if not older_than or entry.stat().st_mtime < older_than:
                shutil.rmtree(entry, ignore_errors=True)
        except Exception:
            continue


