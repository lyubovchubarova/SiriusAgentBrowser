from typing import Literal

from pydantic import BaseModel, Field, model_validator

Action = Literal["navigate", "click", "type", "scroll", "extract"]


class Step(BaseModel):
    step_id: int = Field(..., ge=1)
    action: Action
    description: str = Field(..., min_length=3, max_length=200)
    expected_result: str = Field(..., min_length=3, max_length=200)


class Plan(BaseModel):
    task: str = Field(..., min_length=3, max_length=200)
    steps: list[Step] = Field(..., min_length=1, max_length=10)  # <= 10 шагов
    estimated_time: int = Field(..., ge=1, le=60 * 60)  # seconds

    @model_validator(mode="after")
    def validate_steps(self) -> "Plan":
        ids = [s.step_id for s in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate step_id in steps")
        # требуем 1..n
        expected = list(range(1, len(self.steps) + 1))
        if sorted(ids) != expected:
            raise ValueError(f"step_id must be 1..{len(self.steps)} without gaps")
        return self
