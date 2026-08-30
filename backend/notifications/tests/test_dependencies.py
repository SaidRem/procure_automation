"""Проверка направления зависимостей (ADR-002, ADR-005, ADR-010).

Правила границ выражены здесь исполняемо: нарушение видно тестом, а не
только на ревью.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]


def imported_modules(package: str) -> set[str]:
    """Собрать имена модулей, импортируемых пакетом (без тестов)."""
    modules: set[str] = set()

    for path in (BACKEND / package).rglob("*.py"):
        if "tests" in path.parts:
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)

    return modules


class TestNotificationsIsIndependent:
    """notifications не знает о доменных приложениях."""

    @pytest.mark.parametrize("domain", ("users", "orders", "catalog", "suppliers"))
    def test_does_not_import_domain_apps(self, domain: str) -> None:
        offending = {
            module
            for module in imported_modules("notifications")
            if module == domain or module.startswith(f"{domain}.")
        }

        assert offending == set(), (
            f"notifications импортирует {domain}: {offending}. "
            "Уведомления принимают примитивы и о доменах не знают (ADR-005)."
        )


class TestUsersHasNoTemporaryDependency:
    """Временная зависимость users -> users.tasks снята (ADR-010)."""

    def test_users_tasks_module_is_gone(self) -> None:
        assert not (BACKEND / "users" / "tasks.py").exists()

    def test_users_notifications_facade_is_gone(self) -> None:
        assert not (BACKEND / "users" / "services" / "notifications.py").exists()

    def test_users_does_not_import_celery(self) -> None:
        """Домен вызывает notifications.services, а не задачи напрямую."""
        modules = imported_modules("users")

        assert not any(module.startswith("celery") for module in modules)
        assert "users.tasks" not in modules

    def test_users_calls_notifications_service(self) -> None:
        assert "notifications.services" in imported_modules("users")


class TestOrdersDoesNotImportTasks:
    """orders обращается к уведомлениям только через сервис (ADR-005)."""

    def test_orders_does_not_import_celery(self) -> None:
        modules = imported_modules("orders")

        assert not any(module.startswith("celery") for module in modules)
        assert "notifications.tasks" not in modules
