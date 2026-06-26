def fetch_all_tradfi_data(config=None):
    """Fetch all traditional-finance data (FX, commodities, VIX) using yfinance.

    Returns dict of DataFrames keyed by signal name. Failed fetches return None for that key (non-fatal).
    Each DataFrame has multiple rows (5d of data) so modules can calculate rate of change.
    """
    cfg = config or {}
    data = {}

    print("  📊 Fetching TradFi data (DXY, 10Y, VIX, gold, WTI, USD/JPY)...")

    try:
        import yfinance as yf

        # Fetch DXY (5d, 15m bars)
        if cfg.get('M67_ENABLED', True) or cfg.get('M66_ENABLED', True):
            try:
                df = yf.download("DX-Y.NYB", period="5d", interval="15m", progress=False)
                if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
                    df.columns = df.columns.droplevel(1)
                if df is not None and len(df) > 1:
                    data["dxy"] = df
                    print(f"    DXY: {len(df)} bars")
            except Exception as e:
                print(f"    DXY fetch failed: {e}")

        # Fetch 10Y Yield (5d, 1h bars)
        if cfg.get('M68_ENABLED', True):
            try:
                df = yf.download("^TNX", period="5d", interval="1h", progress=False)
                if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
                    df.columns = df.columns.droplevel(1)
                if df is not None and len(df) > 1:
                    df['yield'] = df['Close'] / 10.0
                    data["tnx"] = df
                    print(f"    10Y: {len(df)} bars")
            except Exception as e:
                print(f"    10Y fetch failed: {e}")

        # Fetch VIX (5d, 15m bars)
        if cfg.get('M69_ENABLED', True):
            try:
                df = yf.download("^VIX", period="5d", interval="15m", progress=False)
                if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
                    df.columns = df.columns.droplevel(1)
                if df is not None and len(df) > 1:
                    data["vix"] = df
                    print(f"    VIX: {len(df)} bars")
            except Exception as e:
                print(f"    VIX fetch failed: {e}")

        # Fetch WTI Crude (5d, 15m bars)
        if cfg.get('M70_ENABLED', True):
            try:
                df = yf.download("CL=F", period="5d", interval="15m", progress=False)
                if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
                    df.columns = df.columns.droplevel(1)
                if df is not None and len(df) > 1:
                    data["wti"] = df
                    print(f"    WTI: {len(df)} bars")
            except Exception as e:
                print(f"    WTI fetch failed: {e}")

        # Fetch Gold (5d, 15m bars)
        if cfg.get('M71_ENABLED', True):
            try:
                df = yf.download("GC=F", period="5d", interval="15m", progress=False)
                if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
                    df.columns = df.columns.droplevel(1)
                if df is not None and len(df) > 1:
                    data["gold"] = df
                    print(f"    Gold: {len(df)} bars")
            except Exception as e:
                print(f"    Gold fetch failed: {e}")

        # Fetch USD/JPY (5d, 1m bars for M66)
        if cfg.get('M66_ENABLED', True):
            try:
                df = yf.download("JPY=X", period="5d", interval="1m", progress=False)
                if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
                    df.columns = df.columns.droplevel(1)
                if df is not None and len(df) > 0:
                    data["usdjpy"] = df
                    print(f"    USD/JPY: {len(df)} bars")
            except Exception as e:
                print(f"    USD/JPY fetch failed: {e}")

    except ImportError:
        print("  ⚠️  yfinance not installed")

    return data
