# RFP Legal Review Agent

RFP 법제도 검토 오케스트레이션 에이전트입니다. `agents/`, `db/`, `tools/`를 백엔드로 배포하고, UI에서는 `/api/review`를 호출해 검토 결과를 JSON으로 표시합니다.

## Local Run

1. `.env.example`을 참고해 로컬 `.env`를 만듭니다.
2. 의존성을 설치합니다.

```bash
pip install -r requirements.txt
```

3. API 서버를 실행합니다.

```bash
uvicorn api.main:app --reload
```

4. 상태 확인:

```text
GET http://127.0.0.1:8000/health
```

## API

### UI JSON Review

```text
POST /api/review
```

Form fields:

- `file`: RFP PDF file
- `items`: optional comma-separated item numbers, for example `1,2,3`

Response shape:

```json
{
  "document_id": 1,
  "parse_status": "ok",
  "audit_score": 100,
  "results": [
    {
      "item_no": "1",
      "law_name": null,
      "review_result": "준수",
      "final_status": "검토 완료",
      "confidence": 0.9,
      "reason": "검토 사유",
      "recommendation": "권고내용",
      "compliance_content": "최종 준수 검토 내용"
    }
  ]
}
```

### Excel Review

```text
POST /review
```

Set `return_excel=true` to download the Excel report. Set `return_excel=false` to receive the original detailed pipeline JSON.

## Deployment

Render 배포용 `render.yaml`을 포함했습니다. Render에서 이 GitHub 저장소를 연결한 뒤 `OPENAI_API_KEY`를 환경변수로 등록하면 됩니다.

GitHub에는 `.env`, 산출물, 고객 자료, 로컬 DB 백업 파일을 올리지 마세요. 필요한 운영 DB는 배포 환경에 별도로 안전하게 업로드하거나 managed storage로 분리하는 것을 권장합니다.
