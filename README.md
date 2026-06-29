# bl-blog-autopilot

Автоматическое наполнение блога [Bratec Lis School](https://www.bl-school.com/blog/) статьями по визуальным искусствам.

## Быстрый старт

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # заполните WP_USER и WP_APP_PASSWORD
```

### Тест: загрузить статью из RSS

```bash
python run.py fetch
```

### Перевод через DeepSeek

```bash
python run.py translate --article data/pending/YYYYMMDD_HHMMSS/article.json
```

Ключ API — в `.env` (`DEEPSEEK_API_KEY`). Перевод: **`deepseek-v4-pro`** (живой стиль); категории: `deepseek-v4-flash`.

### Публикация

```bash
python run.py publish ^
  --article data/pending/YYYYMMDD_HHMMSS/article.json ^
  --body-file data/pending/YYYYMMDD_HHMMSS/body_ru.html ^
  --excerpt "Краткое вступление для каталога"
```

Или положите `meta.json` рядом с `article.json` — поля `title_ru` и `excerpt_ru` подтянутся автоматически.

На `/blog/` показывается только вступление, полный текст — по клику «Continue reading». Скрипт вставляет тег `<!--more-->` как на остальных постах сайта.

## WordPress: Application Password

1. Войдите в админку: `https://www.bl-school.com/blog/wp-admin`
2. Пользователи → Профиль
3. Пароли приложений → создать → скопировать в `.env`

## Источники

Настраиваются в `config/sources.yaml` — RSS-ленты с ротацией по дням недели:

| Источник | Регион | Темы |
|----------|--------|------|
| It's Nice That | intl | иллюстрация, коммерция |
| Creative Boom | intl | иллюстрация, живопись |
| Colossal | intl | выставки, художники |
| Hyperallergic | intl | новости искусства |
| Illustration Age | intl | книжная иллюстрация |
| Juxtapoz | intl | живопись, street art |
| Didatticarte, Roba da Disegnatori, Artribune | 🇮🇹 | история искусства, иллюстрация |
| Connaissance des Arts, Paris Art | 🇫🇷 | музеи, выставки |
| Spoon & Tamago, Design Made in Japan, Japan Forward | 🇯🇵 | дизайн, культура |
| Design By Korea, Artist Jungsoon | 🇰🇷 | корейский дизайн, иллюстрация |
| ArtAsiaPacific | asia | современное искусство Азии |
| Cartoon Brew, PRINT, Booooooom, Artnet… | intl | иллюстрация, арт-новости |

Полный список — в `config/sources.yaml` (26 источников). Регион `region` — справочно; ротация по `weekdays`.

## Cursor Automation

Инструкции для расписания — в [AUTOMATION.md](AUTOMATION.md).

Рекомендуемый триггер: **cron** `0 10 * * 1-5` (пн–пт в 10:00).

Секреты в Cloud Agents dashboard:
- `WP_URL`
- `WP_USER`
- `WP_APP_PASSWORD`
- `WP_POST_STATUS` (`draft` на старте)
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_TRANSLATE_MODEL` (по умолчанию `deepseek-v4-pro`)
- `DEEPSEEK_CATEGORIZE_MODEL` (по умолчанию `deepseek-v4-flash`)

## Стоп-темы

Файл `config/stop_topics.yaml` — статьи с этими темами **не скачиваются и не публикуются**:

- ЛГБТ
- политика
- войны
- межнациональная неприязнь
- порнография

Пропущенные URL записываются в `data/skipped.json`. Проверка вручную:

```bash
python run.py check --title "Заголовок" --body-file path/to/body.html
```

## Структура

```
config/sources.yaml    — RSS-источники
config/categories.yaml — темы блога (ключи → ID WordPress)
data/published.json    — журнал опубликованного (без дублей)
src/fetch_article.py   — скачивание статьи и картинок
src/translate.py       — перевод через DeepSeek API
src/categories.py      — умное присвоение тем WordPress
src/publish_post.py    — публикация в WordPress REST API
run.py                 — CLI
```

## Авторские права

Скрипт скачивает материалы для **пересказа**, не для копипаста. Агент должен переписывать текст; в посте всегда есть ссылка на источник.
