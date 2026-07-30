"""Module 8 — Machine Learning Engine."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from frontend.components.provenance import provenance_for_codes, render_provenance
from frontend.state import get_fund_service
from frontend.components.page import page_header
from frontend.theme import apply_theme
from ml.feature_engineering import FeatureEngineer
from ml.model_trainer import ModelTrainer
from utils.helpers import pct

apply_theme()

page_header(
    "Machine Learning Engine",
    "Feature engineering · RF / GBM / XGB / LGBM / CatBoost / Stacking · TimeSeriesSplit · auto best model",
    "🤖",
)

svc = get_fund_service()
q = st.text_input("Fund search", "flexi cap")
df = svc.search_funds(q, limit=15)
if df.empty:
    st.warning("No funds found.")
    st.stop()

name = st.selectbox("Train on fund", df["scheme_name"].tolist())
code = str(df.loc[df["scheme_name"] == name, "amfi_code"].iloc[0])
target = st.selectbox("Target", ["fwd_ret_63", "fwd_ret_21"])

if st.button("Train & compare models", type="primary"):
    with st.spinner("Engineering features and training…"):
        nav = svc.get_nav_history(code, name)
        bench = svc.yf.get_benchmark("NIFTY 50")
        meta = svc.compute_fund_analytics(code)
        fe = FeatureEngineer()
        feat = fe.from_nav(
            nav,
            bench,
            expense_ratio=meta.get("expense_ratio"),
            aum_cr=meta.get("aum_cr"),
            manager_tenure=meta.get("manager_tenure"),
        )
        X, y = fe.make_supervised(feat, target_col=target)
        result = ModelTrainer().compare(X, y, target_name=target)
        st.session_state["ml_result"] = result
        st.session_state["ml_feat_shape"] = X.shape
        st.session_state["ml_provenance"] = provenance_for_codes(
            svc, entries=[(name, code)], include_holdings=False
        ).to_dict()

_ml_prov = st.session_state.get("ml_provenance")
if _ml_prov:
    render_provenance(_ml_prov, what="This model's training data")

result = st.session_state.get("ml_result")
if not result:
    st.info("Select a fund and train models.")
    st.stop()

st.success(f"Best model: **{result.best_model_name}** · CV RMSE={result.best_cv_rmse:.6f}")
st.caption(result.notes)
st.write(f"Feature matrix shape: {st.session_state.get('ml_feat_shape')}")

if result.scores:
    score_df = pd.DataFrame([s.__dict__ for s in result.scores])
    st.dataframe(score_df, use_container_width=True, hide_index=True)
    st.bar_chart(score_df.set_index("name")["cv_rmse_mean"])

cagr = ModelTrainer().predict_expected_cagr(result)
if cagr is not None:
    st.metric("Implied expected CAGR (rough)", pct(cagr))

if result.feature_importance:
    st.subheader("Top feature importances")
    st.bar_chart(result.feature_importance)

if result.predictions_tail:
    st.subheader("Latest forward-return predictions (tail)")
    st.line_chart(result.predictions_tail)
