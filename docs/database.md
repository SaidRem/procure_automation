# Database Architecture


## Database

PostgreSQL.


## Main principles

- Database schema is managed through Django migrations.
- Direct database modifications are avoided.
- Historical records must be preserved.
- Изменение каталога (Product/ProductInfo) не изменяет историю уже
  оформленных заказов (ADR-003, docs/decisions.md).
- Импорт прайса поставщика не удаляет ProductInfo физически: отсутствующие
  в прайсе предложения помечаются is_active=False (ADR-008,
  docs/decisions.md). Каталожная выдача фильтрует is_active=True.


## Main entities

По приложениям:

### users

- User (кастомная модель, email как USERNAME_FIELD, type: buyer/shop)
- Contact (адрес доставки, телефон; FK -> User)

### suppliers

- Shop (name, url, state — приём заказов вкл/выкл; OneToOne -> User)

### catalog

- Category (name; M2M -> suppliers.Shop)
- Product (name; FK -> Category)
- ProductInfo (model, external_id, quantity, price, price_rrc,
  is_active — BooleanField(default=True, db_index=True), soft-deactivation
  при импорте, ADR-008;
  FK -> Product, FK -> suppliers.Shop;
  unique(shop, external_id))
- Parameter (name)
- ProductParameter (value; FK -> ProductInfo, FK -> Parameter;
  unique(product_info, parameter))

### orders

- Order (dt, state; FK -> User, FK -> users.Contact)
- OrderItem (quantity, snapshot-поля — product_name, shop_name, price,
  price_rrc; FK -> catalog.ProductInfo, nullable, on_delete=SET_NULL)

### notifications

- Без постоянных моделей на текущем этапе (Celery-задачи без хранения
  состояния). Решение может быть пересмотрено при реализации.


## Relations

- catalog.ProductInfo → suppliers.Shop, catalog.Product (many-to-one)
- catalog.ProductParameter → catalog.ProductInfo, catalog.Parameter
- orders.Order → users.User, users.Contact
- orders.OrderItem → orders.Order, catalog.ProductInfo (nullable)
- suppliers.Shop → users.User (one-to-one)

Направление зависимостей между приложениями (уровень моделей/ORM):

```
notifications   ← верхний уровень
  │
  │ «зависит от»
  ▼
orders
  │
  ▼
catalog
  │
  ▼
suppliers
  │
  ▼
users           ← базовый домен, ни от кого не зависит
```

Прямой обратный импорт ORM-моделей (например, suppliers импортирует
модели catalog напрямую) не допускается без нового ADR.

Обращение к данным домена, стоящего "выше" по цепочке, разрешено только
через его публичный сервисный слой (`<app>.services`), а не напрямую к
ORM — например, suppliers обращается к catalog.services при импорте
прайса (ADR-002, ADR-005, docs/decisions.md).