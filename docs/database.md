# Database Architecture


## Database

PostgreSQL.


## Main principles

- Database schema is managed through Django migrations.
- Direct database modifications are avoided.
- Historical records must be preserved.
- Изменение каталога (Product/ProductInfo) не изменяет историю уже
  оформленных заказов (ADR-003, docs/decisions.md).


## Main entities

По приложениям (см. .claude/architecture.md):

### users

- User (кастомная модель, email как USERNAME_FIELD, type: buyer/shop)
- Contact (адрес доставки, телефон; FK -> User)

### suppliers

- Shop (name, url, state — приём заказов вкл/выкл; OneToOne -> User)

### catalog

- Category (name; M2M -> suppliers.Shop)
- Product (name; FK -> Category)
- ProductInfo (model, external_id, quantity, price, price_rrc;
  FK -> Product, FK -> suppliers.Shop;
  unique(product, shop, external_id))
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

Направление зависимостей между приложениями:
users ← suppliers ← catalog ← orders ← notifications.
Обратные зависимости не допускаются без нового ADR.