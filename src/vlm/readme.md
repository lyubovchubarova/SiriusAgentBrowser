## windows
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## linux 
```
python3 -m venv venv
source venv\bin\activate
pip3 install -r requirements.txt
```

Кстати под винду и линукс по разному создаётся венв  
(если вдруг винда + всл)

## создайте файл .env
```
YANDEX_GPT_API_TOKEN=<your-token>
YANDEX_CLOUD_FOLDER_ID=<your-folder-id>
```

## запуск
```cmd
python main.py
```
запускать обязательно из директории с env

## пример запроса от archestrator
```json
{
  "task": "Отправить мем с котиками другу в ВК",
  "steps": [
    {
      "step_id": 1,
      "action": "navigate",
      "description": "Перейти на страницу ВКонтакте",
      "expected_result": "Отобразится главная страница ВКонтакте или страница авторизации"
    },
    {
      "step_id": 2,
      "action": "click",
      "description": "Войти в аккаунт, если не авторизован",
      "expected_result": "Отобразится лента новостей или главная страница пользователя"
    },
    {
      "step_id": 3,
      "action": "click",
      "description": "Перейти в список друзей и выбрать друга для отправки мема",
      "expected_result": "Откроется страница выбранного друга"
    },
    {
      "step_id": 4,
      "action": "click",
      "description": "Открыть диалог с другом",
      "expected_result": "Откроется окно диалога с другом"
    },
    {
      "step_id": 5,
      "action": "navigate",
      "description": "Перейти на сайт с мемами и найти мем с котиками",
      "expected_result": "Найдётся мем с котиками на сайте"
    },
    {
      "step_id": 6,
      "action": "click",
      "description": "Скопировать ссылку на мем или скачать изображение",
      "expected_result": "Ссылка скопирована в буфер обмена или изображение скачано на устройство"
    },
    {
      "step_id": 7,
      "action": "click",
      "description": "Вернуться к диалогу с другом и вставить ссылку или прикрепить файл с мемом",
      "expected_result": "Мем будет готов к отправке в диалоге"
    },
    {
      "step_id": 8,
      "action": "click",
      "description": "Отправить мем другу",
      "expected_result": "Мем отправлен, в диалоге появится сообщение с мемом"
    }
  ],
  "estimated_time": 120
}

```

## взаимодействие с browser
```json
{
  "action": "screenshot",
  "path": "<your-path>"
}
```
```json
{
  "action": "open",
  "url": "<your-url>"
}
```
```json
{
  "action": "click",
  "id": "<your-bbox-id>"
}
```
```json
{
  "action": "type",
  "id": "<your-bbox-id>",
  "text": "<your-text>",
  "press_enter": bool
}
```
```json
{
  "action": "scroll",
  "delta_y": <your-value-int>
}
```