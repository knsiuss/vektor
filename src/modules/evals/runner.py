from dataclasses import dataclass


@dataclass(frozen=True)
class EvalCaseResult:
    case_id: str
    question: str
    passed: bool
    missing_facts: list[str]
    triggered_forbidden: list[str]
    reply: str


@dataclass(frozen=True)
class EvalSuiteSummary:
    total: int
    passed: int
    pass_rate: float
    results: list[EvalCaseResult]


def evaluate_reply(
    *,
    case_id: str,
    question: str,
    reply: str,
    expected_facts: list[str],
    forbidden_claims: list[str],
) -> EvalCaseResult:
    """Evaluate a single bot reply against required facts and forbidden claims."""
    lowered = reply.lower()
    missing = [fact for fact in expected_facts if fact.lower() not in lowered]
    forbidden = [claim for claim in forbidden_claims if claim.lower() in lowered]
    passed = not missing and not forbidden
    return EvalCaseResult(
        case_id=case_id,
        question=question,
        passed=passed,
        missing_facts=missing,
        triggered_forbidden=forbidden,
        reply=reply,
    )


def summarize_eval_results(results: list[EvalCaseResult]) -> EvalSuiteSummary:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    rate = round(passed / total, 4) if total > 0 else 1.0
    return EvalSuiteSummary(total=total, passed=passed, pass_rate=rate, results=results)
