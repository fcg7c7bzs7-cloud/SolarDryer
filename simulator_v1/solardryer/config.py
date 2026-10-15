"""
config.py - Reading the YAML configuration file.

The whole model is controlled by one YAML file (see config/default_dryer.yaml).
This module only loads that file into a Python dictionary and offers two small
helpers to read/change values using a "dotted path", e.g. "fans.count".
"""

import copy
import os

import yaml


def load_config(path):
    """Read a YAML file and return its content as a (nested) dictionary."""
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Remember where the file was, so relative paths (e.g. the weather CSV)
    # can be resolved later.
    cfg["_config_dir"] = os.path.dirname(os.path.abspath(path))
    return cfg


def get_value(cfg, dotted_path):
    """Return the value at e.g. "fans.count" -> cfg["fans"]["count"]."""
    node = cfg
    for key in dotted_path.split("."):
        node = node[key]
    return node


def set_value(cfg, dotted_path, value):
    """
    Return a COPY of cfg where the value at dotted_path is replaced.
    The original dictionary is not changed (important for parameter sweeps).
    """
    new_cfg = copy.deepcopy(cfg)
    keys = dotted_path.split(".")
    node = new_cfg
    for key in keys[:-1]:
        if key not in node:
            raise KeyError(f"Unknown parameter section '{key}' in '{dotted_path}'")
        node = node[key]
    if keys[-1] not in node:
        raise KeyError(f"Unknown parameter '{dotted_path}'. Check the spelling in the YAML file.")
    node[keys[-1]] = value
    return new_cfg
