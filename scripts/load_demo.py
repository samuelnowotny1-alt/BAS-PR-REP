#!/usr/bin/env python3
"""
Demo project loader for BAS Assistant.
Creates a rich "Codex Test Project" with realistic HVAC data on first run.
Idempotent: safe to re-run, refreshes project and example CSVs.
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import csv
from datetime import datetime
from bas_assistant.models import Project, ProjectMetadata, UnitSystem
from bas_assistant.importers import CSVImporter
from bas_assistant.generators import (
    generate_checkout_sheets, generate_reports, generate_graphics, generate_logic
)
from bas_assistant.exporters import (
    NiagaraExporter, BACnetExporter, TridiumExporter,
    JCIExporter, SiemensExporter, HoneywellExporter
)
from bas_assistant.validation import ValidationEngine
from bas_assistant.reasoning import analyze_gaps


# ============================================================
# RICH DEMO DATA DEFINITIONS
# ============================================================

EQUIPMENT_DATA = [
    # Central Plant
    {
        "Equipment ID": "CH-1", "Equipment Type": "CHILLER", "Subtype": "Centrifugal",
        "Building": "Central", "Floor": "B", "Room": "Chiller Room",
        "Served Area": "Campus CHW Loop", "Controller ID": "CPC-1",
        "Parent Equipment": "", "Child Equipment": "CHWP-1,CHWP-2,CT-1",
        "Points": "CH-1 CHWST,CH-1 CHWRT,CH-1 CDWST,CH-1 CDWRT,CH-1 AMPS,CH-1 KW,CH-1 STATUS,CH-1 ALARM,CH-1 VFD SPEED,CH-1 VANE POS",
        "Design CFM": "", "Design Tonnage": "500", "Design GPM": "1200", "Design kW": "400",
        "Voltage": "460", "Phase": "3", "Status": "design",
        "Graphic Sections": "evaporator,condenser,compressor,controls",
        "Notes": "Primary centrifugal chiller, 500 ton"
    },
    {
        "Equipment ID": "CHWP-1", "Equipment Type": "PUMP_CHW", "Subtype": "Primary",
        "Building": "Central", "Floor": "B", "Room": "Chiller Room",
        "Served Area": "CH-1 Primary Loop", "Controller ID": "CPC-1",
        "Parent Equipment": "CH-1", "Child Equipment": "",
        "Points": "CHWP-1 STATUS,CHWP-1 CMD,CHWP-1 SPEED,CHWP-1 AMPS,CHWP-1 FLOW,CHWP-1 DISCH P,CHWP-1 SUCT P",
        "Design CFM": "", "Design Tonnage": "", "Design GPM": "1200", "Design kW": "75",
        "Voltage": "460", "Phase": "3", "Status": "design",
        "Graphic Sections": "pump,motor,vfd,discharge,suction",
        "Notes": "Primary CHW pump for CH-1"
    },
    {
        "Equipment ID": "CHWP-2", "Equipment Type": "PUMP_CHW", "Subtype": "Standby",
        "Building": "Central", "Floor": "B", "Room": "Chiller Room",
        "Served Area": "CH-1 Primary Loop", "Controller ID": "CPC-1",
        "Parent Equipment": "CH-1", "Child Equipment": "",
        "Points": "CHWP-2 STATUS,CHWP-2 CMD,CHWP-2 SPEED,CHWP-2 AMPS,CHWP-2 FLOW,CHWP-2 DISCH P,CHWP-2 SUCT P",
        "Design CFM": "", "Design Tonnage": "", "Design GPM": "1200", "Design kW": "75",
        "Voltage": "460", "Phase": "3", "Status": "design",
        "Graphic Sections": "pump,motor,vfd,discharge,suction",
        "Notes": "Standby CHW pump for CH-1"
    },
    {
        "Equipment ID": "CT-1", "Equipment Type": "COOLING_TOWER", "Subtype": "Open Circuit",
        "Building": "Central", "Floor": "Roof", "Room": "Roof",
        "Served Area": "CH-1 Condenser Loop", "Controller ID": "CPC-1",
        "Parent Equipment": "CH-1", "Child Equipment": "CWP-1,CWP-2",
        "Points": "CT-1 CWT,CT-1 LWT,CT-1 FAN CMD,CT-1 FAN SPEED,CT-1 FAN STATUS,CT-1 BASIN LEVEL,CT-1 VIBRATION",
        "Design CFM": "200000", "Design Tonnage": "500", "Design GPM": "1500", "Design kW": "50",
        "Voltage": "460", "Phase": "3", "Status": "design",
        "Graphic Sections": "fan,basin,fill,drift_eliminator,controls",
        "Notes": "Induced draft cooling tower for CH-1"
    },
    {
        "Equipment ID": "CWP-1", "Equipment Type": "PUMP_CW", "Subtype": "Primary",
        "Building": "Central", "Floor": "B", "Room": "Chiller Room",
        "Served Area": "CH-1 Condenser Loop", "Controller ID": "CPC-1",
        "Parent Equipment": "CT-1", "Child Equipment": "",
        "Points": "CWP-1 STATUS,CWP-1 CMD,CWP-1 SPEED,CWP-1 AMPS,CWP-1 FLOW,CWP-1 DISCH P,CWP-1 SUCT P",
        "Design CFM": "", "Design Tonnage": "", "Design GPM": "1500", "Design kW": "60",
        "Voltage": "460", "Phase": "3", "Status": "design",
        "Graphic Sections": "pump,motor,vfd,discharge,suction",
        "Notes": "Primary condenser water pump"
    },
    {
        "Equipment ID": "CWP-2", "Equipment Type": "PUMP_CW", "Subtype": "Standby",
        "Building": "Central", "Floor": "B", "Room": "Chiller Room",
        "Served Area": "CH-1 Condenser Loop", "Controller ID": "CPC-1",
        "Parent Equipment": "CT-1", "Child Equipment": "",
        "Points": "CWP-2 STATUS,CWP-2 CMD,CWP-2 SPEED,CWP-2 AMPS,CWP-2 FLOW,CWP-2 DISCH P,CWP-2 SUCT P",
        "Design CFM": "", "Design Tonnage": "", "Design GPM": "1500", "Design kW": "60",
        "Voltage": "460", "Phase": "3", "Status": "design",
        "Graphic Sections": "pump,motor,vfd,discharge,suction",
        "Notes": "Standby condenser water pump"
    },
    {
        "Equipment ID": "B-1", "Equipment Type": "BOILER", "Subtype": "Condensing",
        "Building": "Central", "Floor": "B", "Room": "Boiler Room",
        "Served Area": "Campus HWS Loop", "Controller ID": "CPC-1",
        "Parent Equipment": "", "Child Equipment": "HWP-1,HWP-2",
        "Points": "B-1 HWS,B-1 HWR,B-1 FLAME,B-1 STATUS,B-1 ALARM,B-1 FIRING RATE,B-1 SUPPLY T,B-1 RETURN T,B-1 O2",
        "Design CFM": "", "Design Tonnage": "", "Design GPM": "300", "Design kW": "2000",
        "Voltage": "120", "Phase": "1", "Status": "design",
        "Graphic Sections": "burner,heat_exchanger,controls,vent,condensate",
        "Notes": "High-efficiency condensing boiler, 2000 MBH"
    },
    {
        "Equipment ID": "HWP-1", "Equipment Type": "PUMP_HW", "Subtype": "Primary",
        "Building": "Central", "Floor": "B", "Room": "Boiler Room",
        "Served Area": "B-1 Primary Loop", "Controller ID": "CPC-1",
        "Parent Equipment": "B-1", "Child Equipment": "",
        "Points": "HWP-1 STATUS,HWP-1 CMD,HWP-1 SPEED,HWP-1 AMPS,HWP-1 FLOW,HWP-1 DISCH P,HWP-1 SUCT P",
        "Design CFM": "", "Design Tonnage": "", "Design GPM": "300", "Design kW": "25",
        "Voltage": "460", "Phase": "3", "Status": "design",
        "Graphic Sections": "pump,motor,vfd,discharge,suction",
        "Notes": "Primary HW pump for B-1"
    },
    {
        "Equipment ID": "HWP-2", "Equipment Type": "PUMP_HW", "Subtype": "Standby",
        "Building": "Central", "Floor": "B", "Room": "Boiler Room",
        "Served Area": "B-1 Primary Loop", "Controller ID": "CPC-1",
        "Parent Equipment": "B-1", "Child Equipment": "",
        "Points": "HWP-2 STATUS,HWP-2 CMD,HWP-2 SPEED,HWP-2 AMPS,HWP-2 FLOW,HWP-2 DISCH P,HWP-2 SUCT P",
        "Design CFM": "", "Design Tonnage": "", "Design GPM": "300", "Design kW": "25",
        "Voltage": "460", "Phase": "3", "Status": "design",
        "Graphic Sections": "pump,motor,vfd,discharge,suction",
        "Notes": "Standby HW pump for B-1"
    },
    # Air Handling
    {
        "Equipment ID": "AHU-1", "Equipment Type": "AHU", "Subtype": "VAV",
        "Building": "Main", "Floor": "1", "Room": "Mechanical",
        "Served Area": "Floor 1", "Controller ID": "MPC-1",
        "Parent Equipment": "", "Child Equipment": "VAV-101,VAV-102,VAV-103,VAV-104",
        "Points": "AHU-1 SAT,AHU-1 MAT,AHU-1 RAT,AHU-1 OAT,AHU-1 OA HUM,AHU-1 RA HUM,AHU-1 SF CMD,AHU-1 SF STATUS,AHU-1 SF VFD,AHU-1 RF CMD,AHU-1 RF STATUS,AHU-1 RF VFD,AHU-1 OA DAMPER,AHU-1 RA DAMPER,AHU-1 EA DAMPER,AHU-1 CLG VALVE,AHU-1 HTG VALVE,AHU-1 DUCT SP,AHU-1 FILTER DP,AHU-1 FREEZE STAT,AHU-1 DUCT SMOKE,AHU-1 FIRE ALARM",
        "Design CFM": "25000", "Design Tonnage": "60", "Design GPM": "120", "Design kW": "40",
        "Voltage": "460", "Phase": "3", "Status": "design",
        "Graphic Sections": "outside_air,return_air,mixed_air,filter,cooling_coil,heating_coil,supply_fan,return_fan,discharge",
        "Notes": "Main AHU serving Floor 1 VAV boxes"
    },
    {
        "Equipment ID": "AHU-2", "Equipment Type": "AHU", "Subtype": "Constant Volume",
        "Building": "Main", "Floor": "2", "Room": "Mechanical",
        "Served Area": "Floor 2", "Controller ID": "MPC-2",
        "Parent Equipment": "", "Child Equipment": "",
        "Points": "AHU-2 SAT,AHU-2 MAT,AHU-2 RAT,AHU-2 OAT,AHU-2 OA HUM,AHU-2 RA HUM,AHU-2 SF CMD,AHU-2 SF STATUS,AHU-2 RF CMD,AHU-2 RF STATUS,AHU-2 OA DAMPER,AHU-2 RA DAMPER,AHU-2 CLG VALVE,AHU-2 HTG VALVE,AHU-2 DUCT SP,AHU-2 FILTER DP,AHU-2 FREEZE STAT",
        "Design CFM": "15000", "Design Tonnage": "35", "Design GPM": "70", "Design kW": "25",
        "Voltage": "460", "Phase": "3", "Status": "design",
        "Graphic Sections": "outside_air,return_air,mixed_air,filter,cooling_coil,heating_coil,supply_fan,return_fan,discharge",
        "Notes": "Constant volume AHU for Floor 2 labs"
    },
    {
        "Equipment ID": "RTU-1", "Equipment Type": "RTU", "Subtype": "Packaged Gas/Electric",
        "Building": "Main", "Floor": "Roof", "Room": "Roof",
        "Served Area": "Gymnasium", "Controller ID": "MPC-2",
        "Parent Equipment": "", "Child Equipment": "",
        "Points": "RTU-1 SAT,RTU-1 RAT,RTU-1 OAT,RTU-1 ZONE T,RTU-1 SF CMD,RTU-1 SF STATUS,RTU-1 OA DAMPER,RTU-1 CLG STAGE1,RTU-1 CLG STAGE2,RTU-1 HTG STAGE1,RTU-1 HTG STAGE2,RTU-1 FILTER DP,RTU-1 FREEZE STAT,RTU-1 SMOKE",
        "Design CFM": "8000", "Design Tonnage": "20", "Design GPM": "", "Design kW": "80",
        "Voltage": "460", "Phase": "3", "Status": "design",
        "Graphic Sections": "outside_air,filter,cooling_coil,heating_coil,supply_fan,discharge",
        "Notes": "Packaged rooftop unit for gymnasium"
    },
    {
        "Equipment ID": "ERV-1", "Equipment Type": "ENERGY_RECOVERY", "Subtype": "Wheel",
        "Building": "Main", "Floor": "Roof", "Room": "Roof",
        "Served Area": "AHU-1 OA Preconditioning", "Controller ID": "MPC-1",
        "Parent Equipment": "", "Child Equipment": "",
        "Points": "ERV-1 OA TEMP,ERV-1 EA TEMP,ERV-1 SA TEMP,ERV-1 RA TEMP,ERV-1 WHEEL CMD,ERV-1 WHEEL STATUS,ERV-1 BYPASS DAMPER,ERV-1 EXH FAN CMD,ERV-1 EXH FAN STATUS,ERV-1 SUP FAN CMD,ERV-1 SUP FAN STATUS,ERV-1 FILTER DP",
        "Design CFM": "10000", "Design Tonnage": "", "Design GPM": "", "Design kW": "15",
        "Voltage": "460", "Phase": "3", "Status": "design",
        "Graphic Sections": "wheel,bypass_damper,supply_fan,exhaust_fan,filters",
        "Notes": "Energy recovery wheel for AHU-1 OA preconditioning"
    },
    # Terminal Units
    {
        "Equipment ID": "VAV-101", "Equipment Type": "VAV", "Subtype": "Single Duct",
        "Building": "Main", "Floor": "1", "Room": "Zone 101",
        "Served Area": "Office 101", "Controller ID": "VAV-101",
        "Parent Equipment": "AHU-1", "Child Equipment": "",
        "Points": "VAV-101 FLOW,VAV-101 FLOW SP,VAV-101 DAMPER,VAV-101 ZT,VAV-101 ZT SP,VAV-101 REHEAT CMD,VAV-101 OCC",
        "Design CFM": "1200", "Design Tonnage": "", "Design GPM": "4", "Design kW": "2",
        "Voltage": "120", "Phase": "1", "Status": "design",
        "Graphic Sections": "damper,reheat,flow_sensor,zone_temp",
        "Notes": "VAV box with electric reheat"
    },
    {
        "Equipment ID": "VAV-102", "Equipment Type": "VAV", "Subtype": "Single Duct",
        "Building": "Main", "Floor": "1", "Room": "Zone 102",
        "Served Area": "Office 102", "Controller ID": "VAV-102",
        "Parent Equipment": "AHU-1", "Child Equipment": "",
        "Points": "VAV-102 FLOW,VAV-102 FLOW SP,VAV-102 DAMPER,VAV-102 ZT,VAV-102 ZT SP,VAV-102 REHEAT CMD,VAV-102 OCC",
        "Design CFM": "1000", "Design Tonnage": "", "Design GPM": "3", "Design kW": "1.5",
        "Voltage": "120", "Phase": "1", "Status": "design",
        "Graphic Sections": "damper,reheat,flow_sensor,zone_temp",
        "Notes": "VAV box with electric reheat"
    },
    {
        "Equipment ID": "VAV-103", "Equipment Type": "VAV", "Subtype": "Single Duct",
        "Building": "Main", "Floor": "1", "Room": "Zone 103",
        "Served Area": "Conference 103", "Controller ID": "VAV-103",
        "Parent Equipment": "AHU-1", "Child Equipment": "",
        "Points": "VAV-103 FLOW,VAV-103 FLOW SP,VAV-103 DAMPER,VAV-103 ZT,VAV-103 ZT SP,VAV-103 REHEAT CMD,VAV-103 OCC",
        "Design CFM": "1500", "Design Tonnage": "", "Design GPM": "5", "Design kW": "2.5",
        "Voltage": "120", "Phase": "1", "Status": "design",
        "Graphic Sections": "damper,reheat,flow_sensor,zone_temp",
        "Notes": "VAV box with electric reheat, conference room"
    },
    {
        "Equipment ID": "VAV-104", "Equipment Type": "VAV", "Subtype": "Fan Powered",
        "Building": "Main", "Floor": "1", "Room": "Zone 104",
        "Served Area": "Perimeter 104", "Controller ID": "VAV-104",
        "Parent Equipment": "AHU-1", "Child Equipment": "",
        "Points": "VAV-104 FLOW,VAV-104 FLOW SP,VAV-104 DAMPER,VAV-104 ZT,VAV-104 ZT SP,VAV-104 REHEAT CMD,VAV-104 FAN CMD,VAV-104 FAN STATUS,VAV-104 OCC",
        "Design CFM": "800", "Design Tonnage": "", "Design GPM": "3", "Design kW": "1",
        "Voltage": "120", "Phase": "1", "Status": "design",
        "Graphic Sections": "damper,reheat,fan,flow_sensor,zone_temp",
        "Notes": "Fan-powered VAV box for perimeter zone"
    },
    {
        "Equipment ID": "FCU-1", "Equipment Type": "FAN_COIL", "Subtype": "4-Pipe",
        "Building": "Main", "Floor": "3", "Room": "Zone 301",
        "Served Area": "Office 301", "Controller ID": "MPC-2",
        "Parent Equipment": "", "Child Equipment": "",
        "Points": "FCU-1 ZT,FCU-1 ZT SP,FCU-1 FAN CMD,FCU-1 FAN STATUS,FCU-1 CLG VALVE,FCU-1 HTG VALVE,FCU-1 OCC",
        "Design CFM": "600", "Design Tonnage": "2", "Design GPM": "3", "Design kW": "0.5",
        "Voltage": "120", "Phase": "1", "Status": "design",
        "Graphic Sections": "fan,cooling_coil,heating_coil,zone_temp",
        "Notes": "4-pipe fan coil unit"
    },
    # Exhaust & Misc
    {
        "Equipment ID": "EF-1", "Equipment Type": "EXHAUST_FAN", "Subtype": "Centrifugal",
        "Building": "Main", "Floor": "Roof", "Room": "Roof",
        "Served Area": "General Exhaust", "Controller ID": "MPC-2",
        "Parent Equipment": "", "Child Equipment": "",
        "Points": "EF-1 CMD,EF-1 STATUS,EF-1 SPEED,EF-1 FLOW,EF-1 VIBRATION",
        "Design CFM": "5000", "Design Tonnage": "", "Design GPM": "", "Design kW": "5",
        "Voltage": "460", "Phase": "3", "Status": "design",
        "Graphic Sections": "fan,motor,vfd,discharge",
        "Notes": "General building exhaust fan"
    },
    {
        "Equipment ID": "MAU-1", "Equipment Type": "MAKEUP_AIR", "Subtype": "Direct Fired",
        "Building": "Main", "Floor": "Roof", "Room": "Roof",
        "Served Area": "Kitchen Makeup Air", "Controller ID": "MPC-2",
        "Parent Equipment": "", "Child Equipment": "",
        "Points": "MAU-1 SAT,MAU-1 OAT,MAU-1 SF CMD,MAU-1 SF STATUS,MAU-1 BURNER CMD,MAU-1 BURNER STATUS,MAU-1 FLAME,MAU-1 FILTER DP,MAU-1 FREEZE STAT",
        "Design CFM": "6000", "Design Tonnage": "", "Design GPM": "", "Design kW": "300",
        "Voltage": "460", "Phase": "3", "Status": "design",
        "Graphic Sections": "burner,filter,supply_fan,discharge,controls",
        "Notes": "Direct-fired makeup air unit for kitchen"
    },
]


CONTROLLER_DATA = [
    {
        "Controller ID": "CPC-1", "Name": "Central Plant Controller 1",
        "Vendor": "Johnson Controls", "Model": "MPC-8000", "Firmware": "12.3",
        "Type": "MPC", "Protocols": "BACnet/IP",
        "IP Address": "192.168.10.10", "Panel Location": "Chiller Room Panel CP-1",
        "Electrical Panel": "MP-1", "Circuit": "12",
        "Serves Equipment": "CH-1,CHWP-1,CHWP-2,CT-1,CWP-1,CWP-2,B-1,HWP-1,HWP-2,AHU-1,ERV-1",
        "Owned Points": "CH-1 CHWST,CH-1 CHWRT,CH-1 CDWST,CH-1 CDWRT,CH-1 AMPS,CH-1 KW,CH-1 STATUS,CH-1 ALARM,CH-1 VFD SPEED,CH-1 VANE POS,CHWP-1 STATUS,CHWP-1 CMD,CHWP-1 SPEED,CHWP-1 AMPS,CHWP-1 FLOW,CHWP-1 DISCH P,CHWP-1 SUCT P,CHWP-2 STATUS,CHWP-2 CMD,CHWP-2 SPEED,CHWP-2 AMPS,CHWP-2 FLOW,CHWP-2 DISCH P,CHWP-2 SUCT P,CT-1 CWT,CT-1 LWT,CT-1 FAN CMD,CT-1 FAN SPEED,CT-1 FAN STATUS,CT-1 BASIN LEVEL,CT-1 VIBRATION,CWP-1 STATUS,CWP-1 CMD,CWP-1 SPEED,CWP-1 AMPS,CWP-1 FLOW,CWP-1 DISCH P,CWP-1 SUCT P,CWP-2 STATUS,CWP-2 CMD,CWP-2 SPEED,CWP-2 AMPS,CWP-2 FLOW,CWP-2 DISCH P,CWP-2 SUCT P,B-1 HWS,B-1 HWR,B-1 FLAME,B-1 STATUS,B-1 ALARM,B-1 FIRING RATE,B-1 SUPPLY T,B-1 RETURN T,B-1 O2,HWP-1 STATUS,HWP-1 CMD,HWP-1 SPEED,HWP-1 AMPS,HWP-1 FLOW,HWP-1 DISCH P,HWP-1 SUCT P,HWP-2 STATUS,HWP-2 CMD,HWP-2 SPEED,HWP-2 AMPS,HWP-2 FLOW,HWP-2 DISCH P,HWP-2 SUCT P,AHU-1 SAT,AHU-1 MAT,AHU-1 RAT,AHU-1 OAT,AHU-1 OA HUM,AHU-1 RA HUM,AHU-1 SF CMD,AHU-1 SF STATUS,AHU-1 SF VFD,AHU-1 RF CMD,AHU-1 RF STATUS,AHU-1 RF VFD,AHU-1 OA DAMPER,AHU-1 RA DAMPER,AHU-1 EA DAMPER,AHU-1 CLG VALVE,AHU-1 HTG VALVE,AHU-1 DUCT SP,AHU-1 FILTER DP,AHU-1 FREEZE STAT,AHU-1 DUCT SMOKE,AHU-1 FIRE ALARM,ERV-1 OA TEMP,ERV-1 EA TEMP,ERV-1 SA TEMP,ERV-1 RA TEMP,ERV-1 WHEEL CMD,ERV-1 WHEEL STATUS,ERV-1 BYPASS DAMPER,ERV-1 EXH FAN CMD,ERV-1 EXH FAN STATUS,ERV-1 SUP FAN CMD,ERV-1 SUP FAN STATUS,ERV-1 FILTER DP",
        "Universal Inputs": "64", "Digital Inputs": "32", "Analog Outputs": "16", "Digital Outputs": "16", "Total Points": "128",
        "Status": "design", "Notes": "Central plant controller with BACnet/IP"
    },
    {
        "Controller ID": "MPC-1", "Name": "Main Plant Controller 1",
        "Vendor": "Johnson Controls", "Model": "MPC-8000", "Firmware": "12.3",
        "Type": "MPC", "Protocols": "BACnet/IP",
        "IP Address": "192.168.10.11", "Panel Location": "Mechanical Room Panel MP-1",
        "Electrical Panel": "MP-1", "Circuit": "14",
        "Serves Equipment": "AHU-1,VAV-101,VAV-102,VAV-103,VAV-104",
        "Owned Points": "AHU-1 SAT,AHU-1 MAT,AHU-1 RAT,AHU-1 OAT,AHU-1 OA HUM,AHU-1 RA HUM,AHU-1 SF CMD,AHU-1 SF STATUS,AHU-1 SF VFD,AHU-1 RF CMD,AHU-1 RF STATUS,AHU-1 RF VFD,AHU-1 OA DAMPER,AHU-1 RA DAMPER,AHU-1 EA DAMPER,AHU-1 CLG VALVE,AHU-1 HTG VALVE,AHU-1 DUCT SP,AHU-1 FILTER DP,AHU-1 FREEZE STAT,AHU-1 DUCT SMOKE,AHU-1 FIRE ALARM,VAV-101 FLOW,VAV-101 FLOW SP,VAV-101 DAMPER,VAV-101 ZT,VAV-101 ZT SP,VAV-101 REHEAT CMD,VAV-101 OCC,VAV-102 FLOW,VAV-102 FLOW SP,VAV-102 DAMPER,VAV-102 ZT,VAV-102 ZT SP,VAV-102 REHEAT CMD,VAV-102 OCC,VAV-103 FLOW,VAV-103 FLOW SP,VAV-103 DAMPER,VAV-103 ZT,VAV-103 ZT SP,VAV-103 REHEAT CMD,VAV-103 OCC,VAV-104 FLOW,VAV-104 FLOW SP,VAV-104 DAMPER,VAV-104 ZT,VAV-104 ZT SP,VAV-104 REHEAT CMD,VAV-104 FAN CMD,VAV-104 FAN STATUS,VAV-104 OCC",
        "Universal Inputs": "48", "Digital Inputs": "24", "Analog Outputs": "12", "Digital Outputs": "12", "Total Points": "96",
        "Status": "design", "Notes": "AHU and VAV controller for Floor 1"
    },
    {
        "Controller ID": "MPC-2", "Name": "Main Plant Controller 2",
        "Vendor": "Johnson Controls", "Model": "MPC-8000", "Firmware": "12.3",
        "Type": "MPC", "Protocols": "BACnet/IP",
        "IP Address": "192.168.10.12", "Panel Location": "Mechanical Room Panel MP-2",
        "Electrical Panel": "MP-2", "Circuit": "16",
        "Serves Equipment": "AHU-2,RTU-1,FCU-1,EF-1,MAU-1",
        "Owned Points": "AHU-2 SAT,AHU-2 MAT,AHU-2 RAT,AHU-2 OAT,AHU-2 OA HUM,AHU-2 RA HUM,AHU-2 SF CMD,AHU-2 SF STATUS,AHU-2 RF CMD,AHU-2 RF STATUS,AHU-2 OA DAMPER,AHU-2 RA DAMPER,AHU-2 CLG VALVE,AHU-2 HTG VALVE,AHU-2 DUCT SP,AHU-2 FILTER DP,AHU-2 FREEZE STAT,RTU-1 SAT,RTU-1 RAT,RTU-1 OAT,RTU-1 ZONE T,RTU-1 SF CMD,RTU-1 SF STATUS,RTU-1 OA DAMPER,RTU-1 CLG STAGE1,RTU-1 CLG STAGE2,RTU-1 HTG STAGE1,RTU-1 HTG STAGE2,RTU-1 FILTER DP,RTU-1 FREEZE STAT,RTU-1 SMOKE,FCU-1 ZT,FCU-1 ZT SP,FCU-1 FAN CMD,FCU-1 FAN STATUS,FCU-1 CLG VALVE,FCU-1 HTG VALVE,FCU-1 OCC,EF-1 CMD,EF-1 STATUS,EF-1 SPEED,EF-1 FLOW,EF-1 VIBRATION,MAU-1 SAT,MAU-1 OAT,MAU-1 SF CMD,MAU-1 SF STATUS,MAU-1 BURNER CMD,MAU-1 BURNER STATUS,MAU-1 FLAME,MAU-1 FILTER DP,MAU-1 FREEZE STAT",
        "Universal Inputs": "48", "Digital Inputs": "24", "Analog Outputs": "12", "Digital Outputs": "12", "Total Points": "96",
        "Status": "design", "Notes": "AHU-2, RTU, FCU, EF, MAU controller for Floors 2-3/Roof"
    },
    {
        "Controller ID": "VAV-101", "Name": "VAV-101 Terminal Controller",
        "Vendor": "Johnson Controls", "Model": "VAV-3000", "Firmware": "5.2",
        "Type": "VAV", "Protocols": "BACnet/MSTP",
        "IP Address": "", "Panel Location": "Zone 101 Ceiling",
        "Electrical Panel": "LP-1", "Circuit": "8",
        "Serves Equipment": "VAV-101",
        "Owned Points": "VAV-101 FLOW,VAV-101 FLOW SP,VAV-101 DAMPER,VAV-101 ZT,VAV-101 ZT SP,VAV-101 REHEAT CMD,VAV-101 OCC",
        "Universal Inputs": "4", "Digital Inputs": "2", "Analog Outputs": "2", "Digital Outputs": "2", "Total Points": "10",
        "Status": "design", "Notes": "Terminal VAV controller on MSTP trunk from MPC-1"
    },
    {
        "Controller ID": "VAV-102", "Name": "VAV-102 Terminal Controller",
        "Vendor": "Johnson Controls", "Model": "VAV-3000", "Firmware": "5.2",
        "Type": "VAV", "Protocols": "BACnet/MSTP",
        "IP Address": "", "Panel Location": "Zone 102 Ceiling",
        "Electrical Panel": "LP-1", "Circuit": "10",
        "Serves Equipment": "VAV-102",
        "Owned Points": "VAV-102 FLOW,VAV-102 FLOW SP,VAV-102 DAMPER,VAV-102 ZT,VAV-102 ZT SP,VAV-102 REHEAT CMD,VAV-102 OCC",
        "Universal Inputs": "4", "Digital Inputs": "2", "Analog Outputs": "2", "Digital Outputs": "2", "Total Points": "10",
        "Status": "design", "Notes": "Terminal VAV controller on MSTP trunk from MPC-1"
    },
]


# Build point list from equipment data
def build_point_list():
    """Generate comprehensive point list from equipment definitions."""
    points = []
    point_id = 1
    
    # Standard point templates per equipment type
    templates = {
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
    }
    
    for equip in EQUIPMENT_DATA:
        equip_id = equip["Equipment ID"]
        equip_type = equip["Equipment Type"]
        controller_id = equip["Controller ID"]
        
        template = templates.get(equip_type, templates.get("AHU", []))
        
        for idx, (suffix, kind, direction, units, bacnet_type) in enumerate(template):
            point_name = f"{equip_id} {suffix}"
            # Assign BACnet instance sequentially per controller
            bacnet_instance = point_id
            point_id += 1
            
            points.append({
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
                "BACnet Instance": bacnet_instance,
                "Modbus Register": "",
                "Modbus Type": "",
                "Source": "point_list",
                "Source Reference": f"{equip_id} {suffix}",
                "Description": f"{equip_id} {suffix}",
                "Tags": f"{equip_type.lower()},{suffix.lower().replace(' ', '_')}",
            })
    
    return points


def write_rich_example_csvs(examples_dir: Path):
    """Write rich example CSVs that ship with the repo."""
    examples_dir.mkdir(parents=True, exist_ok=True)
    
    # Equipment schedule
    equip_fields = [
        "Equipment ID", "Equipment Type", "Subtype", "Building", "Floor", "Room",
        "Served Area", "Controller ID", "Parent Equipment", "Child Equipment",
        "Points", "Design CFM", "Design Tonnage", "Design GPM", "Design kW",
        "Voltage", "Phase", "Status", "Graphic Sections", "Notes"
    ]
    with open(examples_dir / "equipment_schedule.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=equip_fields)
        writer.writeheader()
        for row in EQUIPMENT_DATA:
            writer.writerow(row)
    
    # Point list
    point_fields = [
        "Point Name", "Equipment ID", "Point Kind", "Direction", "Units",
        "Unit System", "Range Min", "Range Max", "Controller ID",
        "BACnet Object Type", "BACnet Instance", "Modbus Register",
        "Modbus Type", "Source", "Source Reference", "Description", "Tags"
    ]
    points = build_point_list()
    with open(examples_dir / "point_list.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=point_fields)
        writer.writeheader()
        for row in points:
            writer.writerow(row)
    
    # Controller schedule
    ctrl_fields = [
        "Controller ID", "Name", "Vendor", "Model", "Firmware", "Type",
        "Protocols", "IP Address", "Panel Location", "Electrical Panel", "Circuit",
        "Serves Equipment", "Owned Points", "Universal Inputs", "Digital Inputs",
        "Analog Outputs", "Digital Outputs", "Total Points", "Status", "Notes"
    ]
    with open(examples_dir / "controller_schedule.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ctrl_fields)
        writer.writeheader()
        for row in CONTROLLER_DATA:
            writer.writerow(row)
    
    print(f"  Wrote {len(EQUIPMENT_DATA)} equipment rows")
    print(f"  Wrote {len(points)} point rows")
    print(f"  Wrote {len(CONTROLLER_DATA)} controller rows")


def load_demo_project(data_dir: Path, examples_dir: Path, project_id: str = "codex-test-project") -> Project:
    """Load or create the rich demo HVAC project. Idempotent - refreshes on re-run."""
    
    project_dir = data_dir / "projects" / project_id
    project_file = project_dir / "project.json"
    
    # Always regenerate example CSVs so they stay in sync
    write_rich_example_csvs(examples_dir)
    
    if project_file.exists():
        print(f"Refreshing existing demo project from {project_file}")
        with open(project_file) as f:
            data = json.load(f)
        project = Project.model_validate(data)
    else:
        print(f"Creating new demo project: {project_id}...")
        
        metadata = ProjectMetadata(
            project_id=project_id,
            name="Codex Test Project",
            client="Codex Demo",
            location="Demo Campus",
            unit_system=UnitSystem.IP,
            design_phase="Design Development",
            engineer_of_record="Demo Engineer",
            programmer="Demo Programmer",
            commissioning_agent="Demo CxA",
            naming_standard="ASHRAE 135",
        )
        project = Project(metadata=metadata)
    
    # Import fresh data (replaces existing)
    importer = CSVImporter(project)
    
    # Equipment schedule
    equip_file = examples_dir / "equipment_schedule.csv"
    if equip_file.exists():
        result = importer.import_equipment_schedule(equip_file, "equip_schedule_demo")
        print(f"  Equipment: {result.message}")
        if result.errors:
            for e in result.errors:
                print(f"    ERROR: {e}")
        if result.warnings:
            for w in result.warnings:
                print(f"    WARN: {w}")
    
    # Point list
    points_file = examples_dir / "point_list.csv"
    if points_file.exists():
        result = importer.import_point_list(points_file, "point_list_demo")
        print(f"  Points: {result.message}")
        if result.errors:
            for e in result.errors:
                print(f"    ERROR: {e}")
        if result.warnings:
            for w in result.warnings:
                print(f"    WARN: {w}")
    
    # Controller schedule
    ctrl_file = examples_dir / "controller_schedule.csv"
    if ctrl_file.exists():
        result = importer.import_controller_schedule(ctrl_file, "ctrl_schedule_demo")
        print(f"  Controllers: {result.message}")
        if result.errors:
            for e in result.errors:
                print(f"    ERROR: {e}")
        if result.warnings:
            for w in result.warnings:
                print(f"    WARN: {w}")
    
    # Save project
    project_dir.mkdir(parents=True, exist_ok=True)
    with open(project_file, "w") as f:
        f.write(project.model_dump_json(indent=2))
    
    print(f"Demo project saved to {project_file}")
    print(f"  Equipment: {len(project.equipment)}")
    print(f"  Points: {len(project.points)}")
    print(f"  Controllers: {len(project.controllers)}")
    
    return project


def generate_outputs(project: Project, output_dir: Path) -> None:
    """Generate all outputs for the demo project."""
    
    project_output_dir = output_dir / project.metadata.project_id
    project_output_dir.mkdir(parents=True, exist_ok=True)
    
    print("\nGenerating demo outputs...")
    
    # Validation
    engine = ValidationEngine()
    report = engine.validate(project)
    print(f"  Validation: {len(report.errors)} errors, {len(report.warnings)} warnings")
    
    # Gap analysis
    gap_report = analyze_gaps(project)
    print(f"  Gap Analysis: {gap_report.total_count} gaps found")
    
    # Checkout sheets
    checkout_dir = project_output_dir / "checkout"
    checkout_dir.mkdir(parents=True, exist_ok=True)
    result = generate_checkout_sheets(project, checkout_dir)
    sheet_count = result.get('sheet_count', len(list(checkout_dir.glob("*.md"))) + len(list(checkout_dir.glob("*.xlsx"))))
    print(f"  Checkout: {sheet_count} sheets")
    
    # Reports
    reports_dir = project_output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    paths = generate_reports(project, reports_dir)
    print(f"  Reports: {len(paths)} files")
    
    # Graphics
    graphics_dir = project_output_dir / "graphics"
    graphics_dir.mkdir(parents=True, exist_ok=True)
    result = generate_graphics(project, graphics_dir)
    # Handle both dict and list return types
    if isinstance(result, dict):
        total_graphics = sum(len(v) if isinstance(v, list) else 1 for v in result.values())
    elif isinstance(result, list):
        total_graphics = len(result)
    else:
        total_graphics = len(list(graphics_dir.rglob("*")))
    print(f"  Graphics: {total_graphics} files")
    
    # Logic
    logic_dir = project_output_dir / "logic"
    logic_dir.mkdir(parents=True, exist_ok=True)
    result = generate_logic(project, logic_dir)
    if isinstance(result, dict):
        total_logic = sum(len(v) if isinstance(v, list) else 1 for v in result.values())
    elif isinstance(result, list):
        total_logic = len(result)
    else:
        total_logic = len(list(logic_dir.rglob("*")))
    print(f"  Logic: {total_logic} files")
    
    # Exports
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
    
    print(f"\n✅ Demo project '{project.metadata.project_id}' fully loaded and ready!")
    print(f"   Outputs at: {project_output_dir}")


def main():
    import os
    
    base_dir = Path(__file__).parent.parent
    data_dir = Path(os.environ.get("BAS_DATA_DIR", base_dir / "data"))
    output_dir = Path(os.environ.get("BAS_OUTPUT_DIR", base_dir / "ui" / "output"))
    examples_dir = base_dir / "examples"
    
    # Allow project ID override via env
    project_id = os.environ.get("BAS_DEMO_PROJECT_ID", "codex-test-project")
    
    # Load demo project
    project = load_demo_project(data_dir, examples_dir, project_id)
    
    # Generate all outputs
    generate_outputs(project, output_dir)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())