# OCI → RunPod dispatcher 후보

`src/oci/runpod_dispatcher.py`는 기존 클라이언트·API 업로드 흐름 이후에 사용한다. API가 소유권과 입력 객체를 확인해 DB에 Job을 만든 뒤, 별도 Celery 작업이 DB의 입력 snapshot과 고정된 모델 해시로 계약 v2 요청을 만든다.

현재 구현은 이미 검증한 RunPod Pod HTTPS API용 동기 transport다. 응답의 Job ID, attempt ID, manifest 경로가 요청과 일치할 때만 반환한다. 토큰은 HTTP Authorization 헤더에만 넣고 payload·결과·공개 증거에는 넣지 않는다. 자동 POST 재시도는 하지 않는다. 재시도 여부와 새 attempt ID 발급은 DB 상태를 가진 Celery 계층이 결정해야 하기 때문이다.

팀 저장소 통합 시 예상 흐름:

```text
API create_job
→ DB에 서비스 job_id 저장
→ gpu_dispatch 큐에 dispatch_video_analysis(job_id)
→ DB에서 입력·키·모델 snapshot 조회 및 attempt_id 조건부 생성
→ 입력 ObjectRead URL과 시도별 산출물 ObjectWrite URL 4개를 짧은 TTL로 생성
→ RunPodPodClient.submit
→ 응답 manifest 경로를 현재 attempt에 조건부 저장
→ postprocess 큐에 run_postprocess(job_id, attempt_id, manifest_object)
```

기존 `coach.run_object_storage`처럼 `self.request.id`를 서비스 Job ID로 사용하면 분리된 task마다 ID가 달라진다. 서비스 Job ID를 인자로 전달하고 Celery task ID·RunPod 원격 ID는 별도 추적 필드에 둔다.

Pod transport는 요청 처리 동안 dispatcher 프로세스를 점유한다. `coach` 후처리 큐와 분리한 `gpu_dispatch` 큐를 사용해야 한다. Serverless 전환 시에는 `/run`이 돌려준 원격 Job ID를 저장하고 callback 또는 상태 수집 task가 같은 완료 검증을 수행하는 비동기 transport로 교체한다. 저장소 계약과 후처리는 그대로 유지한다.

2026-09-07 격리된 팀 저장소 worktree에는 입력 ETag·크기 snapshot과 `inference_gpu_attempts` migration, `gpu_dispatch`·`postprocess` Celery 큐, 후처리 전용 진입점까지 통합 후보를 작성했다. RunPod 완료는 manifest가 요청과 일치할 때만 SUCCESS attempt로 수락하며, OCI 후처리는 그 성공 attempt를 다시 조회한 뒤 실행한다. 아직 팀 저장소 배포·OCI migration 적용·실제 Object Storage 왕복은 하지 않았다.

RunPod에는 OCI config나 API 개인키를 두지 않는다. OCI Worker의 기존 Object Storage 권한으로 객체별 PAR을 만들고, RunPod은 `*.oraclecloud.com` HTTPS URL만 허용한다. 만료 URL은 전송 envelope에만 존재하며 완료 manifest와 DB 결과에는 포함하지 않는다.
