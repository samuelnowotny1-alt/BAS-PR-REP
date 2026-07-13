#!/usr/bin/env python3
"""Load a production-grade BAS demo project and generate derived artifacts."""

from __future__ import annotations

import csv
import json
import os
import sys
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

# Add project root to path.
sys.path.insert(0, str(Path(__file__).parent.parent))

from bas_assistant.exporters import (
    BACnetExporter,
    HoneywellExporter,
    JCIExporter,
    NiagaraExporter,
    SiemensExporter,
    TridiumExporter,
)
from bas_assistant.generators import (
    generate_checkout_sheets,
    generate_graphics,
    generate_logic,
    generate_reports,
)
from bas_assistant.importers import CSVImporter
from bas_assistant.models import Project, ProjectMetadata, UnitSystem
from bas_assistant.reasoning import analyze_gaps
from bas_assistant.validation import ValidationEngine

DEMO_PROJECT_ID = "demo-hvac-project"
DEMO_PROJECT_NAME = "Demo HVAC Project"

EQUIPMENT_POINT_TEMPLATES: dict[str, list[tuple[str, str, str, str, str]]] = {
    "CHILLER": [
        ("CHWST", "sensor", "input", "degF", "AI"),
        ("CHWRT", "sensor", "input", "degF", "AI"),
        ("CDWST", "sensor", "input", "degF", "AI"),
        ("CDWRT", "sensor", "input", "degF", "AI"),
        ("AMPS", "sensor", "input", "A", "AI"),
        ("KW", "sensor", "input", "kW", "AI"),
        ("STATUS", "status", "input", "", "BI"),
        ("ALARM", "alarm", "input", "", "BI"),
        ("VFD SPEED", "sensor", "input", "%", "AI"),
        ("VANE POS", "sensor", "input", "%", "AI"),
    ],
    "PUMP_CHW": [
        ("STATUS", "status", "input", "", "BI"),
        ("CMD", "actuator", "output", "%", "AO"),
        ("SPEED", "sensor", "input", "%", "AI"),
        ("AMPS", "sensor", "input", "A", "AI"),
        ("FLOW", "sensor", "input", "GPM", "AI"),
        ("DISCH P", "sensor", "input", "psi", "AI"),
        ("SUCT P", "sensor", "input", "psi", "AI"),
    ],
    "PUMP_CW": [
        ("STATUS", "status", "input", "", "BI"),
        ("CMD", "actuator", "output", "%", "AO"),
        ("SPEED", "sensor", "input", "%", "AI"),
        ("AMPS", "sensor", "input", "A", "AI"),
        ("FLOW", "sensor", "input", "GPM", "AI"),
        ("DISCH P", "sensor", "input", "psi", "AI"),
        ("SUCT P", "sensor", "input", "psi", "AI"),
    ],
    "COOLING_TOWER": [
        ("CWT", "sensor", "input", "degF", "AI"),
        ("LWT", "sensor", "input", "degF", "AI"),
        ("FAN CMD", "actuator", "output", "%", "AO"),
        ("FAN SPEED", "sensor", "input", "%", "AI"),
        ("FAN STATUS", "status", "input", "", "BI"),
        ("BASIN LEVEL", "sensor", "input", "ft", "AI"),
        ("VIBRATION", "sensor", "input", "in/s", "AI"),
    ],
    "BOILER": [
        ("HWS", "sensor", "input", "degF", "AI"),
        ("HWR", "sensor", "input", "degF", "AI"),
        ("FLAME", "status", "input", "", "BI"),
        ("STATUS", "status", "input", "", "BI"),
        ("ALARM", "alarm", "input", "", "BI"),
        ("FIRING RATE", "sensor", "input", "%", "AI"),
        ("SUPPLY T", "sensor", "input", "degF", "AI"),
        ("RETURN T", "sensor", "input", "degF", "AI"),
        ("O2", "sensor", "input", "%", "AI"),
    ],
    "PUMP_HW": [
        ("STATUS", "status", "input", "", "BI"),
        ("CMD", "actuator", "output", "%", "AO"),
        ("SPEED", "sensor", "input", "%", "AI"),
        ("AMPS", "sensor", "input", "A", "AI"),
        ("FLOW", "sensor", "input", "GPM", "AI"),
        ("DISCH P", "sensor", "input", "psi", "AI"),
        ("SUCT P", "sensor", "input", "psi", "AI"),
    ],
    "AHU": [
        ("SAT", "sensor", "input", "degF", "AI"),
        ("MAT", "sensor", "input", "degF", "AI"),
        ("RAT", "sensor", "input", "degF", "AI"),
        ("OAT", "sensor", "input", "degF", "AI"),
        ("OA HUM", "sensor", "input", "%RH", "AI"),
        ("RA HUM", "sensor", "input", "%RH", "AI"),
        ("SF CMD", "actuator", "output", "%", "AO"),
        ("SF STATUS", "status", "input", "", "BI"),
        ("SF VFD", "sensor", "input", "%", "AI"),
        ("RF CMD", "actuator", "output", "%", "AO"),
        ("RF STATUS", "status", "input", "", "BI"),
        ("RF VFD", "sensor", "input", "%", "AI"),
        ("OA DAMPER", "actuator", "output", "%", "AO"),
        ("RA DAMPER", "actuator", "output", "%", "AO"),
        ("EA DAMPER", "actuator", "output", "%", "AO"),
        ("CLG VALVE", "actuator", "output", "%", "AO"),
        ("HTG VALVE", "actuator", "output", "%", "AO"),
        ("DUCT SP", "sensor", "input", "inWC", "AI"),
        ("FILTER DP", "sensor", "input", "inWC", "AI"),
        ("FREEZE STAT", "alarm", "input", "", "BI"),
        ("DUCT SMOKE", "alarm", "input", "", "BI"),
        ("FIRE ALARM", "alarm", "input", "", "BI"),
    ],
    "RTU": [
        ("SAT", "sensor", "input", "degF", "AI"),
        ("RAT", "sensor", "input", "degF", "AI"),
        ("OAT", "sensor", "input", "degF", "AI"),
        ("ZONE T", "sensor", "input", "degF", "AI"),
        ("SF CMD", "actuator", "output", "%", "AO"),
        ("SF STATUS", "status", "input", "", "BI"),
        ("OA DAMPER", "actuator", "output", "%", "AO"),
        ("CLG STAGE1", "actuator", "output", "", "BO"),
        ("CLG STAGE2", "actuator", "output", "", "BO"),
        ("HTG STAGE1", "actuator", "output", "", "BO"),
        ("HTG STAGE2", "actuator", "output", "", "BO"),
        ("FILTER DP", "sensor", "input", "inWC", "AI"),
        ("FREEZE STAT", "alarm", "input", "", "BI"),
        ("SMOKE", "alarm", "input", "", "BI"),
    ],
    "ENERGY_RECOVERY": [
        ("OA TEMP", "sensor", "input", "degF", "AI"),
        ("EA TEMP", "sensor", "input", "degF", "AI"),
        ("SA TEMP", "sensor", "input", "degF", "AI"),
        ("RA TEMP", "sensor", "input", "degF", "AI"),
        ("WHEEL CMD", "actuator", "output", "%", "AO"),
        ("WHEEL STATUS", "status", "input", "", "BI"),
        ("BYPASS DAMPER", "actuator", "output", "%", "AO"),
        ("EXH FAN CMD", "actuator", "output", "%", "AO"),
        ("EXH FAN STATUS", "status", "input", "", "BI"),
        ("SUP FAN CMD", "actuator", "output", "%", "AO"),
        ("SUP FAN STATUS", "status", "input", "", "BI"),
        ("FILTER DP", "sensor", "input", "inWC", "AI"),
    ],
    "VAV": [
        ("FLOW", "sensor", "input", "CFM", "AI"),
        ("FLOW SP", "setpoint", "input", "CFM", "AV"),
        ("DAMPER", "actuator", "output", "%", "AO"),
        ("ZT", "sensor", "input", "degF", "AI"),
        ("ZT SP", "setpoint", "input", "degF", "AV"),
        ("REHEAT CMD", "actuator", "output", "%", "AO"),
        ("OCC", "status", "input", "", "BI"),
        ("FAN CMD", "actuator", "output", "", "BO"),
        ("FAN STATUS", "status", "input", "", "BI"),
    ],
    "FAN_COIL": [
        ("ZT", "sensor", "input", "degF", "AI"),
        ("ZT SP", "setpoint", "input", "degF", "AV"),
        ("FAN CMD", "actuator", "output", "%", "AO"),
        ("FAN STATUS", "status", "input", "", "BI"),
        ("CLG VALVE", "actuator", "output", "%", "AO"),
        ("HTG VALVE", "actuator", "output", "%", "AO"),
        ("OCC", "status", "input", "", "BI"),
    ],
    "EXHAUST_FAN": [
        ("CMD", "actuator", "output", "", "BO"),
        ("STATUS", "status", "input", "", "BI"),
        ("SPEED", "sensor", "input", "%", "AI"),
        ("FLOW", "sensor", "input", "CFM", "AI"),
        ("VIBRATION", "sensor", "input", "in/s", "AI"),
    ],
    "MAKEUP_AIR": [
        ("SAT", "sensor", "input", "degF", "AI"),
        ("OAT", "sensor", "input", "degF", "AI"),
        ("SF CMD", "actuator", "output", "%", "AO"),
        ("SF STATUS", "status", "input", "", "BI"),
        ("BURNER CMD", "actuator", "output", "%", "AO"),
        ("BURNER STATUS", "status", "input", "", "BI"),
        ("FLAME", "status", "input", "", "BI"),
        ("FILTER DP", "sensor", "input", "inWC", "AI"),
        ("FREEZE STAT", "alarm", "input", "", "BI"),
    ],
    "HEAT_EXCHANGER": [
        ("PRI EWT", "sensor", "input", "degF", "AI"),
        ("PRI LWT", "sensor", "input", "degF", "AI"),
        ("SEC EWT", "sensor", "input", "degF", "AI"),
        ("SEC LWT", "sensor", "input", "degF", "AI"),
        ("FLOW", "sensor", "input", "GPM", "AI"),
        ("STATUS", "status", "input", "", "BI"),
    ],
    "TERMINAL_UNIT": [
        ("ZT", "sensor", "input", "degF", "AI"),
        ("ZT SP", "setpoint", "input", "degF", "AV"),
        ("FAN CMD", "actuator", "output", "", "BO"),
        ("FAN STATUS", "status", "input", "", "BI"),
        ("VALVE CMD", "actuator", "output", "%", "AO"),
        ("STATUS", "status", "input", "", "BI"),
    ],
}

EQUIPMENT_DATA = [
    {
        "Equipment ID": "CHLR-1",
        "Equipment Type": "CHILLER",
        "Subtype": "Centrifugal",
        "Building": "Central",
        "Floor": "B",
        "Room": "Chiller Room",
        "Served Area": "Campus CHW Loop",
        "Controller ID": "CPC-1",
        "Parent Equipment": "",
        "Child Equipment": "CHWP-1,CHWP-2,CT-1",
        "Design CFM": "",
        "Design Tonnage": "500",
        "Design GPM": "1200",
        "Design kW": "400",
        "Voltage": "460",
        "Phase": "3",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Primary centrifugal chiller for the campus chilled water loop.",
    },
    {
        "Equipment ID": "CHWP-1",
        "Equipment Type": "PUMP_CHW",
        "Subtype": "Primary",
        "Building": "Central",
        "Floor": "B",
        "Room": "Chiller Room",
        "Served Area": "CHLR-1 Primary Loop",
        "Controller ID": "CPC-1",
        "Parent Equipment": "CHLR-1",
        "Child Equipment": "",
        "Design CFM": "",
        "Design Tonnage": "",
        "Design GPM": "1200",
        "Design kW": "75",
        "Voltage": "460",
        "Phase": "3",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Lead chilled water pump.",
    },
    {
        "Equipment ID": "CHWP-2",
        "Equipment Type": "PUMP_CHW",
        "Subtype": "Standby",
        "Building": "Central",
        "Floor": "B",
        "Room": "Chiller Room",
        "Served Area": "CHLR-1 Primary Loop",
        "Controller ID": "CPC-1",
        "Parent Equipment": "CHLR-1",
        "Child Equipment": "",
        "Design CFM": "",
        "Design Tonnage": "",
        "Design GPM": "1200",
        "Design kW": "75",
        "Voltage": "460",
        "Phase": "3",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Standby chilled water pump.",
    },
    {
        "Equipment ID": "CT-1",
        "Equipment Type": "COOLING_TOWER",
        "Subtype": "Open Circuit",
        "Building": "Central",
        "Floor": "Roof",
        "Room": "Tower Deck",
        "Served Area": "CHLR-1 Condenser Loop",
        "Controller ID": "CPC-1",
        "Parent Equipment": "CHLR-1",
        "Child Equipment": "CWP-1,CWP-2",
        "Design CFM": "200000",
        "Design Tonnage": "500",
        "Design GPM": "1500",
        "Design kW": "50",
        "Voltage": "460",
        "Phase": "3",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Cooling tower serving the condenser loop.",
    },
    {
        "Equipment ID": "CWP-1",
        "Equipment Type": "PUMP_CW",
        "Subtype": "Primary",
        "Building": "Central",
        "Floor": "B",
        "Room": "Chiller Room",
        "Served Area": "Condenser Water Loop",
        "Controller ID": "CPC-1",
        "Parent Equipment": "CT-1",
        "Child Equipment": "",
        "Design CFM": "",
        "Design Tonnage": "",
        "Design GPM": "1500",
        "Design kW": "60",
        "Voltage": "460",
        "Phase": "3",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Lead condenser water pump.",
    },
    {
        "Equipment ID": "CWP-2",
        "Equipment Type": "PUMP_CW",
        "Subtype": "Standby",
        "Building": "Central",
        "Floor": "B",
        "Room": "Chiller Room",
        "Served Area": "Condenser Water Loop",
        "Controller ID": "CPC-1",
        "Parent Equipment": "CT-1",
        "Child Equipment": "",
        "Design CFM": "",
        "Design Tonnage": "",
        "Design GPM": "1500",
        "Design kW": "60",
        "Voltage": "460",
        "Phase": "3",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Standby condenser water pump.",
    },
    {
        "Equipment ID": "BLR-1",
        "Equipment Type": "BOILER",
        "Subtype": "Condensing",
        "Building": "Central",
        "Floor": "B",
        "Room": "Boiler Room",
        "Served Area": "Campus HWS Loop",
        "Controller ID": "CPC-1",
        "Parent Equipment": "",
        "Child Equipment": "HWP-1,HWP-2,HX-1,RP-1",
        "Design CFM": "",
        "Design Tonnage": "",
        "Design GPM": "300",
        "Design kW": "2000",
        "Voltage": "120",
        "Phase": "1",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Primary condensing boiler plant.",
    },
    {
        "Equipment ID": "HWP-1",
        "Equipment Type": "PUMP_HW",
        "Subtype": "Primary",
        "Building": "Central",
        "Floor": "B",
        "Room": "Boiler Room",
        "Served Area": "Heating Water Loop",
        "Controller ID": "CPC-1",
        "Parent Equipment": "BLR-1",
        "Child Equipment": "",
        "Design CFM": "",
        "Design Tonnage": "",
        "Design GPM": "300",
        "Design kW": "25",
        "Voltage": "460",
        "Phase": "3",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Lead heating water pump.",
    },
    {
        "Equipment ID": "HWP-2",
        "Equipment Type": "PUMP_HW",
        "Subtype": "Standby",
        "Building": "Central",
        "Floor": "B",
        "Room": "Boiler Room",
        "Served Area": "Heating Water Loop",
        "Controller ID": "CPC-1",
        "Parent Equipment": "BLR-1",
        "Child Equipment": "",
        "Design CFM": "",
        "Design Tonnage": "",
        "Design GPM": "300",
        "Design kW": "25",
        "Voltage": "460",
        "Phase": "3",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Standby heating water pump.",
    },
    {
        "Equipment ID": "HX-1",
        "Equipment Type": "HEAT_EXCHANGER",
        "Subtype": "Plate And Frame",
        "Building": "Central",
        "Floor": "B",
        "Room": "Boiler Room",
        "Served Area": "Heating Water Decoupler",
        "Controller ID": "CPC-1",
        "Parent Equipment": "BLR-1",
        "Child Equipment": "",
        "Design CFM": "",
        "Design Tonnage": "",
        "Design GPM": "180",
        "Design kW": "",
        "Voltage": "120",
        "Phase": "1",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Plate-and-frame heat exchanger isolating the hydronic loop.",
    },
    {
        "Equipment ID": "RP-1",
        "Equipment Type": "PUMP_HW",
        "Subtype": "Recirculation",
        "Building": "Central",
        "Floor": "B",
        "Room": "Boiler Room",
        "Served Area": "Heating Water Bypass",
        "Controller ID": "CPC-1",
        "Parent Equipment": "BLR-1",
        "Child Equipment": "",
        "Design CFM": "",
        "Design Tonnage": "",
        "Design GPM": "120",
        "Design kW": "15",
        "Voltage": "460",
        "Phase": "3",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Recirculation pump for minimum flow maintenance.",
    },
    {
        "Equipment ID": "AHU-1",
        "Equipment Type": "AHU",
        "Subtype": "VAV",
        "Building": "Main",
        "Floor": "1",
        "Room": "Mechanical",
        "Served Area": "Floor 1 Office Wing",
        "Controller ID": "MPC-1",
        "Parent Equipment": "",
        "Child Equipment": "VAV-101,VAV-102,VAV-103,VAV-104",
        "Design CFM": "25000",
        "Design Tonnage": "60",
        "Design GPM": "120",
        "Design kW": "40",
        "Voltage": "460",
        "Phase": "3",
        "Status": "design",
        "Graphic Sections": "outside_air,mixed_air,filter,cooling_coil,heating_coil,supply_fan,return_fan,discharge",
        "Notes": "Main air handler serving the first floor VAV system.",
    },
    {
        "Equipment ID": "AHU-2",
        "Equipment Type": "AHU",
        "Subtype": "Constant Volume",
        "Building": "Main",
        "Floor": "2",
        "Room": "Mechanical",
        "Served Area": "Laboratory Wing",
        "Controller ID": "MPC-2",
        "Parent Equipment": "",
        "Child Equipment": "",
        "Design CFM": "15000",
        "Design Tonnage": "35",
        "Design GPM": "70",
        "Design kW": "25",
        "Voltage": "460",
        "Phase": "3",
        "Status": "design",
        "Graphic Sections": "outside_air,filter,cooling_coil,heating_coil,supply_fan,return_fan,discharge",
        "Notes": "Constant volume lab air handler.",
    },
    {
        "Equipment ID": "DOAS-1",
        "Equipment Type": "AHU",
        "Subtype": "Dedicated Outdoor Air",
        "Building": "Main",
        "Floor": "Roof",
        "Room": "Penthouse",
        "Served Area": "Third Floor Perimeter",
        "Controller ID": "MPC-2",
        "Parent Equipment": "",
        "Child Equipment": "FCU-1,UH-1",
        "Design CFM": "9500",
        "Design Tonnage": "28",
        "Design GPM": "48",
        "Design kW": "18",
        "Voltage": "460",
        "Phase": "3",
        "Status": "design",
        "Graphic Sections": "outside_air,energy_recovery,filter,cooling_coil,heating_coil,supply_fan,discharge",
        "Notes": "Dedicated outdoor air unit for ventilation and latent load control.",
    },
    {
        "Equipment ID": "RTU-1",
        "Equipment Type": "RTU",
        "Subtype": "Packaged Gas Electric",
        "Building": "Main",
        "Floor": "Roof",
        "Room": "Roof",
        "Served Area": "Gymnasium",
        "Controller ID": "MPC-2",
        "Parent Equipment": "",
        "Child Equipment": "",
        "Design CFM": "8000",
        "Design Tonnage": "20",
        "Design GPM": "",
        "Design kW": "80",
        "Voltage": "460",
        "Phase": "3",
        "Status": "design",
        "Graphic Sections": "outside_air,filter,cooling_coil,heating_coil,supply_fan,discharge",
        "Notes": "Packaged rooftop unit serving the gym.",
    },
    {
        "Equipment ID": "ERU-1",
        "Equipment Type": "ENERGY_RECOVERY",
        "Subtype": "Enthalpy Wheel",
        "Building": "Main",
        "Floor": "Roof",
        "Room": "Roof",
        "Served Area": "AHU-1 Preconditioning",
        "Controller ID": "MPC-1",
        "Parent Equipment": "",
        "Child Equipment": "",
        "Design CFM": "10000",
        "Design Tonnage": "",
        "Design GPM": "",
        "Design kW": "15",
        "Voltage": "460",
        "Phase": "3",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Energy recovery section preconditioning outdoor air.",
    },
    {
        "Equipment ID": "VAV-101",
        "Equipment Type": "VAV",
        "Subtype": "Single Duct Reheat",
        "Building": "Main",
        "Floor": "1",
        "Room": "Zone 101",
        "Served Area": "Office 101",
        "Controller ID": "VAV-101",
        "Parent Equipment": "AHU-1",
        "Child Equipment": "",
        "Design CFM": "1200",
        "Design Tonnage": "",
        "Design GPM": "4",
        "Design kW": "2",
        "Voltage": "120",
        "Phase": "1",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Office VAV with reheat.",
    },
    {
        "Equipment ID": "VAV-102",
        "Equipment Type": "VAV",
        "Subtype": "Single Duct Reheat",
        "Building": "Main",
        "Floor": "1",
        "Room": "Zone 102",
        "Served Area": "Office 102",
        "Controller ID": "VAV-102",
        "Parent Equipment": "AHU-1",
        "Child Equipment": "",
        "Design CFM": "1000",
        "Design Tonnage": "",
        "Design GPM": "3",
        "Design kW": "1.5",
        "Voltage": "120",
        "Phase": "1",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Office VAV with reheat.",
    },
    {
        "Equipment ID": "VAV-103",
        "Equipment Type": "VAV",
        "Subtype": "Single Duct Reheat",
        "Building": "Main",
        "Floor": "1",
        "Room": "Zone 103",
        "Served Area": "Conference 103",
        "Controller ID": "MPC-1",
        "Parent Equipment": "AHU-1",
        "Child Equipment": "",
        "Design CFM": "1500",
        "Design Tonnage": "",
        "Design GPM": "5",
        "Design kW": "2.5",
        "Voltage": "120",
        "Phase": "1",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Conference room VAV with reheat.",
    },
    {
        "Equipment ID": "VAV-104",
        "Equipment Type": "VAV",
        "Subtype": "Fan Powered",
        "Building": "Main",
        "Floor": "1",
        "Room": "Zone 104",
        "Served Area": "Perimeter 104",
        "Controller ID": "MPC-1",
        "Parent Equipment": "AHU-1",
        "Child Equipment": "",
        "Design CFM": "800",
        "Design Tonnage": "",
        "Design GPM": "3",
        "Design kW": "1",
        "Voltage": "120",
        "Phase": "1",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Fan-powered perimeter VAV box.",
    },
    {
        "Equipment ID": "FCU-1",
        "Equipment Type": "FAN_COIL",
        "Subtype": "Four Pipe",
        "Building": "Main",
        "Floor": "3",
        "Room": "Zone 301",
        "Served Area": "Office 301",
        "Controller ID": "MPC-2",
        "Parent Equipment": "DOAS-1",
        "Child Equipment": "",
        "Design CFM": "600",
        "Design Tonnage": "2",
        "Design GPM": "3",
        "Design kW": "0.5",
        "Voltage": "120",
        "Phase": "1",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Perimeter fan coil unit.",
    },
    {
        "Equipment ID": "MAU-1",
        "Equipment Type": "MAKEUP_AIR",
        "Subtype": "Direct Fired",
        "Building": "Main",
        "Floor": "Roof",
        "Room": "Roof",
        "Served Area": "Kitchen Makeup Air",
        "Controller ID": "MPC-2",
        "Parent Equipment": "",
        "Child Equipment": "",
        "Design CFM": "6000",
        "Design Tonnage": "",
        "Design GPM": "",
        "Design kW": "300",
        "Voltage": "460",
        "Phase": "3",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Kitchen makeup air unit.",
    },
    {
        "Equipment ID": "EF-1",
        "Equipment Type": "EXHAUST_FAN",
        "Subtype": "Centrifugal",
        "Building": "Main",
        "Floor": "Roof",
        "Room": "Roof",
        "Served Area": "General Exhaust",
        "Controller ID": "MPC-2",
        "Parent Equipment": "",
        "Child Equipment": "",
        "Design CFM": "5000",
        "Design Tonnage": "",
        "Design GPM": "",
        "Design kW": "5",
        "Voltage": "460",
        "Phase": "3",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "General exhaust fan.",
    },
    {
        "Equipment ID": "UH-1",
        "Equipment Type": "TERMINAL_UNIT",
        "Subtype": "Unit Heater",
        "Building": "Main",
        "Floor": "3",
        "Room": "Vestibule",
        "Served Area": "Loading Vestibule",
        "Controller ID": "MPC-2",
        "Parent Equipment": "DOAS-1",
        "Child Equipment": "",
        "Design CFM": "450",
        "Design Tonnage": "",
        "Design GPM": "2",
        "Design kW": "0.25",
        "Voltage": "120",
        "Phase": "1",
        "Status": "design",
        "Graphic Sections": "",
        "Notes": "Hydronic unit heater in the loading vestibule.",
    },
]

CONTROLLER_BLUEPRINTS = [
    {
        "Controller ID": "CPC-1",
        "Name": "Central Plant Controller 1",
        "Vendor": "Johnson Controls",
        "Model": "MPC-8000",
        "Firmware": "12.3",
        "Type": "MPC",
        "Protocols": "BACnet/IP",
        "IP Address": "192.168.10.10",
        "Panel Location": "Chiller Room Panel CP-1",
        "Electrical Panel": "MP-1",
        "Circuit": "12",
        "Universal Inputs": "64",
        "Digital Inputs": "32",
        "Analog Outputs": "16",
        "Digital Outputs": "16",
        "Total Points": "128",
        "Status": "design",
        "Notes": "Central plant supervisory controller.",
    },
    {
        "Controller ID": "MPC-1",
        "Name": "Main Airside Controller 1",
        "Vendor": "Johnson Controls",
        "Model": "MPC-8000",
        "Firmware": "12.3",
        "Type": "MPC",
        "Protocols": "BACnet/IP",
        "IP Address": "192.168.10.11",
        "Panel Location": "Mechanical Room Panel MP-1",
        "Electrical Panel": "MP-1",
        "Circuit": "14",
        "Universal Inputs": "48",
        "Digital Inputs": "24",
        "Analog Outputs": "12",
        "Digital Outputs": "12",
        "Total Points": "96",
        "Status": "design",
        "Notes": "Primary airside controller for AHU-1 and downstream VAVs.",
    },
    {
        "Controller ID": "MPC-2",
        "Name": "Main Airside Controller 2",
        "Vendor": "Johnson Controls",
        "Model": "MPC-8000",
        "Firmware": "12.3",
        "Type": "MPC",
        "Protocols": "BACnet/IP",
        "IP Address": "192.168.10.12",
        "Panel Location": "Mechanical Room Panel MP-2",
        "Electrical Panel": "MP-2",
        "Circuit": "16",
        "Universal Inputs": "48",
        "Digital Inputs": "24",
        "Analog Outputs": "12",
        "Digital Outputs": "12",
        "Total Points": "96",
        "Status": "design",
        "Notes": "Secondary airside controller for roof and third-floor systems.",
    },
    {
        "Controller ID": "VAV-101",
        "Name": "VAV-101 Terminal Controller",
        "Vendor": "Johnson Controls",
        "Model": "VAV-3000",
        "Firmware": "5.2",
        "Type": "VAV",
        "Protocols": "BACnet/MSTP",
        "IP Address": "",
        "Panel Location": "Zone 101 Ceiling",
        "Electrical Panel": "LP-1",
        "Circuit": "8",
        "Universal Inputs": "4",
        "Digital Inputs": "2",
        "Analog Outputs": "2",
        "Digital Outputs": "2",
        "Total Points": "10",
        "Status": "design",
        "Notes": "Terminal controller on the floor 1 MSTP trunk.",
        "MS/TP MAC": "11",
        "Network Number": "2001",
    },
    {
        "Controller ID": "VAV-102",
        "Name": "VAV-102 Terminal Controller",
        "Vendor": "Johnson Controls",
        "Model": "VAV-3000",
        "Firmware": "5.2",
        "Type": "VAV",
        "Protocols": "BACnet/MSTP",
        "IP Address": "",
        "Panel Location": "Zone 102 Ceiling",
        "Electrical Panel": "LP-1",
        "Circuit": "10",
        "Universal Inputs": "4",
        "Digital Inputs": "2",
        "Analog Outputs": "2",
        "Digital Outputs": "2",
        "Total Points": "10",
        "Status": "design",
        "Notes": "Terminal controller on the floor 1 MSTP trunk.",
        "MS/TP MAC": "12",
        "Network Number": "2001",
    },
]


def _template_for_equipment_type(equipment_type: str) -> list[tuple[str, str, str, str, str]]:
    return EQUIPMENT_POINT_TEMPLATES.get(equipment_type, EQUIPMENT_POINT_TEMPLATES["AHU"])


def _point_names_for_row(row: dict[str, str]) -> list[str]:
    equip_id = row["Equipment ID"]
    return [f"{equip_id} {suffix}" for suffix, *_ in _template_for_equipment_type(row["Equipment Type"])]


def build_point_list(equipment_rows: list[dict[str, str]] | None = None) -> list[dict[str, object]]:
    """Generate deterministic point rows from the equipment seed data."""
    rows = equipment_rows or EQUIPMENT_DATA
    points: list[dict[str, object]] = []
    point_instance = 1

    for row in rows:
        equip_id = row["Equipment ID"]
        equip_type = row["Equipment Type"]
        controller_id = row["Controller ID"]

        for suffix, kind, direction, units, bacnet_type in _template_for_equipment_type(equip_type):
            point_name = f"{equip_id} {suffix}"
            points.append(
                {
                    "Point Name": point_name,
                    "Equipment ID": equip_id,
                    "Point Kind": kind,
                    "Direction": direction,
                    "Units": units,
                    "Unit System": "IP",
                    "Range Min": "",
                    "Range Max": "",
                    "Controller ID": controller_id,
                    "BACnet Object Type": bacnet_type,
                    "BACnet Instance": point_instance,
                    "Modbus Register": "",
                    "Modbus Type": "",
                    "Source": "point_list",
                    "Source Reference": point_name,
                    "Description": point_name,
                    "Tags": f"{equip_type.lower()},{suffix.lower().replace(' ', '_')}",
                }
            )
            point_instance += 1

    return points


def build_controller_rows(
    equipment_rows: list[dict[str, str]],
    point_rows: list[dict[str, object]],
) -> list[dict[str, str]]:
    """Build controller rows from static blueprints and dynamic point ownership."""
    equipment_by_controller: dict[str, list[str]] = defaultdict(list)
    points_by_controller: dict[str, list[str]] = defaultdict(list)

    for row in equipment_rows:
        equipment_by_controller[row["Controller ID"]].append(row["Equipment ID"])

    for row in point_rows:
        controller_id = str(row["Controller ID"])
        points_by_controller[controller_id].append(str(row["Point Name"]))

    controller_rows: list[dict[str, str]] = []
    for blueprint in CONTROLLER_BLUEPRINTS:
        row = deepcopy(blueprint)
        controller_id = row["Controller ID"]
        row["Serves Equipment"] = ",".join(equipment_by_controller[controller_id])
        row["Owned Points"] = ",".join(points_by_controller[controller_id])
        controller_rows.append(row)

    return controller_rows


def build_demo_seed_rows() -> tuple[list[dict[str, str]], list[dict[str, object]], list[dict[str, str]]]:
    """Return the seed rows used to build the canonical demo project."""
    equipment_rows = deepcopy(EQUIPMENT_DATA)
    for row in equipment_rows:
        row["Points"] = ",".join(_point_names_for_row(row))

    point_rows = build_point_list(equipment_rows)
    controller_rows = build_controller_rows(equipment_rows, point_rows)
    return equipment_rows, point_rows, controller_rows


def write_rich_example_csvs(examples_dir: Path) -> None:
    """Write the demo seed CSV files that ship with the project."""
    examples_dir.mkdir(parents=True, exist_ok=True)
    equipment_rows, point_rows, controller_rows = build_demo_seed_rows()

    equipment_fields = [
        "Equipment ID",
        "Equipment Type",
        "Subtype",
        "Building",
        "Floor",
        "Room",
        "Served Area",
        "Controller ID",
        "Parent Equipment",
        "Child Equipment",
        "Points",
        "Design CFM",
        "Design Tonnage",
        "Design GPM",
        "Design kW",
        "Voltage",
        "Phase",
        "Status",
        "Graphic Sections",
        "Notes",
    ]
    with (examples_dir / "equipment_schedule.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=equipment_fields)
        writer.writeheader()
        writer.writerows(equipment_rows)

    point_fields = [
        "Point Name",
        "Equipment ID",
        "Point Kind",
        "Direction",
        "Units",
        "Unit System",
        "Range Min",
        "Range Max",
        "Controller ID",
        "BACnet Object Type",
        "BACnet Instance",
        "Modbus Register",
        "Modbus Type",
        "Source",
        "Source Reference",
        "Description",
        "Tags",
    ]
    with (examples_dir / "point_list.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=point_fields)
        writer.writeheader()
        writer.writerows(point_rows)

    controller_fields = [
        "Controller ID",
        "Name",
        "Vendor",
        "Model",
        "Firmware",
        "Type",
        "Protocols",
        "IP Address",
        "Panel Location",
        "Electrical Panel",
        "Circuit",
        "Serves Equipment",
        "Owned Points",
        "Universal Inputs",
        "Digital Inputs",
        "Analog Outputs",
        "Digital Outputs",
        "Total Points",
        "Status",
        "Notes",
        "MS/TP MAC",
        "Network Number",
    ]
    with (examples_dir / "controller_schedule.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=controller_fields)
        writer.writeheader()
        writer.writerows(controller_rows)

    print(f"  Wrote {len(equipment_rows)} equipment rows")
    print(f"  Wrote {len(point_rows)} point rows")
    print(f"  Wrote {len(controller_rows)} controller rows")


def _build_project_metadata(project_id: str, project_name: str) -> ProjectMetadata:
    return ProjectMetadata(
        project_id=project_id,
        name=project_name,
        client="BAS Assistant Demo",
        location="Demo Campus",
        unit_system=UnitSystem.IP,
        design_phase="Design Development",
        engineer_of_record="BAS Assistant Engineering",
        programmer="BAS Assistant Controls",
        commissioning_agent="BAS Assistant Cx",
        naming_standard="ASHRAE 135",
        bacnet_network_number=2001,
    )


def load_demo_project(
    data_dir: Path,
    examples_dir: Path,
    project_id: str = DEMO_PROJECT_ID,
    project_name: str = DEMO_PROJECT_NAME,
) -> Project:
    """Build the demo project from fresh seed data and save it to disk."""
    project_dir = data_dir / "projects" / project_id
    project_file = project_dir / "project.json"

    write_rich_example_csvs(examples_dir)
    project = Project(metadata=_build_project_metadata(project_id, project_name))
    importer = CSVImporter(project)

    equip_file = examples_dir / "equipment_schedule.csv"
    points_file = examples_dir / "point_list.csv"
    ctrl_file = examples_dir / "controller_schedule.csv"

    equip_result = importer.import_equipment_schedule(equip_file, "equipment_schedule_demo")
    print(f"  Equipment: {equip_result.message}")
    for warning in equip_result.warnings:
        print(f"    WARN: {warning}")
    for error in equip_result.errors:
        print(f"    ERROR: {error}")

    points_result = importer.import_point_list(points_file, "point_list_demo")
    print(f"  Points: {points_result.message}")
    for warning in points_result.warnings:
        print(f"    WARN: {warning}")
    for error in points_result.errors:
        print(f"    ERROR: {error}")

    ctrl_result = importer.import_controller_schedule(ctrl_file, "controller_schedule_demo")
    print(f"  Controllers: {ctrl_result.message}")
    for warning in ctrl_result.warnings:
        print(f"    WARN: {warning}")
    for error in ctrl_result.errors:
        print(f"    ERROR: {error}")

    project_dir.mkdir(parents=True, exist_ok=True)
    with project_file.open("w") as handle:
        handle.write(project.model_dump_json(indent=2))

    print(f"Demo project saved to {project_file}")
    print(f"  Equipment: {len(project.equipment)}")
    print(f"  Points: {len(project.points)}")
    print(f"  Controllers: {len(project.controllers)}")
    return project


def generate_outputs(project: Project, output_dir: Path) -> None:
    """Generate all first-class demo outputs for the given project."""
    project_output_dir = output_dir / project.metadata.project_id
    project_output_dir.mkdir(parents=True, exist_ok=True)

    print("\nGenerating demo outputs...")

    engine = ValidationEngine()
    report = engine.validate(project)
    print(f"  Validation: {len(report.errors)} errors, {len(report.warnings)} warnings")

    gap_report = analyze_gaps(project)
    print(f"  Gap Analysis: {gap_report.total_count} gaps found")

    checkout_dir = project_output_dir / "checkout"
    checkout_dir.mkdir(parents=True, exist_ok=True)
    checkout_result = generate_checkout_sheets(project, checkout_dir)
    sheet_count = checkout_result.get(
        "sheet_count",
        len(list(checkout_dir.glob("*.md"))) + len(list(checkout_dir.glob("*.xlsx"))),
    )
    print(f"  Checkout: {sheet_count} sheets")

    reports_dir = project_output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_paths = generate_reports(project, reports_dir)
    print(f"  Reports: {len(report_paths)} files")

    graphics_dir = project_output_dir / "graphics"
    graphics_dir.mkdir(parents=True, exist_ok=True)
    graphics_result = generate_graphics(project, graphics_dir)
    if isinstance(graphics_result, dict):
        graphics_count = sum(len(value) if isinstance(value, list) else 1 for value in graphics_result.values())
    elif isinstance(graphics_result, list):
        graphics_count = len(graphics_result)
    else:
        graphics_count = len(list(graphics_dir.rglob("*")))
    print(f"  Graphics: {graphics_count} files")

    logic_dir = project_output_dir / "logic"
    logic_dir.mkdir(parents=True, exist_ok=True)
    logic_result = generate_logic(project, logic_dir)
    if isinstance(logic_result, dict):
        logic_count = sum(len(value) if isinstance(value, list) else 1 for value in logic_result.values())
    elif isinstance(logic_result, list):
        logic_count = len(logic_result)
    else:
        logic_count = len(list(logic_dir.rglob("*")))
    print(f"  Logic: {logic_count} files")

    exports_dir = project_output_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    vendor_map = {
        "niagara": NiagaraExporter,
        "bacnet": BACnetExporter,
        "tridium": TridiumExporter,
        "jci": JCIExporter,
        "siemens": SiemensExporter,
        "honeywell": HoneywellExporter,
    }
    for vendor_name, exporter_class in vendor_map.items():
        vendor_dir = exports_dir / vendor_name
        vendor_dir.mkdir(parents=True, exist_ok=True)
        exporter = exporter_class(project)
        result = exporter.export(vendor_dir)
        if result.success:
            print(f"  Export {vendor_name}: {len(result.files)} files")
        else:
            print(f"  Export {vendor_name}: FAILED - {result.message}")

    print(f"\nDemo project '{project.metadata.project_id}' fully loaded and ready.")
    print(f"  Outputs at: {project_output_dir}")


def main() -> int:
    base_dir = Path(__file__).parent.parent
    data_dir = Path(os.environ.get("BAS_DATA_DIR", base_dir / "data"))
    output_dir = Path(os.environ.get("BAS_OUTPUT_DIR", base_dir / "ui" / "output"))
    examples_dir = base_dir / "examples"
    project_id = os.environ.get("BAS_DEMO_PROJECT_ID", DEMO_PROJECT_ID)
    project_name = os.environ.get("BAS_DEMO_PROJECT_NAME", DEMO_PROJECT_NAME)

    project = load_demo_project(data_dir, examples_dir, project_id=project_id, project_name=project_name)
    generate_outputs(project, output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
