# Video analysis 처리시간 개선 결과

## 범위

- 입력은 `720p_60fps_crf18.mp4`와 `treadmill_30fps_720p.mp4` 두 개로 고정했다.
- CPU는 시험 당시 운영 Worker 이미지 `sha-d3753fc9...`의 격리 컨테이너에서 측정했다.
- GPU는 OCI 격리 폴더에서 RunPod RTX 2000 Ada API로 요청하고 업로드·분석·NVENC·다운로드 전체 왕복시간을 측정했다.
- 각 방식은 2회 실행했다.
- Runner’s Feed 운영 Worker, DB, Grafana에는 적용하지 않았다.
- 2026-09-07 현재 운영 이미지는 `sha-6743f353...`로 바뀌었다. 시험 당시와 현재 환경 모두 품질 승인 전 보호 설정으로 기본 `coach/scripts/hpe/hpe.py`(SHA-256 `12e86ead...`)를 실행한다. `sehyeon-dcc2d7d` 플러그인의 HPE는 공백 제외 비교에서 기본 HPE와 실행 내용이 동일하고 ONNX 가중치 해시도 일치한다. 아래 수치는 같은 HPE 실행 내용에 대한 격리 성능 자료지만, 최신 이미지 자체를 대상으로 한 사이트·Grafana 결과는 아니다.

## 처리시간

| 입력 | 기존 OCI CPU | 개선 OCI CPU | OCI→RunPod GPU 왕복 | 기존 CPU 대비 GPU | 개선 CPU 대비 GPU |
|---|---:|---:|---:|---:|---:|
| 720p·60fps, 255프레임 | 16.876초 | 12.670초 | 8.773초 | 48.01% 단축 | 30.75% 단축 |
| 720p·29.97fps, 631프레임 | 83.351초 | 73.965초 | 17.461초 | 79.05% 단축 | 76.39% 단축 |

CPU 개선은 OpenCV `mp4v` 중간 영상과 후속 재인코딩을 제거하고, 렌더링 프레임을 FFmpeg `libx264 veryfast CRF23`으로 직접 전달한 방식이다.

GPU는 모델을 한 번만 로드하는 persistent warm CUDA 프로세스와 `h264_nvenc p4 cq23`을 사용했다.

## GPU 내부 시간

| 입력 | GPU 분석 2회 | NVENC 2회 | 전체 왕복 2회 |
|---|---|---|---|
| 60fps | 2.826초, 2.866초 | 0.836초, 0.846초 | 8.648초, 8.899초 |
| 30fps | 10.658초, 10.530초 | 1.027초, 1.040초 | 17.760초, 17.162초 |

짧은 60fps 영상에서는 내부 GPU 처리보다 업로드·응답 준비·다운로드 오버헤드 비중이 크다.

## 결과 검증

- GPU 반복 실행 2회는 두 입력 모두 동일한 예측 SHA256을 생성했다.
- 모든 GPU 출력 영상은 H.264, yuv420p, 1280×720이었다.
- 60fps 출력은 255프레임·4.25초, 30fps 출력은 631프레임·21.054초였다.
- 60fps CPU/GPU는 결과 프레임과 인원 수가 모두 같았다. 평균 관절 차이는 약 0.142px이었다.
- 30fps CPU/GPU는 631개 결과 프레임을 모두 유지했지만 349번 프레임에서 CPU 2명, GPU 1명으로 달랐다.
- 30fps 평균 관절 차이는 약 0.416px이고 95백분위는 약 1.111px이지만 일부 관절에 큰 이상치가 있었다.

따라서 성능 단축은 확인했지만, 30fps 입력의 CPU/CUDA 경계 결과 차이는 해결 전 이슈로 남긴다.

CPU 후보의 `libx264 CRF23`과 GPU의 `h264_nvenc CQ23`은 이름이 비슷해도 동일한 화질 척도가 아니다. 이번 검증은 재생 가능 여부와 영상 메타데이터를 확인했지만 VMAF·SSIM 또는 블라인드 화질 비교는 하지 않았다. 따라서 “같은 출력 화질에서의 속도 비교”는 아직 별도 검증이 필요하다.

## 결론

격리 테스트 기준으로 `video_analysis` 전체 작업은 GPU가 개선 CPU보다도 30.75~76.39% 빨랐다. HPE 실행 내용은 현재 운영 기본 진입점과 동일하지만, 이것은 모델 플러그인의 공식 활성화나 Runner’s Feed 사이트·Grafana에 배포한 결과가 아니다. 기술적 성능 가능성 자료로 사용하고, 공식 전환 후 사이트에서 최종 확인한다.

세부 수치는 `../evidence/cpu_stream_final_evidence.json`과 `../evidence/cpu_gpu_video_analysis_final_evidence.json`, 반복 문제는 `ISSUES.md`에 보존했다.

## 운영 통합 검증

2026-09-08 KST에 팀 저장소 릴리스 `sha-adc592aabd1032b19dceeb965df89a05c50ec5a3`를 OCI에 배포하고 RunPod API의 `MODEL_RELEASE`도 같은 값으로 맞췄다. 사이트에서 `720p_60fps_crf18.mp4`를 사용한 작업 `44c9e8f8-2941-4e48-96e3-5a994b9d14c2`가 완료됐다.

| Grafana 항목 | 값 |
|---|---:|
| 작업 상태 | SUCCESS |
| 총 처리시간 | 24.6초 |
| 큐 대기시간 | 107.956ms |
| 가장 느린 단계 | `video_analysis` |
| `video_analysis` 처리시간 | 5.8초 |

이 결과는 격리 시험과 달리 실제 사이트, OCI API·DB·Celery, scoped signed URL 기반 Object Storage 전송, RunPod GPU 분석, OCI 후처리와 결과 표시를 모두 포함한다. 운영 Prometheus 지표도 완료 1건, 성공 1건, 실패 0건, 성공률 1.0, 평균 처리시간 24.630824초를 기록했다.

현재 운영 통합 표본은 1건이므로 위 값만으로 평균 성능을 확정하지 않는다. 다음 검증에서는 동일 영상 반복 실행과 30fps·긴 영상 표본을 추가해 총 처리시간, `video_analysis`, 네트워크·큐 오버헤드와 결과 품질을 함께 비교한다.

## 운영 안정화 결과

후속 팀 저장소 PR #26과 릴리스 `sha-0418518c7844fe6279f8f0761c8ba9c827cf60fe`에서 운영 배포의 Docker 디스크 guard와 멱등 systemd 동기화를 적용했다. 네 운영 timer가 모두 `enabled`·`active`이며, 새 Release workflow는 마지막 systemd 단계까지 전체 성공했다. RunPod API도 같은 릴리스 값으로 재기동한 뒤 GPU·CUDA provider와 `video-analysis-request-2.0` health를 확인했다.
