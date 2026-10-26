"""Auto-synthesized Apex Tool: Estimate cable drums needed for route km"""

def km_to_drum_estimator(km: float) -> int:
    return int((km * 1000) // 4000) + 1
