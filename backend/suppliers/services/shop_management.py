"""Управление магазином поставщика (ADR-012).

Модуль содержит операции над самой записью `Shop`. Каталог отсюда не
меняется: импорт прайса — отдельный сценарий со своим сервисным слоем
(ADR-016).
"""

from __future__ import annotations

import logging

from suppliers.models import Shop
from suppliers.services.exceptions import ShopNotFound

logger = logging.getLogger(__name__)


def set_shop_state(shop_id: int, *, state: bool) -> Shop:
    """Включить или отключить приём заказов магазином.

    Приём заказов — отдельное действие поставщика: импорт прайса это
    значение не изменяет (ADR-012). Операция идемпотентна — повторный
    вызов с тем же значением записи не трогает.

    Значение передаётся именованным аргументом: в вызове вида
    `set_shop_state(pk, False)` смысл голого булева непонятен.
    """
    shop = _get_shop(shop_id)

    if shop.state == state:
        logger.debug(
            "Shop order acceptance unchanged: shop_id=%s state=%s", shop_id, state
        )
        return shop

    shop.state = state
    shop.save(update_fields=["state"])

    logger.info("Shop order acceptance changed: shop_id=%s state=%s", shop_id, state)
    return shop


def _get_shop(shop_id: int) -> Shop:
    """Найти магазин по идентификатору."""
    try:
        return Shop.objects.get(pk=shop_id)
    except Shop.DoesNotExist as error:
        raise ShopNotFound(f"Магазин {shop_id} не найден.") from error
