from typing import Any

from config.config import Config


def dict_has_tiers(dictionary: dict[str, Any], require_all_keys: bool = False) -> bool:
    """
    Determines whether or not a dictionary contains tier keys
    """
    if require_all_keys:
        return set(Config.tiers) == set(dictionary.keys())
    else:
        return len(set(Config.tiers) & set(dictionary.keys())) == len(dictionary.keys())
