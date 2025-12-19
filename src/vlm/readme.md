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
```python
python main.py
```
запускать обязательно из директории с env