from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    def contains(self, x, y):
        return self.x <= x <= self.x + self.w and self.y <= y <= self.y + self.h


@dataclass
class Control:
    key: str
    rect: Rect
    kind: str
    label: str = ''
    text: str = ''
    icon: str = ''
    active: bool = False
    value: float = 0.0
    color: Optional[Tuple[float, ...]] = None
    tip: str = ''
    shortcut: str = ''


@dataclass
class Layout:
    scale: float
    metrics: object
    controls: list = field(default_factory=list)
    cards: list = field(default_factory=list)
    tool_groups: list = field(default_factory=list)

    def add(self, key, rect, kind, **values):
        control = Control(key, rect, kind, **values)
        self.controls.append(control)
        return control

    def hit(self, x, y):
        return next((control for control in reversed(self.controls) if control.rect.contains(x, y)), None)

    def covers(self, x, y):
        return any(rect.contains(x, y) for rect, _ in self.cards) or any(rect.contains(x, y) for rect in self.tool_groups)
