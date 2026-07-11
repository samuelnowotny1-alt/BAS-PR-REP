"""Core type definitions for BAS Assistant."""

from enum import Enum
from typing import Annotated, Literal
from pydantic import BaseModel, Field, field_validator
from pydantic.types import NonNegativeFloat, NonNegativeInt


class PointKind(str, Enum):
    """BAS point kinds."""

    SENSOR = "sensor"
    ACTUATOR = "actuator"
    SETPOINT = "setpoint"
    STATUS = "status"
    ALARM = "alarm"
    TREND = "trend"
    SCHEDULE = "schedule"
    CALCULATED = "calculated"
    PARAMETER = "parameter"
    DERIVED = "derived"


class PointDirection(str, Enum):
    """Point direction relative to controller."""

    INPUT = "input"
    OUTPUT = "output"
    BIDIRECTIONAL = "bidirectional"


class PointSource(str, Enum):
    """Source of point definition."""

    POINT_LIST = "point_list"
    BACNET = "bacnet"
    MODBUS = "modbus"
    DRAWING = "drawing"
    SUBMITTAL = "submittal"
    SEQUENCE = "sequence"
    MANUAL = "manual"


class EquipmentType(str, Enum):
    """Standard BAS equipment types."""

    AHU = "AHU"
    RTU = "RTU"
    VAV = "VAV"
    FAN_COIL = "FCU"
    CHILLER = "CHILLER"
    BOILER = "BOILER"
    COOLING_TOWER = "CT"
    PUMP_HW = "PUMP_HW"
    PUMP_CHW = "PUMP_CHW"
    PUMP_CW = "PUMP_CW"
    HEAT_EXCHANGER = "HX"
    AIR_COMPRESSOR = "AC"
    EXHAUST_FAN = "EF"
    SUPPLY_FAN = "SF"
    RETURN_FAN = "RF"
    RELIEF_FAN = "RLF"
    HUMIDIFIER = "HUM"
    DEHUMIDIFIER = "DEHUM"
    ENERGY_RECOVERY = "ERU"
    MAKEUP_AIR = "MAU"
    TERMINAL_UNIT = "TU"
    CUSTOM = "CUSTOM"


class Protocol(str, Enum):
    """Communication protocols."""

    BACNET_IP = "BACnet/IP"
    BACNET_MSTP = "BACnet/MSTP"
    MODBUS_TCP = "Modbus/TCP"
    MODBUS_RTU = "Modbus/RTU"
    LONWORKS = "LonWorks"
    N2 = "N2"
    OPC_UA = "OPC-UA"
    MQTT = "MQTT"
    CUSTOM = "CUSTOM"


class ValidationSeverity(str, Enum):
    """Validation issue severity."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationCategory(str, Enum):
    """Validation rule categories."""

    NAMING = "naming"
    COMPLETENESS = "completeness"
    CONSISTENCY = "consistency"
    ENGINEERING = "engineering"
    PROTOCOL = "protocol"
    CAPACITY = "capacity"


class UnitSystem(str, Enum):
    """Unit system."""

    IP = "IP"  # Imperial
    SI = "SI"  # Metric


# Common field types
NonEmptyStr = Annotated[str, Field(min_length=1)]
PositiveFloat = Annotated[float, Field(gt=0)]
NonNegInt = Annotated[int, Field(ge=0)]

# Re-export
__all__ = [
    "PointKind",
    "PointDirection",
    "PointSource",
    "EquipmentType",
    "Protocol",
    "ValidationSeverity",
    "ValidationCategory",
    "UnitSystem",
    "NonEmptyStr",
    "PositiveFloat",
    "NonNegInt",
]