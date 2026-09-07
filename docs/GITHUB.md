# 개인 저장소에 게시하기

이 공개용 폴더 안에서 별도 Git 저장소를 생성합니다. 상위 Oracle_Project의 기존 origin이나 팀 저장소는 변경하지 않습니다.

대상 저장소는 `https://github.com/blueday98/CPU-GPU-Speed-Compare-by-RunPod`입니다.

아래 PowerShell 명령으로 게시합니다.

```powershell
cd C:\path\to\runpod-video-poc
git init -b main
git add README.md .gitignore NOTICE.md requirements-runpod.txt src benchmarks analysis tests docs evidence scripts
git diff --cached --stat
git diff --cached
git commit -m "Document OCI CPU and RunPod GPU video performance PoC"
git remote add origin https://github.com/blueday98/CPU-GPU-Speed-Compare-by-RunPod.git
git push -u origin main
```

`init`: 이 폴더를 새 저장소로 만듭니다.
`add`: 커밋에 담을 파일을 선택합니다.
`commit`: 현재 코드와 문서를 로컬 버전으로 저장합니다.
`remote add`: 업로드할 개인 GitHub 주소를 연결합니다.
`push`: 로컬 커밋을 GitHub에 올립니다.

원격이 이미 연결돼 있다면 `git remote -v`로 확인하고, 주소 변경이 필요할 때만 `git remote set-url origin 새주소`를 사용합니다.

원본 영상·개인정보·공유 토큰·SSH 키·모델 가중치·운영 주소·개인 PDF 학습 노트는 이 폴더에 넣지 않습니다. 사이트·Grafana 정식 실험은 미완료이므로 README에 표시된 한계를 유지해야 합니다.
