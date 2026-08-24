"""KalpaMani - autonomous long/short U.S. equity swing & momentum trading system.

Locked principle (Blueprint V2.1, section 1):
    AI may improve information processing. Mathematics and deterministic
    software control money, risk and broker actions.

Bootstrap status: no brokerage connectivity, no strategy logic and no order
submission exists in this package. Live trading is hard-disabled.
"""

from kalpamani.common.capital import (
    DEFAULT_STRATEGY_CAPITAL_USD,
    RiskParameters,
    StrategyCapital,
)
from kalpamani.common.environment import DEFAULT_ENVIRONMENT, Environment
from kalpamani.common.settings import (
    LIVE_TRADING_HARD_DISABLED,
    Settings,
    enable_live_trading,
    load_settings,
    require_live_execution_permitted,
)

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_ENVIRONMENT",
    "DEFAULT_STRATEGY_CAPITAL_USD",
    "LIVE_TRADING_HARD_DISABLED",
    "Environment",
    "RiskParameters",
    "Settings",
    "StrategyCapital",
    "__version__",
    "enable_live_trading",
    "load_settings",
    "require_live_execution_permitted",
]
