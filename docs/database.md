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
- Денежные значения хранятся как DecimalField(max_digits=12,
  decimal_places=2); float для цен и сумм не используется (ADR-015,
  docs/decisions.md).


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

Шаг 2 (API приложения users) новых таблиц не добавил: токены
подтверждения email и восстановления пароля не хранятся в БД, а
вычисляются генераторами Django (ADR-011).

### suppliers

Реализовано (миграция suppliers/0001_initial).

- Shop (поставщик):
  name — CharField(max_length=50, unique);
  url — URLField(blank, null): в прайсе поставщика ссылки может не быть;
  state — BooleanField(default=True) — приём заказов вкл/выкл, импортом
  не изменяется;
  user — OneToOneField -> users.User (null, blank, on_delete=PROTECT).

  Идентификация магазина при импорте — по user, а не по name из прайса
  (ADR-012). Физическое удаление Shop не предусмотрено и запрещено на
  уровне модели: Shop.delete() возбуждает ProtectedError (ограничение
  действует для экземпляра, массовое удаление через queryset в коде
  проекта не используется).

  Индексы: unique(name), unique(user) — из OneToOneField.

### catalog

Реализовано (миграция catalog/0001_initial, зависит от
suppliers/0001_initial).

- Category:
  name — CharField(max_length=40, unique);
  shops — M2M -> suppliers.Shop (related_name='categories', blank).

  Внешний идентификатор категории из прайса не хранится: соответствие
  разрешается в пределах одного импорта по секции categories файла
  (ADR-013).

  Индексы: unique(name).

- Product (логический товар, ADR-001):
  name — CharField(max_length=80);
  category — FK -> Category (related_name='products', on_delete=PROTECT).

  unique(name, category) — ключ идентификации товара при импорте
  (ADR-014).

  Индексы: unique(name, category), index(name) — под поиск в каталоге.

- ProductInfo (предложение конкретного поставщика, ADR-001):
  external_id — PositiveIntegerField, идентификатор позиции в прайсе
  поставщика;
  model — CharField(max_length=80, blank);
  quantity — PositiveIntegerField;
  price, price_rrc — DecimalField(max_digits=12, decimal_places=2)
  (ADR-015);
  is_active — BooleanField(default=True, db_index=True),
  soft-deactivation при импорте (ADR-008);
  FK -> Product (related_name='product_infos', on_delete=CASCADE);
  FK -> suppliers.Shop (related_name='product_infos', on_delete=CASCADE).

  unique(shop, external_id) — ключ upsert при импорте (ADR-008; заменяет
  unique(product, shop, external_id) из ADR-001).

  Индексы: unique(shop, external_id), index(is_active), составной
  index(shop, is_active) — под каталожную выдачу и массовую деактивацию
  при импорте.

- Parameter:
  name — CharField(max_length=40, unique) — ключ поиска при импорте.

  Индексы: unique(name).

- ProductParameter:
  value — CharField(max_length=100);
  FK -> ProductInfo (related_name='product_parameters',
  on_delete=CASCADE);
  FK -> Parameter (on_delete=PROTECT).

  unique(product_info, parameter).

  Значения характеристик в прайсе могут быть числами; приведение к
  строке и проверка длины выполняются при импорте, а не моделью
  (ADR-016).

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
- suppliers.Shop → users.User (one-to-one, on_delete=PROTECT, ADR-012)
- catalog.Product → catalog.Category (many-to-one, on_delete=PROTECT)
- catalog.Category → suppliers.Shop (many-to-many)

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