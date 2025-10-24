"""
Утилиты для работы с прокси
Парсинг строк прокси в формат Playwright
"""

from typing import Dict, Optional, Union

ProxyConfig = Dict[str, str]
ProxyInput = Union[str, Dict[str, str], None]

__all__ = [
    "proxy_to_playwright",
    "parse_proxy",
    "parse_proxy_for_playwright",
]


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


def parse_proxy(proxy_str: Optional[str]) -> Optional[ProxyConfig]:
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

    result: ProxyConfig = {"server": f"{scheme}://{host}:{port}"}
    if username:
        result["username"] = username
    if password:
        result["password"] = password
    return result


def proxy_to_playwright(proxy: ProxyInput) -> Optional[ProxyConfig]:
    """
    Приводит строку/словарь прокси к формату Playwright.

    Args:
        proxy: строка прокси или уже подготовленный словарь

    Returns:
        dict или None, если прокси не задан
    """
    if not proxy:
        return None

    if isinstance(proxy, dict):
        # Возвращаем копию только с непустыми значениями
        return {k: v for k, v in proxy.items() if isinstance(v, str) and v.strip()}  # type: ignore[return-value]

    normalized = str(proxy).strip()
    if not normalized:
        return None

    return parse_proxy(normalized)


def parse_proxy_for_playwright(proxy_string: str) -> ProxyConfig:
    """
    Парсинг прокси в формат Playwright.

    Поддерживаемые форматы:
    - "http://77.73.134.166:8080"
    - "socks5://user:pass@77.73.134.166:1080"
    - "77.73.134.166:8080" (без протокола → считать HTTP)

    Args:
        proxy_string: Строка прокси
        
    Returns:
        dict: {'server': str, 'username': str, 'password': str}
        None: Если proxy_string пустой
        
    Raises:
        ValueError: Если формат прокси неверный
        
    Example:
        >>> parse_proxy_for_playwright("http://77.73.134.166:8080")
        {'server': 'http://77.73.134.166:8080'}
        
        >>> parse_proxy_for_playwright("socks5://user:pass@host:1080")
        {'server': 'socks5://host:1080', 'username': 'user', 'password': 'pass'}
    """
    result = proxy_to_playwright(proxy_string)
    if result is None:
        raise ValueError(f"Неверный формат прокси: {proxy_string}")
    return result
