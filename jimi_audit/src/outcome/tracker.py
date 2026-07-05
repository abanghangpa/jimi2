"""
Outcome Tracker — evaluates signal outcomes against price history.
"""
import json
import os
import glob
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from .db import OutcomeDB

SCAN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'scans')
HOLD_WINDOWS = [2, 4, 8]  # hours


class OutcomeTracker:
    """Evaluates pending signals and records outcomes."""

    def __init__(self, db: OutcomeDB = None):
        self.db = db or OutcomeDB()
        self._price_cache = None
        self._sorted_timestamps = None

    def _load_price_history(self) -> Tuple[Dict[str, float], List[str]]:
        """Load price history from scan files. Cached for efficiency."""
        if self._price_cache is not None:
            return self._price_cache, self._sorted_timestamps

        price_by_ts = {}
        files = sorted(glob.glob(os.path.join(SCAN_DIR, "scan_*.json")))
        for f in files:
            try:
                with open(f) as fh:
                    d = json.load(fh)
                ts = d.get('timestamp')
                price = d.get('price')
                if ts and price:
                    price_by_ts[ts] = float(price)
            except Exception:
                pass

        self._price_cache = price_by_ts
        self._sorted_timestamps = sorted(price_by_ts.keys())
        return price_by_ts, self._sorted_timestamps

    def _find_price_at_offset(self, base_ts: str, hours: float) -> Optional[float]:
        """Find price closest to base_ts + hours."""
        _, sorted_ts = self._load_price_history()
        price_cache, _ = self._load_price_history()

        try:
            base_dt = datetime.strptime(base_ts, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                base_dt = datetime.fromisoformat(base_ts.replace('Z', '+00:00'))
                base_dt = base_dt.replace(tzinfo=None)
            except Exception:
                return None

        target = base_dt + timedelta(hours=hours)
        best = None
        best_diff = timedelta(hours=999)

        for t in sorted_ts:
            try:
                dt = datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            diff = abs(dt - target)
            if diff < best_diff:
                best_diff = diff
                best = price_cache[t]

        if best_diff < timedelta(hours=2):
            return best
        return None

    def _find_prices_in_range(self, base_ts: str, end_ts: str) -> List[float]:
        """Find all prices between base_ts and end_ts."""
        price_cache, sorted_ts = self._load_price_history()
        prices = []
        for t in sorted_ts:
            if base_ts <= t <= end_ts:
                prices.append(price_cache[t])
        return prices

    def import_from_pending_json(self) -> int:
        """Import signals from pending_signals.json into SQLite."""
        pending_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                     'data', 'pending_signals.json')
        if not os.path.exists(pending_file):
            return 0

        try:
            with open(pending_file) as f:
                signals = json.load(f)
        except (json.JSONDecodeError, IOError):
            return 0

        imported = 0
        for sig in signals:
            signal_id = sig.get('signal_id', '')
            if not signal_id:
                continue

            # Determine regime from available data
            regime = 'UNKNOWN'
            # Try to get regime from ensemble data or scan data
            ensemble = sig.get('ensemble', {})
            if ensemble and ensemble.get('regime'):
                regime_data = ensemble['regime']
                if isinstance(regime_data, dict):
                    regime = regime_data.get('regime', 'UNKNOWN')
                elif isinstance(regime_data, str):
                    regime = regime_data

            signal_data = {
                'signal_id': signal_id,
                'timestamp': sig.get('timestamp', ''),
                'price': sig.get('price', 0),
                'direction': sig.get('direction', ''),
                'source': sig.get('source', 'main_pipeline'),
                'regime': regime,
                'ics': sig.get('ics'),
                'conviction': sig.get('conviction'),
                'entry': sig.get('entry', 0),
                'sl': sig.get('sl', 0),
                'tp1': sig.get('tp1', 0),
                'tp2': sig.get('tp2', 0),
                'tp3': sig.get('tp3', 0),
                'sl_pct': sig.get('sl_pct', 0),
                'tp1_pct': sig.get('tp1_pct', 0),
                'hold_window_hours': sig.get('hold_window_hours', 2),
                'metadata': {'imported_from': 'pending_signals.json'},
            }
            if self.db.insert_signal(signal_data):
                imported += 1

        return imported

    def import_from_scans(self, limit: int = 500) -> int:
        """Import historical signals from scan files."""
        files = sorted(glob.glob(os.path.join(SCAN_DIR, "scan_*.json")))
        imported = 0

        for f in files[-limit:]:
            try:
                with open(f) as fh:
                    d = json.load(fh)

                if d.get('status') != 'SIGNAL':
                    continue

                ts = d.get('timestamp', '')
                source = d.get('source', 'main_pipeline')
                direction = d.get('direction', '')
                price = d.get('price', 0)

                if not ts or not direction or not price:
                    continue

                signal_id = f"{ts}_{source}_{direction}"

                # Check if already exists
                existing = self.db.get_pending_signals(max_age_hours=9999)
                if any(s['signal_id'] == signal_id for s in existing):
                    continue

                # Get regime
                trend = d.get('trend_dir', '')
                swing = d.get('swing_bias', '')
                if 'STRONG_DOWN' in trend:
                    regime = 'STRONG_DOWN'
                elif 'DOWN' in trend:
                    regime = 'DOWN'
                elif 'STRONG_UP' in trend:
                    regime = 'STRONG_UP'
                elif 'UP' in trend:
                    regime = 'UP'
                else:
                    regime = 'RANGING'

                signal_data = {
                    'signal_id': signal_id,
                    'timestamp': ts,
                    'price': price,
                    'direction': direction,
                    'source': source,
                    'regime': regime,
                    'swing_bias': swing,
                    'trend_dir': trend,
                    'ics': d.get('ics'),
                    'conviction': d.get('conviction'),
                    'entry': d.get('entry', price),
                    'sl': d.get('sl'),
                    'tp1': d.get('tp1'),
                    'tp2': d.get('tp2'),
                    'tp3': d.get('tp3'),
                    'sl_pct': d.get('sl_pct'),
                    'tp1_pct': d.get('tp1_pct'),
                    'hold_window_hours': d.get('hold_window_hours', 2),
                    'metadata': {'imported_from': 'scan_file', 'file': os.path.basename(f)},
                }
                if self.db.insert_signal(signal_data):
                    imported += 1

            except Exception:
                pass

        return imported

    def evaluate_pending(self) -> Dict:
        """Evaluate all pending signals against price history."""
        pending = self.db.get_pending_signals(max_age_hours=72)
        evaluated = 0
        results = {'wins': 0, 'losses': 0, 'neutral': 0, 'errors': 0}

        for sig in pending:
            ts = sig.get('timestamp', '')
            direction = sig.get('direction', '')
            entry = sig.get('entry') or sig.get('price', 0)
            sl = sig.get('sl', 0)
            tp1 = sig.get('tp1', 0)
            hold_hours = sig.get('hold_window_hours', 2)

            if not ts or not direction or not entry:
                continue

            # Check if enough time has passed
            try:
                sig_dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    sig_dt = datetime.fromisoformat(ts.replace('Z', '+00:00')).replace(tzinfo=None)
                except Exception:
                    results['errors'] += 1
                    continue

            now = datetime.utcnow()
            hours_elapsed = (now - sig_dt).total_seconds() / 3600

            if hours_elapsed < hold_hours:
                continue  # Not ready yet

            # Find price at hold window
            exit_price = self._find_price_at_offset(ts, hold_hours)
            if exit_price is None:
                results['errors'] += 1
                continue

            # Find max favorable/adverse during hold window
            end_ts = (sig_dt + timedelta(hours=hold_hours)).strftime("%Y-%m-%d %H:%M:%S")
            prices_in_range = self._find_prices_in_range(ts, end_ts)

            max_favorable = 0
            max_adverse = 0

            if direction == 'LONG':
                max_favorable = max((p - entry) / entry * 100 for p in prices_in_range) if prices_in_range else 0
                max_adverse = min((p - entry) / entry * 100 for p in prices_in_range) if prices_in_range else 0
                pnl_pct = (exit_price - entry) / entry * 100
                hit_tp1 = exit_price >= tp1 if tp1 > 0 else False
                hit_sl = exit_price <= sl if sl > 0 else False
            elif direction == 'SHORT':
                max_favorable = max((entry - p) / entry * 100 for p in prices_in_range) if prices_in_range else 0
                max_adverse = min((entry - p) / entry * 100 for p in prices_in_range) if prices_in_range else 0
                pnl_pct = (entry - exit_price) / entry * 100
                hit_tp1 = exit_price <= tp1 if tp1 > 0 else False
                hit_sl = exit_price >= sl if sl > 0 else False
            else:
                results['errors'] += 1
                continue

            # Classify outcome
            if hit_tp1:
                outcome = 'WIN'
            elif hit_sl:
                outcome = 'LOSS'
            elif pnl_pct > 0.1:
                outcome = 'WIN'
            elif pnl_pct < -0.1:
                outcome = 'LOSS'
            else:
                outcome = 'NEUTRAL'

            # Determine exit reason
            if hit_tp1:
                exit_reason = 'TP1_HIT'
            elif hit_sl:
                exit_reason = 'SL_HIT'
            elif pnl_pct > 0:
                exit_reason = 'HOLD_WIN'
            elif pnl_pct < 0:
                exit_reason = 'HOLD_LOSS'
            else:
                exit_reason = 'HOLD_FLAT'

            # Update database
            self.db.update_outcome(sig['signal_id'], {
                'outcome': outcome,
                'pnl_pct': round(pnl_pct, 4),
                'hit_tp1': hit_tp1,
                'hit_sl': hit_sl,
                'max_favorable': round(max_favorable, 4),
                'max_adverse': round(max_adverse, 4),
                'bars_held': int(hold_hours * 4),  # 15m bars
                'exit_price': round(exit_price, 2),
                'exit_reason': exit_reason,
            })

            evaluated += 1
            if outcome == 'WIN':
                results['wins'] += 1
            elif outcome == 'LOSS':
                results['losses'] += 1
            else:
                results['neutral'] += 1

        results['evaluated'] = evaluated
        return results

    def compute_strategy_performance(self, days: int = 30) -> List[Dict]:
        """Compute and store strategy performance stats."""
        stats = self.db.get_regime_stats(days=days)
        updated = []

        for row in stats:
            strategy = row['strategy']
            regime = row['regime']
            direction = row['direction']
            total = row['total']
            wins = row['wins'] or 0
            losses = row['losses'] or 0
            avg_pnl = row['avg_pnl'] or 0

            win_rate = round(wins / total * 100, 1) if total > 0 else 0

            perf = {
                'strategy': strategy,
                'regime': regime,
                'direction': direction,
                'period_days': days,
                'total': total,
                'wins': wins,
                'losses': losses,
                'neutral': total - wins - losses,
                'win_rate': win_rate,
                'avg_pnl': round(avg_pnl, 4),
                'avg_win': 0,  # Computed separately if needed
                'avg_loss': 0,
                'profit_factor': 0,
            }

            self.db.upsert_strategy_performance(perf)
            updated.append(perf)

        return updated

    def run_full_pipeline(self) -> Dict:
        """Run the complete outcome tracking pipeline."""
        result = {
            'imported_pending': 0,
            'imported_scans': 0,
            'evaluated': {},
            'performance_updated': 0,
        }

        # Step 1: Import signals
        result['imported_pending'] = self.import_from_pending_json()
        result['imported_scans'] = self.import_from_scans(limit=500)

        # Step 2: Evaluate pending outcomes
        result['evaluated'] = self.evaluate_pending()

        # Step 3: Update strategy performance
        perf = self.compute_strategy_performance(days=30)
        result['performance_updated'] = len(perf)

        # Step 4: Cleanup old data
        self.db.cleanup_old_signals(days=90)

        return result
