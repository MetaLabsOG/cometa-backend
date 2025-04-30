import time
import logging
import asyncio
from enum import Enum

logger = logging.getLogger(__name__)

class CircuitState(Enum):
    CLOSED = "CLOSED"        # Normal operation
    OPEN = "OPEN"            # Circuit tripped, requests fail fast
    HALF_OPEN = "HALF_OPEN"  # Testing if service recovered

class CircuitBreaker:
    def __init__(self, name, failure_threshold=5, recovery_timeout=60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0
        self._lock = asyncio.Lock()
    
    async def execute(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection"""
        async with self._lock:
            # Check if we should transition from OPEN to HALF_OPEN
            if (self.state == CircuitState.OPEN and 
                time.time() - self.last_failure_time > self.recovery_timeout):
                logger.info(f"Circuit '{self.name}' state: OPEN → HALF_OPEN")
                self.state = CircuitState.HALF_OPEN
            
            # Fast fail if circuit is open
            if self.state == CircuitState.OPEN:
                remaining = self.recovery_timeout - (time.time() - self.last_failure_time)
                logger.warning(f"Circuit '{self.name}' is OPEN. Retry after {max(0, remaining):.1f}s")
                raise Exception(f"Circuit '{self.name}' is open. Service unavailable.")
        
        try:
            result = await func(*args, **kwargs)
            
            # Success - reset circuit if needed
            async with self._lock:
                if self.state == CircuitState.HALF_OPEN:
                    logger.info(f"Circuit '{self.name}' state: HALF_OPEN → CLOSED")
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                elif self.state == CircuitState.CLOSED:
                    # Reset count on success
                    self.failure_count = 0
            
            return result
            
        except Exception as e:
            # Failure - potentially trip circuit
            async with self._lock:
                self.failure_count += 1
                self.last_failure_time = time.time()
                
                if ((self.state == CircuitState.CLOSED and 
                     self.failure_count >= self.failure_threshold) or
                    self.state == CircuitState.HALF_OPEN):
                    if self.state != CircuitState.OPEN:
                        logger.warning(f"Circuit '{self.name}' tripped to OPEN: {str(e)}")
                        self.state = CircuitState.OPEN
            
            # Re-raise the original exception
            raise

# Registry to store circuit breakers
_circuit_breakers = {}

def get_circuit_breaker(name, failure_threshold=5, recovery_timeout=60):
    """Get or create a circuit breaker by name"""
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(name, failure_threshold, recovery_timeout)
    return _circuit_breakers[name] 