from typing import Literal

from pydantic import BaseModel, Field

Action = Literal["navigate", "click", "type", "scroll"]

class Step(BaseModel):
    step_id: int = Field(..., ge=1)
    action: Action
    description: str
    expected_result: str

class Plan(BaseModel):
    task: str
    steps: list[Step] = Field(..., min_length=1)
    estimated_time: int = Field(..., ge=1)  # seconds
