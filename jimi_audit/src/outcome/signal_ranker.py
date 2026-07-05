"""
Signal Ranker — scores signals by expected win rate using historical outcomes.

Instead of filtering binary pass/fail, this ranks signals by probability
and only emits the top tier.
"""
import hashlib
import json
from typing import Dict, List, Optional, Tuple
from .db import OutcomeDB

# Minimum samples before we trust historical data
MIN_SAMPLES_CONFIDENT = 20    # High confidence in WR
MIN_SAMPLES_TENTATIVE = 10    # Tentative, use with caution
MIN_SAMPLES_PRIOR = 5         # Prior belief, very cautious

# Prior WR (when no data exists) — based on overall system performance
PRIOR_WR = 0.46
PRIOR_WEIGHT = 5  # Equivalent to 5 samples of prior belief

# Tier thresholds
TIER_A_THRESHOLD = 0.55  # 55%+ WR → high confidence
TIER_B_THRESHOLD = 0.48  # 48%+ WR → acceptable
TIER_C_THRESHOLD = 0.40  # 40%+ WR → marginal
# Below 40% → reject


class SignalRanker:
    """
    Scores signals based on historical WR for their (strategy, regime, direction) combo.
    
    Uses Bayesian shrinkage: when sample size is small, shrinks toward the prior (46%).
    As sample size grows, trusts the observed WR more.
    """

    def __init__(self, db: OutcomeDB = None):
        self.db = db or OutcomeDB()
        self._perf_cache = {}
        self._cache_ts = None

    def _refresh_cache(self, days: int = 30):
        """Refresh performance cache."""
        perf = self.db.get_all_strategy_performance(days=days)
        self._perf_cache = {}
        for p in perf:
            key = (p['strategy'], p['regime'], p['direction'])
            self._perf_cache[key] = p

    def _bayesian_wr(self, wins: int, total: int) -> float:
        """
        Bayesian estimate of win rate.
        Shrinks toward PRIOR_WR when sample is small.
        """
        if total == 0:
            return PRIOR_WR
        # Beta distribution with prior
        alpha = wins + PRIOR_WEIGHT * PRIOR_WR
        beta = (total - wins) + PRIOR_WEIGHT * (1 - PRIOR_WR)
        return alpha / (alpha + beta)

    def score_signal(self, strategy: str, regime: str, direction: str,
                     conviction: float = 0, ics: float = 0,
                     days: int = 30) -> Dict:
        """
        Score a signal based on historical WR.
        
        Returns:
            {
                'score': float (0-1, higher = better),
                'tier': 'A' | 'B' | 'C' | 'REJECT',
                'wr_estimate': float,
                'sample_size': int,
                'confidence': 'high' | 'tentative' | 'prior',
                'action': 'TRADE' | 'WATCH' | 'SKIP',
            }
        """
        self._refresh_cache(days)
        key = (strategy, regime, direction)
        perf = self._perf_cache.get(key)

        if not perf or perf['total_signals'] == 0:
            # No data — use prior with low confidence
            wr = PRIOR_WR
            total = 0
            confidence = 'prior'
        else:
            total = perf['total_signals']
            wins = perf['wins']
            wr = self._bayesian_wr(wins, total)

            if total >= MIN_SAMPLES_CONFIDENT:
                confidence = 'high'
            elif total >= MIN_SAMPLES_TENTATIVE:
                confidence = 'tentative'
            else:
                confidence = 'prior'

        # Adjust score based on additional signals
        score = wr

        # Conviction bonus: higher conviction → slightly higher score
        if conviction > 0.7:
            score += 0.02
        elif conviction < 0.5:
            score -= 0.02

        # ICS adjustment: very low ICS → penalty
        if ics and ics < 0.40:
            score -= 0.03
        elif ics and ics > 0.50:
            score += 0.01

        score = max(0, min(1, score))

        # Assign tier
        if score >= TIER_A_THRESHOLD:
            tier = 'A'
            action = 'TRADE'
        elif score >= TIER_B_THRESHOLD:
            tier = 'B'
            action = 'TRADE'
        elif score >= TIER_C_THRESHOLD:
            tier = 'C'
            action = 'WATCH'
        else:
            tier = 'REJECT'
            action = 'SKIP'

        return {
            'score': round(score, 4),
            'tier': tier,
            'wr_estimate': round(wr * 100, 1),
            'sample_size': total,
            'confidence': confidence,
            'action': action,
            'strategy': strategy,
            'regime': regime,
            'direction': direction,
        }

    def rank_signals(self, signals: List[Dict], regime: str,
                     days: int = 30) -> Dict:
        """
        Rank a list of signals by expected WR.
        
        Returns:
            {
                'ranked': [...],  # sorted by score descending
                'tier_a': [...],  # 55%+ WR
                'tier_b': [...],  # 48-55% WR
                'tier_c': [...],  # 40-48% WR
                'rejected': [...], # <40% WR
                'best': {...},    # top signal
            }
        """
        scored = []
        for sig in signals:
            strategy = sig.get('strategy', '')
            direction = sig.get('direction', '')
            conviction = sig.get('conviction', 0)
            ics = sig.get('ics', 0)

            result = self.score_signal(strategy, regime, direction,
                                       conviction, ics, days)
            result['original_signal'] = sig
            scored.append(result)

        # Sort by score descending
        scored.sort(key=lambda x: x['score'], reverse=True)

        tier_a = [s for s in scored if s['tier'] == 'A']
        tier_b = [s for s in scored if s['tier'] == 'B']
        tier_c = [s for s in scored if s['tier'] == 'C']
        rejected = [s for s in scored if s['tier'] == 'REJECT']

        return {
            'ranked': scored,
            'tier_a': tier_a,
            'tier_b': tier_b,
            'tier_c': tier_c,
            'rejected': rejected,
            'best': scored[0] if scored else None,
        }

    def generate_report(self, days: int = 30) -> str:
        """Generate a human-readable ranking report."""
        self._refresh_cache(days)

        lines = []
        lines.append("=" * 90)
        lines.append("  SIGNAL RANKING — Historical WR by Strategy + Regime + Direction")
        lines.append("  Period: %d days | Prior WR: %.0f%%" % (days, PRIOR_WR * 100))
        lines.append("=" * 90)

        # Group by tier
        tier_a = []
        tier_b = []
        tier_c = []
        rejected = []

        for key, perf in self._perf_cache.items():
            strategy, regime, direction = key
            result = self.score_signal(strategy, regime, direction, days=days)
            result['total'] = perf['total_signals']
            result['wins'] = perf['wins']

            if result['tier'] == 'A':
                tier_a.append(result)
            elif result['tier'] == 'B':
                tier_b.append(result)
            elif result['tier'] == 'C':
                tier_c.append(result)
            else:
                rejected.append(result)

        def print_tier(tier_name, tier_list, icon):
            if not tier_list:
                return
            lines.append(f"\n  {icon} {tier_name}")
            lines.append("  " + "-" * 85)
            lines.append(f"  {'Strategy':<28} {'Regime':<15} {'Dir':<7} {'WR%':<8} {'Score':<8} {'N':<6} {'Conf':<10}")
            for s in sorted(tier_list, key=lambda x: x['score'], reverse=True):
                lines.append(f"  {s['strategy']:<28} {s['regime']:<15} {s['direction']:<7} "
                           f"{s['wr_estimate']:<8.1f} {s['score']:<8.3f} {s['total']:<6} {s['confidence']:<10}")

        print_tier("TIER A — High Confidence (55%+ WR)", tier_a, "🟢")
        print_tier("TIER B — Acceptable (48-55% WR)", tier_b, "🟡")
        print_tier("TIER C — Marginal (40-48% WR)", tier_c, "🟠")
        print_tier("REJECT — Below 40% WR", rejected, "🔴")

        lines.append(f"\n  SUMMARY:")
        lines.append(f"    Tier A: {len(tier_a)} combos — TRADE with full size")
        lines.append(f"    Tier B: {len(tier_b)} combos — TRADE with reduced size")
        lines.append(f"    Tier C: {len(tier_c)} combos — WATCH only, no trade")
        lines.append(f"    Reject: {len(rejected)} combos — SKIP entirely")

        return "\n".join(lines)
