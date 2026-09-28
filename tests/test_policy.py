from samepage.core.policy import JUDGE, ORGANIZER, VISITOR, allows


def test_judge_cannot_read_another_judges_rows():
    assert allows({JUDGE}, "scores.read_named", target_is_self=False) is False
    assert allows({JUDGE}, "scores.read_named", target_is_self=True) is True


def test_staff_can_read_named_scores_and_visitors_cannot():
    assert allows({ORGANIZER}, "scores.read_named") is True
    assert allows({VISITOR}, "scores.read_own") is False


def test_unpublished_results_are_staff_only_until_publish():
    assert allows({VISITOR}, "results.read", published=False) is False
    assert allows({VISITOR}, "results.read", published=True) is True


def test_gallery_does_not_require_a_role():
    assert allows(set(), "gallery.read") is True
