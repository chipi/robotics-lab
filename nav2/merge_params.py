"""Merge params_overrides.yaml onto nav2_bringup's nav2_params.yaml (RFC-0015 §3.4): dicts merge key by key, anything else
(lists, numbers) is replaced, and the default's base_footprint becomes base_link (the bridge's trunk frame on the floor).
    python3 merge_params.py /opt/ros/jazzy/share/nav2_bringup/params/nav2_params.yaml params_overrides.yaml > nav2_duck.yaml
"""

import sys

import yaml


def merge(base, over):
    if isinstance(over, dict) and "plugin" in over:      # a plugin replaces the default one, with none of its parameters
        return over
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = merge(base[k], v) if k in base else v
        return out
    return over


def rename(x):
    if isinstance(x, dict):
        return {k: rename(v) for k, v in x.items()}
    if isinstance(x, list):
        return [rename(v) for v in x]
    return "base_link" if x == "base_footprint" else x


with open(sys.argv[1]) as f, open(sys.argv[2]) as g:
    print(yaml.safe_dump(rename(merge(yaml.safe_load(f), yaml.safe_load(g))), sort_keys=False))
