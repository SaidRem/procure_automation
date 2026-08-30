"""Тесты поля ссылки со схемой https по умолчанию (ADR-018)."""

from __future__ import annotations

import warnings

import pytest
from django.utils.deprecation import RemovedInDjango60Warning

from suppliers.models import HttpsURLField, ImportLog, Shop

URL_FIELDS = [
    pytest.param(Shop, "url", id="shop-url"),
    pytest.param(ImportLog, "source_url", id="importlog-source-url"),
]


def form_field_of(model: type, field_name: str):
    """Построить поле формы для указанного поля модели."""
    return model._meta.get_field(field_name).formfield()


class TestPolicyIsAppliedToEveryUrl:
    """Все ссылки проекта — источники прайса и подчиняются ADR-018."""

    @pytest.mark.parametrize(("model", "field_name"), [(Shop, "url"), (ImportLog, "source_url")])
    def test_field_uses_the_https_type(self, model: type, field_name: str) -> None:
        assert isinstance(model._meta.get_field(field_name), HttpsURLField)

    def test_no_plain_url_field_is_left(self) -> None:
        # Страховка от новой ссылки, заведённой мимо политики.
        from django.db.models import URLField

        plain = [
            f"{model.__name__}.{field.name}"
            for model in (Shop, ImportLog)
            for field in model._meta.get_fields()
            if isinstance(field, URLField) and not isinstance(field, HttpsURLField)
        ]

        assert plain == []


class TestAssumedScheme:
    """Схема по умолчанию — https, а не http."""

    @pytest.mark.parametrize(("model", "field_name"), [(Shop, "url"), (ImportLog, "source_url")])
    def test_form_field_assumes_https(self, model: type, field_name: str) -> None:
        assert form_field_of(model, field_name).assume_scheme == "https"

    def test_missing_scheme_becomes_https(self) -> None:
        field = form_field_of(Shop, "url")

        assert field.clean("supplier.example/price.yaml") == (
            "https://supplier.example/price.yaml"
        )

    def test_explicit_https_is_kept(self) -> None:
        field = form_field_of(Shop, "url")

        assert field.clean("https://supplier.example/price.yaml") == (
            "https://supplier.example/price.yaml"
        )

    def test_explicit_http_is_not_rewritten(self) -> None:
        # Подстановка схемы не «чинит» явный http: такой адрес обязан
        # дойти до загрузчика и быть отклонённым им (ADR-018).
        field = form_field_of(Shop, "url")

        assert field.clean("http://supplier.example/price.yaml") == (
            "http://supplier.example/price.yaml"
        )


class TestNoDeprecationWarning:
    """Построение формы не поднимает предупреждение Django 6.0."""

    @pytest.mark.parametrize(("model", "field_name"), [(Shop, "url"), (ImportLog, "source_url")])
    def test_form_field_is_built_silently(self, model: type, field_name: str) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            form_field_of(model, field_name)

        assert [w for w in caught if issubclass(w.category, RemovedInDjango60Warning)] == []


class TestMigrationsAreUnaffected:
    """Поле сериализуется как обычный URLField."""

    @pytest.mark.parametrize(("model", "field_name"), [(Shop, "url"), (ImportLog, "source_url")])
    def test_deconstruct_reports_the_builtin_field(
        self, model: type, field_name: str
    ) -> None:
        _, path, _, _ = model._meta.get_field(field_name).deconstruct()

        assert path == "django.db.models.URLField"
