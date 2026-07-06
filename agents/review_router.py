from __future__ import annotations


ROUTE_GROUPS = {
    "rule": {"1", "3", "4", "6", "7", "14", "18"},
    "table": {"11", "12"},
    "attachment": {"2", "2-1", "15", "17"},
    "llm": {"5", "8", "9", "10", "13", "16"},
}


def route_item(item_no: str | int) -> str:
    normalized = str(item_no).strip()
    for route, items in ROUTE_GROUPS.items():
        if normalized in items:
            return route
    return "llm"
