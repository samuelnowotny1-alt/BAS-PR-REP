#!/usr/bin/env python3
"""
Compare BAS Assistant example CSVs against industry standard schemas.
Checks: DOE Reference Buildings, ASHRAE 135 (BACnet), Project Haystack, COBie, COBie 2.4
"""

import csv
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple
from dataclasses import dataclass
from typing import Optional

EXAMPLES_DIR = Path('/home/oem/.openclaw/workspace/bas-assistant/examples')

# ============================================================
# STANDARD SCHEMAS
# ============================================================

# COBie 2.4 Equipment columns (subset relevant to BAS)
COBIE_EQUIPMENT_COLUMNS = {
    'Name', 'CreatedBy', 'CreatedOn', 'Category', 'Description',
    'AssetType', 'Manufacturer', 'ModelNumber', 'WarrantyGuarantorParts',
    'WarrantyDurationParts', 'WarrantyGuarantorLabor', 'WarrantyDurationLabor',
    'WarrantyDurationUnit', 'SerialNumber', 'InstallationDate',
    'WarrantyStartDate', 'TagNumber', 'BarCode', 'AssetIdentifier'
}

# COBie 2.4 Component (Point) columns
COBIE_COMPONENT_COLUMNS = {
    'Name', 'CreatedBy', 'CreatedOn', 'SheetName', 'RowName',
    'Floor', 'Space', 'Zone', 'TypeName', 'Description',
    'AssetType', 'Manufacturer', 'ModelNumber', 'WarrantyGuarantorParts',
    'WarrantyDurationParts', 'WarrantyGuarantorLabor', 'WarrantyDurationLabor',
    'WarrantyDurationUnit', 'SerialNumber', 'InstallationDate',
    'WarrantyStartDate', 'TagNumber', 'BarCode', 'AssetIdentifier'
}

# Project Haystack standard tags for BAS equipment
HAYSTACK_EQUIP_TAGS = {
    'ahu', 'rtu', 'vav', 'fcu', 'chiller', 'boiler', 'coolingTower',
    'pump', 'fan', 'damper', 'valve', 'coil', 'filter', 'humidifier',
    'dehumidifier', 'heatExchanger', 'airSeparator', 'expansionTank',
    'airSeparator', 'bufferTank', 'glycolFeeder', 'airSeparator',
    'airHandlingUnit', 'roofTopUnit', 'variableAirVolume',
    'fanCoilUnit', 'chiller', 'boiler', 'coolingTower',
    'hotWaterPump', 'chilledWaterPump', 'condenserWaterPump',
    'supplyFan', 'returnFan', 'exhaustFan', 'reliefFan',
    'supplyAir', 'returnAir', 'outsideAir', 'exhaustAir',
    'mixedAir', 'preheat', 'reheat', 'cooling', 'heating',
    'economizer', 'heatRecovery', 'humidifier', 'dehumidifier'
}

# Project Haystack standard point tags
HAYSTACK_POINT_TAGS = {
    'sensor', 'cmd', 'setpoint', 'status', 'alarm',
    'temp', 'pressure', 'flow', 'humidity', 'co2', 'voc',
    'occupancy', 'flow', 'pressure', 'power', 'energy',
    'temp', 'pressure', 'flow', 'level', 'speed',
    'position', 'enable', 'run', 'fault', 'override',
    'input', 'output', 'cmd', 'sp', 'stpt', 'alarm',
    'enable', 'run', 'fault', 'override', 'sensor',
    'cmd', 'setpoint', 'status', 'alarm', 'sensor',
    'temp', 'pressure', 'flow', 'humidity', 'co2',
    'occupancy', 'power', 'energy', 'level', 'speed'
}

# ASHRAE 135 (BACnet) standard object types
BACNET_OBJECT_TYPES = {
    'AI', 'AO', 'AV', 'BI', 'BO', 'BV',
    'MSI', 'MSO', 'MSV',
    'LOOP', 'SCHEDULE', 'CALENDAR',
    'TRENDLOG', 'TRENDLOG_MULTIPLE',
    'NOTIFICATION_CLASS', 'ALERT_ENROLLMENT',
    'FILE', 'GLOBAL_GROUP', 'GROUP',
    'EVENT_LOG', 'EVENT_ENROLLMENT',
    'NOTIFICATION_FORWARDER', 'CHARACTERSTRING_VALUE',
    'DATE_TIME_VALUE', 'INTEGER_VALUE',
    'LARGE_ANALOG_VALUE', 'OCTETSTRING_VALUE',
    'POSITIVE_INTEGER_VALUE', 'TIME_VALUE'
}

# DOE Reference Building standard columns (from EnergyPlus IDF)
DOE_EQUIPMENT_FIELDS = {
    'Name', 'Zone_or_ZoneList_Name', 'Schedule_Name',
    'Availability_Schedule_Name', 'Design_Size',
    'Capacity_Control_Method', 'Rated_COP', 'Rated_Air_Flow_Rate',
    'Rated_Evaporator_Fan_Power', 'Rated_Condenser_Fan_Power',
    'Condenser_Type', 'Condenser_Fan_Power_Ratio',
    'Heat_Recovery_Type', 'Sensible_Heat_Recovery_Effectiveness',
    'Latent_Heat_Recovery_Effectiveness', 'Supply_Air_Flow_Rate',
    'Outdoor_Air_Flow_Rate', 'Economizer_Type',
    'Economizer_Control_Action', 'Lockout_Type',
    'Minimum_Outdoor_Air_Flow_Rate', 'Maximum_Outdoor_Air_Flow_Rate'
}

# ASHRAE Guideline 13 - Commissioning point data
ASHRAE_G13_POINT_FIELDS = {
    'Point_Name', 'Point_Description', 'Point_Type',
    'Signal_Type', 'Units', 'Range_Min', 'Range_Max',
    'Accuracy', 'Resolution', 'Response_Time',
    'Calibration_Frequency', 'Calibration_Method',
    'Trend_Log_Interval', 'Trend_Log_Duration',
    'Alarm_Limits_High', 'Alarm_Limits_Low',
    'Alarm_Delay', 'Alarm_Priority'
}

# ============================================================
# COMPARISON ENGINE
# ============================================================

@dataclass
class ComparisonResult:
    file_name: str
    total_columns: int
    matched_standards: Dict[str, int]
    missing_standard_columns: Dict[str, List[str]]
    extra_columns: List[str]
    recommendations: List[str]

class CSVComparator:
    def __init__(self):
        self.results: List[ComparisonResult] = []
    
    def load_csv(self, filepath: Path) -> Tuple[List[str], List[Dict]]:
        """Load CSV and return (headers, rows)"""
        with open(filepath, 'r') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = list(reader)
            return headers, rows
    
    def compare_file(self, filepath: Path, standard_name: str, 
                     standard_columns: Set[str], 
                     standard_name_map: Optional[Dict[str, str]] = None) -> ComparisonResult:
        """Compare a CSV file against a standard schema"""
        headers, rows = self.load_csv(filepath)
        file_columns = set(headers)
        
        # Apply column name mapping if provided
        mapped_standard = set()
        name_map = {}
        if standard_name_map:
            for std_col, our_col in standard_name_map.items():
                if our_col in file_columns:
                    mapped_standard.add(std_col)
                    name_map[std_col] = our_col
        else:
            mapped_standard = standard_columns
        
        # Find matches
        matched = file_columns & standard_columns
        missing = standard_columns - file_columns
        extra = file_columns - standard_columns
        
        # Calculate match percentages
        match_pct = len(matched) / len(standard_columns) * 100 if standard_columns else 0
        
        # Generate recommendations
        recommendations = []
        if missing:
            recommendations.append(f"Missing {len(missing)} standard columns: {', '.join(sorted(missing)[:10])}{'...' if len(missing) > 10 else ''}")
        if extra:
            recommendations.append(f"Extra columns not in standard: {', '.join(sorted(extra)[:10])}{'...' if len(extra) > 10 else ''}")
        if match_pct < 50:
            recommendations.append("Low match rate - consider adding standard columns")
        elif match_pct < 80:
            recommendations.append("Moderate match - consider adding missing standard columns")
        else:
            recommendations.append("Good match with standard")
        
        matched_standards = {
            'match_count': len(matched),
            'total_standard': len(standard_columns),
            'match_percentage': round(match_pct, 1)
        }
        
        return ComparisonResult(
            file_name=filepath.name,
            total_columns=len(file_columns),
            matched_standards={'standard': matched_standards},
            missing_standard_columns={'standard': sorted(missing)},
            extra_columns=sorted(extra),
            recommendations=recommendations
        )
    
    def compare_all(self, examples_dir: Path) -> List[ComparisonResult]:
        """Compare all example CSVs against relevant standards"""
        results = []
        
        # Define standard mappings for each file type
        standards_map = {
            'equipment_schedule.csv': {
                'COBie Equipment': (COBIE_EQUIPMENT_COLUMNS, {
                    'Equipment ID': 'Name',
                    'Equipment Type': 'AssetType',
                    'Manufacturer': 'Manufacturer',
                    'Model': 'ModelNumber',
                    'Serial Number': 'SerialNumber',
                    'Installation Date': 'InstallationDate',
                    'Warranty Start Date': 'WarrantyStartDate',
                    'Tag Number': 'TagNumber',
                    'Notes': 'Description'
                }),
                'DOE Reference': (DOE_EQUIPMENT_FIELDS, {
                    'Equipment ID': 'Name',
                    'Equipment Type': 'AssetType',
                    'Design CFM': 'Design_Size',
                    'Design Tonnage': 'Rated_COP',
                    'Design GPM': 'Design_Air_Flow_Rate',
                    'Design kW': 'Design_Evaporator_Fan_Power',
                    'Voltage': 'Voltage',
                    'Phase': 'Phase'
                }),
                'ASHRAE G13': (ASHRAE_G13_POINT_FIELDS, {})
            },
            'point_list.csv': {
                'BACnet Standard': (BACNET_OBJECT_TYPES, {
                    'BACnet Object Type': 'BACnet Object Type',
                    'BACnet Instance': 'BACnet Instance',
                    'Point Name': 'Name',
                    'Units': 'Units',
                    'Range Min': 'Range_Min',
                    'Range Max': 'Range_Max'
                }),
                'Haystack Tags': (HAYSTACK_POINT_TAGS, {
                    'Tags': 'Tags'
                }),
                'ASHRAE G13': (ASHRAE_G13_POINT_FIELDS, {
                    'Point Name': 'Point_Name',
                    'Description': 'Point_Description',
                    'Point Kind': 'Point_Type',
                    'Direction': 'Signal_Type',
                    'Units': 'Units',
                    'Range Min': 'Range_Min',
                    'Range Max': 'Range_Max',
                    'Description': 'Point_Description'
                })
            },
            'controller_schedule.csv': {
                'COBie Equipment': (COBIE_EQUIPMENT_COLUMNS, {
                    'Controller ID': 'Name',
                    'Name': 'Description',
                    'Vendor': 'Manufacturer',
                    'Model': 'ModelNumber',
                    'Firmware': 'ModelNumber',
                    'Type': 'AssetType',
                    'IP Address': 'BarCode',
                    'Panel Location': 'Description',
                    'Electrical Panel': 'Description',
                    'Circuit': 'AssetIdentifier',
                    'Serves Equipment': 'Description',
                    'Status': 'Description'
                })
            }
        }
        
        for filename, standards in standards_map.items():
            filepath = Path(__file__).parent / 'examples' / filename
            if filepath.exists():
                print(f"\n📄 Analyzing {filename}...")
                for std_name, (std_cols, col_map) in standards.items():
                    result = self.compare_file(
                        Path(__file__).parent / 'examples' / filename,
                        std_name,
                        std_cols,
                        col_map
                    )
                    self.results.append(result)
                    self._print_result(result)
        
        return self.results
    
    def _print_result(self, result: ComparisonResult):
        std = result.matched_standards['standard']
        print(f"  Match: {std['match_count']}/{std['total_standard']} ({std['match_percentage']}%)")
        if result.missing_standard_columns['standard']:
            print(f"  ❌ Missing: {', '.join(result.missing_standard_columns['standard'][:5])}{'...' if len(result.missing_standard_columns['standard']) > 5 else ''}")
        if result.extra_columns:
            print(f"  ➕ Extra: {', '.join(result.extra_columns[:5])}{'...' if len(result.extra_columns) > 5 else ''}")
        for rec in result.recommendations:
            print(f"  💡 {rec}")


def main():
    print("=" * 70)
    print("BAS ASSISTANT - CSV Standards Comparison")
    print("=" * 70)
    
    comparator = CSVComparator()
    results = comparator.compare_all(Path(__file__).parent / 'examples')
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for result in comparator.results:
        std = result.matched_standards['standard']
        status = "✅" if std['match_percentage'] >= 70 else "⚠️" if std['match_percentage'] >= 40 else "❌"
        print(f"{status} {result.file_name}: {std['match_percentage']}% match")


if __name__ == '__main__':
    main()
