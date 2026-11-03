# How It Works: архитектура и логика кода TimeShift

Подробный разбор проекта модуль за модуль: модели данных, бизнес-логика views,
сигналы и виртуальные свойства.

**Стек:** Django 5.2 · SQLite · HTML + Tailwind CSS (CDN)
**Приложения:** `users` (профили, соцфункции) и `bounty` (задачи, переводы)

---

## 1. Общая схема работы

```
Браузер ──► server/urls.py
                ├── users.urls   (auth, профиль, кран, отзывы, подписки, топ, PRO)
                └── bounty.urls  (доска задач)
                        │
                        ▼
              views.py (проверки + бизнес-логика)
                        │
          ┌─────────────┼──────────────┐
          ▼             ▼              ▼
       models.py    signals.py     шаблоны (TLT + Tailwind)
          │             │
          ▼             ▼
      SQLite ──► пересчёт репутации, переводы минут, уведомления
```

Каждое действие пользователя — это класс-вьюха (CBV), обрабатывающая
`GET`/`POST`, проверяющая бизнес-правила и возвращающая `redirect` с
сообщением через `django.contrib.messages`.

---

## 2. Модели базы данных

Файлы: `users/models.py`, `bounty/models.py`.

### 2.1 Схема связей

```
django.contrib.auth.User
        │ OneToOne (related_name='profile')
        ▼
     Profile ────────────── M2M ──────► Skill
        │
        │ (как target_user / author / follower / following)
        ├──► Review (author, target_user)
        ├──► Follow (follower → following)
        ├──► Notification (user)
        └──► DailyQuestProgress (user)

User (creator) ──► BountyTask ◄── User (performer)
                        │ OneToOne (related_name='contract')
                        ▼
                  HelpContract
                  (helper = исполнитель,
                   helped_user = автор задачи)
```

### 2.2 Skill

Справочник навыков (`name`, уникальный). Используется двумя связями M2M:

- `Profile.skill` — навыки участника;
- `BountyTask.required_skills` — требуемые навыки задачи.

### 2.3 Profile

Расширение `User` (OneToOne, `related_name='profile'`). Хранит **всю экономику**:

| Поле | Назначение |
|------|------------|
| `balance_minutes` | Баланс времени (default **60**) — главная валюта |
| `reputation` | Репутация (0…10+), пересчитывается сигналом |
| `daily_bonus_minutes` | Сколько минут сегодня получено из тайм-крана |
| `last_bonus_date` | Дата последнего дня использования крана (для сброса) |
| `last_bonus_time` | Время последнего клика (для кулдауна 20 мин) |
| `is_pro` | Флаг PRO-статуса |
| `daily_spent_minutes` | Сколько минут **израсходовано на переводы сегодня** |
| `last_spend_date` | Дата учёта трат — для сброса дневного лимита |
| `telegram_username`, `telegram_id` | Контакты (unique, для будущего бота) |
| `avatar`, `specialization`, `bio` | Публичные данные профиля |
| `skill` | M2M → `Skill` |

Связи через `related_name`:

- `user.profile` — профиль пользователя;
- `user.created_tasks` / `user.assigned_tasks` — задачи;
- `user.reviews` / `user.written_reviews` — полученные/написанные отзывы;
- `user.followers` / `user.following` — подписчики/подписки;
- `user.notifications` — уведомления;
- `user.quest_progress` — прогресс квестов.

### 2.4 BountyTask

Задача с доски:

| Поле | Назначение |
|------|------------|
| `creator` | Автор (платит минуты) |
| `performer` | Исполнитель (`null=True`, пока не взята) |
| `title`, `description` | Содержание |
| `required_skills` | M2M → `Skill` |
| `reward_minutes` | Награда в минутах (default 60; ранее поле называлось `reward_hours` — миграции `0002`, `0004` конвертируют данные) |
| `status` | `open` / `in_progress` / `completed` / `cancelled` |

### 2.5 HelpContract

Факт оказанной помощи. Создаётся **только** при закрытии задачи:

- `task` — OneToOne к `BountyTask` (`related_name='contract'`), т.е. у задачи
  максимум один договор;
- `helper` — исполнитель (получатель минут);
- `helped_user` — автор задачи (плательщик);
- `feedback`, `complated_at` — обратная связь и время создания.

Именно создание этой записи запускает **сигнал перевода минут** (см. §4).

### 2.6 DailyQuestProgress

Прогресс квестов за день:

- `user` + `date` — запись за конкретную дату;
- `created_tasks`, `completed_tasks`, `faucet_clicks` — счётчики трёх квестов;
- `is_reward_claimed` — выдана ли награда +60 (защита от повтора).

Ключевой метод `check_and_reward()`:

```
если is_reward_claimed → False (награда уже была)
если created_tasks >= 1 И completed_tasks >= 1 И faucet_clicks >= 1:
        is_reward_claimed = True
        profile.balance_minutes += 60
        save()
        return True   ← вызывающая вьюха показывает сообщение «+60 минут»
иначе → False
```

### 2.7 Review

Отзыв: `author` → `target_user`, `rating` (1–10, валидаторы
`MinValueValidator`/`MaxValueValidator`), `text`, `created_at`.
Сохранение/удаление отзыва триггерит пересчёт репутации (см. §4).

### 2.8 Follow

Подписка `follower` → `following` с `unique_together = ('follower', 'following')`
— повторная подписка невозможна на уровне БД.

### 2.9 Notification

Уведомление внутри платформы: `user`, `title`, `message`, `is_read`,
`created_at`. Создаётся сигналом при публикации задачи её подписчикам.

---

## 3. Бизнес-логика (views)

### 3.1 Доска задач — `bounty/views.py`

**`BountyListView`** (`/`)

- `get_queryset()`: `select_related('creator', 'performer')` +
  `prefetch_related('required_skills')` — защита от N+1;
- GET-фильтры: `?status=open|in_progress|completed`, `?skill=<id>`;
- контекст: `skills`, `current_status`, `current_skill` для подсветки фильтров.

**`BountyCreateView`** (`/create/`)

```
form_valid(form):
    1. form.instance.creator = request.user
    2. super().form_valid(form)          ← сохранение задачи
       └─ post_save → сигнал уведомляет подписчиков
    3. DailyQuestProgress.get_or_create(user, date=сегодня)
    4. quest.created_tasks += 1; save()
    5. quest.check_and_reward()          ← может выдать +60 мин
```

**`TakeTaskView`** (`/task/<pk>/take/`, GET)

```
если task.status == 'open' И task.creator != request.user:
        task.performer = request.user
        task.status = 'in_progress'
        task.save()
redirect('bounty_list')
```

Иначе — молчаливый редирект (задача уже занята или это своя задача).

### 3.2 Алгоритм закрытия задачи — `CompleteTaskView`

Это **центральный алгоритм экономики**. `GET /task/<pk>/complete/`,
доступен только автору задачи.

```
ШАГ 1. Проверка доступа
        task = get_object_or_404(BountyTask, pk)
        если task.status != 'in_progress' ИЛИ task.creator != request.user:
                сообщение «Вы не можете закрыть эту задачу.»
                redirect → выход

ШАГ 2. Подготовка учёта трат
        creator_profile = request.user.profile
        если last_spend_date != сегодня:
                daily_spent_minutes = 0        ← сброс дневного лимита
                last_spend_date = сегодня

ШАГ 3. Определение лимита
        daily_limit = 720, если is_pro, иначе 120

ШАГ 4. Проверка дневного лимита переводов
        если daily_spent_minutes + reward_minutes > daily_limit:
                сообщение «Превышен дневной лимит переводов! ...»
                redirect → выход (минуты НЕ списываются)

ШАГ 5. Проверка баланса
        если balance_minutes < reward_minutes:
                сообщение «Недостаточно минут на балансе...»
                redirect → выход

ШАГ 6. Учёт трат
        daily_spent_minutes += reward_minutes
        creator_profile.save()

ШАГ 7. Смена статуса
        task.status = 'completed'; task.save()

ШАГ 8. Создание договора помощи
        HelpContract.objects.create(
            task=task,
            helper=task.performer,        ← исполнитель
            helped_user=task.creator)     ← автор
        └─ post_save → СИГНАЛ process_help_contract
              └─ transaction.atomic():
                     helped_profile.balance -= reward  (пол = 0)
                     helper_profile.balance += reward
                     helper_profile.reputation += 10
                     task.status = 'completed'; save()

ШАГ 9. Квест исполнителя
        quest = DailyQuestProgress.get_or_create(user=task.performer, date=сегодня)
        quest.completed_tasks += 1; save()
        quest.check_and_reward()          ← возможно +60 мин исполнителю

ШАГ 10. Ответ
        сообщения «Ежедневный квест выполнен!» (если сработал)
        + «Задача успешно закрыта! Минуты переведены исполнителю.»
        redirect → bounty_list
```

Важные детали:

- **Списание выполняет сигнал, а не вьюха**: вьюха только *проверяет*
  баланс и лимит, а фактическое движение средств происходит в
  `process_help_contract` внутри `transaction.atomic()` — либо весь перевод
  проходит, либо ничего.
- Сигнал дополнительно защищён: если баланса не хватает, он всё равно не
  уйдёт в минус — значение обрезается до `0`.
- Итого за закрытие задачи автор платит `reward`, исполнитель получает
  `reward` + `10` репутации, автор теряет `reward` из `daily_spent_minutes`
  лимита.

### 3.3 Тайм-кран — `CollectBonusView`

`GET /collect-bonus/` → редирект на профиль с сообщением.

```
profile = request.user.profile
now = timezone.now()

1. Сброс суточного счётчика крана
        если last_bonus_date != сегодня:
                daily_bonus_minutes = 0
                last_bonus_date = сегодня

2. Дневной лимит крана (300 мин)
        если daily_bonus_minutes >= 300:
                ошибка «Дневной лимит исчерпан. Приходи завтра!» → выход

3. Кулдаун 20 минут
        если last_bonus_time установлен И now - last_bonus_time < 20 минут:
                предупреждение «20 минут еще не прошло!» → выход

4. Начисление
        balance_minutes   += 20
        daily_bonus_minutes += 20
        last_bonus_time = now
        save()

5. Квест «тайм-кран»
        quest.faucet_clicks += 1; save()
        quest.check_and_reward()      ← возможно +60 мин

6. успех → «Бонус +20 минут успешно получен!»
```

Отображение: в `profile.html` через `{% widthratio daily_bonus_minutes 300 100 %}`
строится прогресс-бар заполнения крана.

### 3.4 Начисление квестов — сводка точек входа

| Квест | Вьюха | Что делает |
|-------|-------|------------|
| Создать задачу | `BountyCreateView.form_valid` | `created_tasks += 1` → `check_and_reward()` |
| Закрыть задачу | `CompleteTaskView` (у **исполнителя**) | `completed_tasks += 1` → `check_and_reward()` |
| Тайм-кран | `CollectBonusView` | `faucet_clicks += 1` → `check_and_reward()` |

`get_or_create(user, date=...)` гарантирует одну запись прогресса на день;
`is_reward_claimed` гарантирует единственную выдачу +60 минут.

### 3.5 PRO-статус — `BuyProView`

```
POST /buy-pro/
процена = 3000
если is_pro            → warning «У вас уже есть PRO-статус!»
если balance < 3000    → error «Недостаточно времени!...»
иначе:
        balance_minutes -= 3000
        is_pro = True
        save()
        → успех «Вы успешно приобрели PRO-статус 🚀»
```

Эффект применяется в `CompleteTaskView` (ШАГ 3): `720` вместо `120`.

### 3.6 Отзывы — `AddReviewView`

```
POST /user/<username>/
- target_user = get_object_or_404(User, username)
- запрет отзыва на себя
- rating: обязателен, только цифры, диапазон 1…10 (валидация вручную)
- Review.objects.create(author, target_user, rating, text)
  └─ post_save → сигнал update_user_reputation (§4)
```

### 3.7 Подписки — `ToggleFollowView`

```
POST /user/<username>/
- запрет подписки на себя
- follow, created = Follow.objects.get_or_create(follower, following)
- если НЕ created (уже была) → follow.delete()  «Вы отписались»
- если created (новая)       → «Вы подписались»
```

`is_following` для кнопки вычисляется в `UserProfileView.get_context_data`:
`request.user.following.filter(following=self.object).exists()`.

### 3.8 Ледерборд — `LeaderboardView`

```python
Profile.objects.select_related('user').order_by('-balance_minutes')
```

Шаблон обрезает список `|slice:":10"` и раскрашивает первые три места.

### 3.9 Прочие вьюхи (`users/views.py`)

| Вьюха | Роль |
|-------|------|
| `RegisterView` | `UserCreationForm` → редирект на login |
| `ProfileDetailView` | Свой профиль (`get_object` → `request.user`) |
| `ProfileUpdateView` | Редактирование через `ProfileEditForm` (User + Profile + аватар) |
| `UserProfileView` | Публичный профиль по `username`, контекст `is_following` |
| `AboutUsView` | Статическая страница «О нас» |

`ProfileEditForm` (не ModelForm): валидирует уникальность логина и
Telegram-ника, ограничивает аватар 2 МБ, метод `save()` синхронно пишет
данные в `User` и `Profile`.

### 3.10 Прямые переводы минут — `TransferView`

Пользователь может перевести время другому участнику напрямую (банковский
перевод), минуя механизм задач.

**Маршрут:** `POST /transfer/` → `users/urls.py` → `TransferView`
(`users/views.py`). Страница интерфейса — карточка «⏳ Перевести время»
на публичном профиле `templates/users/user_profile.html` (показывается
только авторизованным и не на собственном профиле).

**Форма отправляет:**

- `username` — получатель (hidden-поле, подставляется из профиля);
- `amount` — минуты (числовое поле, 1…3600);
- `csrf_token`.

**Алгоритм:**

```
POST /transfer/
1. recipient = get_object_or_404(User, username=...)   ← получатель
2. запрет перевода самому себе
3. amount = int(...); проверка 0 < amount <= 3600
4. если last_spend_date != сегодня:
        daily_spent_minutes = 0; last_spend_date = сегодня
5. daily_limit = 720, если is_pro, иначе 120        ← общий лимит с задачами
6. если daily_spent + amount > daily_limit → ошибка
7. если balance < amount → ошибка
8. transaction.atomic():
        отправитель: balance -= amount, daily_spent += amount
        получатель:  balance += amount
        получателю → Notification «Вам поступил перевод...»
9. messages.success → redirect на профиль получателя
```

Ключевые свойства:

- **Общий дневной лимит** с закрытием задач — переводы и `CompleteTaskView`
  используют одни и те же поля `daily_spent_minutes` / `last_spend_date`,
  поэтому суммарный расход за день ограничен 120/720 минутами.
- Движение средств атомарно (`transaction.atomic()`).
- Баланс и лимит дублируются в UI: карточка показывает баланс отправителя,
  прогресс-бар `spent / limit` и предупреждение при исчерпании лимита.

### 3.11 Уведомления — `NotificationListView`

Отображение уведомлений (новые задачи от авторов-подписок, переводы времени).

**Составные части:**

| Часть | Файл | Роль |
|-------|------|------|
| Вьюха | `users/views.py` → `NotificationListView` | `LoginRequiredMixin` + `ListView`; при `GET` помечает все непрочитанные `is_read=True` и отдаёт список `request.user.notifications` по убыванию даты |
| Маршрут | `users/urls.py` → `/notifications/` (`name='notifications'`) | анонимы получают 302 на login |
| Контекст-процессор | `users/context_processors.py` → `unread_notifications` | Считает `count()` непрочитанных и кладёт `unread_notifications` в контекст **каждой** страницы — из этого рисуется бейдж |
| Регистрация | `server/settings.py` → `TEMPLATES...context_processors` | Строка `'users.context_processors.unread_notifications'` |
| Страница | `templates/users/notifications.html` | Список карточек: иконка (⏳ перевод / 📋 задача), `title`, `message`, дата; пустое состояние с CTA |
| Бейдж/ссылка | `templates/base.html` | 🔔 в левом сайдбаре (десктоп) и в мобильной шапке; красный `rose-500`-бейдж со счётчиком (99+ при >99), скрыт при 0 |

**Как это работает:**

```
Сигнал/TransferView ──► Notification(is_read=False)
                              │
                              ├─► контекст-процессор: count() → бейдж 🔔 на всех страницах
                              │
Пользователь открывает /notifications/
        └─► filter(is_read=False).update(is_read=True)   ← авто-прочтение
        └─► рендер списка → бейдж обнуляется
```

- Автоматическое прочтение: при первом открытии страницы бейдж сбрасывается.
- Подсветка «нового» не ведётся — после открытия все записи уже прочитаны.
- Иконка карточки определяется по подстроке `перевод` в `message`.

---

## 4. Сигналы

### 4.1 Пересчёт репутации — `users/models.py`

```python
@receiver([post_save, post_delete], sender=Review)
def update_user_reputation(sender, instance, **kwargs):
    avg = Review.objects.filter(target_user=instance.target_user)
                        .aggregate(Avg('rating'))['rating__avg']
    target_profile.reputation = round(avg) if avg else 0
    target_profile.save()
```

- Срабатывает при **создании, изменении и удалении** отзыва.
- Репутация получателя = **средний рейтинг его отзывов, округлённый**
  (`round(8.5) → 8` или `9` — банковское округление Python).
- Если отзывов нет → `0`.
- Оценка в шаблонах отображается как `⭐ {{ reputation }}/10`.
- **Единственный источник репутации — отзывы.** Начисление `+10` за
  закрытую задачу из `process_help_contract` отключено (строка
  закомментирована в `bounty/signals.py`), иначе счётчик уходил за
  пределы шкалы (например, `20/10`). Существующие значения сброшены в `0`.

### 4.2 Перевод минут за помощь — `bounty/signals.py`

```python
@receiver(post_save, sender=HelpContract)
def process_help_contract(sender, instance, created, **kwargs):
    if created:
        reward = instance.task.reward_minutes
        helper_profile  = Profile.objects.get_or_create(user=instance.helper)
        helped_profile  = Profile.objects.get_or_create(user=instance.helped_user)
        with transaction.atomic():
            helped_profile.balance = max(0, balance - reward)   # не уходит в минус
            helper_profile.balance += reward
            # helper_profile.reputation += 10   # отключено: репутация — только по отзывам
            ...
```

Триггерится созданием `HelpContract` в `CompleteTaskView` (ШАГ 8).
Атомарность гарантирует: списание и зачисление выполняются как одна
операция.

### 4.3 Рассылка уведомлений подписчикам — `bounty/signals.py`

```python
@receiver(post_save, sender=BountyTask)
def notify_followers_on_new_task(sender, instance, created, **kwargs):
    if created:
        for follow in Follow.objects.filter(following=instance.creator):
            Notification.objects.create(
                user=follow.follower,
                title=f"Новая задача от {instance.creator.username}",
                message=f"... «{instance.title}». Награда: {instance.reward_minutes} минут.")
        # telegram_id → send_to_telegram_bot(...)   ← заготовка, закомментирована
```

- Срабатывает **один раз** — при `created=True` (публикация задачи).
- Выборка: все, у кого `following == автор задачи`.
- Каждому подписчику создаётся `Notification` (веб-хранилище, `is_read=False`).
- Блок Telegram-отправки по `profile.telegram_id` подготовлен, но отключён.

### 4.4 Создание профиля — `users/signals.py`

```python
@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    Profile.objects.get_or_create(user=instance)
```

Намерение: каждый новый `User` автоматически получает `Profile`.
В `bounty/apps.py` приёмники подключаются в `ready()` (`import bounty.signals`),
приёмники `users` подключаются при импорте `users.models` (сам
`update_user_reputation` объявлен прямо в `models.py` и активен всегда).

### 4.5 Сводка сигналов

| Сигнал | Отправитель | Срабатывает когда | Эффект |
|--------|-------------|-------------------|--------|
| `update_user_reputation` | `Review` (save/delete) | добавлен/изменён/удалён отзыв | `reputation = round(avg)` |
| `process_help_contract` | `HelpContract` (save, created) | закрыта задача | перевод минут + `reputation += 10` |
| `notify_followers_on_new_task` | `BountyTask` (save, created) | опубликована задача | `Notification` всем подписчикам |
| `create_or_update_user_profile` | `User` (save, created) | создан пользователь | автосоздание `Profile` |

---

## 5. Виртуальные свойства (`@property`)

### 5.1 `Profile.formatted_balance`

```python
@property
def formatted_balance(self):
    if self.balance_minutes == 0:
        return "0 мин."
    hours = self.balance_minutes // 60
    remaining_minutes = self.balance_minutes % 60
    if hours > 0 and remaining_minutes > 0:
        return f"{hours} ч. {remaining_minutes} мин."
    elif hours > 0:
        return f"{hours} ч."
    else:
        return f"{remaining_minutes} мин."
```

**Как работает:**

1. Деление `// 60` — целое число часов; остаток `% 60` — минуты.
2. Три ветки вывода:
   - `90` → `1 ч. 30 мин.`;
   - `120` → `2 ч.` (минут нет — часы одни);
   - `45` → `45 мин.`;
   - `0` → `0 мин.`.
3. Свойство **вычисляется на лету** (в памяти), в БД не сохраняется и не
   требует `save()` — в шаблоне вызывается как обычная строка:
   `{{ user.profile.formatted_balance }}`.

**Где используется:**

- `base.html` — баланс в шапке сайта (`⏳ {{ user.profile.formatted_balance }}`);
- `users/profile.html` — карточка баланса;
- `users/user_profile.html` — публичный профиль;
- `users/leaderboard.html` — колонка баланса в топ-10.

### 5.2 Прочие «отображаемые» методы

- `BountyTask.__str__` → `'{title} ({reward} min) - {status}'` — удобен в админке.
- `get_status_display()` (Django-хелпер по `choices`) — локализованное имя
  статуса в карточке задачи.
- `DailyQuestProgress.check_and_reward()` — не `property`, а командный метод:
  меняет состояние (`is_reward_claimed`, баланс) и возвращает `bool`
  для вывода сообщения во вьюхе.

---

## 6. Поток данных: полный жизненный цикл задачи

```
[Создание]  Автор ──► BountyCreateView ──► BountyTask(status=open)
                 └─► сигнал: Notification всем подписчикам автора
                 └─► квест автора: created_tasks += 1

[Отклик]    Исполнитель ──► TakeTaskView ──► status=in_progress, performer=user

[Закрытие]  Автор ──► CompleteTaskView
                 ├─ проверка: только автор + статус in_progress
                 ├─ проверка: дневной лимит 120/720 мин
                 ├─ проверка: баланс >= reward
                 ├─ daily_spent += reward
                 ├─ status = completed
                 ├─ HelpContract.create()
                 │      └─► сигнал: автор −reward, исполнитель +reward
                 └─ квест исполнителя: completed_tasks += 1
                        └─► check_and_reward() → возможно +60 мин

[Перевод]   Отправитель ──► TransferView (POST /transfer/)
                 ├─ проверка: не себе, сумма 1…3600
                 ├─ проверка: общий дневной лимит 120/720 мин
                 ├─ проверка: баланс >= amount
                 ├─ atomic: отправитель −amount (+daily_spent), получатель +amount
                 └─ получателю → Notification «Вам поступил перевод»

[Отзыв]     Участник ──► AddReviewView ──► Review(1..10)
                 └─► сигнал: reputation получателя = round(avg)

[Награда]   Любой из трёх квестов ──► check_and_reward()
                 при 3/3 и первом за день → +60 мин, is_reward_claimed=True
```

---

## 7. Конфигурация и запуск

| Параметр | Значение (`server/settings.py`) |
|----------|--------------------------------|
| `INSTALLED_APPS` | `bounty`, `users` (+ Django-приложения) |
| `DATABASES` | SQLite: `BASE_DIR/db.sqlite3` |
| `TEMPLATES DIRS` | `BASE_DIR/templates` |
| `context_processors` | `request`, `media` (`{{ MEDIA_URL }}`), **`users.context_processors.unread_notifications`** (бейдж 🔔), `auth`, `messages` |
| `STATICFILES_DIRS` | `BASE_DIR/static` |
| `MEDIA_ROOT` | `BASE_DIR/media/` (аватары, видео) |
| `LOGIN_URL` | `login` |
| Frontend | Tailwind CSS (CDN); навигация — **левый сайдбар** на десктопе (`base.html`, `md:pl-60`) + мобильная шапка с пилюлями |

```bash
python manage.py migrate     # применить схему
python manage.py runserver   # запуск: http://127.0.0.1:8000/
```

### Видеообзор на странице «О нас»

- Файл: `media/videos/TimeShift_overview.mp4` (раздаётся в `DEBUG` через
  `static(settings.MEDIA_URL, ...)` в `server/urls.py`).
- Блок «🎬 TimeShift в движке» в `templates/users/about_us.html` (после
  герой-блока): карточка в стиле остальной страницы, градиентная линия,
  `<video controls preload="metadata" playsinline>` с
  `src="{{ MEDIA_URL }}videos/TimeShift_overview.mp4"` — плеер выглядит
  естественно на тёмном фоне.
- `{{ MEDIA_URL }}` доступен благодаря контекст-процессору
  `django.template.context_processors.media`.

---

## 8. Итог: где что искать

| Задача | Файл |
|--------|------|
| Экономика, квесты, репутация, уведомления | `users/models.py` |
| Задачи и договоры помощи | `bounty/models.py` |
| Закрытие задачи, лимиты, PRO | `bounty/views.py:76` (`CompleteTaskView`) |
| Тайм-кран | `users/views.py:30` (`CollectBonusView`) |
| Прямые переводы минут | `users/views.py` (`TransferView`) + маршрут `/transfer/` |
| Форма перевода (UI) | `templates/users/user_profile.html` (карточка «Перевести время») |
| Страница уведомлений | `templates/users/notifications.html` + `NotificationListView` (`/notifications/`) |
| Бейдж уведомлений | `users/context_processors.py` + 🔔 в `templates/base.html` |
| Левый сайдбар / навбар | `templates/base.html` (`<aside>`, активные пункты по `request.resolver_match`) |
| Перевод минут за помощь | `bounty/signals.py:7` (`process_help_contract`) |
| Уведомления подписчикам | `bounty/signals.py:30` (`notify_followers_on_new_task`) |
| Пересчёт репутации по отзывам | `users/models.py:122` (`update_user_reputation`) |
| Форматирование баланса | `users/models.py:38` (`formatted_balance`) |
| Видеообзор | `media/videos/TimeShift_overview.mp4` + `templates/users/about_us.html` |
| Маршруты | `server/urls.py`, `users/urls.py`, `bounty/urls.py` |
