"""
Centralized constants to avoid string drift across the codebase.

Do NOT import this module inside tests to override values; these are fixed
identifiers used by the system and its policy configuration.
"""

# Policy lanes
LANE_ANALYTICS: str = "analytics"
LANE_MODELING: str = "modeling"
LANE_COACHING: str = "coaching"

__all__ = [
    "LANE_ANALYTICS",
    "LANE_MODELING",
    "LANE_COACHING",
]
