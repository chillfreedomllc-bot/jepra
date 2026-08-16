"""アプローチ文面の生成。"""

from .templates import (
    Profile, TEMPLATES, load_profile, pick_variant, render, template_names,
)

__all__ = [
    "Profile", "TEMPLATES", "load_profile", "pick_variant", "render", "template_names",
]
