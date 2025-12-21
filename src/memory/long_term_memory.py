import difflib
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class LongTermMemory:
    def __init__(self, storage_path: str = "memory_db.json"):
        self.storage_path = Path(storage_path)
        self.data = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if not self.storage_path.exists():
            return []
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            print(f"Failed to load memory: {e}")
            return []

    def _save(self) -> None:
        try:
            self.storage_path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            print(f"Failed to save memory: {e}")

    def get_domain(self, url: str) -> str:
        try:
            return urlparse(url).netloc.replace("www.", "")
        except Exception:
            return ""

    def add_experience(
        self, url: str, task: str, plan_steps: list[dict[str, Any]]
    ) -> None:
        """
        Saves a successful experience.
        """
        domain = self.get_domain(url)
        if not domain:
            return

        entry = {
            "domain": domain,
            "task": task,
            "steps": plan_steps,
            "timestamp": time.time(),
        }

        # Check for duplicates (simplified)
        for existing in self.data:
            if existing["domain"] == domain and existing["task"] == task:
                # Update existing
                existing["steps"] = plan_steps
                existing["timestamp"] = time.time()
                self._save()
                return

        self.data.append(entry)
        self._save()

    def retrieve_relevant(self, url: str, current_task: str) -> str:
        """
        Returns a string representation of relevant past experiences.
        """
        # 1. Check for exact domain match
        domain = self.get_domain(url)
        relevant_entries = [e for e in self.data if e["domain"] == domain]

        # 2. Check for global task similarity (even if domain is different, maybe we know the URL)
        # For example, if task is "open youtube", we might have a memory with domain "youtube.com"

        best_match = None
        best_ratio = 0.0

        # Search in domain-specific entries first
        for entry in relevant_entries:
            ratio = difflib.SequenceMatcher(
                None, current_task.lower(), entry["task"].lower()
            ).ratio()
            if ratio > 0.5 and ratio > best_ratio:
                best_ratio = ratio
                best_match = entry

        # If no domain match, search globally (e.g. to find the URL for a task)
        if not best_match:
            for entry in self.data:
                ratio = difflib.SequenceMatcher(
                    None, current_task.lower(), entry["task"].lower()
                ).ratio()
                if ratio > 0.6 and ratio > best_ratio:
                    best_ratio = ratio
                    best_match = entry

        if best_match:
            steps_summary = "\n".join(
                [
                    f"- {s.get('action')} {s.get('description')}"
                    for s in best_match["steps"]
                ]
            )
            return f"MEMORY RECALL: You have successfully completed a similar task '{best_match['task']}' (Domain: {best_match['domain']}).\nSuccessful steps were:\n{steps_summary}\nUse this as a guide. If the task implies navigating to this domain, you can start by navigating to 'https://{best_match['domain']}'."

        return ""
