import json
import os
from pathlib import Path
from typing import List, Dict, Any
from urllib.parse import urlparse
import difflib

class LongTermMemory:
    def __init__(self, storage_path: str = "memory_db.json"):
        self.storage_path = Path(storage_path)
        self.data = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        if not self.storage_path.exists():
            return []
        try:
            return json.loads(self.storage_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Failed to load memory: {e}")
            return []

    def _save(self):
        try:
            self.storage_path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), 
                encoding="utf-8"
            )
        except Exception as e:
            print(f"Failed to save memory: {e}")

    def get_domain(self, url: str) -> str:
        try:
            return urlparse(url).netloc.replace("www.", "")
        except:
            return ""

    def add_experience(self, url: str, task: str, plan_steps: List[Dict[str, Any]]):
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
            "timestamp": time.time()
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
        domain = self.get_domain(url)
        relevant_entries = [e for e in self.data if e["domain"] == domain]
        
        if not relevant_entries:
            return ""

        # Find most similar task
        best_match = None
        best_ratio = 0.0
        
        for entry in relevant_entries:
            ratio = difflib.SequenceMatcher(None, current_task.lower(), entry["task"].lower()).ratio()
            if ratio > 0.5 and ratio > best_ratio: # Threshold
                best_ratio = ratio
                best_match = entry

        if best_match:
            steps_summary = "\n".join([f"- {s.get('action')} {s.get('description')}" for s in best_match["steps"]])
            return f"MEMORY RECALL: You have successfully completed a similar task '{best_match['task']}' on this domain before.\nSuccessful steps were:\n{steps_summary}\nUse this as a guide."
        
        return ""

import time
