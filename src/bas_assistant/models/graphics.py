"""Graphics model - structured graphics definitions."""


from pydantic import BaseModel, Field

from . import NonEmptyStr


class GraphicElement(BaseModel):
    """A graphic element (shape, text, symbol)."""

    element_type: str = Field(description="rect, circle, ellipse, line, text, symbol, image")
    x: float = Field(description="Normalized X position 0-1")
    y: float = Field(description="Normalized Y position 0-1")
    width: float = Field(default=0, description="Normalized width 0-1")
    height: float = Field(default=0, description="Normalized height 0-1")
    rotation: float = Field(default=0, description="Rotation in degrees")
    fill: str | None = None
    stroke: str | None = None
    stroke_width: float = 1
    text: str | None = None
    font_size: float = 12
    font_family: str = "Arial"
    symbol_name: str | None = None
    layer: str = "default"


class GraphicBinding(BaseModel):
    """Point binding on a graphic."""

    point_name: NonEmptyStr
    binding_type: str = Field(description="value, setpoint, status, alarm, trend, override, command")
    x: float = Field(description="Normalized X position 0-1")
    y: float = Field(description="Normalized Y position 0-1")
    label: str | None = None
    format: str | None = None
    color_map: dict | None = None
    min_max: tuple[float, float] | None = None


class GraphicNavigation(BaseModel):
    """Navigation link to another graphic."""

    target_graphic_id: NonEmptyStr
    label: str
    x: float
    y: float
    width: float = 0.1
    height: float = 0.05


class GraphicDefinition(BaseModel):
    """Complete graphic definition."""

    graphic_id: NonEmptyStr
    name: str
    graphic_type: str = Field(description="equipment, system, floor_plan, riser, schematic, dashboard, alarm, trend")
    equipment_id: NonEmptyStr | None = None
    width: int = 1200
    height: int = 800
    background: str = "white"
    elements: list[GraphicElement] = Field(default_factory=list)
    bindings: list[GraphicBinding] = Field(default_factory=list)
    navigation: list[GraphicNavigation] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


__all__ = ["GraphicBinding", "GraphicDefinition", "GraphicElement", "GraphicNavigation"]
