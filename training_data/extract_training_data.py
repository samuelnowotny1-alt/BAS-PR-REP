#!/usr/bin/env python3
"""
Extract and normalize BAS training data from multiple sources into trainable formats.
Outputs: JSONL (for LLMs), CSV (for tabular), Parquet (for ML pipelines)

Legal note:
This script references external data sources that may carry their own license
or redistribution terms. Treat downloaded data and derived outputs as
third-party governed material until a source-by-source rights review is
completed.
"""

import csv
import json
import os
import sys
import zipfile
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import pandas as pd

# Add project root to path
sys.path.insert(0, '/home/oem/.openclaw/workspace/bas-assistant')

# ============================================================
# CONFIGURATION
# ============================================================

PROJECT_ROOT = Path('/home/oem/.openclaw/workspace/bas-assistant')
EXAMPLES_DIR = PROJECT_ROOT / 'examples'
TRAINING_DIR = PROJECT_ROOT / 'training_data'
RAW_DIR = TRAINING_DIR / 'raw'
PROCESSED_DIR = TRAINING_DIR / 'processed'

# Output formats
OUTPUT_FORMATS = ['jsonl', 'csv', 'parquet']

# External data sources
EXTERNAL_SOURCES = {
    'doe_reference_buildings': {
        'url': 'https://www.energy.gov/sites/prod/files/2016/02/f29/RefBldgModels.zip',
        'description': 'DOE Commercial Reference Buildings (16 types, 16 climate zones)'
    },
    'ashrae_rp1312': {
        'url': 'https://data.openei.org/submissions/910/files/ASHRAE_RP1312_Data.zip',
        'description': 'ASHRAE RP-1312 FDD datasets (AHU, RTU, VAV, chiller, boiler)'
    },
    'modelica_buildings': {
        'url': 'https://github.com/lbl-srg/modelica-buildings/archive/refs/heads/main.zip',
        'description': 'Modelica Buildings Library (HVAC models, validation data)'
    }
}

# ============================================================
# DATA CLASSES
# ============================================================

class TrainingRecord:
    """Normalized training record for BAS data"""
    def __init__(self):
        self.id: str = ""
        self.source: str = ""  # 'examples', 'doe_ref', 'ashrae_rp1312', 'modelica', etc.
        self.category: str = ""  # 'equipment', 'point', 'controller', 'sequence', 'validation'
        self.equipment_type: str = ""  # 'AHU', 'VAV', 'Chiller', 'Boiler', 'Pump', etc.
        self.equipment_id: str = ""
        self.point_name: str = ""
        self.point_type: str = ""  # 'sensor', 'actuator', 'setpoint', 'status', 'alarm'
        self.bacnet_object_type: str = ""  # AI, AO, AV, BI, BO, BV, etc.
        self.bacnet_instance: str = ""
        self.units: str = ""
        self.min_range: Optional[float] = None
        self.max_range: Optional[float] = None
        self.default_value: Optional[str] = ""
        self.description: str = ""
        self.tags: List[str] = []  # Haystack tags
        self.validation_rules: List[str] = []  # e.g., "range_check", "rate_of_change"
        self.equipment_relationship: str = ""  # parent equipment ID
        self.controller_id: str = ""
        self.network_address: str = ""
        self.metadata: Dict[str, Any] = {}
        self.created_at: str = datetime.now().isoformat()
        self.source_file: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'source': self.source,
            'category': self.category,
            'equipment_type': self.equipment_type,
            'equipment_id': self.equipment_id,
            'point_name': self.point_name,
            'point_type': self.point_type,
            'bacnet_object_type': self.bacnet_object_type,
            'bacnet_instance': self.bacnet_instance,
            'units': self.units,
            'min_range': self.min_range,
            'max_range': self.max_range,
            'default_value': self.default_value,
            'description': self.description,
            'tags': self.tags,
            'validation_rules': self.validation_rules,
            'equipment_relationship': self.equipment_relationship,
            'controller_id': self.controller_id,
            'network_address': self.network_address,
            'metadata': self.metadata,
            'created_at': self.created_at,
            'source_file': self.source_file
        }

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

# ============================================================
# EXTRACTORS
# ============================================================

class ExampleExtractor:
    """Extract from local example CSVs"""
    
    def __init__(self, examples_dir: Path):
        self.examples_dir = examples_dir
    
    def extract(self) -> List[TrainingRecord]:
        records = []
        
        # Equipment schedule
        equip_file = self.examples_dir / 'equipment_schedule.csv'
        if equip_file.exists():
            records.extend(self._extract_equipment(equip_file))
        
        # Point list
        points_file = self.examples_dir / 'point_list.csv'
        if points_file.exists():
            records.extend(self._extract_points(points_file))
        
        # Controller schedule
        ctrl_file = self.examples_dir / 'controller_schedule.csv'
        if ctrl_file.exists():
            records.extend(self._extract_controllers(ctrl_file))
        
        return records
    
    def _extract_equipment(self, file_path: Path) -> List[TrainingRecord]:
        records = []
        with open(file_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rec = TrainingRecord()
                rec.id = f"equip_{row.get('Equipment ID', '').lower().replace('-', '_')}"
                rec.source = 'examples'
                rec.category = 'equipment'
                rec.equipment_type = row.get('Equipment Type', '')
                rec.equipment_id = row.get('Equipment ID', '')
                rec.description = row.get('Notes', '')
                rec.equipment_relationship = row.get('Parent Equipment', '')
                rec.metadata = {k: v for k, v in row.items() if k not in ['Equipment ID', 'Equipment Type', 'Notes', 'Parent Equipment']}
                rec.source_file = str(file_path)
                rec.tags = ['equipment', rec.equipment_type.lower()] if rec.equipment_type else ['equipment']
                records.append(rec)
        return records
    
    def _extract_points(self, file_path: Path) -> List[TrainingRecord]:
        records = []
        with open(file_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rec = TrainingRecord()
                rec.id = f"point_{row.get('Point Name', '').lower().replace(' ', '_').replace('-', '_')}"
                rec.source = 'examples'
                rec.category = 'point'
                rec.equipment_id = row.get('Equipment ID', '')
                rec.point_name = row.get('Point Name', '')
                rec.point_type = self._map_point_kind(row.get('Point Kind', ''))
                rec.bacnet_object_type = row.get('BACnet Object Type', '')
                rec.bacnet_instance = row.get('BACnet Instance', '')
                rec.units = row.get('Units', '')
                rec.min_range = self._parse_float(row.get('Range Min'))
                rec.max_range = self._parse_float(row.get('Range Max'))
                rec.default_value = row.get('Source Reference', '')
                rec.description = row.get('Description', '')
                rec.tags = [t.strip() for t in row.get('Tags', '').split(',') if t.strip()]
                rec.validation_rules = ['range_check'] if rec.min_range is not None and rec.max_range is not None else []
                rec.equipment_relationship = row.get('Equipment ID', '')
                rec.controller_id = row.get('Controller ID', '')
                rec.metadata = {k: v for k, v in row.items() if k not in [
                    'Point Name', 'Equipment ID', 'Point Kind', 'Direction',
                    'Units', 'Range Min', 'Range Max', 'Controller ID',
                    'BACnet Object Type', 'BACnet Instance', 'Source Reference',
                    'Description', 'Tags'
                ]}
                rec.source_file = str(file_path)
                records.append(rec)
        return records
    
    def _extract_controllers(self, file_path: Path) -> List[TrainingRecord]:
        records = []
        with open(file_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rec = TrainingRecord()
                rec.id = f"ctrl_{row.get('Controller ID', '').lower().replace('-', '_')}"
                rec.source = 'examples'
                rec.category = 'controller'
                rec.equipment_type = row.get('Type', '')
                rec.equipment_id = row.get('Controller ID', '')
                rec.description = row.get('Notes', '')
                rec.controller_id = row.get('Controller ID', '')
                rec.network_address = row.get('IP Address', '')
                rec.metadata = {k: v for k, v in row.items() if k not in [
                    'Controller ID', 'Name', 'Vendor', 'Model', 'Firmware',
                    'Type', 'IP Address', 'Panel Location', 'Electrical Panel',
                    'Circuit', 'Status', 'Notes'
                ]}
                rec.source_file = str(file_path)
                rec.tags = ['controller', rec.equipment_type.lower()] if rec.equipment_type else ['controller']
                records.append(rec)
        return records
    
    def _map_point_kind(self, kind: str) -> str:
        mapping = {
            'sensor': 'sensor',
            'actuator': 'actuator',
            'setpoint': 'setpoint',
            'status': 'status',
            'alarm': 'alarm',
            'parameter': 'parameter'
        }
        return mapping.get(kind.lower() if kind else '', 'unknown')
    
    def _parse_float(self, val: Optional[str]) -> Optional[float]:
        if not val:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None


class DOEReferenceExtractor:
    """Extract from DOE Commercial Reference Buildings"""
    
    def __init__(self, raw_dir: Path):
        self.raw_dir = raw_dir
        self.data_dir = raw_dir / 'doe_reference'
    
    def download(self) -> bool:
        """Download DOE reference buildings if not present"""
        zip_path = self.raw_dir / 'RefBldgModels.zip'
        if not zip_path.exists():
            print("Downloading DOE Reference Buildings...")
            try:
                url = 'https://www.energy.gov/sites/prod/files/2016/02/f29/RefBldgModels.zip'
                response = requests.get(url, timeout=60)
                response.raise_for_status()
                zip_path.write_bytes(response.content)
            except Exception as e:
                print(f"Failed to download DOE data: {e}")
                return False
        
        # Extract
        extract_dir = self.raw_dir / 'doe_reference'
        if not (self.raw_dir / 'doe_reference').exists():
            print("Extracting DOE Reference Buildings...")
            with zipfile.ZipFile(self.raw_dir / 'RefBldgModels.zip', 'r') as zf:
                zf.extractall(self.raw_dir / 'doe_reference')
        return True
    
    def extract(self) -> List[TrainingRecord]:
        """Extract equipment and point data from DOE IDF files"""
        records = []
        # This is a placeholder - full IDF parsing would require eppy or similar
        # For now, we'll create template records from known DOE building types
        building_types = [
            'LargeOffice', 'MediumOffice', 'SmallOffice',
            'LargeHotel', 'SmallHotel', 'Hospital',
            'Outpatient', 'Warehouse', 'RetailStandalone',
            'RetailStripMall', 'PrimarySchool', 'SecondarySchool',
            'QuickServiceRestaurant', 'FullServiceRestaurant',
            'MidriseApartment', 'HighriseApartment'
        ]
        
        for bldg in building_types:
            rec = TrainingRecord()
            rec.id = f"doe_equip_{bldg.lower()}"
            rec.source = 'doe_reference'
            rec.category = 'equipment'
            rec.equipment_type = 'Building'
            rec.equipment_id = bldg
            rec.description = f"DOE Commercial Reference Building: {bldg}"
            rec.metadata = {'source': 'DOE Commercial Reference Buildings', 'climate_zones': '1A-8A'}
            rec.tags = ['reference_building', 'doe', 'commercial']
            rec.source_file = 'DOE_Reference_Buildings'
            records.append(rec)
        
        return records


class ASHRAERP1312Extractor:
    """Extract from ASHRAE RP-1312 FDD datasets"""
    
    def __init__(self, raw_dir: Path):
        self.raw_dir = raw_dir
        self.data_dir = raw_dir / 'ashrae_rp1312'
    
    def download(self) -> bool:
        zip_path = Path('/tmp/ASHRAE_RP1312_Data.zip')
        if not zip_path.exists():
            print("Downloading ASHRAE RP-1312 FDD dataset...")
            try:
                url = 'https://data.openei.org/submissions/910/files/ASHRAE_RP1312_Data.zip'
                response = requests.get(url, timeout=120)
                response.raise_for_status()
                zip_path.write_bytes(response.content)
            except Exception as e:
                print(f"Failed to download ASHRAE RP-1312: {e}")
                return False
        
        extract_dir = Path('/tmp/ashrae_rp1312')
        if not extract_dir.exists():
            print("Extracting ASHRAE RP-1312...")
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(extract_dir)
        return True
    
    def extract(self) -> List[TrainingRecord]:
        """Extract point data from ASHRAE RP-1312 CSV files"""
        records = []
        data_dir = Path('/tmp/ashrae_rp1312')
        
        if not data_dir.exists():
            return records
        
        for csv_file in data_dir.rglob('*.csv'):
            try:
                df = pd.read_csv(csv_file)
                # Extract metadata from filename
                system_type = csv_file.stem.lower()
                
                # Identify point columns (non-timestamp columns)
                timestamp_cols = [c for c in df.columns if 'time' in c.lower() or 'date' in c.lower()]
                point_cols = [c for c in df.columns if c not in timestamp_cols]
                
                for col in point_cols:
                    rec = TrainingRecord()
                    col_clean = col.replace(' ', '_').replace('-', '_').lower()
                    rec.id = f"ashrae_{csv_file.stem}_{col_clean}"
                    rec.source = 'ashrae_rp1312'
                    rec.category = 'point'
                    rec.equipment_type = self._infer_equipment_type(system_type)
                    rec.point_name = col
                    rec.point_type = self._infer_point_type(col)
                    rec.units = self._infer_units(col)
                    rec.description = f"ASHRAE RP-1312 {system_type} point: {col}"
                    rec.metadata = {
                        'source_file': csv_file.name,
                        'system_type': system_type,
                        'row_count': len(df)
                    }
                    rec.tags = ['ashrae', 'rp1312', 'fdd', system_type.lower().replace(' ', '_')]
                    rec.source_file = str(csv_file)
                    rec.tags = ['ashrae', 'rp1312', 'fdd']
                    # Add statistical info
                    if df[col].dtype in ['float64', 'int64']:
                        rec.metadata['min'] = float(df[col].min())
                        rec.metadata['max'] = float(df[col].max())
                        rec.metadata['mean'] = float(df[col].mean())
                        rec.metadata['std'] = float(df[col].std())
                    
                    rec.source_file = str(csv_file)
                    records.append(rec)
            except Exception as e:
                print(f"Error processing {csv_file}: {e}")
        
        return records
    
    def _infer_equipment_type(self, system_type: str) -> str:
        mapping = {
            'rtu': 'RTU',
            'ahu': 'AHU',
            'vav': 'VAV',
            'fan_coil': 'FCU',
            'chiller': 'Chiller',
            'boiler': 'Boiler',
            'cooling_tower': 'CoolingTower',
            'pump': 'Pump'
        }
        for key, val in mapping.items():
            if key in system_type.lower():
                return val
        return 'Unknown'
    
    def _infer_point_type(self, col_name: str) -> str:
        col_lower = col_name.lower()
        if any(k in col_lower for k in ['temp', 'temperature']):
            return 'sensor'
        elif any(k in col_lower for k in ['pressure', 'press']):
            return 'sensor'
        elif any(k in col_lower for k in ['flow', 'cfm', 'gpm']):
            return 'sensor'
        elif any(k in col_lower for k in ['cmd', 'command', 'pos', 'position', 'speed', 'vfd']):
            return 'actuator'
        elif any(k in col_lower for k in ['sp', 'setpoint', 'setpt']):
            return 'setpoint'
        elif any(k in col_lower for k in ['status', 'run', 'on_off', 'enable']):
            return 'status'
        elif any(k in col_lower for k in ['alarm', 'fault', 'trip']):
            return 'alarm'
        return 'unknown'
    
    def _infer_units(self, col_name: str) -> str:
        col_lower = col_name.lower()
        if any(k in col_lower for k in ['temp', 'temperature']):
            return 'degF'
        elif any(k in col_lower for k in ['pressure', 'press', 'static']):
            return 'inWC'
        elif 'cfm' in col_lower:
            return 'cfm'
        elif 'gpm' in col_lower:
            return 'gpm'
        elif 'speed' in col_lower or 'vfd' in col_lower:
            return '%'
        elif 'power' in col_lower or 'kw' in col_lower:
            return 'kW'
        elif 'amp' in col_lower:
            return 'A'
        elif 'volt' in col_lower:
            return 'V'
        return ''


# ============================================================
# MAIN ORCHESTRATOR
# ============================================================

class TrainingDataBuilder:
    """Main orchestrator for building training dataset"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.training_dir = project_root / 'training_data'
        self.raw_dir = self.training_dir / 'raw'
        self.processed_dir = self.training_dir / 'processed'
        
        # Create directories
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize extractors
        self.example_extractor = ExampleExtractor(PROJECT_ROOT / 'examples')
        self.doe_extractor = DOEReferenceExtractor(self.training_dir / 'raw')
        self.ashrae_extractor = ASHRAERP1312Extractor(self.training_dir / 'raw')
    
    def build(self, download_external: bool = True) -> Dict[str, int]:
        """Build complete training dataset"""
        print("=" * 60)
        print("BUILDING BAS ASSISTANT TRAINING DATASET")
        print("=" * 60)
        
        all_records = []
        stats = {}
        
        # 1. Extract from local examples
        print("\n[1/4] Extracting from local examples...")
        example_records = self.example_extractor.extract()
        print(f"  Extracted {len(example_records)} records from local examples")
        all_records.extend(example_records)
        stats['examples'] = len(example_records)
        
        # 2. External data sources (optional)
        if download_external:
            print("\n[2/4] Downloading external datasets...")
            
            # DOE Reference Buildings
            print("  Downloading DOE Reference Buildings...")
            if self.doe_extractor.download():
                doe_records = self.doe_extractor.extract()
                print(f"  Extracted {len(doe_records)} DOE reference records")
                all_records.extend(doe_records)
                stats['doe_reference'] = len(doe_records)
            
            # ASHRAE RP-1312
            print("  Downloading ASHRAE RP-1312...")
            if self.ashrae_extractor.download():
                ashrae_records = self.ashrae_extractor.extract()
                print(f"  Extracted {len(ashrae_records)} ASHRAE RP-1312 records")
                all_records.extend(ashrae_records)
                stats['ashrae_rp1312'] = len(ashrae_records)
        
        # 3. Normalize and deduplicate
        print("\n[3/4] Normalizing and deduplicating records...")
        all_records = self._normalize_records(all_records)
        all_records = self._deduplicate_records(all_records)
        print(f"  Final record count: {len(all_records)}")
        stats['total'] = len(all_records)
        
        # 4. Export in multiple formats
        print("\n[4/4] Exporting to training formats...")
        self._export_records(all_records)
        
        # Print summary
        self._print_summary(all_records)
        
        return stats
    
    def _normalize_records(self, records: List[TrainingRecord]) -> List[TrainingRecord]:
        """Normalize field values across all records"""
        for rec in records:
            # Normalize equipment type
            if rec.equipment_type:
                rec.equipment_type = rec.equipment_type.upper()
            
            # Normalize point type
            if rec.point_type:
                rec.point_type = rec.point_type.lower()
            
            # Normalize tags
            rec.tags = [t.lower().strip() for t in rec.tags if t]
            
            # Ensure ID is unique and valid
            if not rec.id:
                rec.id = f"{rec.source}_{rec.category}_{hash(str(rec.to_dict())) % 1000000}"
        
        return records
    
    def _deduplicate_records(self, records: List[TrainingRecord]) -> List[TrainingRecord]:
        """Remove duplicates based on ID"""
        seen = set()
        unique = []
        for rec in records:
            if rec.id not in seen:
                seen.add(rec.id)
                unique.append(rec)
        return unique
    
    def _export_records(self, records: List[TrainingRecord]):
        """Export records in multiple formats"""
        
        # JSONL (for LLM fine-tuning)
        jsonl_path = self.processed_dir / 'training_data.jsonl'
        with open(jsonl_path, 'w') as f:
            for rec in records:
                f.write(rec.to_jsonl() + '\n')
        print(f"  ✓ JSONL: {jsonl_path} ({len(records)} records)")
        
        # CSV (for spreadsheet analysis)
        csv_path = self.processed_dir / 'training_data.csv'
        df = pd.DataFrame([r.to_dict() for r in records])
        df.to_csv(csv_path, index=False)
        print(f"  ✓ CSV: {csv_path} ({len(records)} records, {len(df.columns)} columns)")
        
        # Parquet (for ML pipelines)
        parquet_path = self.processed_dir / 'training_data.parquet'
        df.to_parquet(parquet_path, index=False)
        print(f"  ✓ Parquet: {parquet_path}")
        
        # Category-specific splits
        self._export_category_splits(records)
        
        # Summary statistics
        stats_path = self.processed_dir / 'dataset_stats.json'
        stats = self._compute_stats(records)
        with open(stats_path, 'w') as f:
            json.dump(stats, f, indent=2)
        print(f"  ✓ Stats: {stats_path}")
    
    def _export_category_splits(self, records: List[TrainingRecord]):
        """Export category-specific files for targeted training"""
        categories = {}
        for rec in records:
            cat = rec.category
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(rec)
        
        for cat, recs in categories.items():
            cat_path = self.processed_dir / f'{cat}_data.jsonl'
            with open(cat_path, 'w') as f:
                for rec in recs:
                    f.write(rec.to_jsonl() + '\n')
            print(f"  ✓ {cat}: {cat_path} ({len(recs)} records)")
    
    def _compute_stats(self, records: List[TrainingRecord]) -> Dict:
        """Compute dataset statistics"""
        df = pd.DataFrame([r.to_dict() for r in records])
        
        return {
            'total_records': len(records),
            'by_source': df['source'].value_counts().to_dict(),
            'by_category': df['category'].value_counts().to_dict(),
            'by_equipment_type': df['equipment_type'].value_counts().to_dict() if 'equipment_type' in df.columns else {},
            'by_point_type': df['point_type'].value_counts().to_dict() if 'point_type' in df.columns else {},
            'sources': df['source'].unique().tolist(),
            'equipment_types': df['equipment_type'].unique().tolist() if 'equipment_type' in df.columns else [],
            'point_types': df['point_type'].unique().tolist() if 'point_type' in df.columns else [],
            'bacnet_types': df['bacnet_object_type'].unique().tolist() if 'bacnet_object_type' in df.columns else [],
            'total_points': len([r for r in records if r.category == 'point']),
            'total_equipment': len([r for r in records if r.category == 'equipment']),
            'total_controllers': len([r for r in records if r.category == 'controller']),
            'generated_at': datetime.now().isoformat()
        }
    
    def _print_summary(self, records: List[TrainingRecord]):
        print("\n" + "=" * 60)
        print("DATASET SUMMARY")
        print("=" * 60)
        print(f"Total Records: {len(records)}")
        
        by_cat = {}
        for r in records:
            by_cat[r.category] = by_cat.get(r.category, 0) + 1
        for cat, count in sorted(by_cat.items()):
            print(f"  {cat}: {count}")
        
        print("\nOutput files:")
        for fmt in OUTPUT_FORMATS:
            print(f"  training_data/processed/training_data.{fmt}")
        for cat in ['equipment', 'point', 'controller']:
            print(f"  training_data/processed/{cat}_data.jsonl")


# ============================================================
# CLI ENTRY POINT
# ============================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Build BAS Assistant training dataset')
    parser.add_argument('--no-external', action='store_true', 
                       help='Skip downloading external datasets')
    parser.add_argument('--output-dir', type=str, default='training_data',
                       help='Output directory for processed data')
    parser.add_argument('--formats', nargs='+', default=['jsonl', 'csv', 'parquet'],
                       help='Output formats')
    
    args = parser.parse_args()
    
    builder = TrainingDataBuilder(PROJECT_ROOT)
    builder.processed_dir = PROJECT_ROOT / args.output_dir / 'processed'
    builder.raw_dir = PROJECT_ROOT / args.output_dir / 'raw'
    
    stats = builder.build(download_external=not args.no_external)
    
    print("\n✅ Training data build complete!")
    return stats


if __name__ == '__main__':
    main()
