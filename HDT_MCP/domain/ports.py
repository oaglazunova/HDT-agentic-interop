from typing import TypedDict, Literal, Optional, List

class WalkRecord(TypedDict):
    date: str              # "YYYY-MM-DD"
    steps: int
    distance_meters: Optional[float]
    duration: Optional[str]
    kcalories: Optional[float]

class DateRange(TypedDict):
    start: str   # "YYYY-MM-DD"
    end: str     # "YYYY-MM-DD"

class HLScore(TypedDict):
    domain: Literal["diabetes"]
    score: float           # 0..1
    sources: dict          # {"trivia": float, "sugarvita": float}
