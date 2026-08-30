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


class TestNotificationsDependencies:
    """Границы приложения notifications.

    Оно стоит на верхнем уровне цепочки зависимостей и опирается на
    `orders` (`docs/database.md`): ADR-005 относит подтверждение заказа
    и накладную администратору к его функциям, а собрать письмо, не
    прочитав заказ, нельзя. Остальные домены остаются недоступными:
    всё, что нужно письму, доступно через сам заказ.
    """

    @pytest.mark.parametrize("domain", ("users", "catalog", "suppliers"))
    def test_does_not_import_lower_domains(self, domain: str) -> None:
        offending = {
            module
            for module in imported_modules("notifications")
            if module == domain or module.startswith(f"{domain}.")
        }

        assert offending == set(), (
            f"notifications импортирует {domain}: {offending}. "
            "Получатель и состав письма берутся из заказа, а не из "
            "чужих моделей (ADR-005, ADR-024)."
        )

    def test_reads_orders_models_only(self) -> None:
        """Разрешён только доступ к моделям заказа, не к его сервисам."""
        order_imports = {
            module
            for module in imported_modules("notifications")
            if module.startswith("orders")
        }

        assert order_imports == {"orders.models"}

    def test_orders_does_not_depend_back(self) -> None:
        """Обратной зависимости нет: цикла между доменами не возникает."""
        assert "notifications.tasks" not in imported_modules("orders")


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

    def test_orders_calls_notifications_service(self) -> None:
        """Допустимое обращение: orders.services -> notifications.services."""
        assert "notifications" in imported_modules("orders")
