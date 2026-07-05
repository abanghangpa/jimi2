"""
Outcome Database — SQLite storage for signal outcomes and strategy performance.
"""
import sqlite3
import os
import json
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'outcomes.db')


class OutcomeDB:
    """SQLite database for signal outcomes and strategy performance metrics."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS signals (
                    signal_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    price REAL NOT NULL,
                    direction TEXT NOT NULL,
                    source TEXT NOT NULL,
                    regime TEXT,
                    swing_bias TEXT,
                    trend_dir TEXT,
                    ics REAL,
                    conviction REAL,
                    entry REAL,
                    sl REAL,
                    tp1 REAL,
                    tp2 REAL,
                    tp3 REAL,
                    sl_pct REAL,
                    tp1_pct REAL,
                    hold_window_hours INTEGER DEFAULT 2,
                    status TEXT DEFAULT 'PENDING',
                    created_at TEXT DEFAULT (datetime('now')),
                    evaluated_at TEXT,
                    outcome TEXT,
                    pnl_pct REAL,
                    hit_tp1 INTEGER DEFAULT 0,
                    hit_sl INTEGER DEFAULT 0,
                    max_favorable REAL,
                    max_adverse REAL,
                    bars_held INTEGER,
                    exit_price REAL,
                    exit_reason TEXT,
                    metadata TEXT
                );

                CREATE TABLE IF NOT EXISTS strategy_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy TEXT NOT NULL,
                    regime TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    period_days INTEGER NOT NULL,
                    total_signals INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    neutral INTEGER DEFAULT 0,
                    win_rate REAL DEFAULT 0.0,
                    avg_pnl REAL DEFAULT 0.0,
                    avg_win REAL DEFAULT 0.0,
                    avg_loss REAL DEFAULT 0.0,
                    profit_factor REAL DEFAULT 0.0,
                    max_drawdown REAL DEFAULT 0.0,
                    sharpe_estimate REAL DEFAULT 0.0,
                    last_updated TEXT DEFAULT (datetime('now')),
                    UNIQUE(strategy, regime, direction, period_days)
                );

                CREATE TABLE IF NOT EXISTS ensemble_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    combo_hash TEXT NOT NULL,
                    strategy_combo TEXT NOT NULL,
                    regime TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    period_days INTEGER NOT NULL,
                    total_signals INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    win_rate REAL DEFAULT 0.0,
                    avg_pnl REAL DEFAULT 0.0,
                    last_updated TEXT DEFAULT (datetime('now')),
                    UNIQUE(combo_hash, regime, direction, period_days)
                );

                CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
                CREATE INDEX IF NOT EXISTS idx_signals_source ON signals(source);
                CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
                CREATE INDEX IF NOT EXISTS idx_signals_regime ON signals(regime);
                CREATE INDEX IF NOT EXISTS idx_perf_strategy ON strategy_performance(strategy, regime, direction);
                CREATE INDEX IF NOT EXISTS idx_ensemble_combo ON ensemble_performance(combo_hash, regime, direction);
            """)
            conn.commit()
        finally:
            conn.close()

    def insert_signal(self, signal: Dict) -> bool:
        """Insert a new signal for tracking."""
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO signals (
                    signal_id, timestamp, price, direction, source,
                    regime, swing_bias, trend_dir, ics, conviction,
                    entry, sl, tp1, tp2, tp3, sl_pct, tp1_pct,
                    hold_window_hours, status, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
            """, (
                signal.get('signal_id'),
                signal.get('timestamp'),
                signal.get('price', 0),
                signal.get('direction'),
                signal.get('source', 'main_pipeline'),
                signal.get('regime'),
                signal.get('swing_bias'),
                signal.get('trend_dir'),
                signal.get('ics'),
                signal.get('conviction'),
                signal.get('entry'),
                signal.get('sl'),
                signal.get('tp1'),
                signal.get('tp2'),
                signal.get('tp3'),
                signal.get('sl_pct'),
                signal.get('tp1_pct'),
                signal.get('hold_window_hours', 2),
                json.dumps(signal.get('metadata', {})),
            ))
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    def get_pending_signals(self, max_age_hours: int = 48) -> List[Dict]:
        """Get signals that haven't been evaluated yet."""
        conn = self._get_conn()
        try:
            rows = conn.execute("""
                SELECT * FROM signals
                WHERE status = 'PENDING'
                AND datetime(timestamp) > datetime('now', ?)
                ORDER BY timestamp ASC
            """, (f'-{max_age_hours} hours',)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def update_outcome(self, signal_id: str, outcome: Dict) -> bool:
        """Update signal with outcome data."""
        conn = self._get_conn()
        try:
            conn.execute("""
                UPDATE signals SET
                    status = 'EVALUATED',
                    evaluated_at = ?,
                    outcome = ?,
                    pnl_pct = ?,
                    hit_tp1 = ?,
                    hit_sl = ?,
                    max_favorable = ?,
                    max_adverse = ?,
                    bars_held = ?,
                    exit_price = ?,
                    exit_reason = ?
                WHERE signal_id = ?
            """, (
                datetime.now(timezone.utc).isoformat(),
                outcome.get('outcome'),
                outcome.get('pnl_pct', 0),
                1 if outcome.get('hit_tp1') else 0,
                1 if outcome.get('hit_sl') else 0,
                outcome.get('max_favorable', 0),
                outcome.get('max_adverse', 0),
                outcome.get('bars_held', 0),
                outcome.get('exit_price'),
                outcome.get('exit_reason'),
                signal_id,
            ))
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    def get_strategy_stats(self, strategy: str, regime: str = None,
                           direction: str = None, days: int = 30) -> Dict:
        """Get performance stats for a strategy."""
        conn = self._get_conn()
        try:
            query = """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
                    SUM(CASE WHEN outcome = 'NEUTRAL' THEN 1 ELSE 0 END) as neutral,
                    AVG(CASE WHEN outcome IS NOT NULL THEN pnl_pct END) as avg_pnl,
                    AVG(CASE WHEN outcome = 'WIN' THEN pnl_pct END) as avg_win,
                    AVG(CASE WHEN outcome = 'LOSS' THEN pnl_pct END) as avg_loss,
                    MAX(pnl_pct) as max_pnl,
                    MIN(pnl_pct) as min_pnl
                FROM signals
                WHERE source = ?
                AND datetime(timestamp) > datetime('now', ?)
            """
            params = [strategy, f'-{days} days']

            if regime:
                query += " AND regime = ?"
                params.append(regime)
            if direction:
                query += " AND direction = ?"
                params.append(direction)

            row = conn.execute(query, params).fetchone()
            if not row or row['total'] == 0:
                return {'total': 0, 'win_rate': 0, 'avg_pnl': 0}

            total = row['total']
            wins = row['wins'] or 0
            losses = row['losses'] or 0
            avg_win = row['avg_win'] or 0
            avg_loss = row['avg_loss'] or 0

            return {
                'total': total,
                'wins': wins,
                'losses': losses,
                'neutral': row['neutral'] or 0,
                'win_rate': round(wins / total * 100, 1) if total > 0 else 0,
                'avg_pnl': round(row['avg_pnl'] or 0, 4),
                'avg_win': round(avg_win, 4),
                'avg_loss': round(avg_loss, 4),
                'profit_factor': round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else 999,
                'max_pnl': round(row['max_pnl'] or 0, 4),
                'min_pnl': round(row['min_pnl'] or 0, 4),
            }
        finally:
            conn.close()

    def get_regime_stats(self, days: int = 30) -> List[Dict]:
        """Get performance stats grouped by strategy + regime + direction."""
        conn = self._get_conn()
        try:
            rows = conn.execute("""
                SELECT
                    source as strategy,
                    regime,
                    direction,
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
                    AVG(CASE WHEN outcome IS NOT NULL THEN pnl_pct END) as avg_pnl
                FROM signals
                WHERE outcome IS NOT NULL
                AND datetime(timestamp) > datetime('now', ?)
                GROUP BY source, regime, direction
                HAVING total >= 5
                ORDER BY source, regime, direction
            """, (f'-{days} days',)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def upsert_strategy_performance(self, stats: Dict):
        """Update strategy_performance table with computed stats."""
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO strategy_performance (
                    strategy, regime, direction, period_days,
                    total_signals, wins, losses, neutral,
                    win_rate, avg_pnl, avg_win, avg_loss,
                    profit_factor, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                stats['strategy'], stats['regime'], stats['direction'],
                stats.get('period_days', 30),
                stats.get('total', 0), stats.get('wins', 0),
                stats.get('losses', 0), stats.get('neutral', 0),
                stats.get('win_rate', 0), stats.get('avg_pnl', 0),
                stats.get('avg_win', 0), stats.get('avg_loss', 0),
                stats.get('profit_factor', 0),
            ))
            conn.commit()
        finally:
            conn.close()

    def get_all_strategy_performance(self, days: int = 30) -> List[Dict]:
        """Get all strategy performance data for adaptive gating."""
        conn = self._get_conn()
        try:
            rows = conn.execute("""
                SELECT * FROM strategy_performance
                WHERE period_days = ?
                ORDER BY strategy, regime, direction
            """, (days,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_ensemble_stats(self, combo_hash: str, regime: str,
                           direction: str, days: int = 30) -> Optional[Dict]:
        """Get ensemble combo performance."""
        conn = self._get_conn()
        try:
            row = conn.execute("""
                SELECT * FROM ensemble_performance
                WHERE combo_hash = ? AND regime = ? AND direction = ? AND period_days = ?
            """, (combo_hash, regime, direction, days)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def upsert_ensemble_performance(self, stats: Dict):
        """Update ensemble performance table."""
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO ensemble_performance (
                    combo_hash, strategy_combo, regime, direction,
                    period_days, total_signals, wins, win_rate,
                    avg_pnl, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                stats['combo_hash'], stats['strategy_combo'],
                stats['regime'], stats['direction'],
                stats.get('period_days', 30),
                stats.get('total', 0), stats.get('wins', 0),
                stats.get('win_rate', 0), stats.get('avg_pnl', 0),
            ))
            conn.commit()
        finally:
            conn.close()

    def get_signal_count(self, status: str = None) -> int:
        """Get total signal count."""
        conn = self._get_conn()
        try:
            if status:
                row = conn.execute("SELECT COUNT(*) FROM signals WHERE status = ?", (status,)).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM signals").fetchone()
            return row[0]
        finally:
            conn.close()

    def cleanup_old_signals(self, days: int = 90):
        """Remove signals older than N days."""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM signals WHERE datetime(timestamp) < datetime('now', ?)", (f'-{days} days',))
            conn.commit()
        finally:
            conn.close()
