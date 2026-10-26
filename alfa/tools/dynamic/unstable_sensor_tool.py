"""Auto-synthesized Apex Tool: Test canary rollback on negative input"""

def unstable_sensor_tool(x: int) -> int:
    if x < 0:
        raise RuntimeError('Sensor calibration underflow')
    return x * 2
