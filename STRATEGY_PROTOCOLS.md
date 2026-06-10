# M-Series Synergy Protocol (MSSP)

## Purpose
To provide high-conviction analysis by combining M75 (Informed Flow) with structural and liquidity modules.

## The Three Core Strategies

### 1. The Liquidity Bridge (Reversals/Sweeps)
**Requirement:** M75 + M5 + M14
*   **M75:** Detects aggressive/informed flow.
*   **M5:** Identifies the target liquidity magnet.
*   **M14:** Confirms the successful liquidity sweep.
*   **High Conviction Signal:** M75 flow moves *toward* an M5 level, followed by an M14 sweep signal.

### 2. The Micro-Flow Stack (Trend Riding)
**Requirement:** M75 + M4 + M12
*   **M75:** Confirms the "Who" (aggressive direction).
*   **M4:** Confirms the "How" (immediate micro-trend).
*   **M12:** Identifies the "Wall" (resistance/support).
*   **High Conviction Signal:** M75 and M4 align in direction, and price is currently moving *away* from an M12 wall.

### 3. The Regime Breakout (Structural Shifts)
**Requirement:** M75 + M9 + M21
*   **M75:** Detects the internal flow shift.
*   **M9:** Identifies the local structure/swing.
*   **M21:** Identifies the broader regime.
*   **High Conviction Signal:** M75 flow shifts aggressively *before* the M9/M21 structure actually breaks.

## Temporal (Accumulation) Logic
When analyzing a sequence of scans:
- **Acceleration:** A rising M75 score over 3+ scans increases conviction.
- **Divergence:** Price moving against a rising M75 score suggests a massive "Absorption" event (High risk of reversal).
- **Confirmation:** M75 peaking exactly at the moment of an M14 sweep is the "Gold Standard" signal.

## Output Schema (Standardized Report)
Every analysis must follow this format:
1. **ACTIVE STRATEGY:** [Name]
2. **CONVICTION SCORE:** [0-100%]
3. **CONFLUENCE CHECK:**
   - M75: [Status/Score] $\rightarrow$ [Trend: $\uparrow$ / $\downarrow$ / $\rightarrow$]
   - Secondary Module(s): [Status/Score]
   - Tertiary Module(s): [Status/Score]
4. **NARRATIVE:** [Short, blunt explanation of the synergy]
5. **RISK ALERT:** [Potential trap/invalidating condition]
