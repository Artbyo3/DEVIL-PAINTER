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
    setup_resolutions: dict = field(default_factory=dict)
    setup_udim: bool = True
    setup_template: str = 'PBR Metal Rough'
    setup_normal_format: str = 'OPENGL'
    setup_normal_space: str = 'TANGENT'
    setup_unwrap: str = 'SMART'
    channels_all: bool = False
    recent_colors: list = field(default_factory=list)
    picking: str = ''
    binding: str = ''
    multi: set = field(default_factory=set)
    clipboard: tuple = ()
    drop: tuple = ()
    geo_pick: str = ''
    bake_keys: set = field(default_factory=lambda: {'ao', 'curvature', 'thickness', 'position', 'world_normal', 'id'})
    bake_found: object = None
    poly_mode: str = ''
    poly_erase: bool = False
    bake_pending: str = ''
    bake_since: float = 0.0
