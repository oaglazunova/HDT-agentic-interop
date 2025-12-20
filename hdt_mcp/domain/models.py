from __future__ import annotations
from typing import Literal, Optional, List, Dict
from pydantic import BaseModel, Field


class WalkRecord(BaseModel):
    date: str  # ISO date (YYYY-MM-DD or datetime string)
    steps: int = 0
    distance_meters: Optional[float] = None
    duration: Optional[str] = None
    kcalories: Optional[float] = None


class WalkStreamStats(BaseModel):
    days: int = 0
    total_steps: int = 0
    avg_steps: int = 0


class WalkStreamView(BaseModel):
    source: Literal["vault", "live"]
    records: List[WalkRecord] = Field(default_factory=list)
    stats: WalkStreamStats = WalkStreamStats()


class IntegratedView(BaseModel):
    user_id: int
    streams: Dict[str, Dict]  # keep generic to allow new streams later
    generated_at: int
