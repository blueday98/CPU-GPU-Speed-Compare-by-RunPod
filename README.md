# OCI CPU / RunPod GPU 영상 분석 성능 검증

동일한 두 영상을 OCI CPU와 RunPod RTX 2000 Ada GPU에서 처리하여 `video_analysis` 전체 시간을 비교한 격리 시험 기록이다. CPU 시험은 당시 운영 Worker 이미지의 격리 복사본에서 실행했으며 Runner's Feed 운영 작업 처리기, DB, Grafana는 변경하지 않았다.

## 결과

각 방식은 두 번 실행하고 중앙값을 사용했다. GPU 시간은 OCI의 영상 업로드, RunPod 분석·렌더링·NVENC 인코딩, 결과 다운로드를 포함한다.

| 입력 | 기존 OCI CPU | 개선 OCI CPU | OCI→RunPod GPU 왕복 | 기존 CPU 대비 GPU |
|---|---:|---:|---:|---:|
| 720p·60fps·255프레임 | 16.876초 | 12.670초 | 8.773초 | **48.01% 단축** |
| 720p·29.97fps·631프레임 | 83.351초 | 73.965초 | 17.461초 | **79.05% 단축** |

CPU 개선은 OpenCV 중간 영상을 제거하고 렌더링 프레임을 FFmpeg `libx264 veryfast CRF23`으로 직접 전달한다. GPU는 모델을 한 번만 적재하는 CUDA 프로세스와 `h264_nvenc p4 cq23`을 사용했다.

## 정확성

- CPU 기존/개선 방식의 자세 예측 JSON은 영상별로 완전히 동일했다.
- GPU 반복 실행 두 번의 자세 예측 JSON도 영상별로 완전히 동일했다.
- 60fps CPU/GPU 결과는 프레임과 인원 수가 같고 평균 관절 차이는 0.1425px였다.
- 29.97fps 입력은 631프레임 중 349번 프레임에서 CPU 2명, GPU 1명으로 달랐다. 이 차이는 미해결 문제로 기록한다.
- 출력은 H.264, yuv420p, 1280×720이며 원본 FPS와 프레임 수를 유지했다.
- CPU 출력은 `libx264 CRF23`, GPU 출력은 `h264_nvenc CQ23`이다. 두 품질 척도는 숫자가 같아도 동일 화질을 뜻하지 않으므로 화질 동등성은 아직 입증하지 않았다.

## 폴더

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

이 결과는 기술적 격리 시험이며 Runner's Feed 사이트나 Grafana에 정식 배포한 결과가 아니다. 특징값 계산과 코칭 리포트 생성도 포함하지 않는다. 운영 적용에는 조장 승인과 최신 작업 처리기 코드 기준의 정식 검토·배포가 필요하다.

CPU 격리 시험 이미지는 `sha-d3753fc9...`였고, 2026-09-07 확인한 운영 이미지는 `sha-6743f353...`였다. 최신 배포에는 `sehyeon-dcc2d7d` 플러그인이 포함됐지만, 품질 승인 전 보호 설정에 따라 실제 HPE 진입점은 기본 `coach/scripts/hpe/hpe.py`(SHA-256 `12e86ead...`)로 유지된다. 플러그인 HPE(공백 제외 비교)는 기본 HPE와 실행 내용이 동일하고 ONNX 가중치 해시도 일치하므로 기존 성능 시험이 다른 HPE 알고리즘을 사용한 것은 아니다. 그래도 최신 운영 이미지 자체를 대상으로 한 사이트·Grafana 최종 검증은 아직 완료되지 않았다.

모델 가중치, 원본 영상, 인증 토큰, SSH 키, 운영 주소는 저장소에 포함하지 않는다. 기반 코드와 모델을 공개할 때는 원본 저장소의 라이선스도 확인해야 한다.

개인 GitHub 게시 절차는 `docs/GITHUB.md`, 재현 조건은 `docs/REPRODUCE.md`에 정리했다. 코드 출처와 공개 범위는 `NOTICE.md`를 따른다.
