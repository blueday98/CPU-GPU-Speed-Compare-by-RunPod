# OCI CPU / RunPod GPU 영상 분석 성능 검증

동일 영상을 OCI CPU와 RunPod RTX 2000 Ada GPU에서 처리해 `video_analysis` 시간을 비교하고, 이후 Runner's Feed 운영 사이트에 Object Storage 기반 GPU 경로를 적용한 기록이다. 격리 성능 시험과 실제 운영 통합 결과를 구분해 보존한다.

## 결과

각 방식은 두 번 실행하고 중앙값을 사용했다. GPU 시간은 OCI의 영상 업로드, RunPod 분석·렌더링·NVENC 인코딩, 결과 다운로드를 포함한다.

| 입력 | 기존 OCI CPU | 개선 OCI CPU | OCI→RunPod GPU 왕복 | 기존 CPU 대비 GPU |
|---|---:|---:|---:|---:|
| 720p·60fps·255프레임 | 16.876초 | 12.670초 | 8.773초 | **48.01% 단축** |
| 720p·29.97fps·631프레임 | 83.351초 | 73.965초 | 17.461초 | **79.05% 단축** |

CPU 개선은 OpenCV 중간 영상을 제거하고 렌더링 프레임을 FFmpeg `libx264 veryfast CRF23`으로 직접 전달한다. GPU는 모델을 한 번만 적재하는 CUDA 프로세스와 `h264_nvenc p4 cq23`을 사용했다.

## 운영 통합 현황

2026-09-08 팀 저장소 릴리스 `sha-0418518c7844fe6279f8f0761c8ba9c827cf60fe`에서 OCI API·DB·Celery, scoped signed URL 기반 Object Storage 전송, RunPod 전체 `video_analysis`, OCI 후처리와 사이트 결과 표시를 연결했다. RunPod은 NVIDIA RTX 2000 Ada와 `CUDAExecutionProvider`를 사용하며 `GPU_DISPATCH_CONCURRENCY=1`로 순차 측정했다.

| 운영 입력 | 결과 | 총 처리시간 | 큐 대기 | 확인된 병목 |
|---|---|---:|---:|---|
| 동일 720p·60fps·255프레임 반복 | SUCCESS | 24.8초 | 111.164ms | `video_analysis` 4.8초 |
| 720p·25fps·136프레임 | SUCCESS | 18.8초 | 45.934ms | 입력 다운로드 3.0초 |
| 720p·30fps·1,105프레임·36.83초 | SUCCESS | 44.1초 | 34.492ms | `video_analysis` 17.6초 |

새 릴리스 운영 표본 세 건은 모두 성공했고 평균 처리시간은 약 29.22초였다. 동일 60fps 입력의 이전 24.6초와 반복 24.8초 차이는 약 0.8%였다. 세부 Job ID와 장애·복구 이력은 [실험 전체 이력](docs/PROJECT_HISTORY.md), 단계별 결과는 [상세 결과](docs/RESULTS.md)에 기록했다.

팀 저장소 반영은 다음 PR에서 확인할 수 있다.

- [#23 Object Storage 기반 RunPod 영상 분석 파이프라인](https://github.com/Temu-F4/Runners_Feed/pull/23)
- [#24 RunPod 프록시 User-Agent 적용](https://github.com/Temu-F4/Runners_Feed/pull/24)
- [#25 GPU 계약 UUID 문자열 정규화](https://github.com/Temu-F4/Runners_Feed/pull/25)
- [#26 systemd 멱등 동기화와 운영 디스크 보호](https://github.com/Temu-F4/Runners_Feed/pull/26)

## 정확성

- CPU 기존/개선 방식의 자세 예측 JSON은 영상별로 완전히 동일했다.
- GPU 반복 실행 두 번의 자세 예측 JSON도 영상별로 완전히 동일했다.
- 60fps CPU/GPU 결과는 프레임과 인원 수가 같고 평균 관절 차이는 0.1425px였다.
- 29.97fps 입력은 631프레임 중 349번 프레임에서 CPU 2명, GPU 1명으로 달랐다. 이 차이는 미해결 문제로 기록한다.
- 출력은 H.264, yuv420p, 1280×720이며 원본 FPS와 프레임 수를 유지했다.
- CPU 출력은 `libx264 CRF23`, GPU 출력은 `h264_nvenc CQ23`이다. 두 품질 척도는 숫자가 같아도 동일 화질을 뜻하지 않으므로 화질 동등성은 아직 입증하지 않았다.

## 폴더

후속 구현: [후처리 전용 실행과 Object Storage 연결](docs/POSTPROCESS_IMPLEMENTATION.md). 이 후보를 기준으로 팀 저장소 운영 경로를 구현하고 사이트 통합 검증까지 완료했다.

RunPod 게시 경로: [Object Storage API](docs/RUNPOD_STORAGE_API.md). warm CUDA 분석과 NVENC 결과를 계약 v2 manifest로 게시한다.

OCI 요청 경로: [OCI→RunPod dispatcher](docs/OCI_DISPATCHER.md). 서비스 Job과 GPU 시도를 분리하고 일치하는 manifest 응답만 후처리로 넘긴다.

정식 통합 설계: [Object Storage 기반 요청·manifest 계약 v2](docs/OBJECT_STORAGE_CONTRACT.md). 격리 성능 수치와 운영 측정값은 포함 범위가 다르므로 직접 같은 값으로 취급하지 않는다.

- `src/cpu`: CPU 직접 스트리밍 후보 코드
- `src/runpod`: RunPod 분석 API, 계약 검증, warm 모델 프로세스
- `benchmarks`: CPU 격리 시험과 OCI→RunPod 왕복 측정
- `analysis`: 증거 생성과 CPU/GPU 자세 결과 비교
- `evidence`: 비밀정보를 제외한 원본 측정 JSON
- `tests`: warm 모델 상태 초기화와 오류 처리 검사
- `requirements-runpod.txt`: CUDA·PyTorch 이미지에 추가할 API 실행 패키지
- `scripts`: OCI 모델 메타데이터 확인 코드
- `docs/RESULTS.md`: 상세 결과
- `docs/PROJECT_HISTORY.md`: 처음부터 최종 검증까지의 전체 실험 이력
- `docs/MEASUREMENT_CATALOG.md`: 측정값별 포함 범위와 유효성
- `docs/ARCHITECTURE.md`: 운영·초기 GPU·최종 격리 경로의 차이
- `docs/ISSUES.md`: GitHub Issue 초안
- `docs/MODEL_RELEASE.md`: 모델 담당자→팀 저장소→OCI 배포 추적
- `docs/OCI_MODEL_METADATA.md`: OCI 모델 배치 시각과 해시
- `docs/LEARNINGS.md`: 반복 작업에서 확인한 시행착오
- `docs/SOURCE_NOTES_POLICY.md`: 개인 학습 노트의 공개 범위
- `docs/TEAM_LEAD_CHECKLIST.md`: 운영 적용 전 조장 확인 사항

## 한계

상단 CPU/GPU 직접 비교 수치는 기술적 격리 시험이고, 운영 통합 표의 시간은 사이트·Object Storage·DB·큐·후처리를 포함한다. 두 범위의 수치를 동일한 벤치마크로 직접 비교하면 안 된다. 현재 사이트 베타는 완료 여부만 노출하며 측정값과 코칭 결과는 품질 승인 후 제공할 예정이다.

CPU 격리 시험 이미지는 `sha-d3753fc9...`였고 현재 운영 통합 검증 릴리스는 `sha-0418518...`이다. 배포에는 `sehyeon-dcc2d7d` 플러그인이 포함됐지만, 품질 승인 전 보호 설정에 따라 실제 HPE 진입점은 기본 경로를 유지한다. 플러그인 HPE는 공백 제외 비교에서 기본 HPE와 실행 내용이 동일하고 ONNX 가중치 해시도 일치한다. 모델 골든 품질 승인과 25fps·30fps 입력의 CPU/GPU 결과 동일성 평가는 별도 과제로 남아 있다.

모델 가중치, 원본 영상, 인증 토큰과 SSH 키는 저장소에 포함하지 않는다. 기반 코드와 모델을 공개할 때는 원본 저장소의 라이선스도 확인해야 한다.

개인 GitHub 게시 절차는 `docs/GITHUB.md`, 재현 조건은 `docs/REPRODUCE.md`에 정리했다. 코드 출처와 공개 범위는 `NOTICE.md`를 따른다.


## 2026-09-10 팀 저장소 후속 반영과 결론

초기 Object Storage 기반 RunPod 통합 변경은 팀의 브랜치 운영 원칙보다 먼저 `main`에 병합되어 [PR #28](https://github.com/Temu-F4/Runners_Feed/pull/28)에서 revert했다. 이 revert는 구현 방향을 폐기한 것이 아니라, 검토와 적용 순서를 다시 맞추기 위해 운영 브랜치에서 변경을 회수한 것이다.

이후 RunPod이 전체 `video_analysis`를 처리하고 OCI가 작업 조정·후처리·결과 제공을 담당한다는 경계를 유지하면서, 상시 Pod용 비동기 영상 분석 서버를 `feature/blueday98-runpod-async-server` 브랜치에 다시 구현했다.

내가 작성한 주요 기능은 다음과 같다.

- `POST /v4/storage-video-analysis` 작업 등록과 HTTP 202 응답
- `remote_job_id` 기반 비동기 polling 및 `queued`·`running`·`complete`·`failed` 상태 계약
- 동일 `attempt_id` 재전달 시 기존 작업을 재사용하는 중복 추론 방지
- SQLite 기반 작업 상태 보존과 Bearer token 인증
- HPE·추적·보간·렌더링 및 NVENC H.264 변환
- OCI Object Storage 산출물 업로드와 CUDA·모델 release 증거를 포함한 manifest 생성

해당 구현은 `aca584a`(`feat: add async RunPod video analysis server`)와 `c51a3f5`(`Add README for RunPod video analysis server`)로 확인할 수 있으며, [PR #34](https://github.com/Temu-F4/Runners_Feed/pull/34)를 통해 팀 저장소 `main`에 정식 병합됐다.

병합 이후 팀원들은 GPU attempt·DB 상태 계약, model canary, RunPod polling 간격, 모델 통합 및 rtmlib 호환성을 후속 보완했다. 특히 polling 단축은 [PR #39](https://github.com/Temu-F4/Runners_Feed/pull/39), RunPod hardening은 [PR #33](https://github.com/Temu-F4/Runners_Feed/pull/33), 후속 모델·호환성 보완은 PR #40~#43의 팀 작업으로 이어졌다. 이 후속 변경 전체를 내가 단독으로 구현한 것으로 보지 않는다.

최종적으로 실제 앱의 목표 경로는 다음과 같다.

`모바일 앱 → OCI API·Celery → RunPod 비동기 video_analysis → OCI Object Storage manifest → OCI 후처리 → 모바일 결과`

**결론:** 초기 통합은 적용 절차 문제로 revert했지만, 성능 시험에서 정한 구조를 비동기 RunPod 영상 분석 서버로 다시 구현했고 그 코드가 PR #34를 통해 팀 저장소에 정식 반영됐다. 따라서 이 작업의 핵심 성과는 단순한 CPU·GPU 속도 비교가 아니라, 전체 `video_analysis`를 RunPod GPU로 분리하는 설계·성능 검증·비동기 서버 구현을 실제 팀 통합의 기반으로 연결한 것이다. 운영 안정화와 후속 모델 변경은 이후 팀 공동 작업으로 완성됐다.
