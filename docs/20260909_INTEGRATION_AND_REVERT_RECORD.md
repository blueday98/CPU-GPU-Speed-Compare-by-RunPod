# RunPod 연동·운영 오류·팀 저장소 revert 기록

작성: blueday98  
기록일: 2026-09-09 (KST)  
대상 작업: 2026-09-07~09-08의 구현·운영 시험과 팀 저장소 반영 정리

이 문서는 기존 README, HISTORY, RESULTS와 코드를 수정하지 않고 후속 경위를 추가한 기록이다. 기존 문서의 운영 성공 기록은 당시 배포에 대한 관측이며, revert 이후의 현재 운영 상태를 보증하지 않는다. 아래 PR 상태는 9월 8일 마지막 확인 기준이다.

## 1. 구현하고 확인한 내용

기존 클라이언트 업로드, Redis + Celery, OCI Object Storage 구조를 유지하면서 영상 분석을 RunPod과 연결했다. 최종적으로 정한 경계는 다음과 같다.

- RunPod은 HPE만이 아니라 검출·자세 추정·추적·렌더링·인코딩을 포함하는 전체 `video_analysis`를 처리한다.
- RunPod은 상시 Pod API를 사용한다. Serverless `/run`·`/status` 구조로 변경하지 않는다.
- 서비스 Job과 GPU attempt를 구분하고, 시도별 산출물과 완료 manifest 계약을 유지한다.
- RunPod은 `pose_predictions.json`, `details.json`, `output.mp4`를 Object Storage에 올린 다음 완료 manifest를 게시한다.
- OCI는 요청 전달, manifest·산출물 검증, 피처·점수·리포트 후처리, 최종 결과와 DB 상태 관리를 담당한다.
- Object Storage 접근에는 시도별 제한된 만료 URL을 사용한다. 인증 토큰이나 서명 URL 원문은 이 기록에 포함하지 않는다.

팀 Worker에는 GPU attempt 상태와 `gpu_dispatch`·`postprocess` 작업을 연결했고, 후처리가 HPE를 다시 실행하지 않는 경로를 구성했다. RunPod 시작 시 모델·소스 해시와 릴리스 일치를 확인하도록 했다.

실제 사이트에서 OCI 업로드 → RunPod 분석 → Object Storage 결과 게시 → OCI 후처리 → 완료 표시와 Grafana 계측까지 확인했다. 기존 HISTORY 22~24절에 기록된 성공 사례는 다음과 같다.

| 분석 이름 | 결과 | 총 처리시간 |
|---|---|---:|
| `runpod-e2e-adc592a` | SUCCESS | 24.6초 |
| `runpod-repeat-60fps-01` | SUCCESS | 24.8초 |
| `runpod-women-25fps-01` | SUCCESS | 18.8초 |
| `runpod-prorunner-30fps-38s-01` | SUCCESS | 44.1초 |

이는 해당 입력·릴리스의 성공 사례다. 모든 영상의 성공이나 모든 배포 상태의 정상 동작을 의미하지 않는다.

## 2. 팀 저장소에 반영했던 변경

대상: [Temu-F4/Runners_Feed](https://github.com/Temu-F4/Runners_Feed)

| PR | 반영 내용 |
|---|---|
| [#23](https://github.com/Temu-F4/Runners_Feed/pull/23) | Object Storage 기반 RunPod 영상 분석 파이프라인 통합 |
| [#24](https://github.com/Temu-F4/Runners_Feed/pull/24) | RunPod 프록시 요청의 명시적 User-Agent 추가 |
| [#25](https://github.com/Temu-F4/Runners_Feed/pull/25) | Job·attempt UUID 문자열 정규화 및 회귀 시험 |
| [#26](https://github.com/Temu-F4/Runners_Feed/pull/26) | systemd 동기화와 배포 전 디스크 점검 보강 |

이 네 PR이 팀 `main`에 병합되고 운영 검증에 사용됐다. 마지막 검증 릴리스는 `0418518c7844fe6279f8f0761c8ba9c827cf60fe`였다.

## 3. 발생한 문제와 확인 범위

- 초기 요청에서 `Object of type UUID is not JSON serializable`이 발생했다. RunPod 호출 전에 OCI 요청 JSON 생성이 실패한 문제로, #25에서 UUID를 문자열로 정규화했다.
- RunPod 프록시에서 HTTP 403 / error 1010이 발생해 요청 User-Agent를 보강했다.
- 릴리스가 맞지 않는 요청에서 409가 발생해 OCI와 RunPod의 `MODEL_RELEASE`를 맞추는 작업을 진행했다.
- OCI 디스크 사용률이 97%에 도달해 배포가 중단됐다. 미사용 Docker 자원 등을 정리한 뒤 약 17GB를 확보하고 배포를 재시도했다.
- systemd 동기화 권한 문제를 확인했다. 관리자 동기화 후 인증서 갱신·DB 백업·백업 검증·모델 품질 watchdog 타이머 네 개가 모두 `enabled`/`active`임을 확인했다.
- RunPod에서 8001 포트를 nginx가 이미 사용해 API 기동이 실패한 적이 있다. 포트를 조정하고 이후 API health에서 `video-analysis-request-2.0` 응답을 확인했다.

9월 8일 Grafana에서 추가로 확인한 실패는 다음과 같다. 시간은 KST이며, 이름은 원본 파일명이 아니라 등록된 분석 이름일 수 있다.

| 실행 시각 | 분석 이름 | 확인된 오류 | 해석과 남은 확인 |
|---|---|---|---|
| 05:45 | `runpod-e2e-c2ef40a` | UUID JSON 직렬화 TypeError | 위의 초기 요청 생성 오류 |
| 10:08 | `analysis-e85006996c6f` | RunPod HTTP 500 | 내부 예외의 정확한 원인은 RunPod 로그 추가 확인 필요 |
| 10:14 | `analysis-0b13225ebb4d` | RunPod HTTP 500 | Grafana의 `Internal Server Error`만으로 영상·모델·저장소 중 원인을 확정할 수 없음 |
| 10:51 | `IMG_1410` | `feature_extract` 실패 | 스트라이드 검출 실패와 값 `0, 0`, 무릎 각도 예외가 기록됨. 원본 영상과 자세 결과를 함께 확인해야 근본 원인 판단 가능 |
| 15:38~15:47 | `analysis-*` 7건 | 모두 FAILED, 약 1.2~1.3초 | 이 중 15:43·15:47 두 건에서 RunPod HTTP 404를 직접 확인. 나머지 다섯 건의 오류 메시지는 개별 확인하지 않음 |

404는 요청한 API 경로 또는 프록시 연결 상태 확인이 필요한 오류다. 실제 설정·서버 로그를 대조하지 않았으므로 정확한 원인이나 revert와의 인과관계는 확정하지 않는다. 자동 생성된 분석 이름만으로 업로더나 원본 영상도 확정하지 않는다.

## 4. 왜 revert했는가

팀 저장소에는 우선 브랜치로 제출하고 검토받아야 했는데, #23~#26을 `main`에 병합한 것이 협업 범위와 맞지 않아 네 PR의 변경을 되돌리기로 했다. 위의 운영 오류가 모두 revert의 직접 원인이었던 것은 아니다.

[#28](https://github.com/Temu-F4/Runners_Feed/pull/28)에서 해당 변경을 revert했고, 팀 `main`에 병합됐다. 당시 확인한 병합 커밋은 `0cb8727`이다.

revert는 과거 커밋과 PR을 삭제하는 작업이 아니라, 변경을 역으로 적용하는 새 커밋을 추가하는 방식이다. 따라서 구현·시험·오류 수정 이력은 남는다. 개인 저장소의 실험 코드와 기록은 유지했다.

또한 Git revert 자체가 OCI의 DB migration, 환경변수, systemd 설정, 실행 중인 컨테이너나 RunPod 프로세스를 모두 원복한다는 뜻은 아니다. 이 문서는 코드 이력의 revert를 기록하며, 운영 자원의 완전한 원복을 주장하지 않는다.

## 5. revert 이후 검토용 브랜치

revert 이후 `feature/blueday98-runpod-video-analysis` 브랜치에 검증했던 구현을 복원하고 [PR #29](https://github.com/Temu-F4/Runners_Feed/pull/29)를 만들었다. 전체 `video_analysis`, 상시 Pod API, GPU attempt·manifest 유지라는 세 결정을 PR에 설명했다.

9월 8일 마지막 확인에서 PR #29는 검사 6개를 통과한 미병합 PR이었다. PR 생성은 브랜치 코드의 운영 배포 또는 운영 재검증 완료를 뜻하지 않는다. 이 기록 추가 작업에서는 개인 저장소에 문서만 게시하며, 팀 저장소 병합이나 OCI·RunPod 배포는 수행하지 않는다.
