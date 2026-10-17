"""Rank Runkeeper activities by distance and duration within their activity type."""

from __future__ import annotations

from dataclasses import dataclass, field

from export_inspector.runkeeper.formatting import ordinal
from export_inspector.runkeeper.models import Activity


def rank_by_type(activities: list[Activity], metric: str) -> dict[int, int]:
    """Map each activity index to its rank (1 = longest) among activities of its type.

    `metric` is "distance"; anything else ranks by duration. Ties share a rank.
    """
    ranks: dict[int, int] = {}
    by_type: dict[str, list[Activity]] = {}
    for activity in activities:
        by_type.setdefault(activity.activity_type, []).append(activity)

    for group in by_type.values():
        if metric == "distance":
            values = [activity.distance_km for activity in group]
            for activity in group:
                ranks[activity.index] = 1 + sum(
                    value > activity.distance_km for value in values
                )
        else:
            values = [activity.duration_seconds for activity in group]
            for activity in group:
                ranks[activity.index] = 1 + sum(
                    value > activity.duration_seconds for value in values
                )
    return ranks


@dataclass
class ActivityRanks:
    """Distance and duration ranks per activity index, with their display labels."""

    distance: dict[int, int] = field(default_factory=dict)
    duration: dict[int, int] = field(default_factory=dict)

    @classmethod
    def from_activities(cls, activities: list[Activity]) -> ActivityRanks:
        return cls(rank_by_type(activities, "distance"), rank_by_type(activities, "duration"))

    def distance_label(self, activity: Activity) -> str:
        """E.g. "2nd longest Running distance", or "unranked … distance"."""
        rank = self.distance.get(activity.index)
        if rank is None:
            return f"unranked {activity.activity_type} distance"
        return f"{ordinal(rank)} longest {activity.activity_type} distance"

    def duration_label(self, activity: Activity) -> str:
        """E.g. "1st longest Cycling duration", or "unranked … duration"."""
        rank = self.duration.get(activity.index)
        if rank is None:
            return f"unranked {activity.activity_type} duration"
        return f"{ordinal(rank)} longest {activity.activity_type} duration"
