from memorygate.model2_stats import compare


def test_compare_counts_and_interval():
    a = {"q1": True, "q2": True, "q3": False, "q4": True}
    b = {"q1": False, "q2": True, "q3": True, "q4": False, "q5": True}
    c = compare(a, b)
    assert c["n"] == 4
    assert (c["fixed"], c["broken"]) == (2, 1)
    assert abs(c["diff"] - 0.25) < 1e-12
    assert c["lo"] < c["diff"] < c["hi"]
