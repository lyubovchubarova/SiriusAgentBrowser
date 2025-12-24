# ruff: noqa: PTH100, PTH110, PTH117, PTH118, PTH120, PTH123
import datetime
import os.path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]

from .base import CalendarTool

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendarTool(CalendarTool):
    def __init__(
        self, credentials_path: str = "credentials.json", token_path: str = "token.json"
    ) -> None:
        # Use absolute paths relative to the project root if not provided
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
        self._authenticate()

    def name(self) -> str:
        return "google_calendar"

    def description(self) -> str:
        return (
            "Tool for interacting with Google Calendar (list, create, delete events)."
        )

    def _authenticate(self) -> None:
        """
        Authenticates with Google API using OAuth2.
        """
        # Check for mock mode first
        if os.environ.get("MOCK_CALENDAR", "false").lower() == "true":
            print("[GoogleCalendar] Mock mode enabled. Skipping authentication.")
            return

        creds = None
        # The file token.json stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)  # type: ignore[no-untyped-call]
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())  # type: ignore[no-untyped-call]
            else:
                if not os.path.exists(self.credentials_path):
                    print(
                        f"Warning: {self.credentials_path} not found. Calendar tool will not work."
                    )
                    return

                # Check if we are in a headless/server environment where we can't open a browser
                # For now, we'll just try to run the local server.
                # In a real production agent, we might need a different flow or pre-generated token.
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_path, SCOPES
                    )
                    # Use a fixed port to make it easier to authorize if needed, or 0 for random
                    creds = flow.run_local_server(port=0)
                except Exception as e:
                    print(f"Authentication failed: {e}")
                    return

            # Save the credentials for the next run
            with open(self.token_path, "w") as token:
                token.write(creds.to_json())

        self.service = build("calendar", "v3", credentials=creds)

    def list_events(
        self, start_time: datetime.datetime, end_time: datetime.datetime
    ) -> list[dict[str, Any]]:
        if not self.service:
            if os.environ.get("MOCK_CALENDAR", "false").lower() == "true":
                return [
                    {
                        "summary": "Mock Event",
                        "start": {"dateTime": start_time.isoformat()},
                    }
                ]
            return [{"error": "Not authenticated"}]

        try:
            events_result = (
                self.service.events()
                .list(
                    calendarId="primary",
                    timeMin=start_time.isoformat() + "Z",
                    timeMax=end_time.isoformat() + "Z",
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            events = events_result.get("items", [])
            return events
        except Exception as e:
            return [{"error": str(e)}]

    def create_event(
        self,
        summary: str,
        start_time: datetime.datetime,
        end_time: datetime.datetime,
        description: str | None = None,
    ) -> dict[str, Any]:
        if not self.service:
            # Fallback for testing/mocking if real auth fails but we want to simulate success
            # Remove this in production!
            if os.environ.get("MOCK_CALENDAR", "false").lower() == "true":
                print(f"[GoogleCalendar MOCK] Created event: {summary} at {start_time}")
                return {
                    "status": "created (mock)",
                    "event": {"summary": summary, "start": str(start_time)},
                }

            return {"error": "Not authenticated"}

        event = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": "UTC",
            },
        }

        try:
            event = (
                self.service.events().insert(calendarId="primary", body=event).execute()
            )
            print(f"[GoogleCalendar] Created event: {summary} at {start_time}")
            return {"status": "created", "event": event}
        except Exception as e:
            return {"error": str(e)}

    def delete_event(self, event_id: str) -> dict[str, Any]:
        if not self.service:
            return {"error": "Not authenticated"}

        try:
            self.service.events().delete(
                calendarId="primary", eventId=event_id
            ).execute()
            print(f"[GoogleCalendar] Deleted event: {event_id}")
            return {"status": "deleted", "eventId": event_id}
        except Exception as e:
            return {"error": str(e)}
