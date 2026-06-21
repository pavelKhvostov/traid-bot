"""
Phase 1 модель: эмпирический lookup-table.

Идея (подход A — прозрачный baseline):
  - бакетируем зону по дискретным фичам (tf, type, side, distance_bucket, age_bucket)
  - на трейне для каждого бакета считаем mean(hit_12h), mean(hit_D), count
  - на инференсе возвращаем эти средние, с Laplace-smoothing α/N для редких бакетов
  - fallback caskade: если бакет редкий (count < min_count) — coarsen
      coarsest → (tf, type, side, distance_bucket)
      coarser → (type, side, distance_bucket)
      coarsest fallback → (side, distance_bucket)
      global → mean overall

Дизайн нацелен на интерпретируемость: всю lookup-таблицу можно напечатать
и увидеть «P(hit | feature combination)».
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DISTANCE_BUCKETS: tuple[float, ...] = (0.0, 0.1, 0.3, 1.0, 3.0, 10.0, 100.0)
DISTANCE_LABELS: tuple[str, ...] = ("0-0.1", "0.1-0.3", "0.3-1", "1-3", "3-10", "10+")

AGE_BUCKETS: tuple[int, ...] = (0, 1, 6, 20, 100, 10_000)
AGE_LABELS: tuple[str, ...] = ("0", "1-5", "6-19", "20-99", "100+")


def distance_bucket(d: float) -> str:
    for i in range(len(DISTANCE_BUCKETS) - 1):
        if d < DISTANCE_BUCKETS[i + 1]:
            return DISTANCE_LABELS[i]
    return DISTANCE_LABELS[-1]


def age_bucket(a: int) -> str:
    for i in range(len(AGE_BUCKETS) - 1):
        if a < AGE_BUCKETS[i + 1]:
            return AGE_LABELS[i]
    return AGE_LABELS[-1]


def add_buckets(df: pd.DataFrame) -> pd.DataFrame:
    """Добавляет колонки dist_bucket / age_bucket в DataFrame."""
    out = df.copy()
    out["dist_bucket"] = out["distance_pct"].apply(distance_bucket)
    out["age_bucket"] = out["age_bars"].apply(age_bucket)
    return out


KEY_FULL = ("tf", "type", "side", "dist_bucket", "age_bucket")
KEY_NO_AGE = ("tf", "type", "side", "dist_bucket")
KEY_TYPE_SIDE = ("type", "side", "dist_bucket")
KEY_SIDE = ("side", "dist_bucket")


@dataclass
class LookupModel:
    """Иерархический lookup-model. Хранит несколько уровней группировки + global rates."""
    table_full: pd.DataFrame             # by KEY_FULL
    table_no_age: pd.DataFrame           # by KEY_NO_AGE
    table_type_side: pd.DataFrame        # by KEY_TYPE_SIDE
    table_side: pd.DataFrame             # by KEY_SIDE
    global_rates: dict                   # {'hit_12h': p, 'hit_D': p}
    min_count: int                       # минимум обc. в бакете чтобы доверять
    alpha: float                         # Laplace smoothing constant

    @classmethod
    def fit(cls, train_df: pd.DataFrame, min_count: int = 20, alpha: float = 1.0) -> "LookupModel":
        df = add_buckets(train_df)
        # Добавляем first_hit_above/below как опц. колонки (могут отсутствовать в старых датасетах)
        has_first = "first_hit_above" in df.columns and "first_hit_below" in df.columns
        if has_first:
            df["first_hit_above"] = df["first_hit_above"].astype(bool)
            df["first_hit_below"] = df["first_hit_below"].astype(bool)
        global_rates = {
            "hit_12h": float(df["hit_12h"].mean()),
            "hit_D": float(df["hit_D"].mean()),
        }
        if has_first:
            # Conditional global: среди above-зон какая доля first_hit_above; то же для below
            above = df[df["side"] == "above"]
            below = df[df["side"] == "below"]
            global_rates["first_hit_above"] = float(above["first_hit_above"].mean()) if len(above) else 0.0
            global_rates["first_hit_below"] = float(below["first_hit_below"].mean()) if len(below) else 0.0

        def _make_table(keys: tuple[str, ...]) -> pd.DataFrame:
            agg = {
                "n": ("hit_D", "size"),
                "hit_12h": ("hit_12h", "mean"),
                "hit_D": ("hit_D", "mean"),
            }
            if has_first:
                agg["first_hit_above"] = ("first_hit_above", "mean")
                agg["first_hit_below"] = ("first_hit_below", "mean")
            t = df.groupby(list(keys)).agg(**agg).reset_index()
            return t

        return cls(
            table_full=_make_table(KEY_FULL),
            table_no_age=_make_table(KEY_NO_AGE),
            table_type_side=_make_table(KEY_TYPE_SIDE),
            table_side=_make_table(KEY_SIDE),
            global_rates=global_rates,
            min_count=min_count,
            alpha=alpha,
        )

    def _smooth(self, hit_rate: float, n: int, prior: float) -> float:
        """Laplace smoothing: shrink toward prior at rate alpha/(n+alpha)."""
        return (hit_rate * n + prior * self.alpha) / (n + self.alpha)

    def _lookup_in_table(self, table: pd.DataFrame, keys: tuple[str, ...], row: pd.Series) -> dict | None:
        mask = pd.Series([True] * len(table))
        for k in keys:
            mask &= (table[k] == row[k])
        match = table[mask]
        if match.empty:
            return None
        r = match.iloc[0]
        if r["n"] < self.min_count:
            return None
        out = {"n": int(r["n"]), "hit_12h": float(r["hit_12h"]), "hit_D": float(r["hit_D"])}
        if "first_hit_above" in table.columns:
            out["first_hit_above"] = float(r["first_hit_above"])
            out["first_hit_below"] = float(r["first_hit_below"])
        return out

    def predict_row(self, row: pd.Series) -> dict:
        """
        row: pd.Series с колонками tf, type, side, dist_bucket, age_bucket.
        Returns: {'P_hit_12h', 'P_hit_D', 'P_first_hit_above', 'P_first_hit_below',
                  'bucket_used', 'n_train'}
        """
        has_first = "first_hit_above" in self.global_rates
        for keys, table, label in [
            (KEY_FULL, self.table_full, "full"),
            (KEY_NO_AGE, self.table_no_age, "no_age"),
            (KEY_TYPE_SIDE, self.table_type_side, "type_side"),
            (KEY_SIDE, self.table_side, "side"),
        ]:
            res = self._lookup_in_table(table, keys, row)
            if res is None:
                continue
            out = {
                "P_hit_12h": self._smooth(res["hit_12h"], res["n"], self.global_rates["hit_12h"]),
                "P_hit_D": self._smooth(res["hit_D"], res["n"], self.global_rates["hit_D"]),
                "bucket_used": label,
                "n_train": res["n"],
            }
            if has_first and "first_hit_above" in res:
                out["P_first_hit_above"] = self._smooth(
                    res["first_hit_above"], res["n"], self.global_rates["first_hit_above"]
                )
                out["P_first_hit_below"] = self._smooth(
                    res["first_hit_below"], res["n"], self.global_rates["first_hit_below"]
                )
            return out
        # Global fallback
        out = {
            "P_hit_12h": self.global_rates["hit_12h"],
            "P_hit_D": self.global_rates["hit_D"],
            "bucket_used": "global",
            "n_train": 0,
        }
        if has_first:
            out["P_first_hit_above"] = self.global_rates["first_hit_above"]
            out["P_first_hit_below"] = self.global_rates["first_hit_below"]
        return out

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Бакетирует df и применяет predict_row построчно."""
        df = add_buckets(df)
        preds = df.apply(self.predict_row, axis=1)
        return pd.DataFrame(list(preds), index=df.index)
