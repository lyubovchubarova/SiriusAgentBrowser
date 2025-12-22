# Интеграция с Productivity-сервисами

## 1. Календарь (Google Calendar)

### Сценарии использования
1. **Создание встречи:** "Запланируй встречу с Максимом на завтра в 14:00"
2. **Просмотр расписания:** "Что у меня запланировано на сегодня?"
3. **Поиск свободного слота:** "Найди свободное время для звонка в пятницу"
4. **Напоминания:** "Поставь напоминание 'Купить молоко' на 18:00"

### Техническая реализация
- **API:** Google Calendar API v3
- **Библиотеки:** `google-auth`, `google-auth-oauthlib`, `google-auth-httplib2`, `google-api-python-client`
- **Аутентификация:** OAuth 2.0 (требуется `credentials.json` и получение `token.json` при первом входе)

### Необходимые методы
- `list_events(time_min, time_max, max_results)`
- `create_event(summary, start_time, end_time, description, attendees)`
- `delete_event(event_id)`
- `update_event(event_id, ...)`

---

## 2. Заметки и Документы (Notion / Google Docs)

### Сценарии использования
1. **Сохранение ресерча:** "Найди информацию про Python 3.12 и сохрани краткую выжимку в Notion"
2. **Ведение списка задач:** "Добавь 'Изучить Playwright' в мой список задач в Notion"
3. **Создание документа:** "Создай Google Doc с планом поездки"
4. **Логирование:** "Записывай все найденные ссылки по теме X в отдельную страницу"

### Техническая реализация (Notion)
- **API:** Notion API (REST)
- **Библиотеки:** `notion-client`
- **Аутентификация:** Internal Integration Token (Secret Key) + Sharing pages with the integration bot.
- **Структура:** Работа с Pages и Blocks.

### Техническая реализация (Google Docs)
- **API:** Google Docs API v1
- **Библиотеки:** Те же, что и для Calendar (`google-api-python-client`)
- **Аутентификация:** OAuth 2.0

### Необходимые методы (Notion)
- `create_page(parent_id, title, content_blocks)`
- `append_block_children(block_id, children)`
- `search(query)` - для поиска страниц, куда добавлять контент

---

## 3. Архитектура интеграции

Предлагается создать абстрактные базовые классы для инструментов, чтобы можно было легко менять провайдеров (например, Google Calendar -> Outlook, Notion -> Obsidian).

### Структура классов
- `BaseTool` (abstract)
  - `CalendarTool` (abstract) -> `GoogleCalendarTool`
  - `NotesTool` (abstract) -> `NotionTool`, `GoogleDocsTool`

### Интеграция с Агентом
1. **Planner:** Должен уметь генерировать действия типа `calendar_add`, `notes_create`.
2. **Orchestrator:** Должен распознавать эти действия и перенаправлять их соответствующему инструменту в `src/tools/`.
3. **Context:** Инструменты должны иметь доступ к результатам предыдущих шагов (например, текст для сохранения в заметку берется из `last_step_result`).
