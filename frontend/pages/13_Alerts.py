"""Module 13 — Real Alerts (Slice B)."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

# Streamlit multipage pages may not inherit path setup — ensure project root
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from frontend.state import (
    get_active_portfolio_id,
    get_current_user,
    init_portfolio_holdings,
    is_logged_in,
)
from frontend.theme import apply_theme

apply_theme()

st.title("Alerts")
st.caption(
    "Real NAV · drawdown · P&L · concentration · overlap rules — "
    "evaluate session portfolio or vault · Celery beat ready"
)

# ---------------------------------------------------------------------------
# Load service (never crash the whole page)
# ---------------------------------------------------------------------------
try:
    # Import ORM from services path only (not models.alert)
    from services.alerts.db_models import ALERT_ORM_VERSION, Alert, AlertRule
    from services.alerts.alert_service import AlertService
    from services.alerts.rules import RULE_HELP, known_alert_types

    assert Alert is not None and AlertRule is not None
except Exception as exc:
    st.error("Failed to import Alerts backend.")
    st.code(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")
    st.stop()

st.caption(f"ORM build: `{ALERT_ORM_VERSION}` · source `services.alerts.db_models`")

try:
    svc = AlertService()
except Exception as exc:
    st.error("Failed to create AlertService.")
    st.code(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")
    st.stop()

user = get_current_user() if is_logged_in() else None
uid = user["id"] if user else None

# Do NOT auto-seed on page load (that path previously crashed Cloud).
# User can seed from the rules expander button.

# ---------------------------------------------------------------------------
# Summary strip
# ---------------------------------------------------------------------------
try:
    counts = svc.count_unread(uid)
except Exception as exc:
    counts = {"total": 0, "critical": 0, "warning": 0, "info": 0}
    st.warning(f"Could not load unread counts: {type(exc).__name__}: {exc}")
    # An UndefinedColumn here means the auto-repair could not add the Slice B
    # columns. Show why — the report names the DB, role, schema, and the real
    # error from each failed ALTER.
    st.error("Alert table schema repair did not complete. Details below.")
    st.json(getattr(AlertService, "schema_report", {}) or {"report": "not populated"})

c1, c2, c3, c4 = st.columns(4)
c1.metric("Unread", counts.get("total", 0))
c2.metric("Critical", counts.get("critical", 0))
c3.metric("Warning", counts.get("warning", 0))
c4.metric("Info", counts.get("info", 0))

# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------
st.subheader("Run evaluation")
holdings = init_portfolio_holdings()
n_hold = len(holdings)
active_pid = get_active_portfolio_id()

ecol1, ecol2, ecol3 = st.columns(3)
with ecol1:
    include_overlap = st.checkbox(
        "Include holdings overlap check",
        value=False,
        help="Slower — fetches stock holdings for top funds",
    )
with ecol2:
    max_funds = st.slider("Max funds to check", 5, 40, 20)
with ecol3:
    dry_run = st.checkbox("Dry run (don't save)", value=False)

b1, b2, b3, b4 = st.columns(4)
with b1:
    run_session = st.button("Evaluate session portfolio", type="primary", use_container_width=True)
with b2:
    run_vault = st.button(
        "Evaluate vault portfolios",
        use_container_width=True,
        disabled=not uid,
        help="Requires sign-in",
    )
with b3:
    mark_all = st.button("Mark all read", use_container_width=True)
with b4:
    refresh = st.button("AMFI refresh task", use_container_width=True)

if run_session:
    if not holdings:
        st.warning("No holdings in session.")
    else:
        try:
            with st.spinner(f"Evaluating {min(n_hold, max_funds)} funds…"):
                if dry_run:
                    out = svc.evaluate_portfolio(
                        holdings,
                        user_id=uid,
                        portfolio_id=active_pid,
                        max_funds=max_funds,
                        include_overlap=include_overlap,
                        persist=False,
                    )
                else:
                    from workers.tasks import evaluate_alerts

                    out = evaluate_alerts(
                        holdings=holdings,
                        user_id=uid,
                        portfolio_id=active_pid,
                        include_overlap=include_overlap,
                        max_funds=max_funds,
                    )
            st.success(
                f"Checked {out.get('checked_funds', 0)} funds · "
                f"{out.get('alerts_created', out.get('candidates', 0))} alert(s)"
                + (" (dry run)" if dry_run else "")
            )
            if out.get("errors"):
                with st.expander("Evaluation notes"):
                    for e in out["errors"]:
                        st.caption(e)
            if dry_run and out.get("alerts"):
                st.dataframe(out["alerts"], use_container_width=True)
            elif not dry_run:
                st.rerun()
        except Exception as exc:
            st.error("Evaluation failed")
            st.code(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")

if run_vault and uid:
    try:
        with st.spinner("Evaluating vault portfolios…"):
            from workers.tasks import evaluate_alerts

            out = evaluate_alerts(
                user_id=uid,
                include_overlap=include_overlap,
                max_funds=max_funds,
            )
        st.success(f"Vault scan created {out.get('alerts_created', 0)} alert(s)")
        if out.get("portfolios"):
            st.dataframe(out["portfolios"], use_container_width=True)
        st.rerun()
    except Exception as exc:
        st.error("Vault evaluation failed")
        st.code(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")

if mark_all:
    try:
        n = svc.mark_all_read(uid)
        st.success(f"Marked {n} alert(s) read")
        st.rerun()
    except Exception as exc:
        st.error(f"Mark read failed: {type(exc).__name__}: {exc}")

if refresh:
    try:
        from workers.tasks import refresh_amfi

        out = refresh_amfi.delay(True) if hasattr(refresh_amfi, "delay") else refresh_amfi(True)
        st.write(out)
    except Exception as exc:
        st.error(f"AMFI refresh failed: {type(exc).__name__}: {exc}")

st.caption(
    f"Session holdings: **{n_hold}**"
    + (f" · active vault portfolio id **{active_pid}**" if active_pid else "")
    + (f" · signed in as **{user.get('email')}**" if user else " · not signed in (alerts are global)")
)

# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
with st.expander("Alert rules", expanded=False):
    st.markdown(
        "Rules define **when** an alert fires. Defaults cover NAV drop, multi-day return, "
        "drawdown, unrealized loss, concentration, and overlap."
    )
    if uid and st.button("Reset / seed default rules for my account"):
        try:
            n = svc.seed_default_rules(uid)
            st.success(f"Seeded {n} rules (0 if you already had some)")
            st.rerun()
        except Exception as exc:
            st.error("Seed failed")
            st.code(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")

    try:
        rules = svc.list_rules(uid)
    except Exception as exc:
        rules = []
        st.code(f"list_rules failed: {type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")

    if rules:
        for r in rules:
            rid = r.get("id")
            cols = st.columns([3, 1, 1, 1, 1])
            cols[0].markdown(
                f"**{r.get('name')}**  \n"
                f"`{r.get('alert_type')}` · scope `{r.get('scope')}` · "
                f"threshold **{r.get('threshold')}** · lookback **{r.get('lookback_days')}d**"
            )
            cols[1].write(r.get("severity", ""))
            enabled = bool(r.get("enabled", True))
            cols[2].write("On" if enabled else "Off")
            if rid is not None:
                if cols[3].button("Toggle", key=f"tog_{rid}"):
                    svc.set_rule_enabled(rid, not enabled, user_id=uid)
                    st.rerun()
                if cols[4].button("Del", key=f"del_{rid}"):
                    svc.delete_rule(rid, user_id=uid)
                    st.rerun()
            else:
                cols[3].caption("virtual")
                cols[4].caption("—")
            help_txt = r.get("help") or RULE_HELP.get(r.get("alert_type") or "", "")
            if help_txt:
                st.caption(help_txt)
            st.markdown("---")

    if uid:
        st.markdown("**Add / update rule**")
        with st.form("rule_form"):
            name = st.text_input("Name", "Custom rule")
            atype = st.selectbox("Type", known_alert_types())
            thr = st.number_input(
                "Threshold (e.g. -0.03 = -3%, 0.40 = 40%)",
                value=-0.03,
                step=0.01,
                format="%.4f",
            )
            lb = st.number_input("Lookback days", min_value=0, max_value=730, value=5)
            sev = st.selectbox("Severity", ["info", "warning", "critical"], index=1)
            scope = st.selectbox("Scope", ["fund", "portfolio"])
            enabled = st.checkbox("Enabled", True)
            if st.form_submit_button("Save rule"):
                try:
                    svc.upsert_rule(
                        user_id=uid,
                        name=name,
                        alert_type=atype,
                        threshold=float(thr),
                        lookback_days=int(lb),
                        severity=sev,
                        scope=scope,
                        enabled=enabled,
                    )
                    st.success("Rule saved")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
    else:
        st.info("Sign in to persist and edit personal rules. Defaults still apply when you evaluate.")

# ---------------------------------------------------------------------------
# Alert feed
# ---------------------------------------------------------------------------
st.subheader("Alert feed")
f1, f2, f3 = st.columns(3)
with f1:
    unread_only = st.checkbox("Unread only", False)
with f2:
    type_filter = st.selectbox("Type", ["All"] + known_alert_types())
with f3:
    sev_filter = st.selectbox("Severity", ["All", "critical", "warning", "info"])

try:
    alerts = svc.list_alerts(
        unread_only=unread_only,
        limit=100,
        user_id=uid,
        alert_type=None if type_filter == "All" else type_filter,
        severity=None if sev_filter == "All" else sev_filter,
    )
except Exception as exc:
    alerts = []
    st.error("Could not load alerts")
    st.code(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")

if not alerts:
    st.info(
        "No alerts yet. Load a portfolio (or CAS), then click **Evaluate session portfolio**."
    )
else:
    for a in alerts:
        color = {"critical": "🔴", "warning": "🟠", "info": "🔵"}.get(a["severity"], "⚪")
        read_tag = "" if a.get("is_read") else " · **NEW**"
        metric = a.get("metric_value")
        thr = a.get("threshold")
        metric_txt = ""
        if metric is not None:
            try:
                metric_txt = f" · metric `{float(metric):.2%}`"
            except Exception:
                metric_txt = f" · metric `{metric}`"
        if thr is not None:
            try:
                metric_txt += f" vs thr `{float(thr):.2%}`"
            except Exception:
                pass

        with st.container():
            st.markdown(
                f"{color} **{a['title']}**{read_tag}  \n"
                f"`{a['alert_type']}` · {a.get('created_at', '')}{metric_txt}"
            )
            st.write(a["message"])
            if a.get("amfi_code"):
                st.caption(f"AMFI `{a['amfi_code']}` · {a.get('scheme_name') or ''}")
            bc1, bc2 = st.columns([1, 5])
            with bc1:
                if not a.get("is_read") and st.button("Mark read", key=f"read_{a['id']}"):
                    svc.mark_read(a["id"], user_id=uid)
                    st.rerun()
            with bc2:
                if st.button("Dismiss", key=f"del_a_{a['id']}"):
                    svc.delete_alert(a["id"], user_id=uid)
                    st.rerun()
            st.markdown("---")

# ---------------------------------------------------------------------------
# Ops
# ---------------------------------------------------------------------------
with st.expander("Scheduled / Celery ops"):
    st.markdown(
        """
When `CELERY_ENABLED=true` and Redis is running:

```bash
celery -A workers.celery_app.celery_app worker -l info
celery -A workers.celery_app.celery_app beat -l info
```

Beat schedule: hourly vault alert scan + daily AMFI refresh.
        """
    )
    st.markdown("**Alert table schema**")
    if st.button("Run schema repair now"):
        svc.ensure_db()
        st.rerun()
    st.json(getattr(AlertService, "schema_report", {}) or {"report": "not populated yet"})

    if st.button("Run full vault scan now (all users)"):
        try:
            with st.spinner("Scanning…"):
                from workers.tasks import evaluate_all_vault_alerts

                out = evaluate_all_vault_alerts(max_users=20, max_funds=10)
            st.json(out)
        except Exception as exc:
            st.code(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")
