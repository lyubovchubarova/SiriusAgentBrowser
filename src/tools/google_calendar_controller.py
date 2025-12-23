"""
GoogleCalendarController - высокоуровневый класс для управления Google Calendar.
Похож на BrowserController, но работает с календарём.
Предоставляет методы для создания/удаления встреч, переключения между днями и т.д.
"""

import datetime
import os
import os.path
from typing import Any, Optional, Callable
import webbrowser

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendarController:
    """
    Высокоуровневый контроллер для Google Calendar.
    Предоставляет методы типа create_event, delete_event, list_events_for_date и т.д.
    Может открывать календарь в браузере для визуального отображения.
    """

    def __init__(
        self,
        credentials_path: str = "credentials.json",
        token_path: str = "token.json",
        browser_navigate_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Инициализирует контроллер календаря.
        
        Args:
            credentials_path: Путь к credentials.json (от корня проекта).
            token_path: Путь к token.json (от корня проекта).
            browser_navigate_callback: Функция для навигации в браузере (для открытия календаря).
        """
        # Используем абсолютные пути относительно корня проекта
        base_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

        if not os.path.isabs(credentials_path):
            self.credentials_path = os.path.join(base_dir, credentials_path)
        else:
            self.credentials_path = credentials_path

        if not os.path.isabs(token_path):
            self.token_path = os.path.join(base_dir, token_path)
        else:
            self.token_path = token_path

        self.service = None
        self._current_date = datetime.date.today()
        self._browser_navigate = browser_navigate_callback

        # Detect local timezone name (IANA) and tzinfo object for correct times
        self._timezone = self._detect_timezone_name()
        self._local_tz = datetime.datetime.now().astimezone().tzinfo
        # Default event offset in minutes (e.g., 120 to schedule 2 hours later)
        try:
            self._event_offset_minutes = int(
                os.environ.get("CALENDAR_EVENT_OFFSET_MINUTES", "0").strip()
            )
        except Exception:
            self._event_offset_minutes = 0
        self._authenticate()

    def _apply_default_offset(
        self, dt: Optional[datetime.datetime]
    ) -> Optional[datetime.datetime]:
        """Apply default event offset (in minutes) to provided datetime.
        Returns the same value if dt is None or offset is 0.
        """
        if dt is None:
            return None
        if not self._event_offset_minutes:
            return dt
        return dt + datetime.timedelta(minutes=self._event_offset_minutes)

    def _authenticate(self) -> None:
        """
        Аутентификация с Google API через OAuth2.
        """
        # Проверка режима эмуляции
        if os.environ.get("MOCK_CALENDAR", "false").lower() == "true":
            print("[GoogleCalendarController] Mock mode enabled. Skipping auth.")
            return

        creds = None

        # Попытка загрузить сохранённые учётные данные
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)

        # Если учётные данные отсутствуют или невалидны
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_path):
                    print(
                        f"[GoogleCalendarController] Warning: {self.credentials_path} not found. "
                        "Calendar will not work. Get credentials from Google Cloud Console."
                    )
                    return

                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_path, SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                except Exception as e:
                    print(f"[GoogleCalendarController] Auth failed: {e}")
                    return

            # Сохраняем учётные данные для следующего запуска
            with open(self.token_path, "w") as token_file:
                token_file.write(creds.to_json())

        self.service = build("calendar", "v3", credentials=creds)
        print("[GoogleCalendarController] Successfully authenticated with Google Calendar.")

    def _detect_timezone_name(self) -> str:
        """Best-effort detection of local IANA timezone name.
        Priority: env CALENDAR_TIMEZONE -> /etc/timezone -> /etc/localtime symlink -> 'UTC'.
        """
        tz_env = os.environ.get("CALENDAR_TIMEZONE")
        if tz_env:
            return tz_env.strip()
        try:
            tz_file = "/etc/timezone"
            if os.path.exists(tz_file):
                with open(tz_file, "r", encoding="utf-8") as f:
                    val = f.read().strip()
                    if val:
                        return val
        except Exception:
            pass
        try:
            lt = "/etc/localtime"
            if os.path.islink(lt):
                target = os.readlink(lt)
                # e.g., /usr/share/zoneinfo/Europe/Moscow
                parts = target.split("zoneinfo/")
                if len(parts) == 2:
                    return parts[1]
        except Exception:
            pass
        return "UTC"

    def _ensure_local(self, dt: datetime.datetime) -> datetime.datetime:
        """Ensure datetime is timezone-aware in local timezone.
        If naive, interpret as local time (not UTC).
        """
        if dt.tzinfo is None:
            # Interpret naive datetime as local time
            return dt.astimezone()
        return dt

    def create_event(
        self,
        summary: str,
        start_time: datetime.datetime,
        end_time: datetime.datetime,
        description: str = "",
        guests: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """
        Создаёт новую встречу в календаре.
        
        Args:
            summary: Название встречи.
            start_time: Начало встречи (datetime).
            end_time: Конец встречи (datetime).
            description: Описание встречи.
            guests: Список email адресов приглашённых.
            
        Returns:
            Словарь с информацией о созданной встречи или ошибкой.
        """
        # Локализуем сначала, затем применяем offset
        start_time = self._ensure_local(start_time)
        end_time = self._ensure_local(end_time)
        start_time = self._apply_default_offset(start_time)
        end_time = self._apply_default_offset(end_time)
        
        # Если end_time раньше start_time, добавляем 1 день к end_time
        if end_time <= start_time:
            end_time = end_time + datetime.timedelta(days=1)

        if not self.service:
            if os.environ.get("MOCK_CALENDAR", "false").lower() == "true":
                event_id = f"mock_{int(datetime.datetime.now().timestamp())}"
                print(
                    f"[GoogleCalendarController MOCK] Created event: {summary} "
                    f"at {start_time} - {end_time}"
                )
                # Открываем календарь на дату события
                self.open_calendar()
                return {
                    "status": "success",
                    "message": f"Event '{summary}' created successfully (mock mode)",
                    "event_id": event_id,
                    "event": {
                        "id": event_id,
                        "summary": summary,
                        "start": {"dateTime": self._ensure_local(start_time).isoformat()},
                        "end": {"dateTime": self._ensure_local(end_time).isoformat()},
                    },
                }
            return {"status": "error", "message": "Not authenticated"}

        try:
            start_local = start_time
            end_local = end_time
            event = {
                "summary": summary,
                "description": description,
                "start": {
                    "dateTime": start_local.isoformat(),
                    "timeZone": self._timezone,
                },
                "end": {
                    "dateTime": end_local.isoformat(),
                    "timeZone": self._timezone,
                },
            }

            if guests:
                event["attendees"] = [{"email": guest} for guest in guests]

            created_event = (
                self.service.events().insert(calendarId="primary", body=event).execute()
            )

            print(
                f"[GoogleCalendarController] Created event: {summary} "
                f"at {start_time} - {end_time}"
            )
            # Открываем главную страницу календаря
            self.open_calendar()
            
            return {
                "status": "success",
                "message": f"Event '{summary}' created successfully",
                "event_id": created_event["id"],
                "event": created_event,
            }
        except Exception as e:
            error_msg = str(e)
            print(f"[GoogleCalendarController] Error creating event: {error_msg}")
            return {"status": "error", "message": error_msg}

    def delete_event(self, event_id: str) -> dict[str, Any]:
        """
        Удаляет встречу из календаря.
        
        Args:
            event_id: ID встречи для удаления.
            
        Returns:
            Словарь со статусом операции.
        """
        if not self.service:
            if os.environ.get("MOCK_CALENDAR", "false").lower() == "true":
                print(f"[GoogleCalendarController MOCK] Deleted event: {event_id}")
                self._open_calendar_default()
                return {
                    "status": "success",
                    "message": f"Event {event_id} deleted successfully (mock mode)",
                }
            return {"status": "error", "message": "Not authenticated"}

        try:
            self.service.events().delete(calendarId="primary", eventId=event_id).execute()
            print(f"[GoogleCalendarController] Deleted event: {event_id}")
            self._open_calendar_default()
            return {
                "status": "success",
                "message": f"Event {event_id} deleted successfully",
            }
        except Exception as e:
            error_msg = str(e)
            print(f"[GoogleCalendarController] Error deleting event: {error_msg}")
            return {"status": "error", "message": error_msg}

    def list_events_for_date(self, date: Optional[datetime.date] = None) -> dict[str, Any]:
        """
        Возвращает список встреч для указанной даты (или текущей).
        
        Args:
            date: Дата для поиска встреч (если None, используется текущая дата).
            
        Returns:
            Словарь с информацией о встречах.
        """
        if date is None:
            date = self._current_date

        # Определяем начало и конец дня в локальной таймзоне
        start_of_day = datetime.datetime.combine(date, datetime.time.min).replace(tzinfo=self._local_tz)
        end_of_day = datetime.datetime.combine(date, datetime.time.max).replace(tzinfo=self._local_tz)

        if not self.service:
            if os.environ.get("MOCK_CALENDAR", "false").lower() == "true":
                print(
                    f"[GoogleCalendarController MOCK] Listed events for {date}"
                )
                return {
                    "status": "success",
                    "date": date.isoformat(),
                    "events": [
                        {
                            "id": "mock_1",
                            "summary": "Mock Meeting",
                            "start": {"dateTime": start_of_day.isoformat()},
                            "end": {
                                "dateTime": (
                                    start_of_day + datetime.timedelta(hours=1)
                                ).isoformat()
                            },
                        }
                    ],
                }
            return {"status": "error", "message": "Not authenticated"}

        try:
            events_result = (
                self.service.events()
                .list(
                    calendarId="primary",
                    timeMin=start_of_day.isoformat(),
                    timeMax=end_of_day.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = events_result.get("items", [])
            print(f"[GoogleCalendarController] Listed {len(events)} events for {date}")
            self._open_calendar_default(date)
            return {
                "status": "success",
                "date": date.isoformat(),
                "events": events,
            }
        except Exception as e:
            error_msg = str(e)
            print(f"[GoogleCalendarController] Error listing events: {error_msg}")
            return {"status": "error", "message": error_msg}

    def set_date(self, date: datetime.date) -> dict[str, Any]:
        """
        Переключается на указанную дату (устанавливает текущую дату для работы).
        
        Args:
            date: Новая дата.
            
        Returns:
            Словарь со статусом и информацией о встречах на эту дату.
        """
        self._current_date = date
        self._open_calendar_default(date)
        print(f"[GoogleCalendarController] Switched to date: {date}")

        # Возвращаем встречи на новую дату
        return self.list_events_for_date(date)

    def get_current_date(self) -> dict[str, Any]:
        """
        Возвращает текущую установленную дату контроллера.
        
        Returns:
            Словарь с информацией о текущей дате и встречах на неё.
        """
        self._open_calendar_default(self._current_date)
        return {
            "status": "success",
            "current_date": self._current_date.isoformat(),
            "events": self.list_events_for_date(self._current_date).get("events", []),
        }

    def update_event(
        self,
        event_id: str,
        summary: Optional[str] = None,
        start_time: Optional[datetime.datetime] = None,
        end_time: Optional[datetime.datetime] = None,
        description: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Обновляет существующую встречу.
        
        Args:
            event_id: ID встречи для обновления.
            summary: Новое название (опционально).
            start_time: Новое время начала (опционально).
            end_time: Новое время конца (опционально).
            description: Новое описание (опционально).
            
        Returns:
            Словарь со статусом операции.
        """
        if not self.service:
            if os.environ.get("MOCK_CALENDAR", "false").lower() == "true":
                print(f"[GoogleCalendarController MOCK] Updated event: {event_id}")
                return {
                    "status": "success",
                    "message": f"Event {event_id} updated successfully (mock mode)",
                }
            return {"status": "error", "message": "Not authenticated"}

        try:
            # Получаем текущее событие
            event = self.service.events().get(calendarId="primary", eventId=event_id).execute()

            # Обновляем поля
            if summary:
                event["summary"] = summary
            if start_time:
                start_time = self._apply_default_offset(start_time)
                start_local = self._ensure_local(start_time)
                event["start"] = {
                    "dateTime": start_local.isoformat(),
                    "timeZone": self._timezone,
                }
            if end_time:
                end_time = self._apply_default_offset(end_time)
                end_local = self._ensure_local(end_time)
                event["end"] = {
                    "dateTime": end_local.isoformat(),
                    "timeZone": self._timezone,
                }
            if description:
                event["description"] = description

            # Сохраняем изменения
            updated_event = (
                self.service.events().update(calendarId="primary", eventId=event_id, body=event).execute()
            )

            print(f"[GoogleCalendarController] Updated event: {event_id}")
            # Открываем календарь на дату начала события, если она есть, иначе текущая дата
            target_date = start_time.date() if start_time else self._current_date
            self._open_calendar_default(target_date)
            return {
                "status": "success",
                "message": f"Event {event_id} updated successfully",
                "event": updated_event,
            }
        except Exception as e:
            error_msg = str(e)
            print(f"[GoogleCalendarController] Error updating event: {error_msg}")
            return {"status": "error", "message": error_msg}

    def open_calendar(self, date: Optional[datetime.date] = None) -> dict[str, Any]:
        """
        Открывает главную страницу Google Calendar в браузере.
        
        Args:
            date: Не используется, оставлено для обратной совместимости.
            
        Returns:
            Словарь с статусом операции.
        """
        # Главная страница, на которой календарь уже отображается
        calendar_url = "https://calendar.google.com/calendar/u/0/r"

        if self._browser_navigate:
            try:
                self._browser_navigate(calendar_url)
                print(f"[GoogleCalendarController] Opened calendar: {calendar_url}")
                return {
                    "status": "success",
                    "message": "Calendar opened",
                    "url": calendar_url,
                }
            except Exception as e:
                error_msg = str(e)
                print(f"[GoogleCalendarController] Error opening calendar: {error_msg}")
                return {"status": "error", "message": f"Failed to open calendar: {error_msg}"}
        else:
            # Если callback не установлен, пробуем открыть системный браузер
            try:
                opened = webbrowser.open(calendar_url)
                print(f"[GoogleCalendarController] Opened calendar via webbrowser: {calendar_url}")
                return {
                    "status": "success" if opened else "info",
                    "message": "Calendar opened" if opened else "Tried to open calendar; check default browser.",
                    "url": calendar_url,
                }
            except Exception as e:
                error_msg = str(e)
                print(f"[GoogleCalendarController] Error opening calendar via webbrowser: {error_msg}")
                return {
                    "status": "error",
                    "message": f"Failed to open calendar: {error_msg}",
                    "url": calendar_url,
                }

    def close(self) -> None:
        """Завершает работу контроллера (очистка ресурсов)."""
        self.service = None
        print("[GoogleCalendarController] Closed.")
