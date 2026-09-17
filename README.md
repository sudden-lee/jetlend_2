# Тестовая задача 2: импорт рассылок

Django management command импортирует рассылки из XLSX-файла в базу данных,
вторая команда имитирует их отправку: пауза 5-20 секунд и запись в лог вместо
реального письма. Повторный импорт того же файла не создаёт дубли: за это
отвечает `external_id`. Django admin показывает очередь в режиме только для
чтения.

Python 3.10+, Django 5.2 LTS, SQLite, openpyxl.

## Быстрый запуск

Все команды выполняются из каталога `task2`.

Linux/macOS:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Создать таблицу, импортировать пример и отправить очередь:

```sh
python manage.py migrate
python manage.py import_mailings examples/mailings.xlsx
python manage.py send_mailings
```

В PowerShell замените `python` на `./.venv/Scripts/python.exe`.

Пример содержит два вымышленных адреса. Первый импорт выводит:

```text
Обработано: 2; создано: 2; пропущено: 0; ошибочных строк: 0
```

Повторный импорт того же файла создаёт 0 записей и пропускает 2. Отправка двух
писем занимает суммарно 10-40 секунд (случайная задержка 5-20 с на письмо).

Для доступа к админке:

```sh
python manage.py createsuperuser
python manage.py runserver
```

Админка доступна на `http://127.0.0.1:8000/admin/`.

## Формат XLSX

Обрабатывается первый лист. Первая строка - заголовки, порядок произвольный,
лишние колонки игнорируются.

| Колонка | Правила |
|---|---|
| `external_id` | Непустое значение, ключ идемпотентности повторного импорта |
| `user_id` | Положительное целое число |
| `email` | Валидный email-адрес |
| `subject` | Непустая тема письма (до 255 символов) |
| `message` | Непустой текст письма |

Полностью пустые строки не входят в статистику. Строка с невалидным значением
увеличивает счётчик ошибок и не создаёт запись - остальные строки файла
импортируются как обычно. Среди повторов одного `external_id` в пределах
файла или между запусками побеждает первая когда-либо сохранённая запись.

## Команды

```sh
python manage.py import_mailings /path/to/file.xlsx
python manage.py send_mailings
```

`import_mailings` печатает `processed/created/skipped/errors` и завершается
ненулевым кодом, если файл не удалось прочитать. `send_mailings` отправляет
все письма со статусом `pending`: успешные помечаются `sent`, письма с ошибкой
транспорта - `failed` с текстом ошибки в `last_error`. Содержимое письма
(email, тема, текст) никогда не попадает в лог. Ошибка базы данных в любой из
команд превращается в понятный `CommandError`, а не в сырой traceback.

## Тесты

Тесты написаны на pytest (`pytest-django`), а не на `manage.py test`.

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
python -m ruff check .
python -m ruff format --check .
```
