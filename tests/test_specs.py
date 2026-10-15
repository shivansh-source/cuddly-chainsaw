from app.specs import check_specs


def test_passes_when_all_met():
    actual = {"flash_mb": 8, "interface": "I2C"}
    req = {"flash_mb": {"op": ">=", "value": 8}, "interface": {"op": "==", "value": "I2C"}}
    assert check_specs(actual, req) == []


def test_reports_each_failure_with_reason():
    actual = {"flash_mb": 4, "package": "SOT-223"}
    req = {"flash_mb": {"op": ">=", "value": 8}, "package": {"op": "in", "value": ["LQFP48"]}}
    reasons = check_specs(actual, req)
    assert len(reasons) == 2
    assert "offered 4" in reasons[0]


def test_missing_spec_never_passes():
    assert check_specs({}, {"iout_ma": {"op": ">=", "value": 1000}})


def test_unknown_operator_fails_closed():
    assert check_specs({"x": 1}, {"x": {"op": "~=", "value": 1}})
