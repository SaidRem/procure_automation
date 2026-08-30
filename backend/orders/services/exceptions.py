"""Исключения сервисного слоя приложения orders."""

from __future__ import annotations


class OrdersServiceError(Exception):
    """Базовая ошибка сервисов приложения orders."""


class InvalidQuantity(OrdersServiceError):
    """Количество позиции должно быть положительным."""


class BasketItemNotFound(OrdersServiceError):
    """Позиция не найдена в корзине текущего пользователя."""


class EmptyBasket(OrdersServiceError):
    """Корзина пуста: оформлять нечего."""


class ContactNotFound(OrdersServiceError):
    """Контакт не существует или принадлежит другому пользователю."""


class IncompleteRecipientData(OrdersServiceError):
    """В контакте не заполнены обязательные данные получателя (ADR-027).

    Список недостающих полей передаётся в `fields`: покупателю нужно
    знать, что именно дописать, а не только факт отказа.
    """

    def __init__(self, fields: tuple[str, ...]) -> None:
        self.fields = fields
        super().__init__(
            "Не заполнены обязательные поля получателя: " + ", ".join(fields)
        )


class OfferUnavailable(OrdersServiceError):
    """Предложение нельзя заказать.

    Базовый класс для трёх различимых причин (ADR-025). Причины
    разделены намеренно: снятие с продажи окончательно, а отключённый
    приём заказов и нехватка остатка временны, и покупателю это меняет
    дальнейшие действия.
    """

    def __init__(self, message: str, *, product_info_id: int | None = None) -> None:
        self.product_info_id = product_info_id
        super().__init__(message)


class OfferInactive(OfferUnavailable):
    """Предложение снято поставщиком с продажи (`is_active=False`)."""


class ShopNotAcceptingOrders(OfferUnavailable):
    """Поставщик временно не принимает заказы (`Shop.state=False`)."""


class InsufficientStock(OfferUnavailable):
    """Остатка предложения не хватает на запрошенное количество."""


class OfferGone(OfferUnavailable):
    """Предложение удалено из каталога: ссылка позиции обнулена.

    Возникает при оформлении заказа, если `ProductInfo` исчез после
    добавления товара в корзину (`SET_NULL`, ADR-003).
    """


class InvalidStateTransition(OrdersServiceError):
    """Переход между состояниями заказа не предусмотрен (ADR-022)."""

    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Переход {current} -> {target} не предусмотрен.")
