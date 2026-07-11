"""Troubleshooting Assistant - Analyzes trends, alarms, and system behavior for diagnostics."""

from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

from ..models import Project, Point, PointKind, Equipment, EquipmentType


class IssueSeverity(str, Enum):
    """Severity of a troubleshooting issue."""
    CRITICAL = "critical"      # Immediate action required
    HIGH = "high"              # Action required soon
    MEDIUM = "medium"          # Investigation recommended
    LOW = "low"                # Monitor
    INFO = "info"              # Informational


class IssueCategory(str, Enum):
    """Category of troubleshooting issue."""
    SENSOR_DRIFT = "sensor_drift"
    SENSOR_FAILURE = "sensor_failure"
    ACTUATOR_ISSUE = "actuator_issue"
    CONTROL_LOOP = "control_loop"
    ECONOMIZER = "economizer"
    ENERGY_WASTE = "energy_waste"
    COMFORT = "comfort"
    COMMUNICATION = "communication"
    SEQUENCE = "sequence"
    MAINTENANCE = "maintenance"


@dataclass
class TrendPoint:
    """A single trend data point."""
    timestamp: datetime
    value: float
    quality: str = "good"  # good, questionable, bad


@dataclass
class TrendData:
    """Trend data for a point."""
    point_name: str
    points: list[TrendPoint] = field(default_factory=list)
    interval_seconds: int = 900  # 15 min default
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    @property
    def values(self) -> list[float]:
        return [p.value for p in self.points if p.quality == "good"]

    @property
    def count(self) -> int:
        return len(self.values)

    @property
    def mean(self) -> Optional[float]:
        if not self.values:
            return None
        return statistics.mean(self.values)

    @property
    def stdev(self) -> Optional[float]:
        if len(self.values) < 2:
            return None
        return statistics.stdev(self.values)

    @property
    def min_val(self) -> Optional[float]:
        if not self.values:
            return None
        return min(self.values)

    @property
    def max_val(self) -> Optional[float]:
        if not self.values:
            return None
        return max(self.values)


@dataclass
class AlarmEvent:
    """An alarm event."""
    alarm_name: str
    point_name: str
    timestamp: datetime
    severity: str  # critical, high, medium, low
    state: str  # active, acknowledged, cleared
    value: Optional[float] = None
    limit: Optional[float] = None
    message: str = ""


@dataclass
class TroubleshootingIssue:
    """A detected troubleshooting issue."""
    issue_id: str
    category: IssueCategory
    severity: IssueSeverity
    title: str
    description: str
    equipment_id: str
    point_names: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    root_cause_hypothesis: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0-1
    detected_at: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)


@dataclass
class TroubleshootingReport:
    """Complete troubleshooting report for equipment or project."""
    report_id: str
    project_id: str
    equipment_id: Optional[str] = None
    generated_at: datetime = field(default_factory=datetime.now)
    issues: list[TroubleshootingIssue] = field(default_factory=list)
    trend_summary: dict = field(default_factory=dict)
    alarm_summary: dict = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.HIGH)

    @property
    def by_category(self) -> dict[IssueCategory, int]:
        counts = defaultdict(int)
        for issue in self.issues:
            counts[issue.category] += 1
        return dict(counts)


class TrendAnalyzer:
    """Analyzes trend data for anomalies and patterns."""

    def __init__(self, project: Project):
        self.project = project

    def analyze_trend(self, trend: TrendData, point: Point) -> list[TroubleshootingIssue]:
        """Analyze a single trend for issues."""
        issues = []

        if trend.count < 10:
            return issues  # Not enough data

        values = trend.values
        mean = trend.mean
        stdev = trend.stdev

        # 1. Check for flatlined sensor (no variation)
        if stdev is not None and stdev < 0.01 * (trend.max_val - trend.min_val + 1):
            issues.append(TroubleshootingIssue(
                issue_id=f"FLAT-{trend.point_name}",
                category=IssueCategory.SENSOR_FAILURE,
                severity=IssueSeverity.HIGH,
                title=f"Sensor {trend.point_name} appears flatlined",
                description=f"Sensor shows minimal variation (stdev={stdev:.3f}) over {trend.count} samples",
                equipment_id=self._get_equipment_for_point(trend.point_name),
                point_names=[trend.point_name],
                evidence=[f"StdDev: {stdev:.3f}", f"Range: {trend.min_val:.1f}-{trend.max_val:.1f}"],
                root_cause_hypothesis=[
                    "Sensor hardware failure",
                    "Wiring disconnected",
                    "Input channel failed",
                    "Value stuck in controller",
                ],
                recommended_actions=[
                    "Verify sensor wiring and connections",
                    "Check controller input channel",
                    "Compare with redundant sensor if available",
                    "Replace sensor if confirmed failed",
                ],
                confidence=0.85,
            ))

        # 2. Check for out-of-range values
        if point.range_min is not None and point.range_max is not None:
            out_of_range = [v for v in values if v < point.range_min or v > point.range_max]
            if out_of_range:
                pct = len(out_of_range) / len(values) * 100
                severity = IssueSeverity.CRITICAL if pct > 5 else IssueSeverity.HIGH
                issues.append(TroubleshootingIssue(
                    issue_id=f"OOR-{trend.point_name}",
                    category=IssueCategory.SENSOR_DRIFT if pct < 5 else IssueCategory.SENSOR_FAILURE,
                    severity=severity,
                    title=f"Sensor {trend.point_name} out of range ({pct:.1f}% of samples)",
                    description=f"{len(out_of_range)} of {len(values)} samples outside configured range [{point.range_min}, {point.range_max}]",
                    equipment_id=self._get_equipment_for_point(trend.point_name),
                    point_names=[trend.point_name],
                    evidence=[f"Min: {trend.min_val:.1f}", f"Max: {trend.max_val:.1f}", f"Expected: {point.range_min}-{point.range_max}"],
                    root_cause_hypothesis=[
                        "Sensor calibration drift",
                        "Sensor failure",
                        "Wrong range configured",
                        "Transient condition (if brief)",
                    ],
                    recommended_actions=[
                        "Verify sensor calibration",
                        "Check range configuration matches sensor",
                        "Inspect sensor installation",
                        "Replace if drift confirmed",
                    ],
                    confidence=0.9,
                ))

        # 3. Check for excessive noise/jitter
        if stdev is not None and mean is not None and mean != 0:
            cv = stdev / abs(mean)  # Coefficient of variation
            if cv > 0.15:  # >15% CV indicates noise
                issues.append(TroubleshootingIssue(
                    issue_id=f"NOISE-{trend.point_name}",
                    category=IssueCategory.SENSOR_DRIFT,
                    severity=IssueSeverity.MEDIUM,
                    title=f"Sensor {trend.point_name} showing excessive noise (CV={cv:.1%})",
                    description=f"High variability detected - possible electrical noise or failing sensor",
                    equipment_id=self._get_equipment_for_point(trend.point_name),
                    point_names=[trend.point_name],
                    evidence=[f"CV: {cv:.1%}", f"StdDev: {stdev:.2f}", f"Mean: {mean:.2f}"],
                    root_cause_hypothesis=[
                        "Electrical noise on wiring",
                        "Sensor nearing end of life",
                        "Poor grounding/shielding",
                        "Controller input filtering issue",
                    ],
                    recommended_actions=[
                        "Check wiring shielding and grounding",
                        "Verify sensor power supply stability",
                        "Add/input filtering in controller",
                        "Plan sensor replacement",
                    ],
                    confidence=0.7,
                ))

        # 4. Check for stuck-at-value (same value repeated)
        if len(values) > 5:
            # Check for 5+ consecutive identical values
            max_consecutive = 1
            current = 1
            for i in range(1, len(values)):
                if abs(values[i] - values[i-1]) < 0.001:
                    current += 1
                    max_consecutive = max(max_consecutive, current)
                else:
                    current = 1

            if max_consecutive >= 5:
                issues.append(TroubleshootingIssue(
                    issue_id=f"STUCK-{trend.point_name}",
                    category=IssueCategory.SENSOR_FAILURE,
                    severity=IssueSeverity.HIGH,
                    title=f"Sensor {trend.point_name} possibly stuck",
                    description=f"Same value repeated {max_consecutive} consecutive times",
                    equipment_id=self._get_equipment_for_point(trend.point_name),
                    point_names=[trend.point_name],
                    evidence=[f"Max consecutive identical: {max_consecutive}"],
                    root_cause_hypothesis=[
                        "Sensor hardware failure",
                        "Controller input channel failure",
                        "Software bug in trend logging",
                    ],
                    recommended_actions=[
                        "Verify with handheld meter",
                        "Check controller diagnostics",
                        "Reboot controller if software issue suspected",
                    ],
                    confidence=0.8,
                ))

        return issues

    def _get_equipment_for_point(self, point_name: str) -> str:
        point = next((p for p in self.project.points if p.name == point_name), None)
        return point.equipment_id if point else "Unknown"


class AlarmAnalyzer:
    """Analyzes alarm patterns for systemic issues."""

    def __init__(self, project: Project):
        self.project = project

    def analyze_alarms(self, alarms: list[AlarmEvent]) -> list[TroubleshootingIssue]:
        """Analyze alarm events for patterns."""
        issues = []

        if not alarms:
            return issues

        # Group by point
        by_point = defaultdict(list)
        for alarm in alarms:
            by_point[alarm.point_name].append(alarm)

        # 1. Chattering alarms (frequent on/off)
        for point_name, point_alarms in by_point.items():
            active_alarms = [a for a in point_alarms if a.state == "active"]
            if len(active_alarms) > 10:
                # Check time between alarms
                active_alarms.sort(key=lambda a: a.timestamp)
                intervals = [
                    (active_alarms[i+1].timestamp - active_alarms[i].timestamp).total_seconds()
                    for i in range(len(active_alarms)-1)
                ]
                avg_interval = statistics.mean(intervals) if intervals else 0
                if avg_interval < 300:  # Less than 5 min average
                    issues.append(TroubleshootingIssue(
                        issue_id=f"CHATTER-{point_name}",
                        category=IssueCategory.SENSOR_DRIFT,
                        severity=IssueSeverity.HIGH,
                        title=f"Alarm chattering on {point_name}",
                        description=f"{len(active_alarms)} alarm activations, avg interval {avg_interval:.0f}s",
                        equipment_id=self._get_equip(point_name),
                        point_names=[point_name],
                        evidence=[f"Activations: {len(active_alarms)}", f"Avg interval: {avg_interval:.0f}s"],
                        root_cause_hypothesis=[
                            "Deadband too tight",
                            "Sensor noise at threshold",
                            "Process oscillation",
                        ],
                        recommended_actions=[
                            "Increase alarm deadband",
                            "Add alarm delay",
                            "Fix root cause of oscillation",
                        ],
                        confidence=0.85,
                    ))

        # 2. Stale alarms (active for long time)
        now = datetime.now()
        for alarm in alarms:
            if alarm.state == "active":
                duration = (now - alarm.timestamp).total_seconds() / 3600  # hours
                if duration > 24:
                    issues.append(TroubleshootingIssue(
                        issue_id=f"STALE-{alarm.point_name}",
                        category=IssueCategory.MAINTENANCE,
                        severity=IssueSeverity.HIGH if duration > 72 else IssueSeverity.MEDIUM,
                        title=f"Stale alarm on {alarm.point_name} ({duration:.1f}h active)",
                        description=f"Alarm has been active for {duration:.1f} hours without acknowledgment",
                        equipment_id=self._get_equip(alarm.point_name),
                        point_names=[alarm.point_name],
                        evidence=[f"Active since: {alarm.timestamp}", f"Duration: {duration:.1f}h"],
                        root_cause_hypothesis=[
                            "Issue not yet addressed",
                            "Alarm acknowledged but not cleared",
                            "Sensor/system failure persists",
                        ],
                        recommended_actions=[
                            "Investigate root cause",
                            "Acknowledge and resolve",
                            "Escalate if maintenance needed",
                        ],
                        confidence=0.95,
                    ))

        # 3. Alarm floods (many alarms in short time)
        if len(alarms) > 50:
            recent = [a for a in alarms if (now - a.timestamp).total_seconds() < 3600]
            if len(recent) > 20:
                issues.append(TroubleshootingIssue(
                    issue_id="FLOOD-RECENT",
                    category=IssueCategory.SEQUENCE,
                    severity=IssueSeverity.CRITICAL,
                    title="Alarm flood detected",
                    description=f"{len(recent)} alarms in last hour - possible systemic issue",
                    equipment_id="Multiple",
                    point_names=list(set(a.point_name for a in recent)),
                    evidence=[f"Total alarms: {len(alarms)}", f"Recent (1h): {len(recent)}"],
                    root_cause_hypothesis=[
                        "Controller/communication failure",
                        "Power event",
                        "Network issue",
                        "Sequence logic error",
                    ],
                    recommended_actions=[
                        "Check controller status",
                        "Verify communication network",
                        "Review recent changes",
                        "Check power supplies",
                    ],
                    confidence=0.9,
                ))

        return issues

    def _get_equip(self, point_name: str) -> str:
        point = next((p for p in self.project.points if p.name == point_name), None)
        return point.equipment_id if point else "Unknown"


class ControlLoopAnalyzer:
    """Analyzes control loop performance."""

    def __init__(self, project: Project):
        self.project = project

    def analyze_pid_loop(
        self,
        pv_trend: TrendData,  # Process variable
        sp_trend: TrendData,  # Setpoint
        cv_trend: TrendData,  # Control variable (output)
        point: Point,
    ) -> list[TroubleshootingIssue]:
        """Analyze PID control loop performance."""
        issues = []

        if pv_trend.count < 20 or sp_trend.count < 20:
            return issues

        pv_vals = pv_trend.values
        sp_vals = sp_trend.values
        cv_vals = cv_trend.values

        # Align by timestamp (simplified - assumes same timestamps)
        min_len = min(len(pv_vals), len(sp_vals), len(cv_vals))
        if min_len < 20:
            return issues

        pv_vals = pv_vals[:min_len]
        sp_vals = sp_vals[:min_len]
        cv_vals = cv_vals[:min_len]

        # 1. Calculate error
        errors = [pv_vals[i] - sp_vals[i] for i in range(min_len)]
        mean_error = statistics.mean(errors)
        error_stdev = statistics.stdev(errors) if len(errors) > 1 else 0

        # 2. Check for offset (steady-state error)
        if abs(mean_error) > 0.5 * (point.range_max or 100 - point.range_min or 0):
            issues.append(TroubleshootingIssue(
                issue_id=f"OFFSET-{point.name}",
                category=IssueCategory.CONTROL_LOOP,
                severity=IssueSeverity.MEDIUM,
                title=f"Control loop offset on {point.name}",
                description=f"Steady-state error of {mean_error:.1f} units (PV-SP)",
                equipment_id=self._get_equip(point.name),
                point_names=[point.name],
                evidence=[f"Mean error: {mean_error:.1f}", f"Error StdDev: {error_stdev:.1f}"],
                root_cause_hypothesis=[
                    "Integral gain too low",
                    "Integral action disabled",
                    "Output saturation",
                    "Process nonlinearity",
                ],
                recommended_actions=[
                    "Increase integral gain (Ki)",
                    "Enable integral action if disabled",
                    "Check for output saturation",
                    "Verify actuator range matches control range",
                ],
                confidence=0.75,
            ))

        # 3. Check for oscillation
        # Count zero crossings of error
        zero_crossings = sum(1 for i in range(1, len(errors)) if errors[i] * errors[i-1] < 0)
        oscillation_freq = zero_crossings / min_len
        if oscillation_freq > 0.3:  # More than 30% zero crossings
            issues.append(TroubleshootingIssue(
                issue_id=f"OSCILLATE-{point.name}",
                category=IssueCategory.CONTROL_LOOP,
                severity=IssueSeverity.HIGH,
                title=f"Control loop oscillation on {point.name}",
                description=f"Error signal crossing zero {zero_crossings} times in {min_len} samples",
                equipment_id=self._get_equip(point.name),
                point_names=[point.name],
                evidence=[f"Zero crossings: {zero_crossings}/{min_len}", f"Freq: {oscillation_freq:.1%}"],
                root_cause_hypothesis=[
                    "Proportional gain too high",
                    "Integral gain too high",
                    "Derivative gain too high",
                    "Process deadtime not accounted for",
                ],
                recommended_actions=[
                    "Reduce proportional gain (Kp)",
                    "Reduce integral gain (Ki)",
                    "Add/derivative filtering",
                    "Consider PID tuning procedure",
                ],
                confidence=0.85,
            ))

        # 4. Check for windup (output saturated)
        cv_saturated = sum(1 for v in cv_vals if v >= 95 or v <= 5)
        sat_pct = cv_saturated / len(cv_vals) * 100
        if sat_pct > 20:
            issues.append(TroubleshootingIssue(
                issue_id=f"WINDUP-{point.name}",
                category=IssueCategory.CONTROL_LOOP,
                severity=IssueSeverity.HIGH,
                title=f"Possible integral windup on {point.name}",
                description=f"Control output saturated {sat_pct:.0f}% of time",
                equipment_id=self._get_equip(point.name),
                point_names=[point.name],
                evidence=[f"Output saturated: {sat_pct:.0f}%"],
                root_cause_hypothesis=[
                    "Process demand exceeds capacity",
                    "Integral windup during saturation",
                    "Wrong output range configured",
                ],
                recommended_actions=[
                    "Add anti-windup logic",
                    "Verify actuator sizing",
                    "Check output range configuration",
                ],
                confidence=0.8,
            ))

        return issues

    def _get_equip(self, point_name: str) -> str:
        point = next((p for p in self.project.points if p.name == point_name), None)
        return point.equipment_id if point else "Unknown"


class TroubleshootingAssistant:
    """Main troubleshooting assistant combining all analyzers."""

    def __init__(self, project: Project):
        self.project = project
        self.trend_analyzer = TrendAnalyzer(project)
        self.alarm_analyzer = AlarmAnalyzer(project)
        self.loop_analyzer = ControlLoopAnalyzer(project)

    def analyze_equipment(
        self,
        equipment_id: str,
        trends: dict[str, TrendData],
        alarms: list[AlarmEvent],
        pid_loops: dict[str, tuple[TrendData, TrendData, TrendData]] = None,
    ) -> TroubleshootingReport:
        """Analyze a single equipment for issues."""
        issues = []
        equip = self.project.get_equipment(equipment_id)

        # Analyze trends
        for point_name, trend in trends.items():
            point = self.project.get_point(point_name)
            if point:
                issues.extend(self.trend_analyzer.analyze_trend(trend, point))

        # Analyze alarms
        issues.extend(self.alarm_analyzer.analyze_alarms(alarms))

        # Analyze PID loops
        if pid_loops:
            for loop_name, (pv, sp, cv) in pid_loops.items():
                pv_point = self.project.get_point(pv.point_name) if pv else None
                if pv_point:
                    issues.extend(self.loop_analyzer.analyze_pid_loop(pv, sp, cv, pv_point))

        # Equipment-specific checks
        issues.extend(self._check_equipment_specific(equip))

        return TroubleshootingReport(
            report_id=f"TS-{equipment_id}-{datetime.now().strftime('%Y%m%d%H%M')}",
            project_id=self.project.metadata.project_id,
            equipment_id=equipment_id,
            issues=issues,
            trend_summary=self._summarize_trends(trends),
            alarm_summary=self._summarize_alarms(alarms),
            recommendations=self._generate_recommendations(issues),
        )

    def _check_equipment_specific(self, equip: Equipment) -> list[TroubleshootingIssue]:
        """Run equipment-specific diagnostic checks."""
        issues = []

        if not equip:
            return issues

        points = self.project.get_points_for_equipment(equip.id)

        if equip.type == EquipmentType.AHU:
            issues.extend(self._check_ahu(equip, points))
        elif equip.type == EquipmentType.VAV:
            issues.extend(self._check_vav(equip, points))
        elif equip.type == EquipmentType.CHILLER:
            issues.extend(self._check_chiller(equip, points))
        elif equip.type == EquipmentType.BOILER:
            issues.extend(self._check_boiler(equip, points))

        return issues

    def _check_ahu(self, equip: Equipment, points: list[Point]) -> list[TroubleshootingIssue]:
        """AHU-specific checks."""
        issues = []

        # Find key points
        sat = next((p for p in points if "SAT" in p.name or "SUPPLY" in p.name.upper()), None)
        mat = next((p for p in points if "MAT" in p.name or "MIXED" in p.name.upper()), None)
        rat = next((p for p in points if "RAT" in p.name or "RETURN" in p.name.upper()), None)
        oat = next((p for p in points if "OAT" in p.name or "OUTSIDE" in p.name.upper()), None)
        econ = next((p for p in points if "ECON" in p.name or "OA DAMPER" in p.name.upper()), None)
        sf = next((p for p in points if "SF " in p.name or "SUPPLY FAN" in p.name.upper()), None)
        freeze = next((p for p in points if "FREEZE" in p.name.upper()), None)

        # Check freeze stat
        if freeze and freeze.kind == PointKind.STATUS:
            issues.append(TroubleshootingIssue(
                issue_id=f"FREEZE-{equip.id}",
                category=IssueCategory.SEQUENCE,
                severity=IssueSeverity.INFO,
                title=f"Freeze stat present on {equip.id}",
                description="Verify freeze stat wiring and sequence logic",
                equipment_id=equip.id,
                point_names=[freeze.name],
                recommended_actions=[
                    "Verify freeze stat trips at 35°F",
                    "Confirm fan shutdown and valve open on trip",
                    "Test annually",
                ],
                confidence=0.9,
            ))

        # Check economizer configuration
        if econ and oat and rat:
            issues.append(TroubleshootingIssue(
                issue_id=f"ECON-CFG-{equip.id}",
                category=IssueCategory.ECONOMIZER,
                severity=IssueSeverity.INFO,
                title=f"Economizer on {equip.id} - verify configuration",
                description="Economizer damper present - verify high limit and changeover strategy",
                equipment_id=equip.id,
                point_names=[econ.name, oat.name, rat.name],
                recommended_actions=[
                    "Verify high limit setpoint (typically 70°F dry bulb or 28 BTU/lb enthalpy)",
                    "Confirm differential dry bulb or enthalpy changeover",
                    "Test economizer operation seasonally",
                ],
                confidence=0.7,
            ))

        return issues

    def _check_vav(self, equip: Equipment, points: list[Point]) -> list[TroubleshootingIssue]:
        """VAV-specific checks."""
        issues = []

        flow = next((p for p in points if "FLOW" in p.name.upper()), None)
        damper = next((p for p in points if "DAMPER" in p.name.upper()), None)
        reheat = next((p for p in points if "REHEAT" in p.name.upper()), None)
        zt = next((p for p in points if "ZT" in p.name.upper() or "ZONE TEMP" in p.name.upper()), None)

        if flow and damper:
            issues.append(TroubleshootingIssue(
                issue_id=f"VAV-FLOW-{equip.id}",
                category=IssueCategory.CONTROL_LOOP,
                severity=IssueSeverity.INFO,
                title=f"VAV {equip.id} flow/damper - verify calibration",
                description="Verify flow sensor calibration and damper authority",
                equipment_id=equip.id,
                point_names=[flow.name, damper.name],
                recommended_actions=[
                    "Calibrate flow sensor per manufacturer",
                    "Verify damper stroke 0-100% = 0-100% flow",
                    "Check minimum flow setpoint",
                ],
                confidence=0.8,
            ))

        return issues

    def _check_chiller(self, equip: Equipment, points: list[Point]) -> list[TroubleshootingIssue]:
        """Chiller-specific checks."""
        issues = []

        chws = next((p for p in points if "CHWS" in p.name.upper()), None)
        chwr = next((p for p in points if "CHWR" in p.name.upper()), None)
        cws = next((p for p in points if "CWS" in p.name.upper()), None)
        cwr = next((p for p in points if "CWR" in p.name.upper()), None)

        if chws and chwr:
            issues.append(TroubleshootingIssue(
                issue_id=f"CHILLER-DT-{equip.id}",
                category=IssueCategory.ENERGY_WASTE,
                severity=IssueSeverity.INFO,
                title=f"Chiller {equip.id} - monitor delta-T",
                description="Monitor CHWS/CHWR delta-T for evaporator performance",
                equipment_id=equip.id,
                point_names=[chws.name, chwr.name],
                recommended_actions=[
                    "Target delta-T typically 10-12°F",
                    "Low delta-T indicates flow issues or fouling",
                    "High delta-T may indicate underflow",
                ],
                confidence=0.85,
            ))

        return issues

    def _check_boiler(self, equip: Equipment, points: list[Point]) -> list[TroubleshootingIssue]:
        """Boiler-specific checks."""
        issues = []

        hws = next((p for p in points if "HWS" in p.name.upper()), None)
        hwr = next((p for p in points if "HWR" in p.name.upper()), None)
        flame = next((p for p in points if "FLAME" in p.name.upper()), None)

        if hws and hwr:
            issues.append(TroubleshootingIssue(
                issue_id=f"BOILER-DT-{equip.id}",
                category=IssueCategory.ENERGY_WASTE,
                severity=IssueSeverity.INFO,
                title=f"Boiler {equip.id} - monitor delta-T",
                description="Monitor HWS/HWR delta-T for boiler efficiency",
                equipment_id=equip.id,
                point_names=[hws.name, hwr.name],
                recommended_actions=[
                    "Target delta-T typically 20-30°F",
                    "Low delta-T = excess flow or fouling",
                    "Check combustion efficiency annually",
                ],
                confidence=0.85,
            ))

        return issues

    def _summarize_trends(self, trends: dict[str, TrendData]) -> dict:
        return {
            "total_points": len(trends),
            "total_samples": sum(t.count for t in trends.values()),
            "date_range": {
                "start": min((t.start_time for t in trends.values() if t.start_time), default=None),
                "end": max((t.end_time for t in trends.values() if t.end_time), default=None),
            },
        }

    def _summarize_alarms(self, alarms: list[AlarmEvent]) -> dict:
        by_severity = defaultdict(int)
        by_state = defaultdict(int)
        for a in alarms:
            by_severity[a.severity] += 1
            by_state[a.state] += 1

        return {
            "total": len(alarms),
            "by_severity": dict(by_severity),
            "by_state": dict(by_state),
        }

    def _generate_recommendations(self, issues: list[TroubleshootingIssue]) -> list[str]:
        recs = set()
        for issue in issues:
            for action in issue.recommended_actions:
                recs.add(action)
        return list(recs)[:10]  # Top 10


def analyze_trends(project: Project, trends: dict[str, TrendData]) -> list[TroubleshootingIssue]:
    """Analyze trends for issues."""
    analyzer = TrendAnalyzer(project)
    all_issues = []
    for point_name, trend in trends.items():
        point = project.get_point(point_name)
        if point:
            all_issues.extend(analyzer.analyze_trend(trend, point))
    return all_issues


def analyze_alarms(project: Project, alarms: list[AlarmEvent]) -> list[TroubleshootingIssue]:
    """Analyze alarms for issues."""
    analyzer = AlarmAnalyzer(project)
    return analyzer.analyze_alarms(alarms)


__all__ = [
    "TroubleshootingAssistant",
    "TrendAnalyzer",
    "AlarmAnalyzer",
    "ControlLoopAnalyzer",
    "TroubleshootingReport",
    "TroubleshootingIssue",
    "TrendData",
    "TrendPoint",
    "AlarmEvent",
    "IssueSeverity",
    "IssueCategory",
    "analyze_trends",
    "analyze_alarms",
]