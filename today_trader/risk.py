"""Money management rules day traders use to survive losing streaks."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RiskPlan:
    balance: float
    risk_pct: float = 1.0        # % of balance per trade
    daily_loss_pct: float = 5.0  # stop trading for the day after losing this much
    max_losses_in_row: int = 3   # or after this many losses in a row
    payout: float = 0.85

    @property
    def stake(self) -> float:
        return round(self.balance * self.risk_pct / 100, 2)

    @property
    def daily_stop(self) -> float:
        return round(self.balance * self.daily_loss_pct / 100, 2)

    @property
    def breakeven_win_rate(self) -> float:
        return 1 / (1 + self.payout)

    def losing_streak_cost(self, n: int = 5) -> float:
        return round(self.stake * n, 2)

    def martingale_cost(self, n: int = 5) -> float:
        """What doubling after every loss would need for n losses in a row."""
        return round(self.stake * (2 ** n - 1), 2)

    def summary(self) -> str:
        lines = [
            f"Balance: {self.balance:,.2f}",
            f"Stake per trade ({self.risk_pct:g}%): {self.stake:,.2f}",
            f"Stop for the day after losing {self.daily_stop:,.2f} ({self.daily_loss_pct:g}%) "
            f"or {self.max_losses_in_row} losses in a row",
            f"Win rate needed to break even at {self.payout:.0%} payout: {self.breakeven_win_rate:.1%}",
            f"5 losses in a row at a flat stake costs {self.losing_streak_cost():,.2f}; "
            f"with martingale (doubling) it costs {self.martingale_cost():,.2f}. Don't use martingale.",
            "Rules: trade only signals that agree with the higher timeframe, skip news minutes,",
            "skip low-liquidity hours, never chase losses, and keep a journal of every trade.",
        ]
        return "\n".join(lines)
