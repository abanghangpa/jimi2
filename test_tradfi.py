from jimi_audit.src.utils.web_data_utils import fetch_tradfi_data
import time

def test_fetch():
    print("Testing TradFi fetch with timeout...")
    start = time.time()
    try:
        data = fetch_tradfi_data()
        print(f"Fetched in {time.time() - start:.2f}s")
        print("Data:", data)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_fetch()
