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

    @property
    def top(self):
        return self.y + self.h


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
    second: float = 0.0
    color: Optional[Tuple[float, ...]] = None
    preview: object = None
    mask: object = None
    tip: str = ''
    shortcut: str = ''
    clip: Optional[Rect] = None
    caret: int = -1
    points: tuple = ()
    selected: bool = False

    def hit(self, x, y):
        return self.rect.contains(x, y) and (self.clip is None or self.clip.contains(x, y))


@dataclass
class Layout:
    scale: float
    metrics: object
    zones: object
    controls: list = field(default_factory=list)
    cards: list = field(default_factory=list)
    tool_groups: list = field(default_factory=list)
    dock: Optional[Rect] = None
    popover: Optional[Rect] = None
    popover_start: int = -1
    scroll_areas: dict = field(default_factory=dict)

    def add(self, key, rect, kind, **values):
        control = Control(key, rect, kind, **values)
        self.controls.append(control)
        return control

    def hit(self, x, y):
        return next((control for control in reversed(self.controls) if control.hit(x, y)), None)

    def covers(self, x, y):
        return ((self.popover is not None and self.popover.contains(x, y)) or any(rect.contains(x, y) for rect, _ in self.cards)
                or any(rect.contains(x, y) for rect in self.tool_groups) or (self.dock is not None and self.dock.contains(x, y)))

    def scroll_area(self, x, y):
        return next((key for key, (rect, _) in self.scroll_areas.items() if rect.contains(x, y)), None)
