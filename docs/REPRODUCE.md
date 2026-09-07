# 실행 전제와 재현 범위

이 코드는 Python 3.12, CUDA가 가능한 ONNX Runtime, rtmlib, OpenCV, FastAPI, Uvicorn, python-multipart, FFmpeg/ffprobe를 사용한 실험에서 추출했습니다. NVENC 실행에는 이를 지원하는 GPU·드라이버·FFmpeg 빌드가 필요합니다. 모델과 원본 영상은 별도로 준비합니다.

`warm_engine.py`는 기반 파이프라인의 모델 초기화 부분을 AST로 제거해 모델을 재사용합니다. 지원하는 소스 구조가 아니면 실패하도록 설계했지만, 모델 인자까지 자동 동기화하지는 않습니다. 원본 코드 변경 후에는 정확성 검사를 다시 해야 합니다.

검사 명령 예시(Linux):

```bash
PYTHONPATH=src/runpod python -m unittest discover -s tests -v
```

RunPod용 Python 패키지는 CUDA·PyTorch가 준비된 이미지에서 설치합니다.

```bash
python -m pip install -r requirements-runpod.txt
```

API 시작 시 `COACH_CODE_ROOT`, `COACH_MODEL_ROOT`, `RUNPOD_SHARED_TOKEN`을 환경에 설정합니다. 토큰을 명령 기록이나 저장소에 넣지 않도록 직접 안전하게 입력하세요.

```bash
read -rsp '공유 토큰: ' RUNPOD_SHARED_TOKEN
echo
export RUNPOD_SHARED_TOKEN
export COACH_CODE_ROOT=/your/coach
export COACH_MODEL_ROOT=/your/models
export RUNPOD_FINAL_ENCODER=h264_nvenc
python -m uvicorn coach_video_analysis_api:app --app-dir src/runpod --host 127.0.0.1 --port 18001
```

OCI에서 RunPod까지의 전체 왕복시간을 재측정할 때는 주소와 시험 폴더를 환경변수로 전달합니다.

```bash
read -rsp '일회용 시험 토큰: ' RUNPOD_BENCHMARK_TOKEN
echo
export RUNPOD_BENCHMARK_TOKEN
export RUNPOD_VIDEO_ANALYSIS_ENDPOINT='https://YOUR_RUNPOD_HOST/v3/video-analysis'
export BENCHMARK_ROOT='/path/to/benchmark'
python benchmarks/run_oci_gpu_http_benchmark.py
unset RUNPOD_BENCHMARK_TOKEN
```

CPU 격리 시험 산출물을 증거 JSON으로 다시 만들려면 비공개 시험 폴더를 명시합니다.

```bash
python analysis/build_cpu_stream_evidence.py \
  --benchmark-root /path/to/cpu-benchmark
```

GPU 원시 결과에는 원본 영상에서 파생된 자세 JSON이 있으므로 공개 저장소에 넣지 않았습니다. 해당 비공개 폴더가 있을 때만 최종 비교 JSON을 재생성할 수 있습니다.

```bash
python analysis/compare_cpu_gpu_final.py \
  --gpu-root /path/to/gpu-http-results
```

OCI 모델의 배치 시각과 해시를 다시 확인하려면 확인 스크립트를 SSH 표준입력으로 실행합니다. 아래 주소와 개인키 경로는 자신의 환경에 맞게 지정합니다.

```bash
ssh -i /path/to/private_key user@oci-host 'bash -s' \
  < scripts/check_oci_model_metadata.sh
```

이 명령은 격리된 로컬 서버 예시입니다. 기존 운영 API를 교체하는 명령이 아닙니다. GPU 클라이언트는 파일·소스·모델 해시 계약에 맞는 multipart POST를 보내야 합니다.

`benchmarks`의 경로와 기준 해시는 당시 4.25초 영상에 고정돼 있습니다. 다른 영상에서는 경로와 기대 결과를 새로 정의해야 하며 기존 수치를 그대로 재현한다고 가정하지 않습니다.

다음 단계에서 반드시 확인할 항목:

- CPU/GPU가 같은 입력 SHA256과 분석 소스·모델을 사용하는지.
- 최신 소스에서 warm 실행의 예측 결과가 일반 실행과 일치하는지.
- Worker가 실제 RunPod 경로를 호출하고 작업별 증거를 저장하는지.
- 최종 영상의 프레임 수·FPS·재생·시각적 품질.
- 동일 영상으로 실제 사이트 CPU/GPU 전체 처리시간.
- 현재 운영 이미지·구성의 복구 가능성과 동시 배포 여부.
