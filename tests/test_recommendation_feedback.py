from api.main import (
    RecommendationReviewInput,
    UserFeedbackInput,
    final_review_from_payload,
)


def test_user_corrected_result_overrides_original_review_result():
    item = RecommendationReviewInput(
        item_no="1",
        review_result="미준수",
        normalized_result="미준수",
        is_target=True,
        reason="원 판단",
        recommendation="보완 문구를 추가하시기 바랍니다.",
        user_feedback=UserFeedbackInput(corrected_result="해당없음", resolved=True),
    )

    review = final_review_from_payload(item)

    assert review.final_result == "해당없음"
    assert review.reviews[0].result == "해당없음"
