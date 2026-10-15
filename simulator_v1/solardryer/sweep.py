"""
sweep.py - Parameter studies: run the model for many combinations of values.

Example: fans.count = [1, 2, 3] and fans.frame_size_mm = [80, 120]
         -> 3 x 2 = 6 simulations, one row per combination in the results.
"""

import itertools

import pandas as pd

from .config import get_value, set_value
from .simulate import run_simulation


def run_sweep(base_cfg, parameters):
    """
    base_cfg   : configuration dictionary (from load_config)
    parameters : dict {"dotted.path": [value1, value2, ...], ...}
    Returns a DataFrame with the parameter values and all summary numbers.
    """
    names = list(parameters.keys())
    for n in names:
        get_value(base_cfg, n)  # raises a clear error if the name is misspelled
    combos = list(itertools.product(*[parameters[n] for n in names]))
    rows = []
    for i, values in enumerate(combos, 1):
        cfg = base_cfg
        for n, v in zip(names, values):
            cfg = set_value(cfg, n, v)
        label = ", ".join(f"{n}={v}" for n, v in zip(names, values))
        print(f"[{i}/{len(combos)}] {label}")
        try:
            _, summary, _ = run_simulation(cfg)
        except (ValueError, RuntimeError) as err:  # e.g. trays do not fit
            print(f"    skipped: {err}")
            continue
        rows.append({**dict(zip(names, values)), **summary})
    return pd.DataFrame(rows)
