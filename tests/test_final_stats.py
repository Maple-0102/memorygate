from memorygate.final_stats import holm


def test_holm_matches_hand_computation():
    # sorted p: .01*3=.03, .02*2=.04, .5*1=.5 ; monotone
    assert [round(x, 6) for x in holm([0.5, 0.01, 0.02])] == [0.5, 0.03, 0.04]
    assert holm([0.04, 0.03]) == [0.06, 0.06]
