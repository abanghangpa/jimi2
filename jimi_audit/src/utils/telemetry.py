import time
import logging
from functools import wraps
from collections import defaultdict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PerformanceWatchdog")

class PerformanceMonitor:
    """
    A telemetry wrapper to track execution time across different components
    of the JIMI framework.
    """
    def __init__(self):
        self.metrics = defaultdict(list)
        self.start_time = None

    def start(self):
        self.start_time = time.time()

    def stop(self, component_name):
        if self.start_time is None:
            logger.warning(f"Stop called for {component_name} without start()")
            return 0
        
        elapsed = time.time() - self.start_time
        self.metrics[component_name].append(elapsed)
        self.start_time = None
        return elapsed

    def track(self, component_name):
        """Decorator to track the execution time of a function."""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                start = time.time()
                result = func(*args, **kwargs)
                elapsed = time.time() - start
                self.metrics[component_name].append(elapsed)
                return result
            return wrapper
        return decorator

    def get_summary(self):
        """Returns a summary of all tracked components."""
        summary = {}
        for component, times in self.metrics.items():
            if not times:
                continue
            summary[component] = {
                "avg": sum(times) / len(times),
                "max": max(times),
                "min": min(times),
                "count": len(times)
            }
        return summary

# Global monitor instance
perf_monitor = PerformanceMonitor()
