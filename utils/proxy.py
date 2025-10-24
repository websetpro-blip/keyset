"""
Утилиты для работы с прокси
Парсинг строк прокси в формат Playwright
"""

from typing import Optional, Dict


def _looks_like_host_port(part: str) -> bool:
    if not part or ":" not in part:
        return False
    host, port = part.split(":", 1)
    host = host.strip()
    port = port.strip()
    if not host or not port:
        return False
    if port.isdigit():
        return True
    return False


def parse_proxy(proxy_str: Optional[str]) -> Optional[Dict[str, str]]:
    """
    Парсит строку прокси в формат Playwright API
    
    Поддерживаемые форматы:
    - ip:port
    - user:pass@ip:port
    - http://user:pass@ip:port
    - https://user:pass@ip:port
    - socks5://user:pass@ip:port
    
    Returns:
        {
            "server": "http://ip:port",
            "username": "user" (optional),
            "password": "pass" (optional)
        }
    """
    if not proxy_str:
        return None
    
    proxy_str = proxy_str.strip()
    if not proxy_str:
        return None
    
    # Добавляем схему если нет
    if "://" not in proxy_str:
        proxy_str = "http://" + proxy_str
    
    # Разбираем схему и основную часть
    scheme = "http"
    rest = proxy_str
    if "://" in rest:
        scheme_part, rest = rest.split("://", 1)
        scheme = scheme_part or "http"
    scheme = scheme.lower()
    rest = rest.strip()

    username = None
    password = None
    host_port_part = rest

    if "@" in rest:
        left, right = rest.split("@", 1)
        left = left.strip()
        right = right.strip()

        if _looks_like_host_port(left) and not _looks_like_host_port(right):
            # Формат host:port@user:pass
            host_port_part = left
            if ":" in right:
                username, password = right.split(":", 1)
            else:
                username = right or None
        elif _looks_like_host_port(right):
            # Формат user:pass@host:port
            host_port_part = right
            if ":" in left:
                username, password = left.split(":", 1)
            else:
                username = left or None
        else:
            # По умолчанию считаем что правая часть - host:port
            host_port_part = right
            if ":" in left:
                username, password = left.split(":", 1)
            else:
                username = left or None

    if not _looks_like_host_port(host_port_part):
        return None

    host, port = host_port_part.split(":", 1)
    host = host.strip()
    port = port.strip()
    if not host or not port:
        return None

    username = username.strip() if isinstance(username, str) else None
    password = password.strip() if isinstance(password, str) else None

    result: Dict[str, str] = {"server": f"{scheme}://{host}:{port}"}
    if username:
        result["username"] = username
    if password:
        result["password"] = password
    return result
