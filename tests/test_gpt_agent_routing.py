import unittest


class GptAgentRoutingTests(unittest.TestCase):
    def test_python_rule_first_items_route_to_rule_agent(self):
        from agents.review_router import route_item

        self.assertEqual(route_item("1"), "rule")
        self.assertEqual(route_item("3"), "rule")
        self.assertEqual(route_item("4"), "rule")
        self.assertEqual(route_item("6"), "rule")
        self.assertEqual(route_item("7"), "rule")

    def test_rule_agent_uses_python_before_gpt_when_rule_evidence_is_sufficient(self):
        from agents.models import CandidatePage, RagContext, RagHit
        from agents.rule_review_agent import RuleReviewAgent

        class FakeClient:
            def __init__(self):
                self.roles = []

            def is_configured(self):
                return True

            def json_response(self, system, user, **kwargs):
                self.roles.append(kwargs.get("model_role"))
                return {
                    "result": "미준수",
                    "is_target": True,
                    "confidence": 0.9,
                    "evidence_pages": [99],
                    "evidence_text": ["gpt evidence"],
                    "reason": "gpt was called",
                    "recommendation": "fix",
                    "needs_human_review": False,
                }

        client = FakeClient()
        rag = RagContext(
            item_no="3",
            hits=[
                RagHit(
                    item_no="3",
                    source_type="criteria_db",
                    source_name="criteria",
                    title="alpha beta gamma",
                    category="criteria",
                    snippet="alpha beta gamma delta epsilon",
                )
            ],
        )
        pages = [
            CandidatePage(
                page_no=3,
                page_text="alpha beta gamma delta are present in the document.",
                text_length=52,
            )
        ]

        result = RuleReviewAgent(client).review("3", pages, rag)

        self.assertEqual(client.roles, [])
        self.assertFalse(result.used_llm)
        self.assertEqual(result.source, "python_rule_rag_overlap")

    def test_item_three_rule_keywords_cover_small_sw_business_participation(self):
        from agents.models import CandidatePage, RagContext
        from agents.rule_review_agent import RuleReviewAgent

        pages = [
            CandidatePage(
                page_no=32,
                page_text=(
                    "본 사업은 20억원 미만 사업으로 중소 소프트웨어사업자의 사업 참여 지원에 관한 "
                    "지침에 따라 대기업 및 중견기업은 입찰에 참여할 수 없음. "
                    "상호출자제한 기업집단 소속회사는 사업금액에 관계없이 입찰에 참여할 수 없음."
                ),
                text_length=120,
            ),
            CandidatePage(
                page_no=44,
                page_text="상호출자제한 기업집단 일반 설명만 포함된 관련성 낮은 페이지",
                text_length=40,
            )
        ]

        result = RuleReviewAgent().review("3", pages, RagContext(item_no="3"))

        self.assertEqual(result.result, "준수")
        self.assertEqual(result.evidence_pages, [32])
        self.assertFalse(result.used_llm)

    def test_item_six_uses_only_sw_output_reuse_evidence(self):
        from agents.models import CandidatePage, RagContext
        from agents.rule_review_agent import RuleReviewAgent

        pages = [
            CandidatePage(
                page_no=27,
                page_text="과업심의위원회 개최 및 과업변경 요청서 제출 문구가 명시되어 있다.",
                text_length=40,
            ),
            CandidatePage(
                page_no=29,
                page_text="산출물 관리 및 SW 사업정보 저장소 데이터 작성 및 제출에 관한 사항을 명시한다.",
                text_length=48,
            ),
            CandidatePage(
                page_no=24,
                page_text="요구사항 명칭 지식재산권 등 지식재산권 공동귀속 및 SW 반출 활용\n- 24 -",
                text_length=70,
            ),
            CandidatePage(
                page_no=25,
                page_text=(
                    "계약목적물의 지식재산권은 발주기관과 계약상대자가 공동으로 소유하며, "
                    "공급자는 지식재산권의 활용을 위하여 S/W 산출물의 반출을 요청할 수 있으며 "
                    "누출금지정보를 삭제하고 공급자 대표 명의의 확약서를 제출하여야 한다. "
                    "반출된 S/W 산출물을 제3자에게 제공하려는 경우 발주기관의 사전승인을 받아야 한다. "
                    "무단 유출하거나 누출금지정보를 삭제하지 않고 활용하는 경우 입찰참가자격을 제한한다.\n- 25 -"
                ),
                text_length=230,
            ),
        ]

        result = RuleReviewAgent().review("6", pages, RagContext(item_no="6"))

        self.assertEqual(result.result, "준수")
        self.assertEqual(result.evidence_pages, [25])
        self.assertFalse(result.used_llm)

    def test_item_six_does_not_pass_on_loose_keyword_only_page(self):
        from agents.models import CandidatePage, RagContext
        from agents.rule_review_agent import RuleReviewAgent

        pages = [
            CandidatePage(
                page_no=61,
                page_text="산출물 반출 관련 일반 안내와 보안 유의사항을 확인한다.",
                text_length=32,
            ),
            CandidatePage(
                page_no=62,
                page_text="제3자 제공 및 사전승인이라는 일반 용어가 보안 교육 문맥에 포함되어 있다.",
                text_length=42,
            ),
        ]

        result = RuleReviewAgent().review("6", pages, RagContext(item_no="6"))

        self.assertEqual(result.result, "미준수")
        self.assertEqual(result.evidence_pages, [])

    def test_item_six_allows_core_requirements_across_multiple_pages(self):
        from agents.models import CandidatePage, RagContext
        from agents.rule_review_agent import RuleReviewAgent

        pages = [
            CandidatePage(
                page_no=50,
                page_text=(
                    "지식재산권의 공동 활용을 원칙으로 하며 공급자는 S/W 산출물의 반출을 요청할 수 있다. "
                    "반출 시 누출금지정보를 삭제하고 공급자 대표 명의의 확약서를 제출하여야 한다."
                ),
                text_length=92,
            ),
            CandidatePage(
                page_no=102,
                page_text=(
                    "반출한 S/W 산출물을 제3자에게 제공하려는 경우에는 발주기관의 사전승인을 받아야 한다. "
                    "제공받은 산출물을 무단 유출하거나 누출금지정보를 삭제하지 않고 활용하면 입찰참가자격을 제한한다."
                ),
                text_length=110,
            ),
        ]

        result = RuleReviewAgent().review("6", pages, RagContext(item_no="6"))

        self.assertEqual(result.result, "준수")
        self.assertEqual(result.evidence_pages, [50, 102])
        self.assertFalse(result.used_llm)

    def test_item_six_requires_sanction_requirement_from_rag_criteria(self):
        from agents.models import CandidatePage, RagContext, RagHit
        from agents.rule_review_agent import RuleReviewAgent

        rag = RagContext(
            item_no="6",
            hits=[
                RagHit(
                    item_no="6",
                    source_type="criteria_db",
                    source_name="legal_requirement",
                    title="SW사업 산출물 활용 보장",
                    category="명시",
                    snippet=(
                        "지식재산 공동귀속, SW산출물 반출 요청절차, 누출금지정보 삭제 및 확약서 제출, "
                        "제3자 제공 시 발주기관 사전승인, 무단 유출 또는 누출금지정보 미삭제 활용 시 "
                        "입찰참가자격 제한 내용을 명시"
                    ),
                )
            ],
        )
        pages = [
            CandidatePage(
                page_no=50,
                page_text=(
                    "지식재산권의 공동 활용을 원칙으로 하며 공급자는 S/W 산출물의 반출을 요청할 수 있다. "
                    "반출 시 누출금지정보를 삭제하고 확약서를 제출하여야 한다."
                ),
                text_length=92,
            ),
            CandidatePage(
                page_no=102,
                page_text="반출한 S/W 산출물을 제3자에게 제공하려는 경우에는 발주기관의 사전승인을 받아야 한다.",
                text_length=54,
            ),
        ]

        result = RuleReviewAgent().review("6", pages, rag)

        self.assertEqual(result.result, "미준수")
        self.assertEqual(result.evidence_pages, [50])

    def test_item_six_requires_confirmation_letter_and_bid_restriction_text(self):
        from agents.models import CandidatePage, RagContext, RagHit
        from agents.rule_review_agent import RuleReviewAgent

        rag = RagContext(
            item_no="6",
            hits=[
                RagHit(
                    item_no="6",
                    source_type="criteria_db",
                    source_name="legal_requirement",
                    title="SW사업 산출물 활용 보장",
                    category="명시",
                    snippet=(
                        "지식재산 공동귀속, SW산출물 반출 요청절차, 누출금지정보 삭제 및 확약서 제출, "
                        "제3자 제공 시 발주기관 사전승인, 무단 유출 또는 누출금지정보 미삭제 활용 시 "
                        "입찰참가자격 제한 내용을 명시"
                    ),
                )
            ],
        )
        pages = [
            CandidatePage(page_no=19, page_text="요구사항 목록 QUR-003 산출물 관리 PMR-005 지식재산권", text_length=40),
            CandidatePage(page_no=30, page_text="장비 반출입 보안 및 산출물 저장매체 승인 절차", text_length=40),
            CandidatePage(page_no=37, page_text="누출금지대상정보 누출 시 입찰참가자격 제한", text_length=40),
            CandidatePage(
                page_no=102,
                page_text=(
                    "□ SW사업 산출물 활용 보장\n"
                    "○ 당해 계약에 따른 계약목적물에 대한 지식재산권 활용\n"
                    "- 발주기관과 계약상대자가 공동으로 소유하나 지식재산권의 타용도 및 상업적 활용은 금지한다.\n"
                    "- (산출물 반출 요청) 계약상대자는 지식재산권의 행사를 위하여 계약산출물의 반출을 요청할 수 있다.\n"
                    "- 누출금지정보를 삭제하고 활용하여야 한다.\n"
                    "- 활용 승인(제3자 제공 포함)을 받지 않고 반출하거나 승인 받은 소프트웨어 산출물을 무단으로 유출하거나 "
                    "누출금지정보를 삭제하지 않고 활용하는 경우 제재 요건에 해당한다."
                ),
                text_length=320,
            ),
            CandidatePage(page_no=137, page_text="서약서 부정당업자의 입찰참가자격 제한 등 제재처분", text_length=40),
        ]

        result = RuleReviewAgent().review("6", pages, rag)

        self.assertEqual(result.result, "미준수")
        self.assertEqual(result.evidence_pages, [102])

    def test_item_six_prefers_single_dense_direct_evidence_page_when_all_atomic_requirements_present(self):
        from agents.models import CandidatePage, RagContext, RagHit
        from agents.rule_review_agent import RuleReviewAgent

        rag = RagContext(
            item_no="6",
            hits=[
                RagHit(
                    item_no="6",
                    source_type="criteria_db",
                    source_name="legal_requirement",
                    title="SW사업 산출물 활용 보장",
                    category="명시",
                    snippet=(
                        "지식재산 공동귀속, SW산출물 반출 요청절차, 누출금지정보 삭제 및 확약서 제출, "
                        "제3자 제공 시 발주기관 사전승인, 무단 유출 또는 누출금지정보 미삭제 활용 시 "
                        "입찰참가자격 제한 내용을 명시"
                    ),
                )
            ],
        )
        pages = [
            CandidatePage(page_no=19, page_text="요구사항 목록 QUR-003 산출물 관리 PMR-005 지식재산권", text_length=40),
            CandidatePage(
                page_no=102,
                page_text=(
                    "□ SW사업 산출물 활용 보장\n"
                    "○ 당해 계약에 따른 계약목적물에 대한 지식재산권 활용\n"
                    "- 발주기관과 계약상대자가 공동으로 소유하나 지식재산권의 타용도 및 상업적 활용은 금지한다.\n"
                    "- (산출물 반출 요청) 계약상대자는 지식재산권의 행사를 위하여 계약산출물의 반출을 요청할 수 있다.\n"
                    "- 공급자는 제공받은 SW산출물 중 누출금지정보를 삭제하고 활용하여야 하며, "
                    "이를 확인하는 공급자 대표 명의의 확약서를 제출하여야 한다.\n"
                    "- 반출된 SW산출물을 제3자에게 제공하려는 경우 발주기관의 사전승인을 받아야 한다.\n"
                    "- 발주기관은 공급자가 제공받은 SW산출물을 무단 유출하거나 누출금지정보를 삭제하지 않고 활용하는 경우 "
                    "입찰참가자격을 제한한다."
                ),
                text_length=420,
            ),
            CandidatePage(page_no=137, page_text="서약서 부정당업자의 입찰참가자격 제한 등 제재처분", text_length=40),
        ]

        result = RuleReviewAgent().review("6", pages, rag)

        self.assertEqual(result.result, "준수")
        self.assertEqual(result.evidence_pages, [102])

    def test_rule_evidence_uses_rfp_printed_page_number_when_available(self):
        from agents.models import CandidatePage, RagContext
        from agents.rule_review_agent import RuleReviewAgent

        pages = [
            CandidatePage(
                page_no=25,
                page_text=(
                    "계약목적물의 지식재산권은 발주기관과 계약상대자가 공동으로 소유하며, "
                    "공급자는 지식재산권의 활용을 위하여 S/W 산출물의 반출을 요청할 수 있으며 "
                    "누출금지정보를 삭제하고 공급자 대표 명의의 확약서를 제출하여야 한다. "
                    "반출한 S/W 산출물을 제3자에게 제공하려는 경우 발주기관의 사전승인을 받아야 한다. "
                    "무단 유출하거나 누출금지정보를 삭제하지 않고 활용하는 경우 입찰참가자격을 제한한다.\n- 23 -"
                ),
                text_length=230,
            ),
        ]

        result = RuleReviewAgent().review("6", pages, RagContext(item_no="6"))

        self.assertEqual(result.evidence_pages, [23])

    def test_rule_rag_overlap_uses_rfp_printed_page_number(self):
        from agents.models import CandidatePage, RagContext, RagHit
        from agents.rule_review_agent import RuleReviewAgent

        pages = [
            CandidatePage(
                page_no=25,
                page_text="alpha beta gamma delta evidence\n- 23 -",
                text_length=40,
            )
        ]
        rag = RagContext(
            item_no="99",
            hits=[
                RagHit(
                    item_no="99",
                    source_type="criteria_db",
                    source_name="criteria",
                    title="alpha beta gamma",
                    category="criteria",
                    snippet="alpha beta gamma delta",
                )
            ],
        )

        result = RuleReviewAgent().review("99", pages, rag)

        self.assertEqual(result.evidence_pages, [23])

    def test_item_seven_uses_only_joint_reuse_plan_evidence(self):
        from agents.models import CandidatePage, RagContext
        from agents.rule_review_agent import RuleReviewAgent

        pages = [
            CandidatePage(
                page_no=37,
                page_text="보안 요구사항과 산출물 관리 방법 및 사업 완료 후 자료 반환 대책을 평가한다.",
                text_length=44,
            ),
            CandidatePage(
                page_no=17,
                page_text="개발 장비와 소프트웨어는 사전에 공단과 협의하여 사용한다.",
                text_length=32,
            ),
            CandidatePage(
                page_no=25,
                page_text=(
                    "본 사업을 통해 개발되는 S/W는 용역계약일반조건 제56조에 따라 "
                    "타 기관과 공동 활용할 계획 없음."
                ),
                text_length=70,
            ),
        ]

        result = RuleReviewAgent().review("7", pages, RagContext(item_no="7"))

        self.assertEqual(result.result, "준수")
        self.assertEqual(result.evidence_pages, [25])
        self.assertFalse(result.used_llm)

    def test_item_eighteen_uses_only_sw_business_information_submission_evidence(self):
        from agents.models import CandidatePage, RagContext
        from agents.rule_review_agent import RuleReviewAgent

        pages = [
            CandidatePage(
                page_no=9,
                page_text="본 사업의 적정 사업기간 산정을 위한 기능점수 규모는 726.4FP로 산정한다.",
                text_length=45,
            ),
            CandidatePage(
                page_no=23,
                page_text="사업 수행과정에서 취득한 자료와 정보는 외부에 유출 또는 누설 금지한다.",
                text_length=45,
            ),
            CandidatePage(
                page_no=25,
                page_text="원격지 개발 장소 보안요구사항 및 보안사고 대응방안을 제안하여야 한다.",
                text_length=45,
            ),
            CandidatePage(
                page_no=29,
                page_text=(
                    "본 사업은 「소프트웨어 진흥법 제46조」에 따라 SW사업정보 데이터를 작성 및 제출하여야 함. "
                    "SW 사업정보 데이터 작성 및 제출에 관한 사항은 www.spir.kr 자료실의 SW 사업정보 저장소 "
                    "데이터 제출안내 문서를 참조토록 함."
                ),
                text_length=120,
            ),
        ]

        result = RuleReviewAgent().review("18", pages, RagContext(item_no="18"))

        self.assertEqual(result.result, "준수")
        self.assertEqual(result.evidence_pages, [29])
        self.assertFalse(result.used_llm)

    def test_item_fourteen_uses_requirement_detail_structure_not_summary(self):
        from agents.models import CandidatePage, RagContext
        from agents.rule_review_agent import RuleReviewAgent

        pages = [
            CandidatePage(
                page_no=10,
                page_text=(
                    "요구사항 총괄표 기능 요구사항 성능 요구사항 데이터 요구사항 "
                    "보안 요구사항 품질 요구사항 제약사항 프로젝트관리 요구사항"
                ),
                text_length=80,
            ),
            CandidatePage(
                page_no=11,
                page_text=(
                    "요구사항 분류 기능 요구사항 요구사항 고유번호 SFR-001 "
                    "요구사항 명칭 지원 결정 및 지원 제외자 관리 정의 "
                    "상세 세부내용 산출정보"
                ),
                text_length=95,
            ),
            CandidatePage(
                page_no=2,
                page_text=(
                    "목차 제안요청 내용 요구사항 총괄표 기능 요구사항 성능 요구사항 "
                    "데이터 요구사항 보안 요구사항 품질 요구사항"
                ),
                text_length=80,
                has_toc_candidate=True,
            ),
            CandidatePage(
                page_no=32,
                page_text="하도급은 원칙적으로 불허한다. 공동수급은 허용한다.",
                text_length=30,
            ),
        ]

        result = RuleReviewAgent().review("14", pages, RagContext(item_no="14"))

        self.assertEqual(result.result, "준수")
        self.assertEqual(result.evidence_pages, [11])
        self.assertFalse(result.used_llm)

    def test_item_eleven_treats_ninety_points_as_ninety_percent(self):
        from agents.models import CandidatePage, RagContext
        from agents.table_review_agent import TableReviewAgent

        class FakeClient:
            def __init__(self):
                self.called = False

            def is_configured(self):
                return True

            def json_response(self, *args, **kwargs):
                self.called = True
                return {
                    "result": "미준수",
                    "is_target": True,
                    "confidence": 0.9,
                    "evidence_pages": [99],
                    "evidence_text": ["wrong"],
                    "reason": "wrong",
                    "recommendation": "wrong",
                    "needs_human_review": False,
                }

        pages = [
            CandidatePage(
                page_no=33,
                page_text="평가원칙 - 기술능력평가점수(90점, 차등점수제*)와 가격평가점수(10점) 합산",
                text_length=60,
                has_table_candidate=True,
                has_eval_table_candidate=True,
            )
        ]
        client = FakeClient()

        result = TableReviewAgent(client).review("11", pages, RagContext(item_no="11"))

        self.assertFalse(client.called)
        self.assertEqual(result.result, "준수")
        self.assertEqual(result.evidence_pages, [33])
        self.assertFalse(result.used_llm)

    def test_item_seventeen_toc_listing_is_not_attachment(self):
        from agents.attach_review_agent import AttachmentReviewAgent
        from agents.models import CandidatePage, RagContext

        class FakeClient:
            def __init__(self):
                self.called = False

            def is_configured(self):
                return True

            def json_response(self, *args, **kwargs):
                self.called = True
                return {
                    "result": "미준수",
                    "is_target": True,
                    "confidence": 0.9,
                    "evidence_pages": [2],
                    "evidence_text": ["붙임 7 소프트웨어사업 영향평가 검토 결과서"],
                    "reason": "붙임 목록에만 표시되어 있고 실제 첨부 본문은 확인되지 않습니다.",
                    "recommendation": "소프트웨어사업 영향평가 결과서를 실제 작성하여 첨부하시기 바랍니다.",
                    "needs_human_review": False,
                }

        pages = [
            CandidatePage(
                page_no=2,
                page_text="[붙임] 7. 소프트웨어사업 영향평가 검토 결과서",
                text_length=40,
                has_toc_candidate=True,
                has_attachment_candidate=True,
            ),
            CandidatePage(
                page_no=30,
                page_text="프로젝트 지원 요구사항 및 하자보수 계획",
                text_length=30,
            ),
        ]
        client = FakeClient()

        result = AttachmentReviewAgent(client).review("17", pages, RagContext(item_no="17"))

        self.assertFalse(client.called)
        self.assertEqual(result.result, "미준수")
        self.assertEqual(result.evidence_pages, [2])
        self.assertFalse(result.needs_human_review)
        self.assertIn("목록", result.reason)

    def test_item_seventeen_blank_impact_form_is_not_compliant(self):
        from agents.attach_review_agent import AttachmentReviewAgent
        from agents.models import CandidatePage, RagContext

        class FakeClient:
            def __init__(self):
                self.called = False

            def is_configured(self):
                return True

            def json_response(self, *args, **kwargs):
                self.called = True
                return {
                    "result": "미준수",
                    "is_target": True,
                    "confidence": 0.91,
                    "evidence_pages": [21, 22],
                    "evidence_text": [
                        "5. 입찰 및 제안서 관련 서식 및 별첨",
                        "별첨 2호\n※작성 후 스캔 첨부 예정\n소프트웨어사업 영향평가 결과서",
                    ],
                    "reason": "별첨 목록과 미작성 영향평가 양식만 있고 실제 검토 결과가 없습니다.",
                    "recommendation": "소프트웨어사업 영향평가 결과서를 실제 작성하여 첨부하시기 바랍니다.",
                    "needs_human_review": False,
                }

        pages = [
            CandidatePage(
                page_no=20,
                page_text=(
                    "본 사업은 「소프트웨어 진흥법」제50조에 따른 과업내용 확정을 위하여\n"
                    "과업심의위원회를 개최한 사업임"
                ),
                text_length=60,
            ),
            CandidatePage(
                page_no=21,
                page_text=(
                    "5. 입찰 및 제안서 관련 서식 및 별첨\n"
                    "NO 구분 번호 내용\n"
                    "1 1호 제안사 일반현황 및 연혁\n"
                    "2 2호 자본금 및 매출액(최근 3년)\n"
                    "3 3호 사업 실적 증명서\n"
                    "4 4호 참여인력 이력사항"
                ),
                text_length=95,
                has_toc_candidate=True,
                has_attachment_candidate=True,
            ),
            CandidatePage(
                page_no=22,
                page_text=(
                    "별첨 2호\n"
                    "※작성 후 스캔 첨부 예정\n"
                    "소프트웨어사업 영향평가 결과서\n"
                    "사업명\n"
                    "□ 예산편성 □ 사업발주\n"
                    "영향평가단계\n"
                    "□ 그 외 필요시 □ 재평가\n"
                    "주요 내용\n"
                    "평가항목 평가결과 비고\n"
                    "민간 소프트웨어 시장 침해 가능성\n"
                    "민간 서비스와의 중복 여부\n"
                    "상용 소프트웨어 활용 가능성\n"
                    "종합 의견"
                ),
                text_length=110,
                has_attachment_candidate=True,
            ),
        ]

        client = FakeClient()
        result = AttachmentReviewAgent(client).review("17", pages, RagContext(item_no="17"))

        self.assertFalse(client.called)
        self.assertEqual(result.result, "미준수")
        self.assertEqual(result.evidence_pages, [22])
        self.assertIn("빈 문서", result.reason)

    def test_item_fifteen_attachment_title_only_is_not_compliant(self):
        from agents.attach_review_agent import AttachmentReviewAgent
        from agents.models import CandidatePage, RagContext

        pages = [
            CandidatePage(
                page_no=41,
                page_text="[붙임 목차]\n【붙임 6】 소프트웨어 개발사업 적정 사업기간 종합산정서",
                text_length=45,
                has_toc_candidate=True,
                has_attachment_candidate=True,
            ),
            CandidatePage(
                page_no=74,
                page_text="[붙임 6] 소프트웨어 개발사업의 적정 사업기간 종합 산정서\n- 74 -",
                text_length=40,
                has_attachment_candidate=True,
            ),
        ]

        result = AttachmentReviewAgent().review("15", pages, RagContext(item_no="15"))

        self.assertEqual(result.result, "미준수")
        self.assertEqual(result.evidence_pages, [74])
        self.assertIn("빈 문서", result.reason)

    def test_item_seventeen_label_only_form_is_not_compliant_without_gpt(self):
        from agents.attach_review_agent import AttachmentReviewAgent
        from agents.models import CandidatePage, RagContext

        pages = [
            CandidatePage(
                page_no=22,
                page_text=(
                    "[붙임 7] 소프트웨어사업 영향평가 검토결과서\n"
                    "사업명\n"
                    "예산편성 대상 사업발주\n"
                    "영향평가 단계\n"
                    "구분 평가항목 평가결과 비고\n"
                    "민간 소프트웨어 시장 침해 가능성\n"
                    "민간 서비스와의 중복 여부\n"
                    "상용 소프트웨어 활용 가능성\n"
                    "주요 내용\n"
                    "종합 의견\n"
                    "작성자 서명"
                ),
                text_length=160,
                has_attachment_candidate=True,
            )
        ]

        result = AttachmentReviewAgent().review("17", pages, RagContext(item_no="17"))

        self.assertEqual(result.result, "미준수")
        self.assertEqual(result.source, "python_attachment_sw_impact_empty")
        self.assertEqual(result.evidence_pages, [22])

    def test_item_seventeen_attachment_reference_is_not_actual_attachment(self):
        from agents.attach_review_agent import AttachmentReviewAgent
        from agents.models import CandidatePage, RagContext

        pages = [
            CandidatePage(
                page_no=106,
                page_text=(
                    "제37조, 「소프트웨어사업 계약 및 관리감독에 관한 지침」 제5조,\n"
                    "제6조에 따라 소프트웨어사업 영향평가를 미리 실시한 사업임\n"
                    "※ 「소프트웨어사업 계약 및 관리감독에 관한 지침」 별지 제1호 서식에 따른\n"
                    "“소프트웨어사업 영향평가 결과서”를 첨부(별첨 2 참조)\n"
                    "□ 소프트웨어사업정보 제출"
                ),
                text_length=180,
                rfp_printed_page_no=104,
                has_attachment_candidate=True,
            )
        ]

        result = AttachmentReviewAgent().review("17", pages, RagContext(item_no="17"))

        self.assertEqual(result.result, "미준수")
        self.assertEqual(result.source, "python_attachment_sw_impact_missing")
        self.assertEqual(result.evidence_pages, [104])

    def test_item_seventeen_missing_attachment_keeps_declaration_and_appendix_evidence(self):
        from agents.attach_review_agent import AttachmentReviewAgent
        from agents.models import CandidatePage, RagContext

        pages = [
            CandidatePage(
                page_no=106,
                page_text=(
                    "본 사업은 「소프트웨어 진흥법」 제43조에 따라 소프트웨어사업 영향평가를 미리 실시한 사업임\n"
                    "※ 「소프트웨어사업 계약 및 관리감독에 관한 지침」 별지 제1호 서식에 따른\n"
                    "“소프트웨어사업 영향평가 결과서”를 첨부(별첨 2 참조)"
                ),
                text_length=150,
                rfp_printed_page_no=104,
                has_attachment_candidate=True,
            ),
            CandidatePage(
                page_no=113,
                page_text="별첨 2 소프트웨어사업 영향평가 검토결과서\n111",
                text_length=40,
                rfp_printed_page_no=111,
                has_attachment_candidate=True,
            ),
        ]

        result = AttachmentReviewAgent().review("17", pages, RagContext(item_no="17"))

        self.assertEqual(result.result, "미준수")
        self.assertEqual(result.evidence_pages, [104, 111])

    def test_item_seventeen_compliance_keeps_declaration_and_attachment_evidence(self):
        from agents.attach_review_agent import AttachmentReviewAgent
        from agents.models import CandidatePage, RagContext

        pages = [
            CandidatePage(
                page_no=106,
                page_text=(
                    "본 사업은 「소프트웨어 진흥법」 제43조에 따라 소프트웨어사업 영향평가를 미리 실시한 사업임\n"
                    "※ 별지 제1호 서식에 따른 “소프트웨어사업 영향평가 결과서”를 첨부함"
                ),
                text_length=120,
                rfp_printed_page_no=104,
                has_attachment_candidate=True,
            ),
            CandidatePage(
                page_no=113,
                page_text=(
                    "[별첨 2] 소프트웨어사업 영향평가 검토결과서\n"
                    "사업명 통합 정보시스템 고도화 사업\n"
                    "민간 소프트웨어 시장 침해 가능성 없음. 본 사업은 내부 행정업무 처리 기능을 개선하는 구축 사업으로 "
                    "동일 기능의 민간 상용 서비스 대체 또는 배포를 목적으로 하지 않는다.\n"
                    "상용 소프트웨어 활용 가능성은 낮으며 기존 라이선스 연계를 우선 검토하였다.\n"
                    "종합 의견 민간시장 침해 및 서비스 중복 가능성이 낮아 사업 추진이 타당하다."
                ),
                text_length=230,
                rfp_printed_page_no=111,
                has_attachment_candidate=True,
            ),
        ]

        result = AttachmentReviewAgent().review("17", pages, RagContext(item_no="17"))

        self.assertEqual(result.result, "준수")
        self.assertEqual(result.evidence_pages, [104, 111])

    def test_item_seventeen_rejects_gpt_compliance_without_actual_attachment_body(self):
        from agents.attach_review_agent import AttachmentReviewAgent
        from agents.models import CandidatePage, RagContext

        class FakeClient:
            def is_configured(self):
                return True

            def json_response(self, *args, **kwargs):
                return {
                    "result": "준수",
                    "is_target": True,
                    "confidence": 0.95,
                    "evidence_pages": [3, 6, 8],
                    "evidence_text": [
                        "시스템 유지관리 및 데이터 관리",
                        "전산지원센터 운영 및 교육 지원",
                        "현행 시스템 개요",
                    ],
                    "reason": "별첨 2로 첨부하여 공개하고 있음이 확인됨.",
                    "recommendation": "",
                    "needs_human_review": False,
                }

        pages = [
            CandidatePage(
                page_no=5,
                page_text="시스템 유지관리 및 데이터 관리\n법ㆍ제도ㆍ지침 등 변경사항 반영",
                text_length=60,
                rfp_printed_page_no=3,
            ),
            CandidatePage(
                page_no=106,
                page_text=(
                    "본 사업은 소프트웨어사업 영향평가를 미리 실시한 사업임\n"
                    "“소프트웨어사업 영향평가 결과서”를 첨부(별첨 2 참조)"
                ),
                text_length=90,
                rfp_printed_page_no=104,
                has_attachment_candidate=True,
            ),
        ]

        result = AttachmentReviewAgent(FakeClient()).review("17", pages, RagContext(item_no="17"))

        self.assertEqual(result.result, "미준수")
        self.assertEqual(result.source, "python_attachment_sw_impact_missing")
        self.assertEqual(result.evidence_pages, [104])

    def test_item_seventeen_substantive_attachment_body_is_compliant_without_gpt(self):
        from agents.attach_review_agent import AttachmentReviewAgent
        from agents.models import CandidatePage, RagContext

        pages = [
            CandidatePage(
                page_no=20,
                page_text=(
                    "본 사업은 「소프트웨어 진흥법」 제43조에 따라 소프트웨어사업 영향평가를 미리 실시한 사업임\n"
                    "별지 제1호서식에 따른 소프트웨어사업 영향평가 결과서를 첨부함"
                ),
                text_length=90,
                rfp_printed_page_no=20,
            ),
            CandidatePage(
                page_no=23,
                page_text=(
                    "[붙임 7] 소프트웨어사업 영향평가 검토결과서\n"
                    "사업명 통합 정보시스템 고도화 사업\n"
                    "민간 소프트웨어 시장 침해 가능성 없음. 본 사업은 내부 행정업무 처리 기능을 개선하는 구축 사업으로 "
                    "동일 기능의 민간 상용 서비스 대체 또는 배포를 목적으로 하지 않는다.\n"
                    "상용 소프트웨어 활용 가능성은 낮으며 기존 라이선스 연계를 우선 검토하였다.\n"
                    "종합 의견 민간시장 침해 및 서비스 중복 가능성이 낮아 사업 추진이 타당하다."
                ),
                text_length=230,
                has_attachment_candidate=True,
            )
        ]

        result = AttachmentReviewAgent().review("17", pages, RagContext(item_no="17"))

        self.assertEqual(result.result, "준수")
        self.assertEqual(result.source, "python_attachment_sw_impact")
        self.assertEqual(result.evidence_pages, [20, 23])

    def test_item_seventeen_attachment_without_declaration_is_noncompliant(self):
        from agents.attach_review_agent import AttachmentReviewAgent
        from agents.models import CandidatePage, RagContext

        pages = [
            CandidatePage(
                page_no=23,
                page_text=(
                    "[붙임 7] 소프트웨어사업 영향평가 검토결과서\n"
                    "사업명 통합 정보시스템 고도화 사업\n"
                    "민간 소프트웨어 시장 침해 가능성 없음. 본 사업은 내부 행정업무 처리 기능을 개선하는 구축 사업으로 "
                    "동일 기능의 민간 상용 서비스 대체 또는 배포를 목적으로 하지 않는다.\n"
                    "종합 의견 민간시장 침해 및 서비스 중복 가능성이 낮아 사업 추진이 타당하다."
                ),
                text_length=200,
                has_attachment_candidate=True,
            )
        ]

        result = AttachmentReviewAgent().review("17", pages, RagContext(item_no="17"))

        self.assertEqual(result.result, "미준수")
        self.assertEqual(result.evidence_pages, [23])

    def test_item_fifteen_label_only_form_is_not_compliant_without_gpt(self):
        from agents.attach_review_agent import AttachmentReviewAgent
        from agents.models import CandidatePage, RagContext

        pages = [
            CandidatePage(
                page_no=74,
                page_text=(
                    "[붙임 6] 소프트웨어 개발사업의 적정 사업기간 종합 산정서\n"
                    "사업명\n"
                    "발주기관\n"
                    "산정 기준\n"
                    "기능점수\n"
                    "보정계수\n"
                    "산정결과\n"
                    "위원명 서명\n"
                    "작성일"
                ),
                text_length=120,
                has_attachment_candidate=True,
            )
        ]

        result = AttachmentReviewAgent().review("15", pages, RagContext(item_no="15"))

        self.assertEqual(result.result, "미준수")
        self.assertEqual(result.source, "python_attachment_project_period_empty")
        self.assertEqual(result.evidence_pages, [74])

    def test_item_fifteen_compliance_requires_declaration_and_attachment_body(self):
        from agents.attach_review_agent import AttachmentReviewAgent
        from agents.models import CandidatePage, RagContext

        pages = [
            CandidatePage(
                page_no=70,
                page_text=(
                    "본 사업은 소프트웨어사업 계약 및 관리감독에 관한 지침 제10조에 따라 "
                    "소프트웨어 개발사업 적정 사업기간 산정 기준에 따른 사업임\n"
                    "별지 제4호서식 소프트웨어 개발사업의 적정 사업기간 종합 산정서를 공지함"
                ),
                text_length=130,
                rfp_printed_page_no=70,
            ),
            CandidatePage(
                page_no=74,
                page_text=(
                    "[붙임 6] 소프트웨어 개발사업의 적정 사업기간 종합 산정서\n"
                    "사업명 통합 정보시스템 고도화 사업\n"
                    "기능점수 720 FP, 보정계수 1.0, 산정결과 10개월\n"
                    "종합 의견 기능 규모와 개발 난이도를 검토한 결과 적정 사업기간은 10개월로 산정함."
                ),
                text_length=170,
                has_attachment_candidate=True,
            ),
        ]

        result = AttachmentReviewAgent().review("15", pages, RagContext(item_no="15"))

        self.assertEqual(result.result, "준수")
        self.assertEqual(result.evidence_pages, [70, 74])

    def test_item_fifteen_attachment_without_declaration_is_noncompliant(self):
        from agents.attach_review_agent import AttachmentReviewAgent
        from agents.models import CandidatePage, RagContext

        pages = [
            CandidatePage(
                page_no=74,
                page_text=(
                    "[붙임 6] 소프트웨어 개발사업의 적정 사업기간 종합 산정서\n"
                    "사업명 통합 정보시스템 고도화 사업\n"
                    "기능점수 720 FP, 보정계수 1.0, 산정결과 10개월\n"
                    "종합 의견 기능 규모와 개발 난이도를 검토한 결과 적정 사업기간은 10개월로 산정함."
                ),
                text_length=170,
                has_attachment_candidate=True,
            )
        ]

        result = AttachmentReviewAgent().review("15", pages, RagContext(item_no="15"))

        self.assertEqual(result.result, "미준수")
        self.assertEqual(result.evidence_pages, [74])

    def test_item_fifteen_without_attachment_or_declaration_is_noncompliant(self):
        from agents.attach_review_agent import AttachmentReviewAgent
        from agents.models import CandidatePage, RagContext

        pages = [
            CandidatePage(
                page_no=6,
                page_text="사업 개요 및 일반 제안 안내",
                text_length=20,
            ),
            CandidatePage(
                page_no=30,
                page_text="제안서 작성 및 제출 방법",
                text_length=20,
            ),
        ]

        result = AttachmentReviewAgent().review("15", pages, RagContext(item_no="15"))

        self.assertEqual(result.result, "미준수")
        self.assertEqual(result.source, "python_attachment_project_period_missing_all")
        self.assertEqual(result.evidence_pages, [])

    def test_item_fifteen_declaration_without_attachment_is_noncompliant_without_gpt(self):
        from agents.attach_review_agent import AttachmentReviewAgent
        from agents.models import CandidatePage, RagContext

        pages = [
            CandidatePage(
                page_no=70,
                page_text=(
                    "본 사업은 소프트웨어사업 계약 및 관리감독에 관한 지침 제10조에 따라 "
                    "소프트웨어 개발사업 적정 사업기간 산정 기준에 따른 사업임"
                ),
                text_length=80,
                rfp_printed_page_no=70,
            ),
            CandidatePage(
                page_no=96,
                page_text="제안서 평가항목 및 배점표",
                text_length=20,
            ),
        ]

        result = AttachmentReviewAgent().review("15", pages, RagContext(item_no="15"))

        self.assertEqual(result.result, "미준수")
        self.assertEqual(result.source, "python_attachment_project_period_missing_attachment")
        self.assertEqual(result.evidence_pages, [70])

    def test_item_two_returns_not_applicable_when_not_direct_purchase_target(self):
        from agents.attach_review_agent import AttachmentReviewAgent
        from agents.models import CandidatePage, RagContext

        pages = [
            CandidatePage(page_no=3, page_text="소프트웨어 개발사업 사업예산 4억원", text_length=20),
            CandidatePage(page_no=10, page_text="기능 요구사항 및 개발 범위", text_length=20),
        ]

        result = AttachmentReviewAgent().review("2", pages, RagContext(item_no="2"))

        self.assertEqual(result.result, "해당없음")
        self.assertFalse(result.needs_human_review)

    def test_item_two_target_requires_budget_and_direct_purchase_commercial_sw(self):
        from agents.attach_review_agent import review_commercial_sw_direct_purchase_target
        from agents.models import CandidatePage

        not_target = review_commercial_sw_direct_purchase_target(
            [
                CandidatePage(
                    page_no=1,
                    page_text="총사업금액 4억원인 소프트웨어 개발사업이나 직접구매 대상 상용SW 구매 내용은 없음",
                    text_length=50,
                )
            ]
        )
        target = review_commercial_sw_direct_purchase_target(
            [
                CandidatePage(
                    page_no=1,
                    page_text="총사업금액 4억원이며 직접구매 대상 상용SW 구매를 포함한다.",
                    text_length=50,
                )
            ]
        )

        self.assertEqual(not_target.result, "해당없음")
        self.assertIsNone(target)

    def test_item_two_one_target_requires_all_bmt_conditions(self):
        from agents.attach_review_agent import review_bmt_target
        from agents.models import CandidatePage

        missing_one = review_bmt_target(
            [
                CandidatePage(
                    page_no=1,
                    page_text="일반경쟁입찰이며 직접구매 대상 상용SW 구매 금액은 1억원이다. 별표3 34종 SW에 해당한다.",
                    text_length=70,
                )
            ]
        )
        target = review_bmt_target(
            [
                CandidatePage(
                    page_no=1,
                    page_text=(
                        "일반경쟁입찰이며 직접구매 대상 상용SW 구매 금액은 1억원이다. "
                        "품질성능 평가시험 운영 지침 별표3의 34종 SW에 해당하고 조달청 종합쇼핑몰 미등록 제품이다."
                    ),
                    text_length=100,
                )
            ]
        )

        self.assertEqual(missing_one.result, "해당없음")
        self.assertIsNone(target)

    def test_attachment_title_only_common_guard_returns_noncompliant(self):
        from agents.attach_review_agent import review_title_only_attachment
        from agents.models import CandidatePage

        result = review_title_only_attachment(
            "2-1",
            [
                CandidatePage(
                    page_no=55,
                    page_text="【붙임 3】 상용소프트웨어 품질성능 평가시험 결과서\n- 55 -",
                    text_length=40,
                    has_attachment_candidate=True,
                )
            ],
        )

        self.assertEqual(result.result, "미준수")
        self.assertEqual(result.evidence_pages, [55])

    def test_item_four_subcontract_disallowed_is_compliant(self):
        from agents.models import CandidatePage, RagContext
        from agents.rule_review_agent import RuleReviewAgent

        pages = [
            CandidatePage(
                page_no=32,
                page_text="본 사업은 소프트웨어 진흥법 제51조에 의거, 하도급은 원칙적으로 불허한다.",
                text_length=50,
            )
        ]

        result = RuleReviewAgent().review("4", pages, RagContext(item_no="4"))

        self.assertEqual(result.result, "준수")
        self.assertEqual(result.evidence_pages, [32])

    def test_item_four_allowed_subcontract_requires_full_subcontract_terms(self):
        from agents.models import CandidatePage, RagContext
        from agents.rule_review_agent import RuleReviewAgent

        pages = [
            CandidatePage(
                page_no=4,
                page_text="사업 개요 및 하도급 관련 일반 안내",
                text_length=20,
            ),
            CandidatePage(
                page_no=100,
                page_text=(
                    "하도급 관리감독 및 시정요구: 발주기관은 소프트웨어 진흥법 제51조제7항에 따라 "
                    "하도급 제한규정 준수 여부를 지속적으로 관리 감독하고 위반한 계약상대자에게 시정을 요구한다. "
                    "하도급 사전승인: 본 사업의 하도급의 경우 반드시 하도급계약 전에 발주기관으로부터 사전승인을 받아야 한다. "
                    "하도급 비율제한: 본 사업의 과업의 일부를 하도급하려는 경우 소프트웨어사업금액의 100분의 50을 초과할 수 없으며 "
                    "다시 하도급은 원칙적으로 불허한다. "
                    "하도급 계획서 제출: 계약체결 시 소프트웨어사업 하도급 계획서를 제출하여야 한다. "
                    "하도급계약의 적정성 판단 세부기준: 별표 3에 따라 평가점수가 85점 이상인 경우에 한하여 하도급계약을 승인한다. "
                    "공동수급체 구성: 전체 사업금액 대비 10%를 초과하여 하도급하려는 경우 하수급인과 공동수급체를 구성하여 참여해야 한다."
                ),
                text_length=450,
                rfp_printed_page_no=100,
            ),
        ]

        result = RuleReviewAgent().review("4", pages, RagContext(item_no="4"))

        self.assertEqual(result.result, "준수")
        self.assertEqual(result.evidence_pages, [100])

    def test_item_four_resubcontract_limit_alone_is_not_disallow_or_full_compliance(self):
        from agents.models import CandidatePage, RagContext
        from agents.rule_review_agent import RuleReviewAgent

        pages = [
            CandidatePage(
                page_no=62,
                page_text=(
                    "본 사업의 과업의 일부를 하도급하려는 경우 「소프트웨어 진흥법」 "
                    "제51조제1항에 따라 물품 구매금액을 제외한 소프트웨어사업금액의 "
                    "100분의 50을 초과할 수 없으며, 같은 법 제3항에 따라 다시 하도급은 원칙적으로 불허함."
                ),
                text_length=140,
                rfp_printed_page_no=62,
            )
        ]

        result = RuleReviewAgent().review("4", pages, RagContext(item_no="4"))

        self.assertNotEqual(result.result, "준수")
        self.assertNotEqual(result.source, "python_rule_subcontract_disallowed")

    def test_item_twelve_missing_differential_score_detail_is_recommendation(self):
        from agents.models import CandidatePage, RagContext
        from agents.table_review_agent import TableReviewAgent

        pages = [
            CandidatePage(
                page_no=33,
                page_text="기술능력평가점수(90점, 차등점수제*)와 가격평가점수(10점) 합산 순위간 점수차는 3점 적용",
                text_length=80,
            ),
            CandidatePage(
                page_no=36,
                page_text="제안서 기술평가 항목 및 배점 한도 정량적 평가항목 하도급계획 적정성 5점 계 10",
                text_length=50,
                has_table_candidate=True,
            ),
            CandidatePage(
                page_no=37,
                page_text="정성적 평가항목 보안 요구사항 제약사항 성능 요구사항 프로젝트 관리 배점한도",
                text_length=60,
                has_table_candidate=True,
            ),
        ]

        result = TableReviewAgent().review("12", pages, RagContext(item_no="12"))

        self.assertEqual(result.result, "보완필요")
        self.assertEqual(result.evidence_pages, [33, 36])
        self.assertIn("원점수 기준", result.recommendation)

    def test_item_twelve_missing_subcontract_plan_score_is_noncompliant(self):
        from agents.models import CandidatePage, RagContext
        from agents.table_review_agent import TableReviewAgent

        pages = [
            CandidatePage(
                page_no=33,
                page_text=(
                    "기술능력평가점수(90점, 차등점수제*)와 가격평가점수(10점) 합산 순위간 점수차는 3점 적용. "
                    "다만, 원점수 기준의 순위별 점수차가 차등점수보다 큰 경우에는 원점수차를 적용하며, "
                    "차등점수를 부여한 후 기술능력평가점수와 가격평가점수를 합산하여 동점인 경우에는 "
                    "기술능력평가점수에 따라 순위를 정함."
                ),
                text_length=180,
            ),
            CandidatePage(
                page_no=36,
                page_text=(
                    "제안서 기술평가항목 및 배점표\n"
                    "사업 이해도 10점\n"
                    "추진전략 20점\n"
                    "프로젝트 관리 5점\n"
                    "품질보증 5점"
                ),
                text_length=80,
                has_table_candidate=True,
                has_eval_table_candidate=True,
            ),
        ]

        result = TableReviewAgent().review("12", pages, RagContext(item_no="12"))

        self.assertEqual(result.result, "미준수")
        self.assertIn("하도급계획", result.reason)

    def test_item_twelve_subcontract_plan_score_five_or_more_is_compliant(self):
        from agents.models import CandidatePage, RagContext
        from agents.table_review_agent import TableReviewAgent

        pages = [
            CandidatePage(
                page_no=33,
                page_text=(
                    "기술능력평가점수(90점, 차등점수제*)와 가격평가점수(10점) 합산 순위간 점수차는 3점 적용. "
                    "다만, 원점수 기준의 순위별 점수차가 차등점수보다 큰 경우에는 원점수차를 적용하며, "
                    "차등점수를 부여한 후 기술능력평가점수와 가격평가점수를 합산하여 동점인 경우에는 "
                    "기술능력평가점수에 따라 순위를 정함."
                ),
                text_length=180,
            ),
            CandidatePage(
                page_no=36,
                page_text=(
                    "제안서 기술평가항목 및 배점표\n"
                    "사업 이해도 10점\n"
                    "하도급계획 적정성 5점\n"
                    "프로젝트 관리 5점"
                ),
                text_length=80,
                has_table_candidate=True,
                has_eval_table_candidate=True,
            ),
        ]

        result = TableReviewAgent().review("12", pages, RagContext(item_no="12"))

        self.assertEqual(result.result, "준수")
        self.assertEqual(result.evidence_pages, [33, 36])

    def test_item_twelve_differential_score_not_applied_is_compliant(self):
        from agents.models import CandidatePage, RagContext
        from agents.table_review_agent import TableReviewAgent

        pages = [
            CandidatePage(
                page_no=63,
                page_text=(
                    "1. 입찰 참가 자격\n"
                    + "일반 안내 문구\n" * 40
                    + "본 사업은 「소프트웨어 기술성 평가기준 지침」 제4조제5항에 따른 차등점수\n"
                    "제를 미적용한 사업임\n"
                    "본 사업은 「소프트웨어 진흥법」제51조에 의거, 하도급은 원칙적으로 불허한다."
                ),
                text_length=600,
            ),
            CandidatePage(
                page_no=65,
                page_text="기술제안서 평가항목 및 배점한도\n사업 이해도 10점\n추진전략 20점",
                text_length=60,
                has_table_candidate=True,
                has_eval_table_candidate=True,
            ),
        ]

        result = TableReviewAgent().review("12", pages, RagContext(item_no="12"))

        self.assertEqual(result.result, "준수")
        self.assertEqual(result.evidence_pages, [63, 65])
        self.assertTrue(any("차등점수" in text and "미적용" in text for text in result.evidence_text))
        self.assertTrue(any("하도급" in text and "불허" in text for text in result.evidence_text))
        self.assertFalse(any(text.startswith("1. 입찰 참가 자격\n일반 안내") for text in result.evidence_text))

    def test_non_rule_agents_use_gpt_with_different_model_roles_when_configured(self):
        from agents.attach_review_agent import AttachmentReviewAgent
        from agents.models import CandidatePage, RagContext, RagHit
        from agents.rule_review_agent import RuleReviewAgent
        from agents.table_review_agent import TableReviewAgent
        from agents.llm_review_agent import LlmReviewAgent

        class FakeClient:
            def __init__(self):
                self.roles = []

            def is_configured(self):
                return True

            def json_response(self, system, user, **kwargs):
                self.roles.append(kwargs.get("model_role"))
                return {
                    "result": "준수",
                    "is_target": True,
                    "confidence": 0.86,
                    "evidence_pages": [1],
                    "evidence_text": ["alpha beta gamma"],
                    "reason": "contextual judgement",
                    "recommendation": "",
                    "needs_human_review": False,
                }

        client = FakeClient()
        pages = [CandidatePage(page_no=1, page_text="alpha beta gamma", text_length=16)]
        rag = RagContext(
            item_no="1",
            hits=[
                RagHit(
                    item_no="1",
                    source_type="criteria",
                    source_name="criteria.xlsx",
                    title="alpha",
                    category="criteria",
                    snippet="alpha beta gamma",
                )
            ],
        )

        rule_result = RuleReviewAgent(client).review("1", pages, rag)
        TableReviewAgent(client).review("11", pages, rag)
        AttachmentReviewAgent(client).review("99", pages, rag)
        LlmReviewAgent(client).review("5", pages, rag)

        self.assertFalse(rule_result.used_llm)
        self.assertEqual(client.roles, ["table", "attachment", "general"])

    def test_model_roles_map_to_environment_specific_models(self):
        from agents.llm_client import OpenAILowCostClient

        client = OpenAILowCostClient(
            api_key="test",
            low_model="low",
            escalate_model="strong",
            role_models={
                "rule": "rule-mini",
                "table": "table-strong",
                "attachment": "attach-mini",
                "general": "general-mini",
            },
        )

        self.assertEqual(client.model_for("rule", escalation=False), "rule-mini")
        self.assertEqual(client.model_for("table", escalation=False), "table-strong")
        self.assertEqual(client.model_for("missing", escalation=False), "low")
        self.assertEqual(client.model_for("rule", escalation=True), "strong")

    def test_llm_json_response_repairs_malformed_json_once(self):
        from agents.llm_client import OpenAILowCostClient

        class FakeClient(OpenAILowCostClient):
            def __init__(self):
                super().__init__(api_key="test")
                self.calls = 0

            def text_response(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return '{"result": "준수" "confidence": 0.9}'
                return '{"result": "준수", "confidence": 0.9}'

        client = FakeClient()

        self.assertEqual(client.json_response("system", "user")["result"], "준수")
        self.assertEqual(client.calls, 2)

    def test_rate_limit_wait_seconds_uses_api_retry_hint(self):
        from agents.llm_client import rate_limit_wait_seconds

        class FakeError:
            headers = {}

        wait = rate_limit_wait_seconds(
            FakeError(),
            "Rate limit reached. Please try again in 14.49s.",
            0,
        )

        self.assertGreaterEqual(wait, 15.0)
        self.assertLess(wait, 16.0)

    def test_item_fifteen_gpt_evidence_keeps_only_project_period_attachment_pages(self):
        from agents.attach_review_agent import validate_attachment_gpt_result
        from agents.models import ReviewResult

        review = ReviewResult(
            item_no="15",
            route_type="attachment_review",
            result="미준수",
            is_target=True,
            confidence=0.95,
            evidence_pages=[6, 74, 101],
            evidence_text=[
                "온라인 연수 시스템 현황",
                "본 사업은 소프트웨어 진흥법 제50조에 따른 과업심의위원회를 개최한 사업임",
                "소프트웨어사업 영향평가 결과서",
            ],
            reason="소프트웨어 개발사업 적정 사업기간 종합 산정서 첨부가 확인되지 않음",
            recommendation="소프트웨어 개발사업의 적정 사업기간 종합 산정서를 첨부하시기 바랍니다.",
            needs_human_review=False,
            source="openai_attachment",
            used_llm=True,
        )

        filtered = validate_attachment_gpt_result("15", review, [])

        self.assertEqual(filtered.evidence_pages, [])
        self.assertEqual(filtered.evidence_text, [])

    def test_llm_client_retries_transient_503_errors(self):
        import io
        import urllib.error
        from unittest.mock import patch

        from agents.llm_client import OpenAILowCostClient

        calls = []

        def fake_urlopen(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    url="https://api.openai.com/v1/responses",
                    code=503,
                    msg="Service Unavailable",
                    hdrs={},
                    fp=io.BytesIO(b"temporary upstream failure"),
                )
            return io.BytesIO(b'{"output_text":"ok"}')

        client = OpenAILowCostClient(api_key="test", max_retries=1)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("time.sleep") as sleep:
            response = client._post_json("https://api.openai.com/v1/responses", {"model": "test"})

        self.assertEqual(response["output_text"], "ok")
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once()

    def test_llm_client_retries_read_timeouts(self):
        import io
        from unittest.mock import patch

        from agents.llm_client import OpenAILowCostClient

        calls = []

        def fake_urlopen(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError("The read operation timed out")
            return io.BytesIO(b'{"output_text":"ok"}')

        client = OpenAILowCostClient(api_key="test", max_retries=1)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("time.sleep") as sleep:
            response = client._post_json("https://api.openai.com/v1/responses", {"model": "test"})

        self.assertEqual(response["output_text"], "ok")
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
