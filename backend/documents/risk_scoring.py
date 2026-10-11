"""
Multi-signal risk scoring with an explicit human-review gate.

No single signal decides the outcome. LLM-extracted fields are cross-checked
against an independent rule-based check (Verhoeff checksum), and the YOLO and
classical computer-vision indicators are blended into one weighted risk score.
When signals conflict, or the evidence is weak, the document is flagged for
human review instead of being reported as authentic or fraudulent.
"""
from typing import Dict, List, Optional

from .verhoeff import validate_aadhaar

# Weights sum to 1.0. Rule-based and detector signals outweigh the LLM verdict,
# and the noisy classical-CV signal gets the least weight.
WEIGHTS = {
    'checksum': 0.30,
    'llm': 0.25,
    'yolo': 0.25,
    'design': 0.10,
    'cv': 0.10,
}

LOW_THRESHOLD = 0.3
HIGH_THRESHOLD = 0.6
LOW_CONFIDENCE = 0.6      # below this the LLM output is not trusted on its own
HIGH_SIGNAL = 0.7         # a single signal this strong counts as a firm "fraud" vote
LOW_SIGNAL = 0.3          # a single signal this weak counts as a firm "clean" vote


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _llm_risk(is_authentic: Optional[bool], confidence: Optional[float]) -> Optional[float]:
    """Risk contributed by the LLM verdict, scaled by how confident it was."""
    if is_authentic is None:
        return None
    conf = _clamp(confidence if confidence is not None else 0.5)
    # A confident "authentic" is ~0 risk, a confident "fake" is ~1, and a
    # low-confidence verdict in either direction collapses towards 0.5.
    return 0.5 - 0.5 * conf if is_authentic else 0.5 + 0.5 * conf


def _cv_risk(cv_indicators: List[str]) -> float:
    return _clamp(0.25 * len(cv_indicators))


def compute_risk(
    aadhaar_number: Optional[str],
    llm_is_authentic: Optional[bool],
    llm_confidence: Optional[float],
    yolo_risk: float,
    cv_indicators: List[str],
    design_missing: int = 0,
) -> Dict:
    """
    Fuse independent signals into a calibrated risk score.

    Args:
        aadhaar_number: Number extracted by the LLM (may be None).
        llm_is_authentic: The LLM's own verdict (None if it gave none).
        llm_confidence: The LLM's confidence in that verdict, 0-1.
        yolo_risk: Risk from YOLO fraud-class detections, 0-1.
        cv_indicators: Classical CV findings (compression, noise, ...).
        design_missing: Number of critical Aadhaar design elements the LLM
            reported missing (emblem, govt text, QR, photo).

    Returns:
        risk_score, risk_level, needs_review, review_reasons and the
        per-signal breakdown.
    """
    signals: Dict[str, Optional[float]] = {}

    # Independent rule-based check on the LLM-extracted field.
    if aadhaar_number:
        signals['checksum'] = 0.0 if validate_aadhaar(aadhaar_number) else 1.0
    else:
        signals['checksum'] = None
    signals['llm'] = _llm_risk(llm_is_authentic, llm_confidence)
    signals['yolo'] = _clamp(yolo_risk)
    signals['design'] = _clamp(design_missing / 2.0)
    signals['cv'] = _cv_risk(cv_indicators)

    # Weighted mean over the signals actually available (missing ones are
    # dropped and the remaining weights renormalised, not treated as "clean").
    available = {k: v for k, v in signals.items() if v is not None}
    total_weight = sum(WEIGHTS[k] for k in available)
    score = sum(WEIGHTS[k] * v for k, v in available.items()) / total_weight

    # A failed checksum is a hard rule violation: floor the score so other
    # clean-looking signals cannot average it away.
    if signals['checksum'] == 1.0:
        score = max(score, HIGH_THRESHOLD)
    score = round(_clamp(score), 3)

    if score < LOW_THRESHOLD:
        level = 'low'
    elif score < HIGH_THRESHOLD:
        level = 'medium'
    else:
        level = 'high'

    reasons: List[str] = []
    if llm_is_authentic is True and signals['checksum'] == 1.0:
        reasons.append('LLM judged the document authentic but the Aadhaar checksum failed')
    if llm_is_authentic is True and signals['yolo'] >= HIGH_SIGNAL:
        reasons.append('LLM judged the document authentic but the detector found tampering')
    if llm_is_authentic is False and signals['yolo'] <= LOW_SIGNAL \
            and signals['checksum'] in (0.0, None) and signals['design'] == 0.0:
        reasons.append('LLM flagged the document but no independent check agrees')
    if llm_is_authentic is None:
        reasons.append('LLM gave no authenticity verdict')
    elif llm_confidence is None or llm_confidence < LOW_CONFIDENCE:
        reasons.append('LLM confidence is low')
    if not aadhaar_number:
        reasons.append('No Aadhaar number could be extracted to verify')
    if level == 'medium':
        reasons.append('Risk score is in the inconclusive range')

    return {
        'risk_score': score,
        'risk_level': level,
        'needs_review': bool(reasons),
        'review_reasons': reasons,
        'signals': {k: (None if v is None else round(v, 3)) for k, v in signals.items()},
        'weights': WEIGHTS,
    }
