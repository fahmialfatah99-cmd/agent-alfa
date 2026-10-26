"""Auto-synthesized Apex Tool: Calculate pole reserve buffer for FTTH cluster"""

def calc_pole_reserve(net_poles: int, buffer_pct: float = 0.1) -> dict:
    reserve = int(round(net_poles * buffer_pct))
    return {'net': net_poles, 'reserve': reserve, 'total_with_buffer': net_poles + reserve}
