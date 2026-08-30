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
- Адрес доставки оформленного заказа хранится snapshot-полями Order и
  не зависит от записи users.Contact: контакт может быть изменён или
  удалён, история заказов при этом не меняется (ADR-024,
  docs/decisions.md).
- Доступность предложения в каталоге и его доступность к заказу —
  разные проверки: выдача фильтрует только is_active, приём заказов
  (Shop.state) и остаток проверяются при работе с корзиной и заказом
  (ADR-025, docs/decisions.md).


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
  Constraints и soft delete отсутствуют намеренно (ADR-003, ADR-024):
  историчность адреса доставки обеспечивается snapshot-полями Order на
  момент подтверждения заказа, а не сохранением записи Contact.
  Следствие: Contact разрешено изменять и удалять физически — после
  введения snapshot он является записью адресной книги пользователя, а
  не исторической записью (ADR-024). Order.contact при удалении
  обнуляется (SET_NULL).

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

  Поле url объявлено типом HttpsURLField — подклассом URLField, который
  меняет только поведение формы (схема по умолчанию https) и в схеме БД
  неотличим от URLField, миграции не требует (ADR-018).

- ImportLog (журнал запусков импорта, ADR-021; миграции
  suppliers/0002_importlog, 0003_alter_importlog_error_code):

  Одна запись — один запуск импорта, а не одна попытка выполнения:
  повторы Celery идут в рамках той же записи и увеличивают attempts.

  shop — FK -> Shop (related_name='import_logs', on_delete=PROTECT);
  initiated_by — FK -> users.User (related_name='import_logs', null,
  blank, on_delete=SET_NULL); пустое значение означает запуск не
  человеком;
  source_url — HttpsURLField(max_length=500) — источник конкретного
  запуска, собственная копия адреса, а не ссылка на Shop.url
  (ADR-026);
  task_id — CharField(max_length=64, blank) — идентификатор задачи
  Celery, записывается после постановки, короткое время пуст
  (ADR-021, amendment);
  status — CharField(max_length=7, db_index, choices ImportStatus:
  queued / running / success / failed);
  attempts — PositiveIntegerField(default=0);
  created_at — DateTimeField(auto_now_add) — момент постановки в
  очередь; started_at, finished_at — DateTimeField(null, blank);
  счётчики результата — offers_total, created, updated, reactivated,
  deactivated, products_created, categories_linked —
  PositiveIntegerField(default=0), повторяют поля
  catalog.services.ImportResult один в один; created — количество
  созданных предложений, момент постановки в очередь хранится в
  created_at;
  error_code — CharField(max_length=32, blank, choices
  ImportErrorCode — закрытый словарь причин отказа);
  error_message — TextField(blank).

  Счётчики хранятся отдельными колонками, а не в JSONField: они
  выводятся в списке админки и участвуют в фильтрах (ADR-021).

  Физическое удаление запрещено: ImportLog.delete() возбуждает
  ProtectedError (ограничение уровня экземпляра).

  Индексы: index(status), составной index(shop, -created_at).
  Meta: ordering ('-created_at',).

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

Не реализовано: приложение будет создано после notifications (ADR-010,
amendment). Раздел фиксирует схему, вытекающую из принятых решений.

- Order (dt, confirmed_at, state; FK -> User, FK -> users.Contact —
  nullable; snapshot-поля адреса доставки)

  Корзина — это Order в состоянии state='basket' (ADR-009), отдельной
  модели корзины нет. Следствия для схемы:

  - UniqueConstraint(fields=['user'], condition=Q(state='basket')) —
    не более одной корзины на пользователя;
  - contact nullable: корзина существует без адреса доставки,
    обязательность контакта проверяется в сервисе подтверждения заказа;
  - dt (auto_now_add) — момент создания корзины, а не оформления
    заказа.

  state — CharField с закрытым набором значений: basket, new,
  confirmed, assembled, sent, delivered, canceled. Схема хранит текущее
  состояние; допустимые переходы задаются кодом orders.services и в
  базе не выражаются (ADR-022). Модели истории смен статуса нет.

  confirmed_at — DateTimeField(null, blank), заполняется один раз при
  переходе basket -> new. Это отдельная от dt отметка времени: dt
  относится к созданию корзины, а история заказов (спецификация:
  «Номер, Дата, Сумма, Статус») показывает дату оформления и по ней же
  сортируется (ADR-022).

  Snapshot адреса доставки (ADR-024) — семь полей, повторяющих
  users.Contact: city, street, house, structure, building, apartment,
  phone. Заполняются один раз при переходе basket -> new и далее не
  изменяются. На уровне схемы допускают пустое значение, так как у
  корзины не заданы; у оформленного заказа непусты city, street, phone
  — как и в Contact. Хранятся отдельными колонками, а не строкой или
  JSONField: накладная и карточка заказа выводят адрес по частям.

  contact (FK -> users.Contact, on_delete=SET_NULL) служит только
  трассируемостью и после удаления адреса становится NULL. Адрес
  оформленного заказа читается из snapshot-полей Order, а не через
  order.contact (ADR-024).

  Физическое удаление Order и OrderItem не предусмотрено: отмена
  выражается состоянием canceled (ADR-022).

- OrderItem (quantity, snapshot-поля — product_name, shop_name, price,
  price_rrc; FK -> catalog.ProductInfo, nullable, on_delete=SET_NULL)

  Snapshot-поля допускают пустое значение: они заполняются один раз в
  момент подтверждения заказа (ADR-003) и до этого не заданы. Пока
  Order находится в состоянии basket, источник цены и наименования —
  текущий catalog.ProductInfo; после подтверждения — snapshot-поля
  самого OrderItem. Сумма корзины и сумма оформленного заказа
  считаются по разным источникам данных (ADR-009).

  Подтверждение заказа не изменяет catalog.ProductInfo.quantity:
  остаток проверяется, но не резервируется — полем владеет прайс
  поставщика, и ближайший импорт перезаписал бы списание (ADR-022,
  ADR-008).

### notifications

- Без постоянных моделей на текущем этапе (Celery-задачи без хранения
  состояния). Решение может быть пересмотрено при реализации.
- Приложение создаётся в базовой части проекта, до реализации orders
  (ADR-010, amendment от 2026-08-30). До этого момента задача
  send_email временно живёт в users/tasks.py; таблиц ни та, ни другая
  схема не добавляет.


## Relations

- catalog.ProductInfo → suppliers.Shop, catalog.Product (many-to-one)
- catalog.ProductParameter → catalog.ProductInfo, catalog.Parameter
- orders.Order → users.User; orders.Order → users.Contact (nullable,
  on_delete=SET_NULL; трассируемость, не источник адреса оформленного
  заказа — ADR-024)
- orders.OrderItem → orders.Order, catalog.ProductInfo (nullable;
  используется как ссылка на актуальную карточку товара и как источник
  цены для корзины, но не для расчёта оформленного заказа)
- suppliers.Shop → users.User (one-to-one, on_delete=PROTECT, ADR-012)
- suppliers.ImportLog → suppliers.Shop (many-to-one, on_delete=PROTECT);
  suppliers.ImportLog → users.User (many-to-one, nullable,
  on_delete=SET_NULL, ADR-021)
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