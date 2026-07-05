"""
Strategy Health Monitor — proactive degradation detection.

Tracks rolling 7d/14d/30d win rates and alerts when a strategy degrades.
"""
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
from .db import OutcomeDB

ALERT_DEGRADATION_THRESHOLD = 15.0  # 7d WR < 30d WR by 15%+ = alert
RED_ZONE_WR = 35.0                   # WR below 35% = red zone
YELLOW_ZONE_WR = 45.0                # WR below 45% = yellow zone
MIN_SAMPLES_7D = 5                   # Min samples for 7d stats
MIN_SAMPLES_14D = 10                 # Min samples for 14d stats
MIN_SAMPLES_30D = 15                 # Min samples for 30d stats


class StrategyHealthMonitor:
    """
    Monitors strategy health across multiple time windows.
    Detects degradation and generates alerts.
    """

    def __init__(self, db: OutcomeDB = None):
        self.db = db or OutcomeDB()

    def _get_stats_for_period(self, strategy: str, regime: str,
                               direction: str, days: int) -> Dict:
        """Get stats for a specific period."""
        stats = self.db.get_strategy_stats(strategy, regime, direction, days)
        return stats

    def check_health(self, strategy: str, regime: str, direction: str) -> Dict:
        """
        Check health of a strategy across time windows.
        
        Returns:
            {
                'strategy': str,
                'regime': str,
                'direction': str,
                'status': 'GREEN' | 'YELLOW' | 'RED' | 'DEGRADED',
                'stats': {7d: ..., 14d: ..., 30d: ...},
                'alerts': [...],
            }
        """
        stats_7d = self._get_stats_for_period(strategy, regime, direction, 7)
        stats_14d = self._get_stats_for_period(strategy, regime, direction, 14)
        stats_30d = self._get_stats_for_period(strategy, regime, direction, 30)

        alerts = []
        status = 'GREEN'

        # Check 30d baseline
        if stats_30d['total'] >= MIN_SAMPLES_30D:
            wr_30d = stats_30d['win_rate']

            if wr_30d < RED_ZONE_WR:
                status = 'RED'
                alerts.append({
                    'type': 'RED_ZONE',
                    'message': f'{strategy} {direction} in {regime}: {wr_30d:.1f}% WR (30d) — below {RED_ZONE_WR}%',
                    'severity': 'HIGH',
                })
            elif wr_30d < YELLOW_ZONE_WR:
                if status != 'RED':
                    status = 'YELLOW'
                alerts.append({
                    'type': 'YELLOW_ZONE',
                    'message': f'{strategy} {direction} in {regime}: {wr_30d:.1f}% WR (30d) — below {YELLOW_ZONE_WR}%',
                    'severity': 'MEDIUM',
                })

        # Check 7d degradation
        if stats_7d['total'] >= MIN_SAMPLES_7D and stats_30d['total'] >= MIN_SAMPLES_30D:
            wr_7d = stats_7d['win_rate']
            wr_30d = stats_30d['win_rate']
            degradation = wr_30d - wr_7d

            if degradation > ALERT_DEGRADATION_THRESHOLD:
                if status != 'RED':
                    status = 'DEGRADED'
                alerts.append({
                    'type': 'DEGRADATION',
                    'message': f'{strategy} {direction} in {regime}: 7d WR {wr_7d:.1f}% vs 30d WR {wr_30d:.1f}% (dropped {degradation:.1f}%)',
                    'severity': 'HIGH',
                    'wr_7d': wr_7d,
                    'wr_30d': wr_30d,
                    'degradation': degradation,
                })

        # Check 14d trend
        if stats_14d['total'] >= MIN_SAMPLES_14D and stats_30d['total'] >= MIN_SAMPLES_30D:
            wr_14d = stats_14d['win_rate']
            wr_30d = stats_30d['win_rate']
            trend = wr_14d - wr_30d

            if trend < -10:
                alerts.append({
                    'type': 'TREND_DOWN',
                    'message': f'{strategy} {direction} in {regime}: 14d WR {wr_14d:.1f}% trending down from 30d {wr_30d:.1f}%',
                    'severity': 'MEDIUM',
                })

        return {
            'strategy': strategy,
            'regime': regime,
            'direction': direction,
            'status': status,
            'stats': {
                '7d': stats_7d,
                '14d': stats_14d,
                '30d': stats_30d,
            },
            'alerts': alerts,
        }

    def scan_all(self, days: int = 30) -> Dict:
        """
        Scan all strategies for health issues.
        
        Returns:
            {
                'healthy': [...],
                'degraded': [...],
                'red': [...],
                'alerts': [...],
            }
        """
        all_perf = self.db.get_all_strategy_performance(days=days)

        healthy = []
        degraded = []
        red = []
        all_alerts = []

        for perf in all_perf:
            strategy = perf['strategy']
            regime = perf['regime']
            direction = perf['direction']

            health = self.check_health(strategy, regime, direction)

            if health['status'] == 'RED':
                red.append(health)
            elif health['status'] in ('DEGRADED', 'YELLOW'):
                degraded.append(health)
            else:
                healthy.append(health)

            all_alerts.extend(health['alerts'])

        return {
            'healthy': healthy,
            'degraded': degraded,
            'red': red,
            'alerts': all_alerts,
        }

    def generate_report(self, days: int = 30) -> str:
        """Generate a human-readable health report."""
        scan = self.scan_all(days)

        lines = []
        lines.append("=" * 80)
        lines.append("  STRATEGY HEALTH MONITOR REPORT")
        lines.append(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append("=" * 80)

        # Alerts first
        if scan['alerts']:
            lines.append("\n  🚨 ALERTS")
            lines.append("  " + "-" * 60)
            for alert in sorted(scan['alerts'], key=lambda a: {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}.get(a['severity'], 3)):
                icon = '🔴' if alert['severity'] == 'HIGH' else '🟡' if alert['severity'] == 'MEDIUM' else '⚪'
                lines.append(f"  {icon} [{alert['type']}] {alert['message']}")

        # Red zone
        if scan['red']:
            lines.append("\n  🔴 RED ZONE STRATEGIES")
            lines.append("  " + "-" * 60)
            for h in scan['red']:
                s = h['stats']['30d']
                lines.append(f"  {h['strategy']:<25} {h['direction']:<8} {h['regime']:<15} "
                           f"WR: {s['win_rate']:.1f}% (n={s['total']})")

        # Degraded
        if scan['degraded']:
            lines.append("\n  🟡 DEGRADED STRATEGIES")
            lines.append("  " + "-" * 60)
            for h in scan['degraded']:
                s7 = h['stats']['7d']
                s30 = h['stats']['30d']
                lines.append(f"  {h['strategy']:<25} {h['direction']:<8} {h['regime']:<15} "
                           f"7d: {s7['win_rate']:.1f}% → 30d: {s30['win_rate']:.1f}%")

        # Healthy
        if scan['healthy']:
            lines.append(f"\n  🟢 HEALTHY ({len(scan['healthy'])} strategies)")
            lines.append("  " + "-" * 60)
            for h in sorted(scan['healthy'], key=lambda x: x['stats']['30d'].get('win_rate', 0), reverse=True):
                s = h['stats']['30d']
                if s['total'] > 0:
                    lines.append(f"  {h['strategy']:<25} {h['direction']:<8} {h['regime']:<15} "
                               f"WR: {s['win_rate']:.1f}% (n={s['total']})")

        lines.append("")
        return "\n".join(lines)

    def generate_alert_message(self) -> Optional[str]:
        """Generate a WhatsApp-friendly alert message for critical issues."""
        scan = self.scan_all(days=30)

        critical_alerts = [a for a in scan['alerts'] if a['severity'] == 'HIGH']
        if not critical_alerts:
            return None

        lines = []
        lines.append("🚨 JIMI Strategy Health Alert")
        lines.append("")

        for alert in critical_alerts[:5]:  # Max 5 alerts
            lines.append(f"• {alert['message']}")

        if len(critical_alerts) > 5:
            lines.append(f"... and {len(critical_alerts) - 5} more")

        lines.append("")
        lines.append("Run health monitor for full report.")

        return "\n".join(lines)
