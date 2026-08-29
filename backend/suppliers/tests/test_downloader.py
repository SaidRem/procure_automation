"""Тесты загрузки прайса по ссылке (ADR-018)."""

from __future__ import annotations

import socket

import pytest
import requests

from suppliers.importers import downloader
from suppliers.importers.exceptions import (
    InsecurePriceSource,
    PriceFileTooLarge,
    PriceSourceUnavailable,
)

URL = "https://supplier.example/price.yaml"
CONTENT = b"shop: \xd0\xa1\xd0\xb2\xd1\x8f\xd0\xb7\xd0\xbd\xd0\xbe\xd0\xb9\n"


class FakeResponse:
    """Минимальный ответ requests с потоковым телом."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        body: bytes = CONTENT,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def iter_content(self, chunk_size: int):
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start : start + chunk_size]


@pytest.fixture(autouse=True)
def public_dns(monkeypatch) -> None:
    """Считать, что имя разрешается в публичный адрес."""
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )


def respond_with(monkeypatch, response: object) -> list[dict]:
    """Подменить requests.get, вернув журнал вызовов."""
    calls: list[dict] = []

    def fake_get(url: str, **kwargs: object):
        calls.append({"url": url, **kwargs})
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(requests, "get", fake_get)
    return calls


class TestSuccessfulDownload:
    """Успешная загрузка."""

    def test_returns_decoded_content(self, monkeypatch) -> None:
        respond_with(monkeypatch, FakeResponse())

        assert downloader.fetch_price_file(URL) == CONTENT.decode("utf-8")

    def test_request_is_streamed_with_timeouts_and_without_redirects(
        self, monkeypatch
    ) -> None:
        calls = respond_with(monkeypatch, FakeResponse())

        downloader.fetch_price_file(URL)

        assert calls[0]["stream"] is True
        assert calls[0]["allow_redirects"] is False
        assert calls[0]["timeout"] == (
            downloader.CONNECT_TIMEOUT,
            downloader.READ_TIMEOUT,
        )

    def test_content_length_within_limit_is_accepted(self, monkeypatch) -> None:
        respond_with(
            monkeypatch,
            FakeResponse(headers={"Content-Length": str(len(CONTENT))}),
        )

        assert downloader.fetch_price_file(URL)


class TestUrlRules:
    """Схема ссылки и адрес назначения."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://supplier.example/price.yaml",
            "ftp://supplier.example/price.yaml",
            "file:///etc/passwd",
            "supplier.example/price.yaml",
        ],
    )
    def test_non_https_scheme_is_rejected(self, url: str, monkeypatch) -> None:
        calls = respond_with(monkeypatch, FakeResponse())

        with pytest.raises(InsecurePriceSource):
            downloader.fetch_price_file(url)

        assert calls == []

    def test_url_without_host_is_rejected(self) -> None:
        with pytest.raises(InsecurePriceSource):
            downloader.fetch_price_file("https:///price.yaml")

    def test_credentials_in_url_are_rejected(self) -> None:
        with pytest.raises(InsecurePriceSource):
            downloader.fetch_price_file("https://user:pass@supplier.example/price.yaml")

    @pytest.mark.parametrize(
        "address", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1"]
    )
    def test_internal_address_is_rejected(self, address: str, monkeypatch) -> None:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *args, **kwargs: [(family, socket.SOCK_STREAM, 6, "", (address, 443))],
        )
        calls = respond_with(monkeypatch, FakeResponse())

        with pytest.raises(InsecurePriceSource):
            downloader.fetch_price_file(URL)

        assert calls == []

    def test_unresolvable_host_is_retryable(self, monkeypatch) -> None:
        def fail(*args: object, **kwargs: object):
            raise socket.gaierror("nodename nor servname provided")

        monkeypatch.setattr(socket, "getaddrinfo", fail)

        with pytest.raises(PriceSourceUnavailable) as error:
            downloader.fetch_price_file(URL)

        assert error.value.retryable is True


class TestUnavailableSource:
    """Недоступный источник."""

    def test_timeout(self, monkeypatch) -> None:
        respond_with(monkeypatch, requests.Timeout("read timeout"))

        with pytest.raises(PriceSourceUnavailable) as error:
            downloader.fetch_price_file(URL)

        assert error.value.retryable is True

    def test_connection_error(self, monkeypatch) -> None:
        respond_with(monkeypatch, requests.ConnectionError("connection refused"))

        with pytest.raises(PriceSourceUnavailable):
            downloader.fetch_price_file(URL)

    def test_server_error_is_retryable(self, monkeypatch) -> None:
        respond_with(monkeypatch, FakeResponse(status_code=503))

        with pytest.raises(PriceSourceUnavailable) as error:
            downloader.fetch_price_file(URL)

        assert error.value.retryable is True

    def test_too_many_requests_is_retryable(self, monkeypatch) -> None:
        respond_with(monkeypatch, FakeResponse(status_code=429))

        with pytest.raises(PriceSourceUnavailable):
            downloader.fetch_price_file(URL)

    def test_client_error_is_terminal(self, monkeypatch) -> None:
        respond_with(monkeypatch, FakeResponse(status_code=404))

        with pytest.raises(InsecurePriceSource) as error:
            downloader.fetch_price_file(URL)

        assert error.value.retryable is False

    def test_redirect_is_not_followed(self, monkeypatch) -> None:
        respond_with(
            monkeypatch,
            FakeResponse(status_code=302, headers={"Location": "http://127.0.0.1/"}),
        )

        with pytest.raises(InsecurePriceSource):
            downloader.fetch_price_file(URL)


class TestSizeLimit:
    """Ограничение размера файла."""

    def test_declared_size_over_limit_is_rejected(self, monkeypatch) -> None:
        respond_with(
            monkeypatch,
            FakeResponse(headers={"Content-Length": str(downloader.MAX_FILE_BYTES + 1)}),
        )

        with pytest.raises(PriceFileTooLarge) as error:
            downloader.fetch_price_file(URL)

        assert error.value.retryable is False

    def test_streamed_body_over_limit_is_rejected(self, monkeypatch) -> None:
        monkeypatch.setattr(downloader, "MAX_FILE_BYTES", 100)
        monkeypatch.setattr(downloader, "CHUNK_BYTES", 10)
        respond_with(monkeypatch, FakeResponse(body=b"x" * 500))

        with pytest.raises(PriceFileTooLarge):
            downloader.fetch_price_file(URL)

    def test_lying_content_length_does_not_help(self, monkeypatch) -> None:
        monkeypatch.setattr(downloader, "MAX_FILE_BYTES", 100)
        respond_with(
            monkeypatch,
            FakeResponse(body=b"x" * 500, headers={"Content-Length": "10"}),
        )

        with pytest.raises(PriceFileTooLarge):
            downloader.fetch_price_file(URL)

    def test_non_utf8_body_is_rejected(self, monkeypatch) -> None:
        respond_with(monkeypatch, FakeResponse(body=b"\xff\xfe\x00"))

        with pytest.raises(InsecurePriceSource):
            downloader.fetch_price_file(URL)
