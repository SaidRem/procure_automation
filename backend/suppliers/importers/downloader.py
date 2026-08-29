"""Загрузка прайса поставщика по ссылке (ADR-018).

Ссылку задаёт внешний пользователь-поставщик, поэтому запрос считается
недоверенным: разрешена только схема https, адрес назначения проверяется
до обращения, редиректы не выполняются, объём ответа ограничен, а сам
запрос — таймаутами.

Слой отвечает только за транспорт: разбор содержимого выполняет
`suppliers.importers.yaml_parser`, запись в каталог — `catalog.services`
(ADR-016).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlsplit

import requests

from suppliers.importers.exceptions import (
    InsecurePriceSource,
    PriceFileTooLarge,
    PriceSourceUnavailable,
)

logger = logging.getLogger(__name__)

ALLOWED_SCHEME = "https"
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 30.0
MAX_FILE_BYTES = 10 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
RETRYABLE_STATUSES = frozenset({429})


def fetch_price_file(url: str) -> str:
    """Загрузить файл прайса и вернуть его содержимое.

    Возбуждает `InsecurePriceSource` для недопустимой ссылки,
    `PriceFileTooLarge` при превышении лимита и `PriceSourceUnavailable`
    при сетевом сбое или временной ошибке сервера.
    """
    host = _check_url(url)
    _check_destination(host)

    logger.info("Price download started: url=%s", url)

    try:
        with requests.get(
            url,
            stream=True,
            allow_redirects=False,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        ) as response:
            _check_response(url, response)
            content = _read_limited(response)
    except requests.Timeout as error:
        raise PriceSourceUnavailable(f"Таймаут при загрузке {url}.") from error
    except requests.RequestException as error:
        raise PriceSourceUnavailable(f"Не удалось загрузить {url}: {error}.") from error

    logger.info("Price download finished: url=%s bytes=%s", url, len(content))
    return content


def _check_url(url: str) -> str:
    """Проверить схему ссылки и вернуть имя хоста."""
    parts = urlsplit(url)

    if parts.scheme != ALLOWED_SCHEME:
        raise InsecurePriceSource(
            f"Прайс загружается только по {ALLOWED_SCHEME}, получено: {parts.scheme or 'без схемы'}."
        )

    if not parts.hostname:
        raise InsecurePriceSource("В ссылке не указан хост.")

    if parts.username or parts.password:
        raise InsecurePriceSource("Ссылка не должна содержать учётные данные.")

    return parts.hostname


def _check_destination(host: str) -> None:
    """Не позволить обратиться к внутреннему адресу (SSRF, ADR-018)."""
    try:
        addresses = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as error:
        raise PriceSourceUnavailable(f"Не удалось разрешить имя {host}.") from error

    for info in addresses:
        address = ipaddress.ip_address(info[4][0])

        if not address.is_global or address.is_multicast:
            raise InsecurePriceSource(
                f"Адрес {address} хоста {host} недоступен для загрузки прайса."
            )


def _check_response(url: str, response: requests.Response) -> None:
    """Проверить код ответа и заявленный размер файла."""
    status = response.status_code

    if status >= 500 or status in RETRYABLE_STATUSES:
        raise PriceSourceUnavailable(f"Источник {url} вернул {status}.")

    if not 200 <= status < 300:
        raise InsecurePriceSource(f"Источник {url} вернул {status}.")

    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > MAX_FILE_BYTES:
        raise PriceFileTooLarge(
            f"Размер прайса {declared} байт превышает лимит {MAX_FILE_BYTES}."
        )


def _read_limited(response: requests.Response) -> str:
    """Прочитать тело ответа, прервав чтение при превышении лимита."""
    chunks: list[bytes] = []
    size = 0

    for chunk in response.iter_content(chunk_size=CHUNK_BYTES):
        size += len(chunk)

        if size > MAX_FILE_BYTES:
            raise PriceFileTooLarge(
                f"Размер прайса превышает лимит {MAX_FILE_BYTES} байт."
            )

        chunks.append(chunk)

    try:
        return b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as error:
        raise InsecurePriceSource("Файл прайса не является текстом в UTF-8.") from error
