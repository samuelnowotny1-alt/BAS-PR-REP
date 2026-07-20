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


class IsometricAssetAnchor(BaseModel):
    """Named connection or placement anchor for a reusable asset."""

    key: NonEmptyStr
    x: float = Field(description="Normalized X position 0-1")
    y: float = Field(description="Normalized Y position 0-1")
    role: str = Field(
        default="connection",
        description="connection, airflow_inlet, airflow_outlet, pipe_inlet, pipe_outlet, point_bind, label",
    )
    description: str | None = None


class IsometricAssetBindingTarget(BaseModel):
    """Point-binding target inside an isometric asset."""

    key: NonEmptyStr
    component: NonEmptyStr = Field(description="Logical component this target represents")
    binding_types: list[str] = Field(default_factory=list, description="value, status, command, setpoint, alarm, trend")
    preferred_point_kinds: list[str] = Field(default_factory=list, description="sensor, status, actuator, setpoint, alarm")
    anchor_key: NonEmptyStr
    description: str | None = None


class AssetVisualReference(BaseModel):
    """Public visual reference used to ground an isometric asset in real equipment."""

    source: NonEmptyStr
    label: NonEmptyStr
    reference_url: NonEmptyStr
    notes: str = ""


class IsometricAssetDefinition(BaseModel):
    """Reusable isometric asset definition for realistic equipment graphics."""

    asset_id: NonEmptyStr
    label: str
    category: str = Field(description="ahu, duct, fan, coil, damper, valve, terminal, piping, accessory")
    variant: str | None = None
    description: str = ""
    width: int = 240
    height: int = 160
    tags: list[str] = Field(default_factory=list)
    compatible_equipment_types: list[str] = Field(default_factory=list)
    anchor_points: list[IsometricAssetAnchor] = Field(default_factory=list)
    binding_targets: list[IsometricAssetBindingTarget] = Field(default_factory=list)
    preview_svg: str = Field(default="", description="Asset preview used by the library UI")
    visual_references: list[AssetVisualReference] = Field(default_factory=list)


def default_isometric_asset_library() -> list[IsometricAssetDefinition]:
    """Return the built-in isometric asset catalog."""

    library = [
        IsometricAssetDefinition(
            asset_id="ahu_drawthrough_doubledeck",
            label="AHU Draw-Through Cabinet",
            category="ahu",
            variant="double_deck",
            description="Primary air-handler cabinet with filter, coil, fan, and discharge section anchors.",
            compatible_equipment_types=["AHU", "RTU", "MAU"],
            tags=["cabinet", "supply", "draw-through", "main-unit"],
            anchor_points=[
                IsometricAssetAnchor(key="air_inlet", x=0.04, y=0.52, role="airflow_inlet", description="Outside or mixed air entry"),
                IsometricAssetAnchor(key="air_outlet", x=0.96, y=0.52, role="airflow_outlet", description="Supply air discharge"),
                IsometricAssetAnchor(key="filter_bay", x=0.22, y=0.52, role="point_bind"),
                IsometricAssetAnchor(key="cooling_coil_bay", x=0.42, y=0.52, role="point_bind"),
                IsometricAssetAnchor(key="heating_coil_bay", x=0.58, y=0.52, role="point_bind"),
                IsometricAssetAnchor(key="fan_bay", x=0.78, y=0.52, role="point_bind"),
            ],
            binding_targets=[
                IsometricAssetBindingTarget(key="filter_dp", component="filter", binding_types=["value", "alarm"], preferred_point_kinds=["sensor", "alarm"], anchor_key="filter_bay", description="Filter differential or alarm"),
                IsometricAssetBindingTarget(key="cooling_valve", component="cooling_valve", binding_types=["command", "status"], preferred_point_kinds=["actuator", "status"], anchor_key="cooling_coil_bay", description="Cooling valve control"),
                IsometricAssetBindingTarget(key="heating_valve", component="heating_valve", binding_types=["command", "status"], preferred_point_kinds=["actuator", "status"], anchor_key="heating_coil_bay", description="Heating valve control"),
                IsometricAssetBindingTarget(key="supply_fan", component="supply_fan", binding_types=["status", "command", "value"], preferred_point_kinds=["status", "actuator", "sensor"], anchor_key="fan_bay", description="Supply fan proof, command, or speed"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="ahu-shell" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#eef2f5"/>
      <stop offset="100%" stop-color="#8d96a0"/>
    </linearGradient>
    <linearGradient id="ahu-face" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="100%" stop-color="#c4ccd5"/>
    </linearGradient>
  </defs>
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="18" y="32" width="190" height="84" rx="10" fill="url(#ahu-shell)" stroke="#5b5b57" stroke-width="2"/>
  <rect x="25" y="39" width="176" height="70" rx="8" fill="url(#ahu-face)" stroke="#9aa0a6" stroke-width="1"/>
  <rect x="28" y="61" width="162" height="26" rx="4" fill="#475569" stroke="#6b7280" stroke-width="1"/>
  <rect x="43" y="48" width="20" height="48" fill="#dbe4ee" stroke="#64748b" stroke-width="1"/>
  <path d="M47 93 L57 50 M55 93 L65 50" stroke="#475569" stroke-width="2"/>
  <rect x="80" y="48" width="30" height="48" fill="#93c5fd" stroke="#2563eb" stroke-width="1"/>
  <path d="M84 57 L106 57 M84 67 L106 67 M84 77 L106 77 M84 87 L106 87" stroke="#1d4ed8" stroke-width="2"/>
  <rect x="116" y="48" width="24" height="48" fill="#fdba74" stroke="#c2410c" stroke-width="1"/>
  <path d="M120 57 L136 57 M120 67 L136 67 M120 77 L136 77 M120 87 L136 87" stroke="#c2410c" stroke-width="2"/>
  <circle cx="167" cy="74" r="18" fill="#d7dee6" stroke="#475569" stroke-width="2"/>
  <circle cx="178" cy="79" r="6" fill="#6b7280" stroke="#374151" stroke-width="1"/>
  <path d="M173 80 L158 69 M166 91 L167 74 M155 82 L173 77" stroke="#475569" stroke-width="2" stroke-linecap="round"/>
  <rect x="208" y="52" width="18" height="44" fill="#b7c0c9" stroke="#6b7280" stroke-width="1.5"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="rtu_packaged_rooftop",
            label="Packaged Rooftop Unit",
            category="ahu",
            variant="packaged_rooftop",
            description="Packaged rooftop cabinet with DX, heat, supply section, and condenser fans.",
            compatible_equipment_types=["RTU"],
            tags=["rtu", "packaged", "rooftop", "dx"],
            anchor_points=[
                IsometricAssetAnchor(key="air_inlet", x=0.06, y=0.54, role="airflow_inlet"),
                IsometricAssetAnchor(key="air_outlet", x=0.94, y=0.48, role="airflow_outlet"),
                IsometricAssetAnchor(key="dx_bay", x=0.44, y=0.52, role="point_bind"),
                IsometricAssetAnchor(key="heat_bay", x=0.62, y=0.52, role="point_bind"),
                IsometricAssetAnchor(key="fan_bay", x=0.8, y=0.5, role="point_bind"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="24" y="44" width="176" height="76" rx="10" fill="#d9dee5" stroke="#5b6470" stroke-width="2"/>
  <rect x="34" y="54" width="156" height="56" rx="8" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1"/>
  <circle cx="176" cy="44" r="16" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
  <circle cx="146" cy="44" r="16" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
  <rect x="86" y="62" width="28" height="40" fill="#93c5fd" stroke="#2563eb" stroke-width="1.5"/>
  <rect x="122" y="62" width="24" height="40" fill="#fdba74" stroke="#c2410c" stroke-width="1.5"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="mixing_damper_bank",
            label="Mixing Damper Bank",
            category="damper",
            description="Outside/mixed air damper bank with blade and linkage anchors.",
            compatible_equipment_types=["AHU", "RTU", "MAU"],
            tags=["damper", "mixing-box", "outside-air"],
            anchor_points=[
                IsometricAssetAnchor(key="air_inlet", x=0.05, y=0.5, role="airflow_inlet"),
                IsometricAssetAnchor(key="air_outlet", x=0.95, y=0.5, role="airflow_outlet"),
                IsometricAssetAnchor(key="blade_pack", x=0.5, y=0.5, role="point_bind"),
            ],
            binding_targets=[
                IsometricAssetBindingTarget(key="damper_command", component="damper", binding_types=["command", "status", "value"], preferred_point_kinds=["actuator", "status", "sensor"], anchor_key="blade_pack", description="Damper position, command, or proof"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="38" y="44" width="164" height="72" rx="8" fill="#dce3ea" stroke="#5b6470" stroke-width="2"/>
  <rect x="50" y="56" width="140" height="48" rx="4" fill="#f6f8fb" stroke="#94a3b8" stroke-width="1"/>
  <path d="M60 67 L180 79 M60 80 L180 92 M60 54 L180 66" stroke="#4b5563" stroke-width="3"/>
  <circle cx="188" cy="81" r="6" fill="#6b7280"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="mixing_damper_low_leak",
            label="Low-Leak Opposed-Blade Damper",
            category="damper",
            description="Low-leak outdoor/mixed air damper with opposed blades and external actuator.",
            compatible_equipment_types=["AHU", "RTU", "MAU"],
            tags=["damper", "low-leak", "opposed-blade", "outside-air"],
            anchor_points=[
                IsometricAssetAnchor(key="air_inlet", x=0.05, y=0.5, role="airflow_inlet"),
                IsometricAssetAnchor(key="air_outlet", x=0.95, y=0.5, role="airflow_outlet"),
                IsometricAssetAnchor(key="blade_pack", x=0.5, y=0.5, role="point_bind"),
            ],
            binding_targets=[
                IsometricAssetBindingTarget(key="damper_command", component="damper", binding_types=["command", "status", "value"], preferred_point_kinds=["actuator", "status", "sensor"], anchor_key="blade_pack", description="Damper position, command, or proof"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="38" y="42" width="164" height="76" rx="8" fill="#dce3ea" stroke="#5b6470" stroke-width="2"/>
  <rect x="50" y="54" width="140" height="52" rx="4" fill="#f8fafc" stroke="#94a3b8" stroke-width="1"/>
  <path d="M60 64 L178 64 M60 78 L178 78 M60 92 L178 92" stroke="#475569" stroke-width="3"/>
  <path d="M170 58 L170 98" stroke="#64748b" stroke-width="3"/>
  <rect x="192" y="68" width="12" height="24" rx="2" fill="#6b7280" stroke="#374151" stroke-width="1"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="filter_bank_vcell",
            label="V-Cell Filter Bank",
            category="filter",
            description="Dimensional filter bank asset for prefilter or final filter sections.",
            compatible_equipment_types=["AHU", "RTU", "MAU"],
            tags=["filter", "v-bank", "air-cleaning"],
            anchor_points=[
                IsometricAssetAnchor(key="air_inlet", x=0.05, y=0.5, role="airflow_inlet"),
                IsometricAssetAnchor(key="air_outlet", x=0.95, y=0.5, role="airflow_outlet"),
                IsometricAssetAnchor(key="filter_face", x=0.5, y=0.5, role="point_bind"),
            ],
            binding_targets=[
                IsometricAssetBindingTarget(key="filter_dp", component="filter", binding_types=["value", "alarm"], preferred_point_kinds=["sensor", "alarm"], anchor_key="filter_face", description="Filter differential pressure or dirty filter alarm"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="44" y="38" width="152" height="84" rx="8" fill="#dbe4ee" stroke="#64748b" stroke-width="2"/>
  <path d="M64 110 L92 50 L120 110 L148 50 L176 110" fill="none" stroke="#475569" stroke-width="4"/>
  <rect x="56" y="50" width="128" height="58" rx="4" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="filter_bank_bag",
            label="Bag Filter Bank",
            category="filter",
            description="Multi-pocket bag filter section with header frame and hanging media pockets.",
            compatible_equipment_types=["AHU", "MAU"],
            tags=["filter", "bag", "final-filter", "air-cleaning"],
            anchor_points=[
                IsometricAssetAnchor(key="air_inlet", x=0.05, y=0.5, role="airflow_inlet"),
                IsometricAssetAnchor(key="air_outlet", x=0.95, y=0.5, role="airflow_outlet"),
                IsometricAssetAnchor(key="filter_face", x=0.5, y=0.45, role="point_bind"),
            ],
            binding_targets=[
                IsometricAssetBindingTarget(key="filter_dp", component="filter", binding_types=["value", "alarm"], preferred_point_kinds=["sensor", "alarm"], anchor_key="filter_face", description="Filter differential pressure or dirty filter alarm"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="42" y="36" width="156" height="88" rx="8" fill="#dbe4ee" stroke="#64748b" stroke-width="2"/>
  <rect x="54" y="48" width="132" height="14" rx="3" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1"/>
  <path d="M66 62 L66 112 Q78 120 90 112 L90 62" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
  <path d="M102 62 L102 112 Q114 120 126 112 L126 62" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
  <path d="M138 62 L138 112 Q150 120 162 112 L162 62" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="filter_bank_panel",
            label="Panel Prefilter Bank",
            category="filter",
            description="Flat panel prefilter rack used for upstream particulate removal before final filters.",
            compatible_equipment_types=["AHU", "RTU", "MAU"],
            tags=["filter", "panel", "prefilter", "merv-8"],
            anchor_points=[
                IsometricAssetAnchor(key="air_inlet", x=0.05, y=0.5, role="airflow_inlet"),
                IsometricAssetAnchor(key="air_outlet", x=0.95, y=0.5, role="airflow_outlet"),
                IsometricAssetAnchor(key="filter_face", x=0.5, y=0.5, role="point_bind"),
            ],
            binding_targets=[
                IsometricAssetBindingTarget(key="filter_dp", component="filter", binding_types=["value", "alarm"], preferred_point_kinds=["sensor", "alarm"], anchor_key="filter_face", description="Prefilter differential pressure or dirty filter alarm"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="44" y="38" width="152" height="84" rx="8" fill="#dbe4ee" stroke="#64748b" stroke-width="2"/>
  <rect x="58" y="52" width="124" height="56" rx="4" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1"/>
  <path d="M68 66 L172 66 M68 80 L172 80 M68 94 L172 94" stroke="#64748b" stroke-width="2"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="cooling_coil_chw",
            label="Cooling Coil CHW",
            category="coil",
            description="Chilled-water cooling coil with headers and fin pack.",
            compatible_equipment_types=["AHU", "RTU", "MAU", "FCU"],
            tags=["coil", "cooling", "chw"],
            anchor_points=[
                IsometricAssetAnchor(key="air_inlet", x=0.05, y=0.5, role="airflow_inlet"),
                IsometricAssetAnchor(key="air_outlet", x=0.95, y=0.5, role="airflow_outlet"),
                IsometricAssetAnchor(key="valve", x=0.15, y=0.15, role="pipe_inlet"),
                IsometricAssetAnchor(key="coil_face", x=0.5, y=0.5, role="point_bind"),
            ],
            binding_targets=[
                IsometricAssetBindingTarget(key="cooling_valve", component="cooling_valve", binding_types=["command", "status"], preferred_point_kinds=["actuator", "status"], anchor_key="valve", description="Cooling valve command/proof"),
                IsometricAssetBindingTarget(key="leaving_air_temp", component="cooling_coil", binding_types=["value"], preferred_point_kinds=["sensor"], anchor_key="coil_face", description="Cooling section leaving air value"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="54" y="42" width="118" height="76" rx="6" fill="#93c5fd" stroke="#2563eb" stroke-width="2"/>
  <path d="M66 54 L160 54 M66 66 L160 66 M66 78 L160 78 M66 90 L160 90 M66 102 L160 102" stroke="#1d4ed8" stroke-width="3"/>
  <path d="M42 48 L42 112 M184 48 L184 112" stroke="#8b5e34" stroke-width="6"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="cooling_coil_dx",
            label="DX Cooling Coil",
            category="coil",
            description="Direct-expansion refrigerant coil with distributor and suction/liquid connections.",
            compatible_equipment_types=["RTU", "AHU", "MAU"],
            tags=["coil", "cooling", "dx", "refrigerant"],
            anchor_points=[
                IsometricAssetAnchor(key="air_inlet", x=0.05, y=0.5, role="airflow_inlet"),
                IsometricAssetAnchor(key="air_outlet", x=0.95, y=0.5, role="airflow_outlet"),
                IsometricAssetAnchor(key="valve", x=0.16, y=0.18, role="pipe_inlet"),
                IsometricAssetAnchor(key="coil_face", x=0.5, y=0.5, role="point_bind"),
            ],
            binding_targets=[
                IsometricAssetBindingTarget(key="cooling_valve", component="cooling_valve", binding_types=["command", "status"], preferred_point_kinds=["actuator", "status"], anchor_key="valve", description="Compressor or valve-stage command"),
                IsometricAssetBindingTarget(key="leaving_air_temp", component="cooling_coil", binding_types=["value"], preferred_point_kinds=["sensor"], anchor_key="coil_face", description="Cooling section leaving air value"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="54" y="42" width="118" height="76" rx="6" fill="#93c5fd" stroke="#2563eb" stroke-width="2"/>
  <path d="M66 54 L160 54 M66 66 L160 66 M66 78 L160 78 M66 90 L160 90 M66 102 L160 102" stroke="#1d4ed8" stroke-width="3"/>
  <path d="M42 54 L42 110" stroke="#8b5e34" stroke-width="5"/>
  <path d="M184 48 L184 112" stroke="#8b5e34" stroke-width="5"/>
  <path d="M184 58 L202 50 L212 58 L202 66 Z" fill="#dbeafe" stroke="#2563eb" stroke-width="1.2"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="heating_coil_hw",
            label="Heating Coil HW",
            category="coil",
            description="Hot-water heating coil with headers and fin pack.",
            compatible_equipment_types=["AHU", "RTU", "MAU", "FCU", "VAV"],
            tags=["coil", "heating", "hw"],
            anchor_points=[
                IsometricAssetAnchor(key="air_inlet", x=0.05, y=0.5, role="airflow_inlet"),
                IsometricAssetAnchor(key="air_outlet", x=0.95, y=0.5, role="airflow_outlet"),
                IsometricAssetAnchor(key="valve", x=0.15, y=0.15, role="pipe_inlet"),
                IsometricAssetAnchor(key="coil_face", x=0.5, y=0.5, role="point_bind"),
            ],
            binding_targets=[
                IsometricAssetBindingTarget(key="heating_valve", component="heating_valve", binding_types=["command", "status"], preferred_point_kinds=["actuator", "status"], anchor_key="valve", description="Heating valve command/proof"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="54" y="42" width="118" height="76" rx="6" fill="#fdba74" stroke="#c2410c" stroke-width="2"/>
  <path d="M66 54 L160 54 M66 66 L160 66 M66 78 L160 78 M66 90 L160 90 M66 102 L160 102" stroke="#c2410c" stroke-width="3"/>
  <path d="M42 48 L42 112 M184 48 L184 112" stroke="#8b5e34" stroke-width="6"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="heating_coil_steam",
            label="Steam Heating Coil",
            category="coil",
            description="Steam distribution coil with condensate header and trap-side piping.",
            compatible_equipment_types=["AHU", "MAU"],
            tags=["coil", "heating", "steam"],
            anchor_points=[
                IsometricAssetAnchor(key="air_inlet", x=0.05, y=0.5, role="airflow_inlet"),
                IsometricAssetAnchor(key="air_outlet", x=0.95, y=0.5, role="airflow_outlet"),
                IsometricAssetAnchor(key="valve", x=0.14, y=0.18, role="pipe_inlet"),
                IsometricAssetAnchor(key="coil_face", x=0.5, y=0.5, role="point_bind"),
            ],
            binding_targets=[
                IsometricAssetBindingTarget(key="heating_valve", component="heating_valve", binding_types=["command", "status"], preferred_point_kinds=["actuator", "status"], anchor_key="valve", description="Steam valve command/proof"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="54" y="42" width="118" height="76" rx="6" fill="#fdba74" stroke="#c2410c" stroke-width="2"/>
  <path d="M66 54 L160 54 M66 66 L160 66 M66 78 L160 78 M66 90 L160 90 M66 102 L160 102" stroke="#c2410c" stroke-width="3"/>
  <path d="M42 48 L42 112" stroke="#8b5e34" stroke-width="6"/>
  <path d="M184 56 L184 104" stroke="#8b5e34" stroke-width="4"/>
  <circle cx="196" cy="104" r="8" fill="#d1d5db" stroke="#4b5563" stroke-width="1.2"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="supply_fan_scroll",
            label="Supply Fan Scroll",
            category="fan",
            description="Scroll housing fan section with wheel and motor anchor.",
            compatible_equipment_types=["AHU", "RTU", "EF", "SF", "RF"],
            tags=["fan", "scroll", "motor", "supply"],
            anchor_points=[
                IsometricAssetAnchor(key="air_inlet", x=0.12, y=0.54, role="airflow_inlet"),
                IsometricAssetAnchor(key="air_outlet", x=0.88, y=0.42, role="airflow_outlet"),
                IsometricAssetAnchor(key="motor", x=0.76, y=0.64, role="point_bind"),
                IsometricAssetAnchor(key="wheel", x=0.5, y=0.54, role="point_bind"),
            ],
            binding_targets=[
                IsometricAssetBindingTarget(key="fan_status", component="supply_fan", binding_types=["status", "command", "value"], preferred_point_kinds=["status", "actuator", "sensor"], anchor_key="motor", description="Fan proof, command, or speed"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <path d="M52 102 C52 56, 92 38, 136 38 L164 38 L164 90 C164 112, 148 122, 124 122 L78 122 C62 122, 52 116, 52 102 Z" fill="#d8dee6" stroke="#4b5563" stroke-width="3"/>
  <circle cx="102" cy="82" r="24" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
  <path d="M108 82 L90 75 M100 92 L103 74 M89 84 L108 79" stroke="#475569" stroke-width="2.5" stroke-linecap="round"/>
  <circle cx="166" cy="92" r="12" fill="#6b7280" stroke="#374151" stroke-width="1.5"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="supply_fan_plenum",
            label="Plenum Fan Array",
            category="fan",
            description="Plenum fan cell with direct-drive wheel and motor package used in larger AHUs.",
            compatible_equipment_types=["AHU", "MAU"],
            tags=["fan", "plenum", "direct-drive", "array"],
            anchor_points=[
                IsometricAssetAnchor(key="air_inlet", x=0.12, y=0.54, role="airflow_inlet"),
                IsometricAssetAnchor(key="air_outlet", x=0.88, y=0.42, role="airflow_outlet"),
                IsometricAssetAnchor(key="motor", x=0.72, y=0.62, role="point_bind"),
                IsometricAssetAnchor(key="wheel", x=0.5, y=0.54, role="point_bind"),
            ],
            binding_targets=[
                IsometricAssetBindingTarget(key="fan_status", component="supply_fan", binding_types=["status", "command", "value"], preferred_point_kinds=["status", "actuator", "sensor"], anchor_key="motor", description="Fan proof, command, or speed"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="44" y="38" width="152" height="86" rx="8" fill="#d8dee6" stroke="#4b5563" stroke-width="2"/>
  <circle cx="96" cy="80" r="20" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
  <circle cx="144" cy="80" r="20" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
  <path d="M101 80 L85 73 M95 89 L97 72 M84 82 L103 77" stroke="#475569" stroke-width="2.2" stroke-linecap="round"/>
  <path d="M149 80 L133 73 M143 89 L145 72 M132 82 L151 77" stroke="#475569" stroke-width="2.2" stroke-linecap="round"/>
  <rect x="166" y="68" width="14" height="24" rx="2" fill="#6b7280" stroke="#374151" stroke-width="1"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="relief_fan_housed",
            label="Relief Fan Housed",
            category="fan",
            description="Housed relief or return fan with discharge plenum and external motor mount.",
            compatible_equipment_types=["AHU", "EF", "RF"],
            tags=["fan", "relief", "return", "housed"],
            anchor_points=[
                IsometricAssetAnchor(key="air_inlet", x=0.12, y=0.56, role="airflow_inlet"),
                IsometricAssetAnchor(key="air_outlet", x=0.9, y=0.34, role="airflow_outlet"),
                IsometricAssetAnchor(key="motor", x=0.76, y=0.62, role="point_bind"),
                IsometricAssetAnchor(key="wheel", x=0.44, y=0.56, role="point_bind"),
            ],
            binding_targets=[
                IsometricAssetBindingTarget(key="fan_status", component="return_fan", binding_types=["status", "command", "value"], preferred_point_kinds=["status", "actuator", "sensor"], anchor_key="motor", description="Return or relief fan proof, command, or speed"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <path d="M50 104 C50 62, 84 42, 132 42 L172 42 L172 90 C172 110, 156 120, 128 120 L82 120 C62 120, 50 114, 50 104 Z" fill="#d8dee6" stroke="#4b5563" stroke-width="3"/>
  <circle cx="94" cy="84" r="22" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
  <path d="M99 84 L83 77 M93 93 L95 76 M82 86 L101 81" stroke="#475569" stroke-width="2.3" stroke-linecap="round"/>
  <rect x="164" y="76" width="18" height="26" rx="3" fill="#6b7280" stroke="#374151" stroke-width="1.2"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="steam_humidifier_grid",
            label="Steam Humidifier Grid",
            category="accessory",
            description="Steam dispersion humidifier grid with manifold, tube bank, and visible vapor discharge.",
            compatible_equipment_types=["AHU", "MAU"],
            tags=["humidifier", "steam", "dispersion", "grid"],
            anchor_points=[
                IsometricAssetAnchor(key="steam_inlet", x=0.14, y=0.42, role="pipe_inlet"),
                IsometricAssetAnchor(key="grid", x=0.54, y=0.54, role="point_bind"),
            ],
            binding_targets=[
                IsometricAssetBindingTarget(key="humidity_control", component="humidity", binding_types=["value", "command", "status"], preferred_point_kinds=["sensor", "actuator", "status"], anchor_key="grid", description="Humidity control or proof across dispersion grid"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="48" y="46" width="144" height="68" rx="8" fill="#dce3ea" stroke="#64748b" stroke-width="2"/>
  <path d="M58 78 L184 78" stroke="#0f766e" stroke-width="4"/>
  <path d="M76 78 L76 110 M104 78 L104 110 M132 78 L132 110 M160 78 L160 110" stroke="#0f766e" stroke-width="2"/>
  <circle cx="76" cy="116" r="5" fill="#dbeafe"/><circle cx="104" cy="116" r="5" fill="#dbeafe"/><circle cx="132" cy="116" r="5" fill="#dbeafe"/><circle cx="160" cy="116" r="5" fill="#dbeafe"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="energy_recovery_wheel",
            label="Energy Recovery Wheel",
            category="accessory",
            description="Rotary energy recovery wheel cassette with purge section and drive motor.",
            compatible_equipment_types=["AHU", "MAU", "ERV"],
            tags=["energy-recovery", "wheel", "rotary", "erv"],
            anchor_points=[
                IsometricAssetAnchor(key="exhaust_inlet", x=0.14, y=0.64, role="airflow_inlet"),
                IsometricAssetAnchor(key="supply_outlet", x=0.86, y=0.36, role="airflow_outlet"),
                IsometricAssetAnchor(key="wheel", x=0.5, y=0.5, role="point_bind"),
            ],
            binding_targets=[
                IsometricAssetBindingTarget(key="wheel_status", component="energy_recovery", binding_types=["status", "command", "value"], preferred_point_kinds=["status", "actuator", "sensor"], anchor_key="wheel", description="Energy wheel proof, command, or speed"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="46" y="38" width="148" height="84" rx="8" fill="#dce3ea" stroke="#64748b" stroke-width="2"/>
  <circle cx="120" cy="80" r="28" fill="#f8fafc" stroke="#5e35b1" stroke-width="2.5"/>
  <path d="M120 52 L120 108 M92 80 L148 80 M100 60 L140 100 M140 60 L100 100" stroke="#5e35b1" stroke-width="2"/>
  <rect x="154" y="70" width="14" height="20" rx="3" fill="#6b7280" stroke="#374151" stroke-width="1"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="uv_c_lamp_bank",
            label="UV-C Lamp Bank",
            category="accessory",
            description="UV-C irradiation section with lamp rack, ballast housings, and service frame.",
            compatible_equipment_types=["AHU", "MAU"],
            tags=["uv", "uv-c", "ultraviolet", "iaq"],
            anchor_points=[
                IsometricAssetAnchor(key="lamp_rack", x=0.5, y=0.5, role="point_bind"),
            ],
            binding_targets=[
                IsometricAssetBindingTarget(key="uv_status", component="uv", binding_types=["status", "command", "value"], preferred_point_kinds=["status", "actuator", "sensor"], anchor_key="lamp_rack", description="UV bank enable, proof, or intensity"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="48" y="42" width="144" height="76" rx="8" fill="#ede9fe" stroke="#7c3aed" stroke-width="2"/>
  <path d="M76 54 L76 106 M104 54 L104 106 M132 54 L132 106 M160 54 L160 106" stroke="#7c3aed" stroke-width="3"/>
  <rect x="62" y="48" width="112" height="10" rx="3" fill="#c4b5fd" stroke="#7c3aed" stroke-width="1"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="sound_attenuator_baffle",
            label="Sound Attenuator Baffle",
            category="duct",
            description="Acoustic splitter attenuator section with lined baffles for fan discharge noise control.",
            compatible_equipment_types=["AHU", "MAU", "RTU"],
            tags=["silencer", "attenuator", "acoustic", "baffle"],
            anchor_points=[
                IsometricAssetAnchor(key="air_inlet", x=0.05, y=0.5, role="airflow_inlet"),
                IsometricAssetAnchor(key="air_outlet", x=0.95, y=0.5, role="airflow_outlet"),
                IsometricAssetAnchor(key="baffle_pack", x=0.5, y=0.5, role="point_bind"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="34" y="46" width="172" height="68" rx="8" fill="#cfd6de" stroke="#5b6470" stroke-width="2"/>
  <rect x="52" y="56" width="18" height="48" fill="#94a3b8" stroke="#475569" stroke-width="1"/>
  <rect x="92" y="56" width="18" height="48" fill="#94a3b8" stroke="#475569" stroke-width="1"/>
  <rect x="132" y="56" width="18" height="48" fill="#94a3b8" stroke="#475569" stroke-width="1"/>
  <rect x="172" y="56" width="18" height="48" fill="#94a3b8" stroke="#475569" stroke-width="1"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="rectangular_supply_duct",
            label="Rectangular Supply Duct",
            category="duct",
            description="Main supply duct section with inlet/outlet anchors for trunk assembly.",
            tags=["duct", "supply", "trunk"],
            anchor_points=[
                IsometricAssetAnchor(key="air_inlet", x=0.03, y=0.5, role="airflow_inlet"),
                IsometricAssetAnchor(key="air_outlet", x=0.97, y=0.5, role="airflow_outlet"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="duct-shell" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#d6dbe1"/>
      <stop offset="100%" stop-color="#69727f"/>
    </linearGradient>
  </defs>
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="24" y="54" width="192" height="52" rx="6" fill="url(#duct-shell)" stroke="#4b5563" stroke-width="2"/>
  <rect x="30" y="64" width="180" height="32" rx="4" fill="#334155" stroke="#94a3b8" stroke-width="1"/>
  <path d="M24 54 L38 44 L229 44 L216 54" fill="#c2c9d0" stroke="#6b7280" stroke-width="1.5"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="chiller_air_cooled",
            label="Air-Cooled Chiller",
            category="accessory",
            variant="air_cooled",
            description="Air-cooled chiller skid with compressor bay, evaporator barrel, and top condenser fans.",
            compatible_equipment_types=["CHILLER"],
            tags=["chiller", "air-cooled", "plant"],
            anchor_points=[
                IsometricAssetAnchor(key="chw_supply", x=0.18, y=0.74, role="pipe_outlet"),
                IsometricAssetAnchor(key="chw_return", x=0.82, y=0.74, role="pipe_inlet"),
                IsometricAssetAnchor(key="compressor_bay", x=0.28, y=0.48, role="point_bind"),
                IsometricAssetAnchor(key="evaporator_bay", x=0.56, y=0.48, role="point_bind"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="26" y="54" width="188" height="64" rx="10" fill="#dce4ee" stroke="#4b5563" stroke-width="2"/>
  <circle cx="150" cy="52" r="16" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
  <circle cx="184" cy="52" r="16" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
  <ellipse cx="78" cy="86" rx="22" ry="16" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
  <rect x="108" y="70" width="42" height="32" rx="5" fill="#93c5fd" stroke="#2563eb" stroke-width="1.5"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="boiler_condensing",
            label="Condensing Boiler",
            category="accessory",
            variant="condensing",
            description="Floor-mounted condensing boiler with burner door, heat exchanger block, and flue.",
            compatible_equipment_types=["BOILER"],
            tags=["boiler", "condensing", "plant"],
            anchor_points=[
                IsometricAssetAnchor(key="hws", x=0.84, y=0.3, role="pipe_outlet"),
                IsometricAssetAnchor(key="hwr", x=0.84, y=0.72, role="pipe_inlet"),
                IsometricAssetAnchor(key="burner", x=0.24, y=0.52, role="point_bind"),
                IsometricAssetAnchor(key="heat_block", x=0.56, y=0.52, role="point_bind"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="42" y="44" width="132" height="82" rx="10" fill="#f6e7c9" stroke="#c2410c" stroke-width="2"/>
  <circle cx="74" cy="86" r="18" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
  <rect x="102" y="62" width="42" height="46" rx="4" fill="#fdba74" stroke="#c2410c" stroke-width="1.5"/>
  <rect x="176" y="28" width="16" height="44" rx="3" fill="#6b7280" stroke="#374151" stroke-width="1.2"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="pump_end_suction",
            label="End-Suction Pump",
            category="accessory",
            variant="end_suction",
            description="Base-mounted end-suction pump with motor, volute, suction and discharge flanges.",
            compatible_equipment_types=["PUMP_HW", "PUMP_CHW", "PUMP_CW"],
            tags=["pump", "end-suction", "hydronic"],
            anchor_points=[
                IsometricAssetAnchor(key="suction", x=0.1, y=0.58, role="pipe_inlet"),
                IsometricAssetAnchor(key="discharge", x=0.88, y=0.4, role="pipe_outlet"),
                IsometricAssetAnchor(key="motor", x=0.7, y=0.58, role="point_bind"),
                IsometricAssetAnchor(key="volute", x=0.42, y=0.58, role="point_bind"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="42" y="104" width="126" height="14" rx="3" fill="#94a3b8" stroke="#475569" stroke-width="1"/>
  <circle cx="94" cy="82" r="24" fill="#dbeafe" stroke="#2563eb" stroke-width="2"/>
  <rect x="122" y="64" width="38" height="34" rx="4" fill="#d1d5db" stroke="#4b5563" stroke-width="1.5"/>
  <path d="M48 82 L70 82 M118 76 L182 76 L182 52" stroke="#1976d2" stroke-width="5" fill="none"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="cooling_tower_open_cell",
            label="Open Cooling Tower",
            category="accessory",
            variant="open_cell",
            description="Open-cell cooling tower with fan stack, fill pack, drift section, and basin.",
            compatible_equipment_types=["CT"],
            tags=["cooling-tower", "open-cell", "condenser-water"],
            anchor_points=[
                IsometricAssetAnchor(key="cw_supply", x=0.5, y=0.1, role="pipe_inlet"),
                IsometricAssetAnchor(key="cw_return", x=0.12, y=0.86, role="pipe_outlet"),
                IsometricAssetAnchor(key="fan", x=0.5, y=0.22, role="point_bind"),
                IsometricAssetAnchor(key="fill", x=0.5, y=0.56, role="point_bind"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <path d="M70 32 L170 32 L152 122 L88 122 Z" fill="#d6f0eb" stroke="#0f766e" stroke-width="2"/>
  <circle cx="120" cy="46" r="18" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
  <rect x="96" y="72" width="48" height="28" fill="#b7e4dc" stroke="#0f766e" stroke-width="1.5"/>
  <rect x="82" y="122" width="76" height="12" rx="3" fill="#bfdbfe" stroke="#2563eb" stroke-width="1.2"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="chiller_centrifugal_water_cooled",
            label="Water-Cooled Centrifugal Chiller",
            category="accessory",
            variant="water_cooled_centrifugal",
            description="Water-cooled centrifugal chiller with barrel heat exchangers, compressor body, and condenser-water connections.",
            compatible_equipment_types=["CHILLER"],
            tags=["chiller", "water-cooled", "centrifugal", "plant"],
            anchor_points=[
                IsometricAssetAnchor(key="chw_supply", x=0.14, y=0.72, role="pipe_outlet"),
                IsometricAssetAnchor(key="chw_return", x=0.42, y=0.72, role="pipe_inlet"),
                IsometricAssetAnchor(key="cw_supply", x=0.72, y=0.72, role="pipe_outlet"),
                IsometricAssetAnchor(key="cw_return", x=0.9, y=0.72, role="pipe_inlet"),
                IsometricAssetAnchor(key="compressor_bay", x=0.52, y=0.4, role="point_bind"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <ellipse cx="72" cy="98" rx="28" ry="16" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
  <ellipse cx="158" cy="98" rx="30" ry="16" fill="#dbeafe" stroke="#2563eb" stroke-width="2"/>
  <rect x="88" y="56" width="58" height="52" rx="12" fill="#dce4ee" stroke="#4b5563" stroke-width="2"/>
  <path d="M42 98 L54 98 M100 112 L100 126 M188 112 L188 126" stroke="#1976d2" stroke-width="5" fill="none"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="boiler_firetube",
            label="Firetube Boiler",
            category="accessory",
            variant="firetube",
            description="Horizontal firetube boiler with cylindrical shell, burner front, and stack connection.",
            compatible_equipment_types=["BOILER"],
            tags=["boiler", "firetube", "scotch-marine", "plant"],
            anchor_points=[
                IsometricAssetAnchor(key="hws", x=0.86, y=0.36, role="pipe_outlet"),
                IsometricAssetAnchor(key="hwr", x=0.14, y=0.66, role="pipe_inlet"),
                IsometricAssetAnchor(key="burner", x=0.18, y=0.5, role="point_bind"),
                IsometricAssetAnchor(key="shell", x=0.52, y=0.5, role="point_bind"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <ellipse cx="116" cy="86" rx="62" ry="34" fill="#f6e7c9" stroke="#c2410c" stroke-width="2"/>
  <circle cx="64" cy="86" r="18" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
  <rect x="172" y="42" width="14" height="42" rx="3" fill="#6b7280" stroke="#374151" stroke-width="1.2"/>
  <path d="M40 102 L60 102 M176 70 L206 70" stroke="#ef6c00" stroke-width="5" fill="none"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="pump_vertical_inline",
            label="Vertical Inline Pump",
            category="accessory",
            variant="vertical_inline",
            description="Vertical inline pump with top-mounted motor and inline suction/discharge flanges.",
            compatible_equipment_types=["PUMP_HW", "PUMP_CHW", "PUMP_CW"],
            tags=["pump", "vertical-inline", "inline", "hydronic"],
            anchor_points=[
                IsometricAssetAnchor(key="suction", x=0.34, y=0.84, role="pipe_inlet"),
                IsometricAssetAnchor(key="discharge", x=0.66, y=0.16, role="pipe_outlet"),
                IsometricAssetAnchor(key="motor", x=0.5, y=0.28, role="point_bind"),
                IsometricAssetAnchor(key="volute", x=0.5, y=0.56, role="point_bind"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <rect x="100" y="30" width="40" height="34" rx="4" fill="#d1d5db" stroke="#4b5563" stroke-width="1.5"/>
  <circle cx="120" cy="90" r="28" fill="#dbeafe" stroke="#2563eb" stroke-width="2"/>
  <path d="M120 54 L120 126 M78 90 L162 90" stroke="#1976d2" stroke-width="6" fill="none"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="cooling_tower_induced_draft",
            label="Induced-Draft Cooling Tower",
            category="accessory",
            variant="induced_draft",
            description="Induced-draft cooling tower with tall fan stack, louvered casing, and cold-water basin.",
            compatible_equipment_types=["COOLING_TOWER"],
            tags=["cooling-tower", "induced-draft", "counterflow", "condenser-water"],
            anchor_points=[
                IsometricAssetAnchor(key="cw_supply", x=0.7, y=0.18, role="pipe_inlet"),
                IsometricAssetAnchor(key="cw_return", x=0.16, y=0.86, role="pipe_outlet"),
                IsometricAssetAnchor(key="fan", x=0.5, y=0.16, role="point_bind"),
                IsometricAssetAnchor(key="fill", x=0.5, y=0.58, role="point_bind"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <path d="M72 44 L168 44 L150 118 L90 118 Z" fill="#d7f0ea" stroke="#0f766e" stroke-width="2"/>
  <circle cx="120" cy="40" r="16" fill="#f8fafc" stroke="#475569" stroke-width="2"/>
  <path d="M92 72 L148 72 M88 84 L152 84 M84 96 L156 96" stroke="#0f766e" stroke-width="2"/>
  <rect x="86" y="118" width="68" height="16" rx="3" fill="#bfdbfe" stroke="#2563eb" stroke-width="1.2"/>
</svg>
            """.strip(),
        ),
        IsometricAssetDefinition(
            asset_id="vav_reheat_terminal",
            label="VAV Reheat Terminal",
            category="terminal",
            description="Single-duct VAV box with damper and reheat coil anchors.",
            compatible_equipment_types=["VAV", "TU"],
            tags=["vav", "terminal", "reheat"],
            anchor_points=[
                IsometricAssetAnchor(key="air_inlet", x=0.06, y=0.52, role="airflow_inlet"),
                IsometricAssetAnchor(key="air_outlet", x=0.94, y=0.52, role="airflow_outlet"),
                IsometricAssetAnchor(key="damper", x=0.32, y=0.52, role="point_bind"),
                IsometricAssetAnchor(key="reheat", x=0.66, y=0.52, role="point_bind"),
            ],
            binding_targets=[
                IsometricAssetBindingTarget(key="damper_position", component="damper", binding_types=["command", "value", "status"], preferred_point_kinds=["actuator", "sensor", "status"], anchor_key="damper", description="Damper position or proof"),
                IsometricAssetBindingTarget(key="reheat_valve", component="reheat_valve", binding_types=["command", "status"], preferred_point_kinds=["actuator", "status"], anchor_key="reheat", description="Reheat control"),
            ],
            preview_svg="""
<svg viewBox="0 0 240 160" class="h-40 w-full" xmlns="http://www.w3.org/2000/svg">
  <rect width="240" height="160" rx="18" fill="#eef3f8"/>
  <path d="M36 74 L74 56 L186 56 L206 74 L186 92 L74 92 Z" fill="#cfd6de" stroke="#5b6470" stroke-width="2"/>
  <rect x="54" y="66" width="126" height="18" rx="3" fill="#334155" stroke="#94a3b8" stroke-width="1"/>
  <path d="M76 84 L95 66" stroke="#475569" stroke-width="3"/>
  <rect x="118" y="61" width="30" height="28" fill="#fdba74" stroke="#c2410c" stroke-width="1.5"/>
  <path d="M122 68 L144 68 M122 75 L144 75 M122 82 L144 82" stroke="#c2410c" stroke-width="2"/>
</svg>
            """.strip(),
        ),
    ]
    for asset in library:
        asset.visual_references = list(_ASSET_VISUAL_REFERENCE_MAP.get(asset.asset_id, ()))
    return library


_ASSET_VISUAL_REFERENCE_MAP: dict[str, tuple[AssetVisualReference, ...]] = {
    "ahu_drawthrough_doubledeck": (
        AssetVisualReference(
            source="AAON",
            label="H3 Series Horizontal Indoor Air Handling Units",
            reference_url="https://www.aaon.com/products/h3-series",
            notes="Good cabinet proportions, double-wall construction, and plenum-fan AHU sectioning.",
        ),
        AssetVisualReference(
            source="Trane",
            label="Performance Climate Changer Air Handlers",
            reference_url="https://www.trane.com/commercial/north-america/us/en/products-systems/airside-equipment/performance-air-handlers.html",
            notes="Useful for large commercial AHU layouts with filter, coil, and fan sections.",
        ),
    ),
    "rtu_packaged_rooftop": (
        AssetVisualReference(
            source="AAON",
            label="RN Series Rooftop Units",
            reference_url="https://www.aaon.com/products/rn-series",
            notes="Primary RTU cabinet segmentation, access-door pattern, and serviceable rooftop form.",
        ),
        AssetVisualReference(
            source="AAON",
            label="Packaged Rooftop Units",
            reference_url="https://www.aaon.com/products/packaged-rooftop-units",
            notes="High-level RTU family reference with condenser fan and packaged cabinet details.",
        ),
    ),
    "mixing_damper_bank": (
        AssetVisualReference(
            source="Greenheck",
            label="Control Dampers",
            reference_url="https://www.greenheck.com/products/air-control/dampers/control-dampers",
            notes="Useful blade, frame, and linkage proportions for opposed-blade and mixing dampers.",
        ),
    ),
    "mixing_damper_low_leak": (
        AssetVisualReference(
            source="Greenheck",
            label="FSD-211 Combination Fire Smoke Damper",
            reference_url="https://www.greenheck.com/shop/fsd-211",
            notes="Useful low-leak blade and sleeve detailing for damper-face treatment.",
        ),
    ),
    "filter_bank_vcell": (
        AssetVisualReference(
            source="AAF",
            label="V-Bank Filters",
            reference_url="https://aafintl.com/en/commercial/products/air-filters/v-bank-filters",
            notes="V-cell pack geometry and frame spacing for deep final filter sections.",
        ),
    ),
    "filter_bank_bag": (
        AssetVisualReference(
            source="AAF",
            label="Bag Filters",
            reference_url="https://aafintl.com/en/commercial/products/air-filters/bag-filters",
            notes="Pocket filter silhouette and header layout for final filter banks.",
        ),
    ),
    "filter_bank_panel": (
        AssetVisualReference(
            source="Camfil",
            label="Panel Filters",
            reference_url="https://www.camfil.com/en-us/products/general-ventilation-filters/panel-filters",
            notes="Flat panel and pleated prefilter appearance reference.",
        ),
    ),
    "cooling_coil_chw": (
        AssetVisualReference(
            source="Carrier",
            label="39DC Data Center Air Handler",
            reference_url="https://www.carrier.com/us/en/commercial/airside/39dc/",
            notes="Useful chilled-water coil face, copper-tube/aluminum-fin pattern, and service-access framing reference.",
        ),
    ),
    "cooling_coil_dx": (
        AssetVisualReference(
            source="Carrier",
            label="39HX Air Handling Unit",
            reference_url="https://www.carrier.com/commercial/en/se/products/air-treatment/air-handling-units/compact/39hx/",
            notes="Official DX-coil reference with copper-tube/aluminum-fin construction and compact AHU integration notes.",
        ),
    ),
    "heating_coil_hw": (
        AssetVisualReference(
            source="Daikin Applied",
            label="Custom Air Handlers",
            reference_url="https://www.daikinapplied.com/products/air-handlers/custom-air-handler",
            notes="Good source for commercial AHU heating-coil proportions, headers, and service-bay spacing.",
        ),
    ),
    "heating_coil_steam": (
        AssetVisualReference(
            source="Carrier",
            label="Gemini 40RLQ Packaged Air-Handling Unit",
            reference_url="https://www.carrier.com/commercial/en/us/products/split-systems-and-condensers/split-systems/40rlq/",
            notes="Official packaged-air-handler reference that explicitly includes hot-water and steam-coil configurations.",
        ),
    ),
    "supply_fan_scroll": (
        AssetVisualReference(
            source="Twin City Fan",
            label="Centrifugal Fans",
            reference_url="https://www.tcf.com/products/centrifugal-fans",
            notes="Scroll housing, wheel proportion, and motor arrangement reference.",
        ),
    ),
    "supply_fan_plenum": (
        AssetVisualReference(
            source="Greenheck",
            label="HPA Direct Drive Plenum Fan Array",
            reference_url="https://www.greenheck.com/products/fans/fan-arrays/hpa",
            notes="Official direct-drive plenum-fan and fan-array reference with better wheel-cell proportions than generic AHU overviews.",
        ),
    ),
    "relief_fan_housed": (
        AssetVisualReference(
            source="Twin City Fan",
            label="Centrifugal Fans",
            reference_url="https://www.tcf.com/products/centrifugal-fans",
            notes="Housed return/relief fan appearance and external motor relationships.",
        ),
    ),
    "steam_humidifier_grid": (
        AssetVisualReference(
            source="Condair",
            label="Steam Humidifier Dispersion Systems",
            reference_url="https://www.condair.com/humidifiers/dispersion-systems",
            notes="Steam manifold and dispersion tube arrangements for in-duct humidification.",
        ),
    ),
    "energy_recovery_wheel": (
        AssetVisualReference(
            source="SEMCO",
            label="True 3A Wheel",
            reference_url="https://www.semcohvac.com/wheels/true-3a",
            notes="Rotary wheel cassette, purge section, and drive side reference.",
        ),
    ),
    "uv_c_lamp_bank": (
        AssetVisualReference(
            source="Fresh-Aire UV",
            label="Commercial HVAC UV Systems",
            reference_url="https://www.freshaireuv.com/commercial-hvac/",
            notes="Official lamp-bank, rack, and service-frame reference for in-duct UV-C accessories.",
        ),
    ),
    "sound_attenuator_baffle": (
        AssetVisualReference(
            source="Nailor",
            label="Rectangular Dissipative Silencer",
            reference_url="https://nailor.com/products/silencers",
            notes="Official splitter-baffle duct silencer reference for acoustic attenuator proportions and perforated-liner treatment.",
        ),
    ),
    "rectangular_supply_duct": (
        AssetVisualReference(
            source="SMACNA",
            label="Rectangular Duct Construction",
            reference_url="https://shop.smacna.org/smacna-rectangular-industrial-duct-construction-standards.html",
            notes="General rectangular duct shape, seam, and reinforcement reference.",
        ),
    ),
    "chiller_air_cooled": (
        AssetVisualReference(
            source="Carrier",
            label="AquaSnap 30RC Air-Cooled Scroll Chiller",
            reference_url="https://www.carrier.com/us/en/commercial/chillers/30rc/",
            notes="Current official air-cooled chiller reference with top fans and packaged skid proportions.",
        ),
        AssetVisualReference(
            source="Carrier",
            label="AquaSnap 30RB Technical Specifications",
            reference_url="https://www.carrier.com/us/en/commercial/chillers/30rb/technical-specifications/",
            notes="Supplemental air-cooled chiller family reference with clear cabinet and coil details.",
        ),
    ),
    "boiler_condensing": (
        AssetVisualReference(
            source="Cleaver-Brooks",
            label="ClearFire-CE Condensing Hydronic Boiler",
            reference_url="https://cleaverbrooks.com/Product/cfce",
            notes="Official condensing boiler reference with strong cabinet, burner-door, and vent-connection geometry.",
        ),
    ),
    "pump_end_suction": (
        AssetVisualReference(
            source="Xylem Bell & Gossett",
            label="e-1510X Smart Pumps",
            reference_url="https://www.xylem.com/en-us/products--services/pumps-packaged-pump-systems/pumps/end-suction-pumps/e-1510x-smart-pumps/",
            notes="Official base-mounted end-suction pump reference with motor, volute, and discharge proportions.",
        ),
    ),
    "cooling_tower_open_cell": (
        AssetVisualReference(
            source="SPX Cooling Technologies",
            label="Marley NC Cooling Tower",
            reference_url="https://spxcooling.com/cooling-towers/marley-nc/",
            notes="Official open cooling tower reference with basin, casing, fan cylinder, and access-door geometry.",
        ),
    ),
    "chiller_centrifugal_water_cooled": (
        AssetVisualReference(
            source="Daikin Applied",
            label="Magnitude Magnetic Bearing Centrifugal Chiller",
            reference_url="https://www.daikinapplied.com/products/chiller-products/magnitude",
            notes="Official water-cooled centrifugal chiller reference with barrel, compressor, and service-clearance proportions.",
        ),
    ),
    "boiler_firetube": (
        AssetVisualReference(
            source="Cleaver-Brooks",
            label="CBEX Firetube Boiler",
            reference_url="https://www.cleaverbrooks.com/Product/cbex",
            notes="Official firetube boiler reference with strong horizontal shell, burner-front, and trim layout cues.",
        ),
    ),
    "pump_vertical_inline": (
        AssetVisualReference(
            source="Xylem Bell & Gossett",
            label="Series e-90 ECM Small Close-Coupled In-Line Centrifugal Pumps",
            reference_url="https://www.xylem.com/en-us/products--services/pumps-packaged-pump-systems/pumps/in-line-pumps/series-e-90-ecm-small-close-coupled-in-line-centrifugal-pumps-with-ecm-motors/",
            notes="Official vertical-inline pump reference with cleaner current product imagery and better motor-can/flange relationships.",
        ),
    ),
    "cooling_tower_induced_draft": (
        AssetVisualReference(
            source="SPX Cooling Technologies",
            label="Marley NC Cooling Tower",
            reference_url="https://spxcooling.com/cooling-towers/marley-nc/",
            notes="Official induced-draft cooling-tower reference with strong fan-stack, casing, and louver proportions.",
        ),
    ),
    "vav_reheat_terminal": (
        AssetVisualReference(
            source="Price Industries",
            label="FDC/FPC Constant Volume Series Flow Fan Powered Terminal Unit",
            reference_url="https://priceindustries.com/product/fdc-fpc-constant-volume-series-flow",
            notes="Official fan-powered terminal reference with clear casing, inlet, fan section, and reheat-option geometry.",
        ),
    ),
}


__all__ = [
    "AssetVisualReference",
    "GraphicBinding",
    "GraphicDefinition",
    "GraphicElement",
    "GraphicNavigation",
    "IsometricAssetAnchor",
    "IsometricAssetBindingTarget",
    "IsometricAssetDefinition",
    "default_isometric_asset_library",
]
