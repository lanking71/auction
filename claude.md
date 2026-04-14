# 옥션 자동입찰 프로그램 - 개발 가이드

## 프로젝트 개요
- **목적**: Auction(옥션, auction.co.kr) 쇼핑몰 자동입찰 자동화 프로그램
- **GUI**: PySide6 (Qt for Python)
- **자동화**: Selenium + undetected-chromedriver
- **아키텍처**: MVC 패턴

---

## 아키텍처 구조

```
main.py
  ├── ViewController/ViewController.py  ← View (GUI 이벤트 처리)
  │     └── ViewController/auctionUi.py  ← Qt Designer 자동생성 UI
  ├── Controller/AuctionController.py   ← Controller (신호 중계, 스레드 관리)
  └── Auction.py                        ← Model (핵심 입찰 로직)
```

### 데이터 흐름
```
사용자 입력 (ViewController)
    ↓ start_crawling 시그널
AuctionController.auctionStart()
    ↓ QThreadPool Worker
Auction.auctionStart()
    ↓
1. setupbrowser()    → Chrome 초기화 (undetected-chromedriver)
2. loginstart()      → 쿠키 세션 또는 수동 로그인
3. startCrawling()   → BeautifulSoup으로 상품 정보 수집
4. bidWindow()       → 입찰 대화창 열기
5. check_time()      → 마감 시간까지 대기 후 입찰 실행
6. cleanup_resources() → 브라우저 종료
    ↓ Qt 시그널
ViewController UI 업데이트
```

---

## 파일 구조 및 역할

| 파일 | 역할 |
|------|------|
| `main.py` | 앱 진입점. QApplication, ViewController, Auction, AuctionController 인스턴스 생성 |
| `Auction.py` | 핵심 자동입찰 로직 (691줄). 브라우저 제어, 로그인, 입찰 타이밍, 낙찰 확인 |
| `ViewController/ViewController.py` | GUI 이벤트 처리. 입력값 저장/로드, 계정 관리, 가격 포맷팅 |
| `ViewController/auctionUi.py` | Qt Designer 자동생성 UI 레이아웃 (직접 수정 금지) |
| `Controller/AuctionController.py` | View-Model 사이 시그널 중계, Worker 스레드 생성/관리 |
| `setupbrowser_simple.py` | 브라우저 설정 독립 테스트용 스크립트 |
| `tempAuction.py` | 구버전 Auction 로직 (표준 chromedriver 사용) — 레거시/백업 |
| `tempView.py` | 구버전 뷰 컨트롤러 — 레거시/백업 |
| `input_data.json` | 사용자 입력값 영속화 (URL, 가격, 계정, 마감시간 등) |
| `account_data.json` | 저장된 옥션 계정 목록 (ID/PW — 평문 저장 주의) |
| `auction_cookies.pkl` | 브라우저 쿠키 세션 저장 (pickle 형식) |
| `requirements.txt` | Python 패키지 의존성 |
| `build/`, `dist/` | PyInstaller 빌드 산출물 (git에서 제외 권장) |

---

## 주요 기능

### 입찰 모드
1. **일반 모드**: 입찰가 = 현재가 + 추가금액, 최고가 상한선 적용
2. **고정가 모드**: 4개 고정 입찰가 + 각각 독립된 마감 시간 설정

### 봇 탐지 우회 기술
- `undetected-chromedriver`: webdriver 감지 우회
- CDP 명령어로 자동화 마커 제거
- User-Agent 스푸핑
- 랜덤 딜레이 및 마우스 움직임 시뮬레이션
- 한 글자씩 입력하는 키보드 시뮬레이션
- `selenium-stealth` 모듈

### 정밀 타이밍
- 마이크로초 단위 폴링 루프 (`interval=0.0001`)
- 네트워크 레이턴시 측정 (클라이언트 시간 vs 서버 등록 시간 비교)
- 경쟁 입찰자 ID 확인

### 세션 관리
- 쿠키 pickle 저장/불러오기
- 쿠키 유효성 검사 및 만료 확인
- 새 세션에 자동 쿠키 적용

---

## 현재 알려진 문제

### 로그인 차단 (최우선 이슈)
- 옥션의 봇 탐지 시스템으로 **자동 로그인이 차단**됨
- 로그인 시도 시 "아이디 또는 비밀번호를 잘못 입력했습니다" 오류 발생
- undetected-chromedriver, selenium-stealth 사용에도 불구하고 탐지됨
- **pickle 저장 쿠키 로그인도 현재 막혀있음**

### 수동 로그인 우회 방식 (현재 구현 목표)
1. 프로그램 시작 시 Chrome 브라우저 열림
2. **사용자가 직접 손으로 로그인** (자동 로그인 X)
3. 로그인 완료 후 GUI에서 "로그인 완료" 버튼 클릭
4. 이후 입찰 시간이 되면 **자동으로 입찰만** 수행

### 코드 레벨 버그

| 위치 | 문제 |
|------|------|
| `Auction.py` check_time() | CPU 과점유 타이트 폴링 (`time.sleep(0.0001)`) |
| `Auction.py` vs `ViewController.py` | 시그널 파라미터 불일치 — `start_crawling(list, list)` 방출 vs `auctionStart(startData, closing_time, interrupted, finished)` 수신 |
| `Auction.py` refresh() | try-except 블록에서 실패 무시 (silent fail) |
| `Auction.py` local_data | 스레드 ID 키 방식 → 스레드 미정리 시 메모리 누수 가능 |
| `account_data.json` | 자격증명 평문 저장 (보안 취약) |

---

## 수정하지 않을 기능
- 입찰 시간 설정 기능
- 입찰 금액 설정 기능
- 긴급 중단 (ESC 키) 기능

---

## 개발 지침

### 코드 수정 시 주의사항
1. **`ViewController/auctionUi.py` 직접 수정 금지** — Qt Designer에서 .ui 파일 수정 후 재생성
2. 시그널 수정 시 반드시 `ViewController.py`, `AuctionController.py`, `Auction.py` **세 파일 모두** 일관성 확인
3. 스레드 관련 코드 수정 시 `local_data` 스레드 로컬 스토리지 패턴 유지
4. 브라우저 자동화 코드 추가 시 **랜덤 딜레이** 반드시 포함 (봇 탐지 방지)
5. `tempAuction.py`, `tempView.py`는 레거시 파일 — 여기서 코드 참조만, 수정 불필요

### 가격 포맷팅 규칙
- 모든 금액 입력은 **천 단위 콤마** 자동 적용
- `on_price_changed()`, `on_Additional_changed()`, `on_fixedPrice_chaged()` 핸들러 참고

### 마감 시간 형식
- 형식: `HH:MM:SS.mmm` (예: `14:30:00.500`)
- 고정가 모드에서는 4개 입력란 각각 독립 설정

### Qt 시그널/슬롯 패턴
```python
# ViewController → Controller
self.start_crawling.emit(startData, closingTimes)

# Controller → Auction (Worker 통해)
worker = Worker(self.auction.auctionStart, startData, closingTimes, interrupted, finished)

# Auction → ViewController (상태 업데이트)
self.auction_operation_signal.emit("메시지")
self.auction_bid_results.emit("낙찰 결과")
self.auction_bid_title.emit("상품명")
```

### 멀티스레드 고정가 입찰
- `fixedMultipleBid()`에서 스레드 간 **20초 간격** 필수 유지 (봇 탐지 방지)
- 각 스레드는 `local_data[thread_id]`로 독립 브라우저 인스턴스 관리

---

## 환경 설정

### Python 패키지 설치
```bash
pip install -r requirements.txt
```

### 주요 의존성
| 패키지 | 버전 | 용도 |
|--------|------|------|
| PySide6 | >=6.6.0 | GUI 프레임워크 |
| selenium | >=4.15.0 | 브라우저 자동화 |
| undetected-chromedriver | >=3.5.0 | 봇 탐지 우회 |
| selenium-stealth | >=1.0.6 | 추가 스텔스 설정 |
| beautifulsoup4 | >=4.12.0 | HTML 파싱 |
| requests | >=2.31.0 | HTTP 요청 |
| keyboard | >=0.13.0 | 긴급중단 ESC 감지 |
| dill | — | 스레드 인자 고급 직렬화 |

### 빌드 (PyInstaller)
```bash
pyinstaller main.spec
```
빌드 결과물: `dist/` 폴더

### Chrome 드라이버
- `chromedriver.exe` 포함 (프로젝트 루트)
- `undetected-chromedriver`가 버전 자동 관리
- `Auction.py` 내 `version_main=147` 하드코딩 — Chrome 업데이트 시 수정 필요

---

## 데이터 파일

### input_data.json 구조
```json
{
  "url": "https://...",
  "maxPrice": "100,000",
  "additionalPrice": "1,000",
  "id": "옥션아이디",
  "pw": "비밀번호",
  "closingTime": "14:30:00.500",
  "fixedPrices": ["50000", "60000", "70000", "80000"],
  "fixedTimes": ["14:30:00.000", "..."],
  "networkTiming": "..."
}
```

### account_data.json 구조
```json
[
  {"id": "계정ID", "pw": "비밀번호"},
  ...
]
```
> **보안 주의**: 비밀번호 평문 저장 — 운영 환경에서는 암호화 필요

---

## 디버깅

### 스크린샷 파일
- `debug_screenshot.png`, `debug_screenshot1.png`, `debug_screenshot2.png` — 자동화 중 캡처된 디버그 이미지

### 크롬 강제 종료
- GUI의 "Kill Chrome" 버튼 사용
- 또는 `ViewController.kill_all_chrome()` 직접 호출

### 일반적인 오류 상황
| 증상 | 원인 | 해결책 |
|------|------|--------|
| 로그인 실패 | 봇 탐지 | 수동 로그인으로 전환 |
| ChromeDriver 오류 | 버전 불일치 | `version_main` 값 수정 또는 chromedriver.exe 교체 |
| 시그널 연결 오류 | 파라미터 불일치 | 세 파일 시그널 정의 동기화 확인 |
| 입찰 미실행 | 타이밍 오차 | 마감 시간 형식 및 시스템 시계 확인 |
| 메모리 증가 | 스레드 누수 | `cleanup_resources()` 호출 확인 |

---

## 보안 주의사항
- `account_data.json` / `input_data.json` — 자격증명 포함, 외부 유출 주의
- `auction_cookies.pkl` — 세션 쿠키 포함, 동일하게 민감 정보
- 위 파일들은 `.gitignore`에 반드시 포함 권장
- pickle 형식은 역직렬화 취약점 존재 — 신뢰된 환경에서만 사용

---

## 향후 개선 과제 (우선순위)

### 높음
- [ ] ViewController ↔ Auction 시그널 파라미터 불일치 수정
- [ ] 수동 로그인 완료 버튼 UI 구현 및 플로우 안정화
- [ ] check_time() CPU 과점유 개선 (이벤트 기반 타이밍)
- [ ] 자격증명 암호화 저장 (keyring 또는 AES)

### 중간
- [ ] 입찰 실패 시 자동 재시도 로직
- [ ] 세션 만료 시 자동 재로그인 또는 알림
- [ ] 영속 로그 파일 (현재 Qt 시그널에만 의존)
- [ ] Auction.py와 tempAuction.py 코드 통합 정리

### 낮음
- [ ] 하드코딩된 매직넘버 설정 파일로 분리
- [ ] 입찰 결과 CSV/JSON 내보내기
- [ ] 단위 테스트 추가
- [ ] 주석/docstring 보강
