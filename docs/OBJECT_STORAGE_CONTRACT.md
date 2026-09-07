# Object Storage 기반 영상 분석 계약 v2 (설계 후보)

상태: 2단계 계약 정의. 운영 배포 또는 성능 검증 완료를 뜻하지 않는다.

## 확인한 처리 경계

2026-09-07 팀 저장소 로컬 체크아웃 `8a2ac7f`를 읽었다. 실행 중인 OCI 및 원격 최신 버전은 별도 확인 대상이다.

| 소비자 | 입력 | 출력 |
|---|---|---|
| RunPod 영상 분석 | 원본 영상, 고정 모델 | pose_predictions.json, details.json, rendered.mp4 |
| OCI feature_extract | 자세 JSON, details JSON, user_info.json | feature_results.json |
| OCI Agent | 피처, 논문, 프롬프트 | running_report.md |
| OCI report_adapter | 자세·details·피처 JSON, 선택적 코칭 문서 | report.json |
| OCI skeleton_adapter | 자세·details JSON | skeleton.json.gz |
| API·클라이언트 | 저장된 결과 영상 객체 | 만료되는 재생 URL |

근거: `coach/scripts/features/feature_extract.py`, `worker/coach_adapter/{report,skeleton}_adapter.py`, `coach/scripts/hpe/hpe.sh`, `worker/coach_tasks.py`, `api/app/main.py`.
후처리에 MP4 재렌더링은 없다. 플러그인의 show_video_frames는 현재 피처 경로에서 호출되지 않는다.

## 요청

JSON 필드:

- schema_version: `video-analysis-request-2.0`
- job_id: 서비스 Job ID. Celery task ID와 분리한다.
- attempt_id: 논리적 GPU 시도 ID. 동일 시도의 재전달에는 같은 값을 사용한다.
- model_id, model_release: 선택 모델과 불변 릴리스 식별자
- source_sha256, model_sha256: 비어 있지 않은 파일명→SHA-256 맵
- input: object_name, etag, bytes
- result_prefix: `jobs/{job_id}/video-analysis/{attempt_id}`
- transfer: OCI가 발급한 input_url과 predictions·details·video·manifest별 upload_urls. 모두 HTTPS OCI Object Storage URL이며 manifest에는 복사하지 않는다.

input 객체는 API가 소유권을 확인한 뒤 요청한다. RunPod은 OCI 도메인의 객체별 만료 URL만 사용하며 임의 호스트 URL은 거부한다. URL은 자격증명이므로 로그·manifest·DB·공개 증거에 저장하지 않는다. 사용자 키와 LLM 키는 OCI에 남는다.

## 완료 manifest

- schema_version: `video-analysis-manifest-2.0`
- status: `complete`
- 요청의 job_id, attempt_id, model_id, model_release, source_sha256, model_sha256, input을 그대로 포함
- input_sha256: RunPod이 ETag 고정 다운로드 후 계산한 원본 SHA-256
- objects: predictions, details, video 각각 object_name, sha256, bytes, content_type
- execution: device=`cuda`, gpu_name, provider=`CUDAExecutionProvider`
- timings_seconds: download, analysis, encode, upload, worker_total (0 이상 유한수)

파일명은 각각 pose_predictions.json, details.json, rendered.mp4로 고정한다. 영상은 H.264/yuv420p로 검증하고 해상도·FPS·프레임 수 및 원본과의 대응을 기록한다. 예측 JSON의 프레임 수와 영상 프레임 수는 항상 같다고 가정하지 않는다.

API는 HEAD로 얻은 ETag와 크기를 Job snapshot에 저장한다. RunPod은 `If-Match`로 같은 버전의 객체만 내려받고 SHA-256을 계산한다.

모든 파일 업로드·무결성 확인 후 `{result_prefix}/pose_manifest.json`을 마지막에 게시한다. manifest 존재만으로 성공을 확정하지 않고 스키마, 요청 일치, 실제 객체 SHA-256·크기, JSON 내용 및 영상 메타데이터를 검증한다. 첨부 검증 코드는 스키마와 요청 일치만 담당하며 저장소 접근/내용 검증은 다음 구현 단계다.

## 재시도와 완료 처리

1. 같은 Job의 재시도마다 새 attempt_id를 발급한다. 이전 산출물을 덮어쓰지 않는다.
2. 같은 시도의 중복 전달은 잠금/lease로 조정한다. 이미 검증된 manifest가 있으면 재사용한다.
3. OCI는 DB의 현재 attempt_id와 일치하는 완료만 조건부 갱신으로 수락한다. 늦은 완료·중복 callback이 후처리를 중복 발행하지 않도록 outbox 또는 동등한 복구 가능한 발행 구조를 사용한다.
4. 후처리에는 job_id와 manifest 객체 경로를 전달한다. 사용자 키는 Job 생성 시 저장한 snapshot을 사용한다.
5. 후처리 실패 시 승인된 manifest부터 재개한다. 전체 Job SUCCESS는 최종 결과 검증·등록 후에만 기록한다.
6. 실패·미완료 시도는 별도 보존 기간 후 정리한다. 기존 사용자 삭제/보존 정책에도 중간 객체를 포함한다.

RunPod Pod HTTP와 Serverless는 이 데이터 계약을 공유할 수 있다. 어느 배포 방식을 선택할지는 아직 확정하지 않았다. 콜백은 완료 힌트이며 인증과 현재 시도·실제 산출물 검증을 통과해야 한다. CPU fallback은 명시적으로 기록하며 GPU 성공으로 표시하지 않는다.

## 다음 구현 변경

- 후처리 전용 진입점: 기존 main.sh의 HPE 재실행 방지
- ObjectStorageGateway: 결과 JSON 다운로드 및 객체 검증 지원
- 최종 검증/업로드: 로컬 MP4 대신 검증된 객체 참조 지원
- 플러그인 Agent 어댑터: `/workspace/Coach/run`과 `/workspace/run` 경로 차이, 키·모델 설정 처리
- DB: 서비스 Job ID, 시도 ID, 원격 실행 ID, manifest 경로, 조건부 완료 및 단계별 재시도
- GPU 영상 메타데이터 검증, JSON 의미 검증, 동시 요청 격리

골든 승인과 모델 플러그인 활성화는 별도 배포 조건이다. 계약 작성은 승인 상태를 변경하지 않는다. 기존 벤치마크의 48~79% 단축을 새 Object Storage 경로의 측정값으로 사용하지 않는다.
