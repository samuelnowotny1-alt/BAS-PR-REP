"""Logic model - structured control logic representation."""

from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime

from . import NonEmptyStr


class LogicSignal(BaseModel):
    """A signal in the logic diagram."""

    name: NonEmptyStr
    data_type: str = Field(description="boolean, analog, integer, enum, string")
    description: str = ""
    units: Optional[str] = None
    default_value: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    point_ref: Optional[str] = None
    is_input: bool = True
    is_output: bool = False
    is_parameter: bool = False


class LogicParameter(BaseModel):
    """A configurable parameter."""

    name: NonEmptyStr
    value: str
    data_type: str = Field(description="boolean, analog, integer, enum, string")
    description: str = ""
    units: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    tunable: bool = True


class LogicConnection(BaseModel):
    """Connection between logic blocks."""

    from_block: NonEmptyStr
    from_signal: NonEmptyStr
    to_block: NonEmptyStr
    to_signal: NonEmptyStr


class LogicBlock(BaseModel):
    """A single logic block."""

    block_id: NonEmptyStr
    block_type: str = Field(description="pid, mode, schedule, alarm, etc.")
    name: str
    description: str = ""
    signals: list[LogicSignal] = Field(default_factory=list)
    parameters: list[LogicParameter] = Field(default_factory=list)
    position: tuple[float, float] = (0.0, 0.0)
    enabled: bool = True
    metadata: dict = Field(default_factory=dict)


class LogicDiagram(BaseModel):
    """Complete logic diagram."""

    diagram_id: NonEmptyStr
    name: str
    equipment_id: Optional[NonEmptyStr] = None
    description: str = ""
    blocks: list[LogicBlock] = Field(default_factory=list)
    connections: list[LogicConnection] = Field(default_factory=list)
    version: str = "1.0"
    created_at: datetime = Field(default_factory=datetime.now)
    created_by: str = "BAS Assistant"
    metadata: dict = Field(default_factory=dict)

    def add_block(self, block: LogicBlock) -> None:
        self.blocks.append(block)

    def add_connection(self, conn: LogicConnection) -> None:
        self.connections.append(conn)

    def get_block(self, block_id: str):
        return next((b for b in self.blocks if b.block_id == block_id), None)


__all__ = ["LogicSignal", "LogicParameter", "LogicConnection", "LogicBlock", "LogicDiagram"]