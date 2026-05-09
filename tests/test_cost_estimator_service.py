from application.services.cost_estimator_service import CostEstimatorService


def test_estimate_tokens_scales_with_length():
    svc = CostEstimatorService()
    est_small = svc.estimate(input_text="abcd" * 10, expected_output_tokens=100)
    est_big = svc.estimate(input_text="abcd" * 100, expected_output_tokens=100)
    assert est_big.input_tokens > est_small.input_tokens
    assert est_small.output_tokens == 100
    assert est_big.output_tokens == 100

