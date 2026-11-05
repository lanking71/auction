# Aucton

Windows용 옥션 자동입찰 도구입니다. 정밀 모드는 가격을 미리 확정하는 **고정가 입찰에만** 적용됩니다. 100µs는 내부 스케줄러의 목표 해상도이며 Windows, Chrome, 네트워크를 포함한 서버 등록 정확도를 보장하지 않습니다.

## 앱 전용 브라우저

시스템 Chrome을 사용하지 않습니다. 릴리스에는 공식 Chrome for Testing `157.0.8103.38`과 같은 버전의 ChromeDriver를 아래 위치에 함께 넣습니다.

- `browser/chrome-win64/chrome.exe`
- `browser/chromedriver-win64/chromedriver.exe`

`browser_manifest.json`과 두 실행파일의 실제 버전이 완전히 같아야 합니다. 릴리스에서는 SHA-256 값도 채웁니다. 검증 실패 시 입찰은 차단되며 전체 패키지를 다시 설치해야 합니다. 브라우저 갱신은 별도 릴리스에서 로그인, 팝업, dry-run을 검증한 뒤 manifest와 바이너리를 함께 교체합니다.

## 시간 보정과 정밀 모드

실행 시각은 `목표 서버 시각 - 자동 보정 - 수동 보정`입니다. 최근 유효 20건을 저장하고 최근 5건의 중앙값을 씁니다. 실패 기록과 0~2,000ms 밖의 값은 제외하며 수동값은 -500~+500ms입니다.

고정가 모드는 가격을 먼저 입력하고 브라우저 `performance.now()` 타이머를 장전합니다. 마지막 20ms는 브라우저가 담당하고 마지막 2ms는 busy-spin합니다. 장전 실패 시에만 Python `perf_counter_ns()` fallback이 동작합니다. 일반 입찰은 마감 순간 새로고침과 가격 계산 때문에 정밀 모드 대상이 아닙니다.

## 로컬 데이터와 보안

설정과 로그는 개발 실행 시 프로젝트 디렉터리, 배포 실행 시 EXE가 있는 디렉터리에 저장됩니다. 비밀번호는 Windows Credential Manager, 쿠키는 Windows DPAPI로 보관합니다. 설정에는 ID만 저장하며 로그의 ID는 마스킹합니다. 기존 평문 계정과 pickle 쿠키는 보안 저장 성공 후 제거됩니다.

노출된 적이 있는 비밀번호는 릴리스 전에 반드시 변경하고 기존 옥션 세션을 모두 로그아웃하십시오.

## 취소와 복구

각 작업은 자신이 만든 Chrome과 HTTP 세션만 닫으며 사용자의 일반 Chrome은 종료하지 않습니다. 앱 전용 브라우저가 손상되었거나 버전이 다르면 전체 배포 패키지를 다시 설치하십시오.

## 빌드 및 검증

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m pytest -q
pyinstaller --clean main.spec
```

실제 옥션 검증은 제출 직전까지 dry-run이 기본입니다. 실제 입찰은 사용자가 명시적으로 활성화한 검증 계정과 상품에서만 수행하십시오.
