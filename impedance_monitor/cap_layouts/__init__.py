from .ca209 import CA209_LAYOUT, CapLayout, Electrode
from .ca001 import CA001_LAYOUT
from .ca200 import CA200_LAYOUT

LAYOUTS: dict[str, CapLayout] = {
    "ca209": CA209_LAYOUT,
    "ca001": CA001_LAYOUT,
    "ca200": CA200_LAYOUT,
}


def get_layout(name: str) -> CapLayout:
    """Return CapLayout by name. Raises ValueError for unknown names."""
    try:
        return LAYOUTS[name]
    except KeyError:
        raise ValueError(
            f"Unknown cap layout '{name}'. Valid options: {', '.join(LAYOUTS)}"
        )


__all__ = ["CapLayout", "Electrode", "get_layout", "LAYOUTS",
           "CA209_LAYOUT", "CA001_LAYOUT", "CA200_LAYOUT"]
