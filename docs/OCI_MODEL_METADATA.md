# OCI 모델 파일 확인 결과

확인 시각: 2026-09-07 (한국시간)

운영 서비스를 변경하지 않고 OCI 호스트의 모델 파일 메타데이터와 해시를 읽기 전용으로 확인했다.

## 확인 결과

| 모델 | 파일 내부 수정 시각(`mtime`, 한국시간) | OCI 파일 생성 시각(`birth`, 한국시간) | OCI 메타데이터 변경 시각(`ctime`, 한국시간) |
|---|---|---|---|
| RTMDet 사람 검출 | 2026-08-25 16:48:52 | 2026-08-26 01:17:55.724 | 2026-08-26 01:17:55.958 |
| RTMPose 자세 추정 | 2026-08-25 16:48:52 | 2026-08-26 01:18:02.083 | 2026-08-26 01:18:04.809 |

모델 최상위 폴더는 한국시간 2026-08-26 01:17:48.444에 생성됐다. 현재 메타데이터만 보면 두 모델은 이때 OCI에 배치된 뒤 다시 교체되지 않았다.

`mtime`은 원본 파일이 마지막으로 수정된 시각이며 복사 과정에서 보존될 수 있다. OCI에 실제로 배치된 시각은 이 경우 `birth`와 `ctime`이 더 직접적인 근거다. 다만 파일 시스템 메타데이터만으로 누가 어떤 배포 명령을 실행했는지는 알 수 없다.

## SHA-256

```text
dae7d98b247441ec4e408381c72087be5bbf325df939704bb978e21725a948ea  detector/end2end.onnx
f43e623a47dd21e465d1f4e7b3083e99c589cd4048958b152d650b27732e6946  pose/end2end.onnx
```

호스트와 실행 중인 작업 처리기 컨테이너에서 계산한 해시가 각각 동일했다. 컨테이너의 `/workspace/models`는 호스트의 `/home/ubuntu/runners-feed-runtime/models`를 읽기 전용(`RW=false`)으로 마운트한다.

## Runners_Feed 최신 모델 명세와 비교

2026-09-07 08:29:58+09:00의 Runners_Feed 커밋 `ed8eeb2726d810f51ded08817167796c41dce29f`에 포함된 `coach/model_plugins/sehyeon-dcc2d7d/model_manifest.json`과 비교했다.

- 모델 ID: `sehyeon-dcc2d7d`
- 알고리즘 버전: `dcc2d7d7a7eaacb8b2828745d31a5b375c5b893b`
- 검출 모델 명세 해시: OCI 해시와 일치
- 자세 모델 명세 해시: OCI 해시와 일치
- 결론: 최신 Runners_Feed 모델 명세가 요구하는 ONNX 가중치는 OCI와 작업 처리기에 반영되어 있다.
- 명세 표시 상태: `golden_status=pending_modeler_approval`.
- 실제 배포 차단 상태: `quality_baseline.json`의 `approval_status=pending_modeler_approval`. 배포 후보 검증 스크립트는 이 값이 `approved`가 아니면 중단한다.

ONNX 파일의 OCI 배치 시각이 8월 26일인 것과 최신 모델 명세 커밋이 9월 7일인 것은 모순이 아니다. 9월 7일 명세가 기존과 동일한 ONNX 해시를 지정하기 때문이다.

실제 작업 처리기의 `COACH_MODEL_ID`는 `sehyeon-dcc2d7d`였지만 `COACH_HPE_ENTRYPOINT=/app/coach/scripts/hpe/hpe.py`가 명시되어 있어 현재는 기본 HPE 파일을 실행한다. 기본 파일의 SHA-256은 `12e86ead...`다.

플러그인 HPE 파일도 이미지에 있으며 SHA-256은 `94e883a3...`다. 두 파일은 공백을 제외한 비교에서 실행 내용이 동일하다. 따라서 현재 성능 시험이 다른 HPE 알고리즘을 사용한 것은 아니지만, 플러그인 진입점의 공식 활성화가 끝났다고 표현해서는 안 된다.

재확인 코드는 `scripts/check_oci_model_metadata.sh`에 있다.

GitHub에서 내려받은 모델과 OCI·작업 처리기 모델을 한 번에 비교하려면 `scripts/verify_model_deployment.sh`를 사용한다. Git LFS 포인터만 내려받은 경우에는 검사를 중단하도록 했다.
