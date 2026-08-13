# CPV26 Live Card DB

컴프야V26 라이브 히트용 원격 카드 데이터 저장소입니다.

이 저장소는 APK와 분리되어 있으며 앱은 `catalog.json`을 기준으로 현재/과거 카드세트를 자동 선택합니다.

## 구조

- `catalog.json` — 활성 카드세트, 날짜별 적용기간, 원격 파일 URL/SHA-256
- `players.json` — 한글 선수명/alias 선수 마스터
- `cards/2026_v2.json` — 2026 V2 카드 포지션 DB
- 향후 `cards/2026_v3.json`, `cards/2027_v1.json` 등을 추가

새 카드세트가 추가되어도 catalog 스키마 범위 안에서는 APK 수정 없이 앱이 자동 다운로드할 수 있습니다.

### 운영 규칙

1. DB 내용 변경 시 `catalog.json`의 `revision`을 반드시 증가시킵니다.
2. 새 카드세트 추가 시 이전 카드세트의 `effectiveTo`를 종료합니다.
3. 과거 카드세트는 백테스트를 위해 삭제하지 않습니다.
4. 검증된 포지션만 `verified: true`로 등록합니다.
