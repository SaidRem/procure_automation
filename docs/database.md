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

Реализовано (миграция users/0001_initial).

- User (кастомная модель, наследник AbstractUser, ADR-004):
  username удалён (username = None), USERNAME_FIELD = 'email',
  REQUIRED_FIELDS = [];
  email — EmailField(unique=True);
  first_name, last_name — CharField(max_length=150, blank);
  company, position — CharField(max_length=40, blank);
  type — CharField(max_length=5, choices buyer/shop, default 'buyer');
  is_active — BooleanField(default=False), пользователь активируется после
  подтверждения email; суперпользователь создаётся сразу с is_active=True
  (users.managers.UserManager).
  Meta: ordering ('email',). Других ограничений, кроме unique email, нет.

- Contact (адрес доставки; FK -> User, related_name='contacts',
  on_delete=CASCADE):
  city — CharField(max_length=50), street — CharField(max_length=100),
  phone — CharField(max_length=20) — обязательные;
  house, structure, building, apartment — CharField(max_length=15, blank).
  Constraints и soft delete отсутствуют намеренно (ADR-003): историчность
  адреса доставки обеспечивается snapshot-полями Order на момент
  подтверждения заказа, а не сохранением записи Contact.

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

- Order (dt, state; FK -> User, FK -> users.Contact — nullable)

  Корзина — это Order в состоянии state='basket' (ADR-009), отдельной
  модели корзины нет. Следствия для схемы:

  - UniqueConstraint(fields=['user'], condition=Q(state='basket')) —
    не более одной корзины на пользователя;
  - contact nullable: корзина существует без адреса доставки,
    обязательность контакта проверяется в сервисе подтверждения заказа;
  - dt (auto_now_add) — момент создания корзины, а не оформления заказа;
    для истории заказов требуется отдельная отметка времени
    подтверждения (поле определяется при реализации orders).

- OrderItem (quantity, snapshot-поля — product_name, shop_name, price,
  price_rrc; FK -> catalog.ProductInfo, nullable, on_delete=SET_NULL)

  Snapshot-поля допускают пустое значение: они заполняются один раз в
  момент подтверждения заказа (ADR-003) и до этого не заданы. Пока
  Order находится в состоянии basket, источник цены и наименования —
  текущий catalog.ProductInfo; после подтверждения — snapshot-поля
  самого OrderItem. Сумма корзины и сумма оформленного заказа
  считаются по разным источникам данных (ADR-009).

### notifications

- Без постоянных моделей на текущем этапе (Celery-задачи без хранения
  состояния). Решение может быть пересмотрено при реализации.


## Relations

- catalog.ProductInfo → suppliers.Shop, catalog.Product (many-to-one)
- catalog.ProductParameter → catalog.ProductInfo, catalog.Parameter
- orders.Order → users.User, users.Contact
- orders.OrderItem → orders.Order, catalog.ProductInfo (nullable;
  используется как ссылка на актуальную карточку товара и как источник
  цены для корзины, но не для расчёта оформленного заказа)
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