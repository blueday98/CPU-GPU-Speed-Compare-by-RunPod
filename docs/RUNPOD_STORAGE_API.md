# RunPod Object Storage API 후보

`src/runpod/coach_storage_video_analysis_api.py`는 계약 v2 요청을 받아 기존 warm CUDA 모델로 HPE를 실행하고 NVENC H.264 영상을 생성한다. 원본은 OCI raw bucket에서 받고, 자세 JSON·영상 정보 JSON·완성 영상을 results bucket에 올린 뒤 manifest를 마지막에 게시한다.

RunPod을 켜기 전까지는 GPU·OCI 통합 성공을 주장하지 않는다. 기존 ZIP 반환 API 및 벤치마크 증거는 변경하지 않았다.

필요 환경변수:

- RUNPOD_SHARED_TOKEN
- COACH_CODE_ROOT, COACH_MODEL_ROOT, MODEL_RELEASE
- 선택적 VIDEO_ANALYSIS_TIMEOUT

RunPod에는 OCI config나 API 개인키를 배치하지 않는다. OCI dispatcher가 attempt마다 입력 ObjectRead URL과 산출물 4개의 ObjectWrite URL을 짧은 TTL로 발급한다. URL은 요청의 `transfer` envelope에만 포함하고 manifest·DB·로그·공개 증거에는 저장하지 않는다.

```bash
python -m uvicorn coach_storage_video_analysis_api:app \
  --app-dir src/runpod --host 0.0.0.0 --port 8000
```

요청은 `docs/OBJECT_STORAGE_CONTRACT.md`의 JSON 객체다. API는 완료된 manifest 경로만 응답하며 파일 자체를 HTTP로 반환하지 않는다. 한 프로세스는 GPU 작업 하나만 실행한다. 동시 처리량은 GPU 하나를 공유하는 동시 handler보다 독립 Worker 수로 확장한다.

API는 시작할 때 `COACH_CODE_ROOT/model_manifest.json`을 읽고 HPE 소스 3개와 선언된 모든 ONNX 가중치의 실제 SHA-256을 계산한다. 가중치가 manifest와 다르면 서버가 시작되지 않는다. 각 요청의 model ID, image release, source hash, model hash가 이 시작 시 증거와 정확히 일치하지 않아도 분석 전에 거부한다.

실제 시험에서는 다음을 확인한다.

1. `/health`의 CUDA provider와 GPU 이름
2. 입력·소스·모델 해시 일치
3. 세 산출물의 OCI 객체 해시와 크기
4. manifest가 마지막에 생성되는지
5. OCI 후처리가 manifest부터 재개되는지
6. 사이트 결과 영상·리포트와 Grafana 시간

현재 후보는 동일 attempt의 동시 중복 실행을 프로세스 잠금으로만 막는다. 여러 Worker에 같은 attempt가 전달되지 않도록 dispatcher의 현재 시도 조건부 갱신과 RunPod 작업 ID 저장이 필요하다.
