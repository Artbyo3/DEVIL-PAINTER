from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Popover:
    kind: str
    anchor: object
    target: str = ''
    items: tuple = ()


@dataclass
class TextEdit:
    key: str
    text: str
    cursor: int


@dataclass
class WorkspaceState:
    resolution: int = 2048
    collapsed: set = field(default_factory=set)
    scroll: dict = field(default_factory=dict)
    popover: Optional[Popover] = None
    text: Optional[TextEdit] = None
    drag: Optional[tuple] = None
    hsv: tuple = (0.0, 0.0, 0.0)
    column_width: float = 330.0
    split: float = .5
    shelf_open: bool = True
    shelf_tab: str = 'MATERIALS'
    armed: str = ''
    view_2d: bool = False
    bake_keys: set = field(default_factory=lambda: {'ao', 'curvature', 'thickness', 'position', 'world_normal', 'id'})
