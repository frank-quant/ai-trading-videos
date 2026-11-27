"""Percentile transform + LightGBM combination (paper hyperparameters)."""
from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd

from .data import MarketData


def percentile_transform(values: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    v = values.where(eligible)
    return v.rank(axis=1, pct=True)


def build_dataset(pool_ids: list[str], values: dict[str, pd.DataFrame], md: MarketData):
    pcts = {cid: percentile_transform(values[cid], md.eligible) for cid in pool_ids}
    long = pd.DataFrame({cid: pcts[cid].stack() for cid in pool_ids})
    elig = md.eligible.stack()
    elig_pairs = elig[elig].index
    long = long.reindex(elig_pairs)
    long = long.dropna()
    long.index.names = ["date", "code"]
    return long


def fit_combine(stack: pd.DataFrame, md: MarketData):
    p = md.cfg["combine"]["params"]
    lab = md.labels["train"].stack()
    lab_v = md.labels["validation"].stack()
    train = stack.loc[stack.index.get_level_values("date").isin(md.seg_days["train"])].copy()
    val = stack.loc[stack.index.get_level_values("date").isin(md.seg_days["validation"])].copy()
    train["y"] = lab.reindex(train.index)
    val["y"] = lab_v.reindex(val.index)
    train = train.dropna(subset=["y"])
    val = val.dropna(subset=["y"])
    print(f"combine rows: train={len(train)} val={len(val)}", flush=True)
    feats = list(stack.columns)
    params = {
        "objective": p["objective"], "num_leaves": p["num_leaves"],
        "max_depth": p["max_depth"], "learning_rate": p["learning_rate"],
        "lambda_l1": p["reg_alpha"], "lambda_l2": p["reg_lambda"],
        "verbosity": -1,
    }
    dtrain = lgb.Dataset(train[feats], label=train["y"])
    dval = lgb.Dataset(val[feats], label=val["y"], reference=dtrain)
    booster = lgb.train(
        params, dtrain, num_boost_round=p["n_estimators"], valid_sets=[dval],
        callbacks=[lgb.early_stopping(p["early_stopping_rounds"]),
                   lgb.log_evaluation(p["log_evaluation"])],
    )
    scores = pd.Series(booster.predict(stack[feats], num_iteration=booster.best_iteration),
                       index=stack.index, name="score")
    info = {
        "best_iteration": int(booster.best_iteration or p["n_estimators"]),
        "train_rows": int(len(train)), "val_rows": int(len(val)),
        "feature_importance": dict(zip(feats, booster.feature_importance().tolist())),
    }
    wide = scores.unstack("code").reindex(index=md.calendar)
    return booster, wide, info