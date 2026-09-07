# 최신 모델 버전과 OCI 반영 확인

## 전달 관계

```text
모델 담당자 저장소
Oracle_Project/sehyeon@dcc2d7d7a7eaacb8b2828745d31a5b375c5b893b
        ↓
팀 Runners_Feed 통합 커밋
ed8eeb2726d810f51ded08817167796c41dce29f
        ↓
OCI Worker 이미지 태그
sha-6743f3534519c93b2e6a96b6ed44f91ac0fb6cbf
```

## 모델 가중치

| 모델 | 최신 명세 SHA-256 | OCI·Worker 판정 |
|---|---|---|
| RTMDet | `dae7d98b247441ec4e408381c72087be5bbf325df939704bb978e21725a948ea` | 일치 |
| RTMPose | `f43e623a47dd21e465d1f4e7b3083e99c589cd4048958b152d650b27732e6946` | 일치 |

ONNX 파일은 Git 저장소에 포함되지 않고 OCI의 런타임 모델 폴더에 별도로 배치된다. Worker는 이를 `/workspace/models`에 읽기 전용으로 마운트한다.

OCI 파일의 생성 시각은 2026-08-26 01:17~01:18 KST이고, 2026-09-07에 통합된 최신 명세가 같은 해시를 요구한다. 파일이 8월에 배치됐다는 이유만으로 구버전인 것은 아니다.

## 현재 진입점

```ini
COACH_MODEL_ID=sehyeon-dcc2d7d
COACH_HPE_ENTRYPOINT=/app/coach/scripts/hpe/hpe.py
COACH_FEATURE_ENTRYPOINT=/app/coach/scripts/features/feature_extract.py
COACH_AGENT_ENTRYPOINT=/app/coach/scripts/Agent/Running_coach.py
```

플러그인은 이미지 안에 있지만 기본 진입점이 명시되어 있어 현재 작업은 기본 경로를 실행한다.

- 기본 HPE와 플러그인 HPE: 공백 제외 동일
- 기본 피처와 플러그인 피처: 공백 제외 동일
- 기본 리포트와 플러그인 리포트: 실행 인자, API 키 탐색, LLM 모델 설정이 다름

## 골든 품질 상태

```text
model_manifest.json: golden_status=pending_modeler_approval
quality_baseline.json: approval_status=pending_modeler_approval
```

실제 후보 배포 스크립트는 `approval_status`가 `approved`가 아니면 중단한다. 현재 기준은 `feature1`, 추적률 0.5, 처리시간 3600초, 값 범위 0~1뿐이어서 완성된 피처 품질 계약으로 보기 어렵다.

피처 구현 완료, 동일 골든 입력 최소 3회 실행, 결과·추적률·처리시간 검토, 모델 담당자 승인, PR 검토 후에만 플러그인 진입점을 전환해야 한다.

## 확인 코드

- `scripts/check_oci_model_metadata.sh`: OCI 모델 파일 시각과 해시
- `scripts/verify_model_deployment.sh`: GitHub·OCI·Worker 모델 해시 비교
- `scripts/check_oci_active_model.sh`: 실제 선택 모델과 HPE 해시
- `scripts/check_oci_model_release.sh`: 이미지·환경·진입점·명세 확인
