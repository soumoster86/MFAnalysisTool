"""LLM-powered financial assistant (OpenAI-compatible) with RAG-lite context."""

from __future__ import annotations

from typing import Any, Optional

from config.settings import settings
from utils.logging_config import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are an expert mutual fund and personal finance assistant for Indian investors.
You help users understand mutual funds, risk metrics, SIPs, asset allocation, and portfolio decisions.

STRICT RULES:
1. Never hallucinate numbers. Only use figures provided in the CONTEXT block or clearly label estimates.
2. Always cite which calculation or context field a number comes from when possible.
3. Prefer educational, balanced language. You are NOT a SEBI-registered advisor.
4. Include a short disclaimer when giving decision-oriented answers.
5. If data is missing, say so and explain what is needed.
6. Match the user's requested style (beginner / Warren Buffett / with examples) when asked.
7. Explain Alpha, Beta, Sharpe, Sortino, Drawdown, Expense Ratio clearly when asked.
"""


class FinancialAssistant:
    """Chat assistant with optional OpenAI-compatible backend."""

    # Models that reject non-default temperature (reasoning / restricted APIs)
    _TEMP_RESTRICTED_MARKERS = (
        "gpt-5",
        "o1",
        "o3",
        "o4",
        "-sol",
        "reasoning",
    )

    def __init__(self) -> None:
        self.model = settings.openai_model
        self.api_key = settings.openai_api_key
        self.base_url = settings.openai_base_url
        # None = omit temperature (use API default). Set OPENAI_TEMPERATURE in .env for chat models.
        self.temperature = getattr(settings, "openai_temperature", None)

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    @classmethod
    def supports_custom_temperature(cls, model: str) -> bool:
        """gpt-5.x / o-series / *-sol often only allow default temperature (1)."""
        m = (model or "").lower()
        return not any(marker in m for marker in cls._TEMP_RESTRICTED_MARKERS)

    def build_context(
        self,
        *,
        portfolio_summary: Optional[dict[str, Any]] = None,
        fund_analytics: Optional[list[dict[str, Any]]] = None,
        comparison: Optional[dict[str, Any]] = None,
        extra: Optional[str] = None,
    ) -> str:
        parts = ["CONTEXT (authoritative data — cite these figures):"]
        if portfolio_summary:
            parts.append(f"PORTFOLIO: {portfolio_summary}")
        if fund_analytics:
            for i, fa in enumerate(fund_analytics, 1):
                parts.append(f"FUND[{i}]: {fa}")
        if comparison:
            parts.append(f"COMPARISON: {comparison}")
        if extra:
            parts.append(f"EXTRA: {extra}")
        if len(parts) == 1:
            parts.append("No portfolio/fund metrics were injected for this turn.")
        return "\n".join(parts)

    def chat(
        self,
        user_message: str,
        *,
        context: str = "",
        history: Optional[list[dict[str, str]]] = None,
        temperature: Optional[float] = None,
    ) -> dict[str, Any]:
        """
        Returns {reply, source, model, error?}.
        Falls back to deterministic education engine if no API key.

        Temperature is omitted for models that only support the API default
        (e.g. gpt-5.6-sol). Override via arg or OPENAI_TEMPERATURE in settings.
        """
        if not self.is_configured:
            return {
                "reply": self._offline_reply(user_message, context),
                "source": "offline_rules",
                "model": None,
                "error": None,
            }

        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key, base_url=self.base_url or None)
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            if context:
                messages.append({"role": "system", "content": context})
            for h in history or []:
                messages.append({"role": h["role"], "content": h["content"]})
            messages.append({"role": "user", "content": user_message})

            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
            }
            # Prefer explicit arg → settings → legacy 0.3 only for classic chat models
            temp = temperature if temperature is not None else self.temperature
            if temp is None and self.supports_custom_temperature(self.model):
                temp = 0.3
            if temp is not None and self.supports_custom_temperature(self.model):
                kwargs["temperature"] = float(temp)
            else:
                logger.debug(
                    "Omitting temperature for model {} (default only)", self.model
                )

            try:
                resp = client.chat.completions.create(**kwargs)
            except Exception as first_exc:
                # Retry without temperature if API rejects custom value
                err = str(first_exc).lower()
                if "temperature" in err and "temperature" in kwargs:
                    logger.warning(
                        "Model rejected temperature={}; retrying with API default",
                        kwargs.get("temperature"),
                    )
                    kwargs.pop("temperature", None)
                    resp = client.chat.completions.create(**kwargs)
                else:
                    raise

            reply = resp.choices[0].message.content or ""
            return {
                "reply": reply,
                "source": "openai_compatible",
                "model": self.model,
                "error": None,
            }
        except Exception as exc:
            logger.error("LLM call failed: {}", exc)
            return {
                "reply": self._offline_reply(user_message, context)
                + f"\n\n_(LLM error: {exc}. Showing offline answer.)_",
                "source": "offline_fallback",
                "model": self.model,
                "error": str(exc),
            }

    def _offline_reply(self, message: str, context: str) -> str:
        m = message.lower().strip()
        glossary = {
            "alpha": (
                "**Alpha** measures excess return vs a benchmark after adjusting for market risk. "
                "Positive alpha means the fund beat what its beta would predict. "
                "Cite: CAPM residual; in this app see `metrics.alpha` in CONTEXT."
            ),
            "beta": (
                "**Beta** measures sensitivity to the market. Beta 1.0 ≈ moves with the market; "
                ">1 is more volatile; <1 is defensive. Cite: regression of fund vs benchmark returns."
            ),
            "sharpe": (
                "**Sharpe Ratio** = (Return − Risk-free rate) / Volatility. "
                "Higher is better risk-adjusted performance. Cite: `metrics.sharpe`."
            ),
            "sortino": (
                "**Sortino Ratio** is like Sharpe but only penalizes downside volatility. "
                "Useful when upside volatility is desirable. Cite: `metrics.sortino`."
            ),
            "drawdown": (
                "**Maximum Drawdown** is the worst peak-to-trough decline in NAV. "
                "E.g. -30% means the fund fell 30% from a prior high before recovering. "
                "Cite: `metrics.max_drawdown`."
            ),
            "expense": (
                "**Expense Ratio (TER)** is the annual fund cost as % of AUM. "
                "Lower costs compound into higher investor returns, all else equal. "
                "Cite: `expense_ratio` in CONTEXT."
            ),
        }
        for key, text in glossary.items():
            if key in m:
                return text + self._ctx_footer(context)

        if "sip" in m and ("stop" in m or "pause" in m):
            return (
                "Whether to stop a SIP depends on goal horizon, emergency corpus, and whether the "
                "fund's thesis broke (manager exit, style drift, persistent underperformance with high TER). "
                "Temporary market drops alone are usually a weak reason to stop a long-horizon SIP. "
                "Review health score, drawdown, and overlap in this tool before deciding.\n\n"
                "Disclaimer: educational only, not personalized advice."
                + self._ctx_footer(context)
            )

        if "should i invest" in m or "invest?" in m:
            return (
                "A structured check before investing:\n"
                "1. Goal + horizon (≥5y for equity-heavy funds)\n"
                "2. Emergency fund in place\n"
                "3. Risk appetite matches category (small-cap ≠ large-cap)\n"
                "4. Costs (prefer Direct plans), overlap with existing portfolio\n"
                "5. Health score pillars (growth/risk/quality/cost)\n\n"
                "Use the Recommendation and X-Ray modules for calculation-backed inputs."
                + self._ctx_footer(context)
            )

        if "warren buffett" in m or "buffett" in m:
            return (
                "Buffett-style framing: Prefer simple businesses you understand, long holding periods, "
                "and avoid paying high fees for mediocre active results. An index fund in a durable "
                "market often beats a fancy story. Margin of safety matters more than excitement."
                + self._ctx_footer(context)
            )

        if "beginner" in m or "explain like" in m:
            return (
                "Beginner view: A mutual fund pools many investors' money and buys a basket of stocks/bonds. "
                "NAV is the price of one unit. SIP invests a fixed amount regularly. "
                "Returns are not guaranteed; equity funds can fall. Diversification and time reduce risk of "
                "permanent loss from a single stock, but not market risk."
                + self._ctx_footer(context)
            )

        return (
            "I can explain Alpha/Beta/Sharpe/Sortino/Drawdown/Expense Ratio, help compare funds, "
            "or discuss SIP decisions using CONTEXT metrics.\n\n"
            "Set `OPENAI_API_KEY` in `.env` for full LLM answers (OpenAI-compatible).\n"
            "Meanwhile, ask a specific concept or inject portfolio context from the UI."
            + self._ctx_footer(context)
        )

    @staticmethod
    def _ctx_footer(context: str) -> str:
        if context and "No portfolio" not in context:
            return "\n\n---\n_Context was provided for this answer; prefer those numbers over generalities._"
        return "\n\n---\n_No live portfolio context attached. Open Dashboard/Analyzer first for cited figures._"
