from typing import Literal

from pydantic import BaseModel, Field, model_validator

Action = Literal[
    "navigate",
    "click",
    "type",
    "scroll",
    "extract",
    "hover",
    "inspect",
    "wait",
    "finish",
    "search",
    "solve_captcha",
]


class Step(BaseModel):
    step_id: int = Field(..., ge=1)
    action: Action
    description: str = Field(..., min_length=3, max_length=200)
    expected_result: str = Field(..., min_length=3, max_length=200)


class Plan(BaseModel):
    reasoning: str = Field(..., description="Chain-of-thought reasoning for the plan")
    task: str = Field(..., min_length=3, max_length=200)
    steps: list[Step] = Field(..., min_length=0, max_length=10)  # <= 10 шагов
    estimated_time: int = Field(..., ge=1, le=60 * 60)  # seconds
    needs_vision: bool = Field(
        default=False,
        description="Set to true if DOM is insufficient and a screenshot is needed to plan.",
    )

    @model_validator(mode="after")
    def validate_steps(self) -> "Plan":
        ids = [s.step_id for s in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate step_id in steps")

        if not ids:
            return self

        sorted_ids = sorted(ids)
        start = sorted_ids[0]
        expected = list(range(start, start + len(self.steps)))

        if sorted_ids != expected:
            raise ValueError(
                f"step_id must be sequential without gaps (got {sorted_ids}, expected {expected})"
            )
        return self
