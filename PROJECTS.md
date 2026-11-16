# 만든 것들

게임을 만들 때는 브라우저로 함께 플레이할 수 있는지, 행사 도구를 만들 때는 현장에서 바로 쓸 수 있는지를 먼저 봤습니다. 학교생활에서 반복하던 일은 직접 도구로 만들어봤습니다.

[게임과 인터랙션](#게임과-인터랙션) · [임베디드와 현장 도구](#임베디드와-현장-도구) · [AI와 학습 도구](#ai와-학습-도구) · [웹과 문서 도구](#웹과-문서-도구)

## 게임과 인터랙션

### BID! LIMIT

[Roomcon](https://roomcon.team/) 첫 회차에 참여하면서 혼자 개발한 4인 경매 카드 게임입니다. 별도 설치 없이 모여서 플레이할 수 있게 Godot 웹 빌드를 Vercel에 올렸습니다. 방에 접속하는 흐름부터 WebRTC를 이용한 멀티플레이와 브라우저 음성 채팅까지 구현했습니다. Roomcon에서는 매달 새 주제로 하나씩 만들 계획입니다.

[코드](https://github.com/K-Lunatic/bid-limit) · [플레이](https://bid-limit.vercel.app/)

### Catpera Symphony · 음악에 반응하는 3D 오케스트라

악기 소리를 시각적으로 구분해 볼 수 있게, 직접 모델링한 고양이에 MIDI 악기를 배정하고 연주에 맞춰 움직이도록 만들었습니다. 브라우저에서 실행되며 Vercel에 배포했습니다.

[코드와 MIDI 예제](https://github.com/K-Lunatic/catpera-public) · [체험](https://k-lunatic.github.io/catpera-public/)

### Void

관객의 휴대폰을 전시 조작기로 썼습니다. 휴대폰에서 낸 고주파 소리를 전시장 마이크가 감지하면 화면과 배경음이 바뀝니다. 휴대폰 화면과 전시 화면을 각각 웹에서 열도록 구성했습니다.

[코드](https://github.com/K-Lunatic/void-public)

## 임베디드와 현장 도구

### Punch Master

몸을 움직여 조작하는 아케이드 펀치 게임입니다. M5Atom(ESP32)의 IMU 센서에서 움직임을 읽어 Unity 게임에 연결했습니다.

[코드](https://github.com/K-Lunatic/punch-master)

### BillPhoto · 행사 포토부스

행사 참가자가 직접 사진을 찍고 가져갈 수 있도록 만들었습니다. 촬영본 중 세 장을 골라 한 장으로 합성하고 블루투스 영수증 프린터로 출력합니다. 행사에서 직접 운영했습니다.

[시연](https://k-lunatic.github.io/billphoto-demo/) · [시연 코드](https://github.com/K-Lunatic/billphoto-demo)

### Angel24 · 일산 서코 부스 키오스크

블루아카이브 팬 부스를 일산 서울코믹월드에서 열고, 방문객이 굿즈를 보고 주문할 수 있게 터치 키오스크를 만들었습니다. 운영자용 상품·주문 화면과 방문객 화면은 따로 만들어 Vercel에 배포했고, 주문 흐름은 Firebase로 연결했습니다.

[방문객용 키오스크](https://angel24-kiosk.vercel.app/)

### QR 안내와 인쇄 도구

- **[K_Army_qr](demos/k-army-qr/README.md)** — 행정병 근무 중 안내와 배치도를 매번 전달하는 대신, QR을 찍으면 휴대폰에서 바로 확인할 수 있게 만들었습니다. 예제 배치도로 동작을 볼 수 있습니다.
- **[QR Ticket PDF](https://github.com/K-Lunatic/qr-ticket-pdf)** — 이름과 링크를 입력하면 참가자별 QR 카드를 만들고, 가로 A4 한 장에 세 장씩 배치한 PDF를 내려받습니다. 브라우저에서 생성합니다.
- **Safety Monitor** — Windows에서 C로 수집한 네트워크 정보를 UDP로 전달하고 브라우저에서 확인하는 실험입니다.

## AI와 학습 도구

### 터틀넥

해커톤에서 학교 공지, 과제, 강의자료를 여러 화면에서 확인하던 일을 줄이려고 시작했습니다. 강의자료에서 복습 문제를 만들고 웹 시험지에서 직접 풀 수 있는 흐름도 붙였습니다.

[예제 시험지 풀기](https://k-lunatic.github.io/Foundation/turtleneck/) · [코드와 사용법](https://github.com/K-Lunatic/Turtleneck)

### Logics · INK — 생활 데이터를 실행 가능한 도구로

흩어진 물품·일정·식단·재무 기록을 한곳에 모으고, 채팅에서 필요한 기록을 조회하거나 수정하는 앱입니다. 웹 앱과 MySQL을 개인 라즈베리파이에서 함께 돌릴 수 있도록 Docker 구성을 만들었습니다.

[코드와 라즈베리파이 실행 구성](https://github.com/K-Lunatic/logics-public)

### 졸업할KU야 · GradKUya

성적표와 입학연도 요람을 손으로 대조하는 일을 줄이려고 만들었습니다. 성적표 PDF에서 과목을 읽고 졸업요건을 대조한 뒤, 남은 요건과 수강 시간표 후보를 확인할 수 있습니다.

[가상 성적표 결과](https://k-lunatic.github.io/Foundation/gradkuya/) · [코드와 예제 데이터](https://github.com/K-Lunatic/gradkuya-public)

### Notability Study

필기에 적어둔 단어만으로 녹음에서 설명을 찾기 어려워 만든 자동화입니다. 필기 내용을 녹음·전사와 연결해, 복습할 때 해당 설명을 다시 찾을 수 있게 했습니다.

[도구와 사용법](tools/notability-study/README.md)

## 웹과 문서 도구

### Our-Frequency

질문에 답하면 성향을 시각화해 보여주는 웹 프로젝트입니다. Vercel에 올린 본 프로젝트는 질문부터 결과까지 체험할 수 있고, 같은 아이디어를 과제 제출용으로 다시 구현한 코드도 남겨뒀습니다.

[본 프로젝트 체험](https://our-frequency.vercel.app/) · [과제 제출판 코드](https://github.com/K-Lunatic/Our-Frequency)

### HOP Web Editor

HWP/HWPX 문서를 브라우저에서 다룰 수 있도록 WASM 문서 엔진을 연결했습니다. 편집 화면과 단축키, 문서에서 반복되는 문자열을 한 번에 바꾸는 기능을 만들었습니다.
