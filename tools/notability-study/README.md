# Notability Study · 필기와 강의 설명 연결

Notability의 필기·녹음·완료된 전사를 읽어 개념별 복습 근거를 준비하는 Python 도구와 AI 스킬입니다.

## 어떤 작업을 하나요?

선택한 노트 → 획·페이지·미디어·전사 추출 → JSON·검토 HTML → 개념 영역 지정 → 관련 전사 후보와 시간 근거 확인.

- Mac 로컬 저장소, 내보낸 `.note`·`.nbn`·`.ntb`를 읽습니다.
- 녹음과 연결된 완료 전사 또는 외부 SRT·VTT·JSON·TXT를 처리합니다.
- 페이지·획의 근거와 녹음 시계를 보존하고 시간 겹침·키워드로 후보를 정렬합니다.
- 원본 노트를 수정하지 않습니다. `watch`는 저장 파일 변경의 주기적 확인이며 실시간 음성인식이 아닙니다.

음성인식·OCR·의미 검색 모델을 자체 구현한 프로젝트가 아닙니다. 스킬은 추출된 입력을 읽고 문맥을 판단하는 지침이며 Python 매칭은 규칙 기반입니다.

## 개인정보 없는 데모

Python 3.11 이상으로 저장소 루트에서 실행합니다. 표준 라이브러리만 필요하며 노트·계정·모델 API가 필요 없습니다.

```bash
python3 tools/notability-study/examples/demo.py --output /tmp/notability-demo
python3 -m unittest discover -s tools/notability-study/tests -v
```

출력 폴더는 새 경로여야 합니다. `concepts.html`을 브라우저로 열면 직접 만든 가상 획·전사의 후보를 볼 수 있습니다. 이 데모는 **추출 이후의 매칭·HTML 생성 과정**을 검증하며 실제 Notability 파일 해독이나 손글씨 인식 정확도를 증명하지 않습니다. 오디오 파일도 포함하지 않습니다.

## 실제 노트 사용

저장소 루트 기준 예시이며 경로는 본인의 파일로 바꿉니다.

```bash
python3 tools/notability-study/scripts/notability.py list --limit 20
python3 tools/notability-study/scripts/notability.py extract --input /absolute/path/example.note --output /tmp/note-review
python3 tools/notability-study/scripts/notability.py align --output /tmp/note-review --annotations /absolute/path/regions.json
```

권한이 있는 노트만 처리하고 원본 밖의 새 출력 폴더를 지정합니다. 내보낸 결과에는 개인 미디어와 전사가 복사될 수 있으므로 GitHub에 올리지 않습니다. 정확한 시각 비교는 공식 PDF 내보내기와 대조합니다.

## 파일 구조

| 파일 | 역할 |
|---|---|
| [SKILL.md](SKILL.md) | 입력 선택·근거 확인·AI 분석 지침 |
| [scripts/notability.py](scripts/notability.py) | 읽기 전용 추출, 전사 처리, 미리보기, 후보 정렬 |
| [scripts/note_formats.py](scripts/note_formats.py) | legacy keyed archive·modern operation 해독 |
| [references/formats.md](references/formats.md) | 필드 출처·구현 범위·미해결 항목 |
| [examples/demo.py](examples/demo.py) | 개인 데이터 없는 재현 예시 |
| [tests/test_matching.py](tests/test_matching.py) | 시계 분리·후보 순서·입력 검증 |

## 한계와 다음 실험

앱 버전에 따라 형식이 달라질 수 있습니다. 압력·회전·부분 지우개와 일부 편집 복원은 불완전합니다. 유도된 시간 연결은 원래 앱의 Note Replay와 독립 검증되지 않았으며 의미 일치의 증거가 아닙니다. 외부 녹음은 재생 속도·탐색·일시정지로 시계가 달라집니다.

다음 단계는 동의 데이터에 정답 연결을 부여하고, 규칙 기반 후보 검색과 의미 검색을 비교하는 것입니다. 정확도 수치와 사용자 학습 효과는 아직 측정하지 않았습니다. 이 공개본은 로컬 스킬의 소스 사본이며 설치된 원본 스킬은 변경하지 않습니다.

[연구 관심 설명으로 돌아가기](../../RESEARCH.md)

[공개본 검증 기록](VALIDATION.md): 합성 데이터 테스트 6개와 데모 실행 확인.
