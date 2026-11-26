# 협객풍운전 세이브 에디터 v1.0.1

스팀판 **협객풍운전** (앱 번호 `377530`, 빌드 `13538331`, 한국어 패치 `1.32` 기준) 전용 무손실 세이브 · 전역 업적(`Round.dat`) · 회차 고유 기록 편집기입니다.

외부 서버 통신이나 계정 로그인 없이 모든 처리가 사용자 기기 내부에서만 동작하며, 세이브 덮어쓰기 전 SHA-256 해시 검증 백업(`.bak`)과 원자적 파일 교체를 자동으로 수행합니다.

---

## 주요 기능

1. **4종 세이브 규격 무손실 지원 (`JsonFx` 토큰 보존 코덱)**
   - 캐릭터 수동·자동 세이브(`Save0.Save` ~ `Save19.Save`, `AutomaticSave*.Save`, `AutomaticDSave*.Save`)
   - 전역 다회차 · 업적 기록(`Round.dat`)
   - 회차 고유 기록(천부 · 보물상자 개방 정보)
   - 슬롯 목록 색인(`SaveTitle.SaveTitle`, `SaveAutomaticTitle.SaveTitle`, `SaveAutomaticDTitle.SaveTitle`) 자동 동기화
   - 비편집 원시 수치 리터럴(지수 표기 실수·수학적 정수 지수 표기·64비트 정수; `validate`·`inspect`·`apply` 프리셋 및 모드 A/B/C 불러오기·저장 전 구간에서 수학적 정수 지수 표기 수용 및 비편집 원문 토큰 보존), JsonFx 호환 대문자 유니코드 이스케이프(`\uXXXX`, `\u003C`), 주인공 이름 후행 개행(`\r`), 단일 UTF-8 서명(BOM) 및 줄바꿈 형식(CRLF/LF) 보존 (동반 `.SaveTitle`은 대상 슬롯 원소만 부분 치환해 나머지 슬롯 원문 바이트 보존)

2. **순수 한국어 도감 내장**
   - 물품 `830`종(원본 21필드 `_ItemDataNode` 구조 완비), 투로 `362`종, 내공 심법 `146`종, 무공 비급 연동 `244`종, 천부 `25`종, 칭호 `42`종, 우호도 인물 `47`명, 동료 `90`명, 지역 `34`곳, 육성 행동 `71`종, 보물상자 `111`개, 공식 업적 `164`종

3. **6개 편집 범주 및 8종 원클릭 빠른 설정**
   - **기본 · 일정**: 성씨·이름, 보유 금전, 연도·월·순·시진, 현재 장소, 전투 난이도, 육성 체력·기분, 기초 공방 수치
   - **능력치 · 천부**: 제1~제3천부, 장착 칭호, 5대 속성군 `41`종 능력치·기예 수치 및 경험치 (모든 수치 입력란은 `valueAsNumber` 기반 엄격 정수 검증·범위 보정 및 입력란 표시값 동기화를 수행해 `1e5` 등 지수 표기 정수 입력도 정확히 반영하며, 브리지 저장 확인창에서 능력치·경험치 개별 변경 전후 수치를 구체적으로 대조 표시)
   - **투로 · 내공**: 보유 투로·내공 심법 추가/삭제·성급(`1~10`성)·누적 경험치 편집 및 역공학 기반 전투 피해 계산기
   - **행낭 · 장비**: 장착 무기·방어구·장신구 변경, `830`종 물품 검색·수량 편집·추가·삭제
   - **인물 · 동료**: 주요 인물 우호도(`0~100`, 일괄 생사고락 지원) 및 동료 편성(`최대 9명`)
   - **업적 · 회차 · 백업**: 공식 업적 `164`종 해금, 성당 다회차 특전(`최대 7점`), 회차 천부·보물상자 전체 개방, 백업 목록 조회 및 즉시 복원

4. **3가지 실행 방식 제공**
   - **단독 윈도우 실행 파일 (`TaleOfWuxiaSaveEditor-v1.0.1.exe`)**: 설치 없이 바로 실행되는 64비트 윈도우 데스크톱 앱(`WebView2` 기반)
   - **오프라인 단일 웹 파일 (`TaleOfWuxiaSaveEditor-v1.0.1.html`)**: 브라우저에서 인터넷 없이 바로 열어 파일 열기·내려받기로 편집
   - **표준 파이썬 명령줄 도구 및 로컬 브리지 서버 (`twx_editor.py`)**: 외부 패키지 설치 없이 파이썬 `3.10` 이상 표준 라이브러리만으로 슬롯 탐색·검증·적용·복원 및 로컬 웹 편집 서버 구동

---

## 세이브 파일 기본 위치

- **스팀 클라우드 저장소**: `%ProgramFiles(x86)%\Steam\userdata\<스팀계정번호>\377530\remote\`
- **게임 설치 폴더 내 저장소**: `<스팀 라이브러리>\steamapps\common\Tale of Wuxia\Config\SaveData\`

> **주의**: 협객풍운전(`wuxia.exe`) 실행 중에는 세이브 파일 보호를 위해 덮어쓰기 및 복원이 자동으로 차단됩니다. 반드시 게임을 종료한 뒤 저장하세요.

---

## 실행 방법

### 1) 윈도우 데스크톱 앱 (`TaleOfWuxiaSaveEditor-v1.0.1.exe`)
1. 릴리스에서 `TaleOfWuxiaSaveEditor-v1.0.1-Windows.zip`을 내려받아 압축을 해제합니다.
2. `TaleOfWuxiaSaveEditor-v1.0.1.exe`를 실행하면 설치된 세이브 경로를 자동으로 찾아 연결합니다(사용자 지정 경로는 `TWX_SAVE_ROOT` 환경변수로 지정 가능).
3. 상단 슬롯 목록에서 편집할 슬롯을 선택하고 수치를 조정한 뒤 **백업 후 안전 저장**을 누릅니다.

### 2) 오프라인 단일 웹 파일 (`TaleOfWuxiaSaveEditor-v1.0.1.html`)
1. `TaleOfWuxiaSaveEditor-v1.0.1.html`을 크롬·엣지 등 최신 브라우저로 엽니다.
2. **파일 열기**로 `.Save` 또는 `Round.dat` 파일을 불러와 편집한 뒤 **세이브 파일 내려받기**로 저장합니다.

### 3) 파이썬 명령줄 및 로컬 서버 (`twx_editor.py`)
```bash
# 세이브 경로 및 슬롯 자동 탐색
python3 twx_editor.py discover

# 세이브 요약 조회 및 무결성 검증
python3 twx_editor.py inspect Save0.Save
python3 twx_editor.py validate Save0.Save

# 원클릭 빠른 설정 목록 확인 및 적용 (자동 백업 포함)
python3 twx_editor.py presets
python3 twx_editor.py apply Save0.Save --preset max_money

# 신규 예시 파일 생성 (기존 파일 덮어쓰기 자동 거부)
python3 twx_editor.py demo --kind save --out SampleSave.Save

# 로컬 루프백 브리지 웹 서버 실행 (기본 127.0.0.1:8765)
python3 twx_editor.py serve
```

---

## 안전 및 보안 설계

- **원자적 저장 · 해시 검증 백업 · 동시 수정 보호**: 최초 루트 확정 및 미존재 루트 생성(`serve` 및 데스크톱 `LocalBridgeServer` / `EnsureSafeRootDirectory`)과 잠금 진입 시 정션·심볼릭 링크 조상 너머로 미검증 `Directory.CreateDirectory`를 호출하지 않고, `realpath` 선행 해석 없이 파일시스템 최상위 조상부터 존재하는 모든 상위 조상 핸들을 링크·재분석 지점 미추적(`O_NOFOLLOW` / `FILE_FLAG_OPEN_REPARSE_POINT`) 체인으로 먼저 검증·고정한 뒤에만 누락된 디렉터리를 생성하고 루트 식별자를 고정합니다. 또한 CLI `apply --out` 및 `_open_pinned_parent`를 포함한 모든 미존재 루트·하위 출력 디렉터리 생성은 경로 문자열 `mkdir(parents=True)`를 사용하지 않고 최상위 조상부터 고정된 부모 핸들 내부에서 한 세그먼트씩만 생성합니다. 단일 파일 인자를 받는 CLI 명령(`demo`, `inspect`, `validate`)은 대상 파일의 직계 부모 디렉터리 `.twx_store.lock`을 획득하고, 루트 단독 조회(`discover`, `/api/slots`, 슬롯 미지정 `/api/backups`)는 루트 `.twx_store.lock`을, 루트·슬롯 기반 명령(`apply`, `restore` 및 파이썬·C# 브리지 `/api/load`, `/api/backups?slot=<슬롯>`, `/api/save`, `/api/restore`; 정적·상태 응답인 `presets`·`/api/health` 제외)은 파이썬(`_slot_lock_guard`·`_store_lock_guard` 및 CLI `apply`)과 윈도우 C# `SaveStore`(`PinnedSlotLockScope`) 모두 POSIX 선행 다중 슬래시(`//`)를 정규화하고 고정된 디렉터리 파일시스템 식별자(POSIX `(st_dev, st_ino)` / 윈도우 `(VolumeSerialNumber, FileIndexHigh, FileIndexLow)` `FileId`)의 전역 오름차순으로 다중 디렉터리 `.twx_store.lock`을 중복 제거·획득(역순 해제 및 동일 디렉터리 재진입)하여 바인드 마운트·다중 경로 접근 및 파이썬 CLI와 C# 데스크톱·브리지 프로세스 간 동시 실행 시 교착과 잠금 대기 시간 초과를 방지하며, POSIX `.twx_store.lock`은 `flock` 획득 직후 `fstat(fd)`와 `lstat(".twx_store.lock", dir_fd)`의 inode 일치를 검증하고 대기 중 unlink/교체가 감지되면 재시도하며, POSIX `/api/slots`는 검증된 열린 루트 디렉터리 디스크립터(`dir_fd`)를 기준으로 열거합니다. 최초 확인 시 존재하지 않던 신규 슬롯 및 `demo` 신규 예시 파일 생성은 기대 해시 인자 유무와 무관하게 항상 스테이징 검증 후 비덮어쓰기 경로(POSIX `/proc/self/fd/<fd>` 결속 `os.link`·윈도우 비덮어쓰기 `SetFileInformationByHandle(FileRenameInfo)`)로 게시한 뒤 임시 링크 삭제 성공 여부 및 최종 게시 파일의 단일 링크(`st_nlink == 1`)·식별자·SHA-256 해시를 모두 확인한 시점에만 성공을 확정하며(임시 링크 삭제 실패 시 반쪽 하드링크를 남기지 않고 본인 생성 파일을 정리한 뒤 오류 반환; 실패 정리도 생성 당시 파일 식별자(`(st_dev, st_ino)` / `FileId`)와 SHA-256 일치 파일에만 제한해 경쟁 생성·교체된 타 프로세스 파일을 절대 덮어쓰거나 삭제하지 않음), POSIX 신규 슬롯 `os.link`는 `/proc/self/fd/<fd>`를 통해 검증된 열린 스테이징 디스크립터(`fd_new`, `expected_tmp_id`)에만 직접 결속해 커밋하고(`/proc/self/fd` 미지원 환경에서는 이름 기반 링크를 수행하지 않고 `ATOMIC_FD_LINK_UNSUPPORTED`로 거부), 임시 이름의 inode 불일치나 `os.unlink(tmp)` 실패 시 열린 `fd_new`와 `lstat(leaf, dir_fd)`로 대상 경로가 여전히 본인이 생성한 스테이징 식별자(`expected_tmp_id`)와 의도한 바이트 해시(`expected_out_sha`)를 모두 유지하는 정규 파일일 때만 `os.unlink(leaf)`와 디렉터리 `fsync`를 수행하고 `lstat(leaf, dir_fd)` `FileNotFoundError`로 실제 삭제 부재를 확인한 경우에만 정리 완료(`slot_replaced = False`)로 기록하고(`os.unlink(leaf)` 실패로 대상 슬롯이 남아 있으면 중복 `.tmp` 하드링크만 정리한 뒤 `slot_replaced = True`로 표시하여 상위 롤백 재시도 및 미삭제 시 동반 `.SaveTitle` `.bak` 백업 보존을 보장하며, `lstat(leaf, dir_fd)`가 `FileNotFoundError` 외의 `OSError`(`EIO` 등)로 실패해 대상 상태를 확정할 수 없거나 삭제 직후 디렉터리 `fsync`가 실패한 경우에도 미확정/미동기화 실패 상태로 유지해 동반 `.SaveTitle` `.bak` 백업을 보존하고, 동일 inode에 대한 외부 쓰기 감지 시 외부 수정 바이트가 기록된 대상 경로는 보존하고 중복 `.tmp` 하드링크만 정리) `CONFLICT_MODIFIED`/오류를 반환함으로써 미검증 하드링크나 반쪽 상태가 남지 않게 하면서도 링크 직후 외부에서 다른 inode로 교체하거나 같은 inode에 기록한 데이터는 절대 삭제하지 않습니다. 기존 슬롯과 동반 `.SaveTitle` 모두 윈도우 `FILE_SHARE_READ` 전용 핸들 고정 및 POSIX 열린 `fd`·`dir_fd` `lstat` 식별자(`(st_dev, st_ino)`)·SHA-256 해시 대조(충돌 시 임시 파일만 정리하고 `CONFLICT_MODIFIED` 반환; CLI `apply --out` 역시 `realpath` 문자열 비교에만 의존하지 않고 부모 디렉터리 파일시스템 식별자+슬롯명 일치 및 검증된 열린 원본·출력 파일 식별자 대조[`source_file_guard`]를 함께 수행하여 바인드 마운트·다중 마운트 경로로 같은 슬롯을 지정한 경우에도 최초 읽기 해시 불일치 시 외부 변경 덮어쓰기를 차단)를 수행하고, 백업 생성(`_write_backup_in_pinned_dir` · C# `CreateVerifiedBackup`)은 선행 존재 여부 확인 후 덮어쓰기 커밋을 사용하지 않고 스테이징 후 비덮어쓰기 커밋(POSIX는 열린 스테이징 디스크립터 `b_fd`에서 식별자·SHA-256을 검증한 뒤 `/proc/self/fd/<fd>`에만 직접 결속하는 `dir_fd` `os.link`[`/proc/self/fd` 미지원 시 `ATOMIC_FD_LINK_UNSUPPORTED`로 거부] · 윈도우는 비덮어쓰기 `SetFileInformationByHandle(FileRenameInfo)`)과 최대 33회 이름 충돌 재시도를 수행해 먼저 생성된 동일 이름 백업을 절대 덮어쓰지 않으며, 백업 생성부터 슬롯·동반 `.SaveTitle` 커밋 및 정리·복구 전 구간에서 검증된 `backups/` 디렉터리 핸들·식별자를 유지하여 공개 `backups/` inode 일치 및 백업 식별자·SHA-256 해시를 확인합니다(실패 정리 시에도 고정된 핸들 내부에서 식별자·해시 일치 백업만 삭제). 윈도우(파이썬·C#)는 검증된 스테이징 및 롤백 `.tmp` 임시 파일을 배타적 `FILE_SHARE_NONE`(`dwShareMode = 0`, `GENERIC_READ | DELETE`) 핸들로 열어 대상 검증과 기존 대상 `FILE_SHARE_READ` 핸들 해제 직전·직후 전 구간에서 해당 배타 핸들을 유지한 채 열린 임시 핸들을 통해 `SetFileInformationByHandle(FileRenameInfo)`로 직접 이름을 변경함으로써 커밋과 롤백 전 과정에서 임시 파일 쓰기·교체를 커널 수준에서 차단하며(이름 변경 성공 후에는 이전 `.tmp` 경로에 대한 정리를 생략하고, 이름 변경 전 실패 정리 시에도 삭제용 `FILE_FLAG_OPEN_REPARSE_POINT` 배타 핸들에서 생성 당시 `FileId` 일치를 재검증한 뒤에만 `SetFileInformationByHandle(FileDispositionInfo)`로 삭제해 스테이징 핸들 해제 뒤 같은 임시 경로에 들어온 외부 파일을 절대 삭제하지 않음), POSIX는 백업·동반 타이틀 확인 뒤 `_verify_tmp_and_target_before_posix_replace`가 `.twx_store.lock` 하에서 열린 `tmp_vfd`와 `orig_fd`를 함께 유지한 채 `orig_fd` 검증 후 마지막으로 `tmp_vfd` 바이트 재해시·`fstat`/`lstat`로 (`st_dev`, `st_ino`) 식별자와 SHA-256 해시를 연속 확인하며, Linux POSIX 기존 파일 교체와 롤백은 교체 직전 스테이징 임시 파일의 본인 생성 inode(`expected_tmp_id`) 일치 및 `pre_exchange_tmp_sha == expected_tmp_sha` 바이트 해시 일치를 먼저 강제(불일치 시 `RENAME_EXCHANGE`를 호출하지 않고 본인 `.tmp`만 정리한 뒤 `CONFLICT_MODIFIED` 반환)한 뒤 고정된 `dir_fd` 내부의 원자적 `renameat2(RENAME_EXCHANGE)`를 수행하고 교체 즉시 교체 상태를 기록하며, 새로 설치된 대상 파일의 `(st_dev, st_ino)`와 SHA-256을 먼저 검증한 뒤 교체로 밀려난 원본 파일의 `(st_dev, st_ino)`와 SHA-256을 검증하고, 최종 `unlink` 직전에도 밀려난 사본의 `(st_dev, st_ino)`와 SHA-256(`expected_orig_sha`) 일치를 재검증한 뒤에만 unlink하며(밀려난 원본이 사전 개방된 fd 등을 통해 수정된 경우 unlink하지 않고 되교환 또는 원자적 `RENAME_EXCHANGE` 복구로 수정된 원본과 `.bak` 백업을 보존한 채 `CONFLICT_MODIFIED` 반환), 검증 불일치 또는 교체 후 unlink 실패 시 활성 대상이 여전히 본인의 스테이징 inode(`expected_tmp_id`)와 교체 직전 해시(`pre_exchange_tmp_sha`)를 모두 그대로 유지할 때만 검증된 되교환을 엄격히 수행하고 임시 파일 정리 역시 본인 스테이징 inode와 교체 직전 해시(`pre_exchange_tmp_sha`)가 모두 일치할 때만 unlink하여 외부 작성자의 교환 직후 대체 파일이나 동일 inode 제자리(in-place) 수정을 밀어내거나 덮어쓰거나 삭제하지 않으며(교환 직후 대체 또는 동일 inode 제자리 외부 수정 감지 시 활성 대상과 밀려난 사본·`.bak` 백업을 모두 보존한 채 `CONFLICT_MODIFIED` 반환), 되교환 성공 시 미수정 본인 스테이징 `.tmp`를 정리하고 디렉터리 `fsync`가 성공한 뒤에만 복구 완료(`keep_bak = False`)로 기록한 뒤 `CONFLICT_MODIFIED`/원인 예외를 전달하고(밀려난 원본 변경 감지 또는 되교환 직후 디렉터리 `fsync` 실패 시 슬롯과 동반 `.SaveTitle`의 `.bak` 백업을 모두 유지), `installed_ok`/`displaced_ok` 및 `RENAME_EXCHANGE` 되교환이 실패했지만 활성 대상이 여전히 미수정 본인 스테이징 상태(`expected_tmp_id` 및 `pre_exchange_tmp_sha`)로 남아 있을 때만 밀려난 사본(`fd_disp`)을 열린 채로 유지하여 읽기 전후 `fstat`/`lstat` 식별자·메타데이터 일치와 재탐색(`lseek`) SHA-256 해시 불변성을 먼저 확정하고, 교체 직전 활성 대상 재검증 후에도 덮어쓰기 `os.replace` 대신 원자적 `renameat2(RENAME_EXCHANGE)`로 복구본을 교환한 뒤 밀려난 이전 활성 대상이 미수정 본인 스테이징본이 아닌 최신 외부 변경본으로 확인되면 즉시 재교환·보존하여 활성 대상의 최신 외부 수정이 유실되지 않게 하면서(불완전·찢어진 읽기 감지 시에도 복구 교환을 중단하고 상위 검증 롤백으로 전환) `tmp_name`과 `.bak` 백업을 모두 삭제하지 않고 보존하며, `RENAME_EXCHANGE`가 없는 POSIX 파일시스템(`UNSUPPORTED`)에서는 비원자적 `os.replace` 폴백을 수행하지 않고 본인 스테이징 inode(`expected_tmp_id`)와 일치하는 `.tmp`만 정리한 뒤 대상 무변경 상태로 `ATOMIC_EXCHANGE_UNSUPPORTED`를 반환해 저장·복원을 거부하고 윈도우는 열린 `FILE_SHARE_NONE` 핸들을 통해 `SetFileInformationByHandle(FileRenameInfo)`로 이름을 변경하며, 교체 후 실패 시 복구용 임시 파일을 선스테이징·동기화(`fsync`)한 뒤 본인이 기록한 식별자(POSIX `(st_dev, st_ino)` · 윈도우 `FileId`)와 SHA-256 해시를 이중 검증해 롤백하고 POSIX 롤백도 동일한 이중 열린 fd 검증에 더해 Linux `renameat2(RENAME_EXCHANGE)` 대체 파일 검증과 되교환을 수행합니다, 스테이징 임시 파일 커밋 직전 및 커밋 완료 직후 디스크 대상 파일의 식별자(`(st_dev, st_ino)` · `FileId`)와 SHA-256 해시를 재검증한 뒤에만 성공 응답 해시를 반환합니다(커밋 직후 재검증에서 외부 변조 감지 시 즉시 거부 또는 롤백 수행). 교체 후 실패 롤백 시에는 `TryRollbackReplacedSlot`·`_rollback_target_bytes`·`_rollback_replaced_in_parent`가 먼저 스테이징한 복구용 임시 파일의 식별자·해시(`inode`/`FileId` + `SHA-256`)를 검증하고, 교체 직전 현재 대상 파일의 본인 기록 식별자·해시를 확인한 뒤 교체하며, 교체 직후 복원된 디스크 대상 파일의 식별자·해시(`inode`/`FileId` + `SHA-256`)까지 재검증합니다(신규 슬롯 삭제 롤백 시에도 삭제 후 부재 확인 수행). 이때 `TryRollbackReplacedSlot`·`_rollback_target_bytes`·`_rollback_replaced_in_parent`는 현재 식별자(`(st_dev, st_ino)` / `FileId`)와 SHA-256 해시가 본인이 기록한 커밋 내용과 여전히 일치하는 파일만 복원하므로, 외부에서 수정된 `.SaveTitle`이나 슬롯은 절대 덮어쓰지 않고 본인이 기록한 미수정 대응 파일만 롤백하며 `.bak` 백업은 `PruneBackups`를 실행하지 않고 그대로 보존합니다. 롤백이나 롤백 직후 재검증이 완전히 성공하지 않으면 검증된 `.bak` 백업을 삭제하지 않고 `backups/`에 그대로 보존합니다. 백업 개수 정리(`PruneBackups`)는 슬롯과 동반 `.SaveTitle` 커밋이 모두 성공한 뒤에만 수행하고 시계 역행 시에도 방금 생성한 백업은 제외하는 동작이 Windows C# `SaveStore`에 적용됩니다. 반면 Python CLI/서버는 실패한 트랜잭션이 깨끗하게 롤백된 경우를 제외하고 검증된 모든 `.bak` 백업을 `backups/`에 유지합니다. 슬롯, 동반 `.SaveTitle`, 생성된 `.bak` 백업의 커밋 후 최종 검증은 모두 롤백 경계 내부에서 수행되며 C# `SaveStore`에서는 `PruneBackups` 실행 전에 수행됩니다. C# 커밋 최종 검증에서는 슬롯·동반 `.SaveTitle`·백업 파일 모두 `FILE_SHARE_READ` 검증 핸들을 열어 `PruneBackups` 및 성공 확정 시점까지 유지합니다. 외부 수정 감지나 예외로 미복구 시 검증된 `.bak` 백업을 삭제하지 않고 `backups/`에 보존합니다(백업 파일명은 ASCII 대소문자 폴딩(`A-Z -> a-z`) 및 코드 포인트 단위 정규화를 거친 `<safe_stem>__s<16hex>` 접두사를 사용하며, Linux `renameat2(RENAME_EXCHANGE)` + 설치본·밀려난 원본 해시 재검증·되교환으로 경로 교체 및 unlink 직전 재검증 시점까지의 외부 쓰기 유실을 방지하고 사전 개방 fd에 대한 최종 unlink 호출 직전 커널 미세 구간만 남기며, 윈도우는 대상 핸들 해제 직후·이름 변경 직전의 운영체제 수준 미세 경쟁 구간만 남깁니다). 모드 B/C의 `목록 새로고침`은 슬롯 드롭다운과 백업 목록만 갱신하며 저장하지 않은 메모리 내 편집 내용이나 `baseSha256` 기준 해시를 다시 불러오거나 덮어쓰지 않습니다. 브리지 초기 자동 불러오기는 `/api/slots` 도착 시점과 `/api/load` 적용 직전 모두에서 수정되지 않은 최초 세션 상태를 검증하며, `/api/slots` 또는 `/api/load` 진행 중 사용자가 수행한 로컬 파일 열기·편집·프리셋 변경을 보존합니다. 모드 A/B/C 모든 진입점은 단일 UTF-8 BOM만 허용해 이중 UTF-8 BOM을 불러오기·저장·백업 복원 전 구간에서 거부하고 엄격 UTF-8(`fatal: true` / `UTF-8` 예외 검증)로 비유효 바이트의 `U+FFFD` 손실 치환을 원천 차단하며, 파일 열기, `/api/load`, HTTP `POST /api/save`·`/api/restore` 본문 전 구간에서 이스케이프된 형태와 이스케이프되지 않은 형태의 단독 UTF-16 서로게이트(`\uD800`–`\uDFFF`)를 브라우저 `twx-codec.js`, Python, C#에서 모두 거부하며, C# `SaveStore.ValidateSaveJson`이 `JavaScriptSerializer` 실행 전에 `twx-codec.js` 및 `twx_editor.py`와 동일한 엄격 RFC 8259 JSON 구문 문법을 강제하고 POSIX CLI·슬롯 경로는 리터럴 역슬래시(`\`) 구분자 모호성을 사전에 거부합니다.
- **경로 경계 유지 · 심볼릭 링크 · 대체 데이터 스트림 차단**: 상위 조상 경로 전체의 심볼릭 링크·정션·재분석 지점(최상위 조상부터 단계별 `O_NOFOLLOW` / `FILE_FLAG_OPEN_REPARSE_POINT` 핸들 체인 검증 포함), 루트 외부 경로(`..`), 하드링크, CLI `inspect`·`validate` 및 저장·목록 조회·백업 복원 전 구간의 `backups` 디렉터리와 `backups/<백업파일>`을 포함한 모든 경로 대소문자 충돌(윈도우 대소문자 구분 디렉터리 및 기존 대문자 `Backups` 폴더 선행 차단 포함), 예약 장치명(`CON`, `NUL` 등), 대체 데이터 스트림(`:`), 윈도우 NTFS 8.3 단축 파일·디렉터리 별칭 및 후행 공백·마침표 별칭, POSIX 비정규 파일(`O_NONBLOCK` 검증)을 차단하며, POSIX CLI·슬롯 경로는 리터럴 역슬래시(`\`) 구분자 모호성을 사전에 거부하고, `.twx_store.lock`의 재분석 지점 미추적(`O_NOFOLLOW` / `FILE_FLAG_OPEN_REPARSE_POINT`)·정확 최종 경로 일치 검증 및 신규 하위 디렉터리(`backups/` 등) 생성 시 상위 디렉터리 `fsync`를 수행하고, `WeakMap` 기반 무손실 코덱 메타데이터 분리(자체 프로퍼티 서술자 조회 포함)로 특수 JSON 키(`__proto__`, `__twxMeta` 등) 충돌·원시 토큰 유실을 원천 차단합니다. 자동 탐색(`discover`, 기본 `serve`, 데스크톱 자동 탐색)은 `~/.local/share/Steam` 등을 우선 검사하고 Linux `~/.steam/steam` 기본 심볼릭 링크는 재분석 지점이 없는 실체 Steam 루트로만 해석하되 `userdata`·`remote`·`SaveData` 이하의 심볼릭 링크·재분석 지점·별칭 후보는 건너뛰어 검증된 실제 디렉터리만 선택하며, 명시적 `--root` 및 `TWX_SAVE_ROOT` 지정 시에는 모든 심볼릭 링크·재분석 지점·별칭을 즉시 거부합니다.
- **엄격한 오프라인·루프백 격리**: 단일 HTML 번들은 `default-src 'none'; connect-src 'none'` 정책으로 외부 통신을 완전히 차단하며, 로컬 브리지는 `127.0.0.1` 바인딩과 세션별 난수 토큰(`X-TWX-Token`)·출처(`Origin`/`Host`/`Sec-Fetch-Site`) 검증을 강제합니다.

---

## 빌드 및 테스트

```bash
# 카탈로그 무결성 검증 및 단일 HTML 번들 생성
python3 -B tools/extract_catalog.py --check-only
python3 -B build.py && python3 -B build.py --check

# 코덱·코어 및 파이썬 CLI·서버 단위 테스트
node tests/test_editor.cjs
python3 -W error -B -m unittest discover -s tests -v
```

---

## 라이선스

- 본 프로젝트 소스 코드는 [MIT License](LICENSE)를 따릅니다.
- 윈도우 실행 파일 배포본에 포함된 `Microsoft.Web.WebView2` 구성 요소의 재배포 조건은 동봉된 `WebView2-LICENSE.txt`를 따릅니다.
