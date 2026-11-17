from dataclasses import dataclass, field
from typing import Optional
from .shell import HEIGHTS, WIDTHS, default_strips


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
    revealed: set = field(default_factory=set)
    scroll: dict = field(default_factory=dict)
    popover: Optional[Popover] = None
    text: Optional[TextEdit] = None
    drag: Optional[tuple] = None
    hsv: tuple = (0.0, 0.0, 0.0)
    strips: dict = field(default_factory=default_strips)
    section_heights: dict = field(default_factory=lambda: dict(HEIGHTS))
    section_widths: dict = field(default_factory=lambda: dict(WIDTHS))
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
    gesture: list = None
    gizmo: tuple = ()
    shelf_query: str = ''
    shelf_scope: str = 'ALL'
    ghost: tuple = ()
    path_mode: str = ''
    path_points: list = field(default_factory=list)
    clone_source: tuple = None
    poly_erase: bool = False
    bake_pending: str = ''
    bake_since: float = 0.0
