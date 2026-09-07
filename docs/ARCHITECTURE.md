# 실험 아키텍처와 측정 경계

## 운영 CPU 경로

```text
브라우저
→ Runner's Feed API
→ Object Storage
→ Redis 작업 큐
→ Celery Worker
→ 영상 분석
→ 피처 계산
→ 코칭 리포트
→ 결과 업로드
```

Grafana 총 처리시간은 Worker가 `PROCESSING`을 기록한 시점부터 결과 업로드 후 `SUCCESS`를 기록한 시점까지다. 브라우저 업로드, 큐 대기, 사용자 다운로드는 포함하지 않는다.

## 초기 GPU 추론 전용 경로

```text
OCI Worker
→ 영상 또는 프레임을 HTTPS로 RunPod에 전송
→ CUDA 사람 검출·자세 추정
→ 포즈 JSON 반환
→ OCI에서 렌더링·합성·피처·리포트 계속 수행
```

이 방식은 HPE는 빨라지지만 나머지 병목이 OCI에 남는다.

## 최종 격리 영상 분석 경로

```text
OCI 시험 클라이언트
→ 고정 MP4 업로드
→ RunPod의 warm CUDA 모델
→ 프레임 디코딩
→ 사람 검출·자세 추정·추적
→ 프레임 렌더링
→ NVENC H.264 인코딩
→ 결과 ZIP 다운로드
```

최종 GPU 왕복시간은 이 전체 구간을 포함한다. 피처 계산과 LLM 코칭 리포트는 포함하지 않는다.

## 포트 8000의 역할

- Pod 내부 API가 `0.0.0.0:8000`에서 요청 대기
- RunPod 콘솔에서 8000번 HTTP 포트를 외부 HTTPS 주소로 노출
- 8888번은 Jupyter용이며 GPU API와 별개
- 공유 토큰으로 무단 요청 차단
- `/health`는 모델 서버 준비 여부를 확인

Pod의 영구 볼륨에는 코드·모델·가상환경이 남지만, Pod를 다시 켜도 API 프로세스는 자동으로 시작되지 않을 수 있다. 시작 스크립트나 서비스 관리가 필요하다.

## CPU 영상 경로 개선

기존:

```text
렌더링 프레임
→ OpenCV mp4v 중간 영상
→ 다시 읽기
→ FFmpeg libx264 최종 영상
```

후보:

```text
렌더링 프레임
→ FFmpeg 표준입력
→ libx264 최종 영상 한 번 생성
```

## GPU 영상 경로 개선

```text
CUDA 추론
→ CPU 기반 스켈레톤 그리기
→ NVENC H.264 인코딩
```

스켈레톤 그리기 자체가 자동으로 GPU 가속되는 것은 아니다. GPU의 확실한 역할은 ONNX CUDA 추론과 NVENC 인코딩이다.
