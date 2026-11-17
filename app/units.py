"""Display helpers for metric / imperial. Everything is stored in metric."""

LB_PER_KG = 2.20462
CM_PER_IN = 2.54


def imperial(profile) -> bool:
    return getattr(profile, "units", "metric") == "imperial"


def mass(kg: float, profile, signed: bool = False) -> str:
    if imperial(profile):
        v, u = kg * LB_PER_KG, "lb"
    else:
        v, u = kg, "kg"
    return f"{v:+.1f} {u}" if signed else f"{v:.1f} {u}"


def length(cm: float, profile) -> str:
    if imperial(profile):
        inches = round(cm / CM_PER_IN)
        return f"{inches // 12}′{inches % 12}″"
    return f"{cm:g} cm"
