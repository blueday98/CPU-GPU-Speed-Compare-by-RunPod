# 3단계: 후처리 전용 실행 및 Object Storage 연동

`src/cpu/storage_postprocess.py`는 신뢰된 dispatcher 요청 snapshot과 결과 manifest를 대조하고 OCI 결과 버킷에서 산출물을 읽는다. 전체 HPE 스크립트를 실행하지 않고 feature → 계약 검증 → 선택적 Agent → report adapter → skeleton adapter를 호출한다.

사용 조건: Python 3.11+, OCI SDK 및 팀 Worker의 피처/리포트 의존성, FFprobe, 팀 코드와 서비스 어댑터. 기존 Worker 이미지의 OCI SDK를 재사용할 수 있다. 이 저장소만으로 모델 피처 코드가 제공되는 것은 아니다.

```bash
python src/cpu/storage_postprocess.py \
  --request /private/trusted-dispatch-request.json \
  --height-m 1.75 \
  --coach-root /app/coach \
  --adapter-root /app/coach_adapter \
  --feature-entry /app/coach/scripts/features/feature_extract.py \
  --agent-entry /app/coach/scripts/Agent/Running_coach.py
```

환경: OCI_CONFIG_FILE, 선택적 OCI_CONFIG_PROFILE, OCI_NAMESPACE, OCI_RESULTS_BUCKET. 키 파일이나 요청 원문을 Git에 넣지 않는다. height는 신뢰된 DB의 Job snapshot에서 가져온다. CLI는 통합 전 수동 실행용이며 외부 요청을 그대로 전달하면 안 된다.

## 실제 동작

- manifest 스키마·시도·모델·해시 계약을 확인한다.
- 파일별 크기와 실제 SHA-256을 확인한다. manifest 1MiB, 개별 산출물 512MiB 상한을 적용한다.
- 자세/영상 정보 JSON과 H.264/yuv420p·해상도·FPS·디코딩 프레임 수를 검증한다.
- 영상은 검증을 위해 임시 다운로드한다. 검증 후 삭제하고 후처리 결과에는 원래 Object Storage 경로를 사용한다. 영상 재인코딩·재업로드는 없다.
- 매 실행은 별도 임시 작업 폴더와 별도 후처리 업로드 prefix를 사용한다. 실패 후 같은 GPU manifest로 재실행할 수 있다.
- 피처·리포트·스켈레톤 검증 후 업로드하고 결과 객체 참조를 반환한다. DB SUCCESS는 이 코드가 기록하지 않는다.

이 구현은 영상 다운로드 자체를 없앤 상태가 아니다. 원격 객체의 실제 바이트 무결성과 영상 메타데이터 검증을 우선 구현했다. 이후 GPU 측 검증 증거·불변 객체 보장을 갖춘 뒤 다운로드 생략을 검토한다. 새 경로 성능은 별도 측정해야 한다.

## 통합 시 남은 작업

- Celery dispatcher 및 현재 시도 DB 조건부 갱신, 중복 발행 방지, 실패 객체 정리 정책
- RunPod v2 산출물/manifest 게시자 연결
- 승인된 플러그인과 서비스 어댑터 선택·해시 고정. 원본 플러그인 Agent의 Coach/run 경로는 이 CLI와 호환되지 않으므로 그대로 선택하면 안 된다.
- 실제 OCI 객체, 실제 피처/Agent/FFprobe를 사용한 통합 검증
- 이미지 배포와 사이트/Grafana 검증

단위 테스트는 메모리 Object Storage와 가짜 산출물로 무결성 차단·영상 참조 재사용·실패 재개·HPE 미호출을 검증한다. 실제 OCI 및 모델 실행 성공을 뜻하지 않는다.
