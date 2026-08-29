# Change this to change color theme. Options: "default" | "enduserrr"
# Can also be set from bagbot_settings.py (THEME / THEME_SETTINGS), which takes priority.
THEME = "default"

# New themes by adding a new theme block with your colors and name,
# and placing its name as THEME above.

_THEMES = {
    "default": {
        "header_style":   "bold white on dark_blue",
        "id":             "bright_cyan",
        "sn":             "white",
        "alpha":          "magenta",
        "max_alpha":      "magenta",
        "fill_pct":       "magenta",
        "tao_val":        "yellow",
        "buy_min":        "grey66",
        "curr_buy":       "bright_green",
        "buy_max":        "grey66",
        "price":          "bright_cyan",
        "sell_min":       "grey66",
        "curr_sell":      "bright_red",
        "sell_max":       "grey66",
        "price_prox":     "white",
    },
    "enduserrr": {
        "header_style":   "bold white on dark_blue",
        "id":             "bright_cyan",
        "sn":             "white",
        "alpha":          "rgb(255,0,255)",
        "max_alpha":      "dim magenta",
        "fill_pct":       "dim magenta",
        "tao_val":        "yellow",
        "buy_min":        "dim light_green",
        "curr_buy":       "bright_green",
        "buy_max":        "dim green",
        "price":          "bold bright_cyan",
        "sell_min":       "dim bright_yellow",
        "curr_sell":      "bright_red",
        "sell_max":       "dim bright_red",
        "price_prox":     "white",
    },
}

def get_theme() -> dict:
    """Returns the active theme dict based on the THEME variable above."""
    # bagbot_settings.py (or its overrides file) may carry a commented-out THEME /
    # THEME_SETTINGS pair. When uncommented they overwrite the defaults here.
    settings_theme = _settings_theme_override()
    if settings_theme is not None:
        return settings_theme

    if THEME not in _THEMES:
        raise ValueError(f"Unknown theme '{THEME}'. Available themes: {list(_THEMES.keys())}")
    return _THEMES[THEME]


def _settings_theme_override() -> dict | None:
    """Returns a custom theme dict from bagbot_settings, or None if unset/incomplete."""
    try:
        from settings_loader import bagbot_settings
    except Exception:
        return None

    overrides = getattr(bagbot_settings, 'THEME_SETTINGS', None)
    if not isinstance(overrides, dict):
        return None

    theme_name = getattr(bagbot_settings, 'THEME', THEME)
    if theme_name in _THEMES:
        merged = dict(_THEMES[theme_name])
    else:
        merged = {}
    merged.update(overrides)
    return merged

