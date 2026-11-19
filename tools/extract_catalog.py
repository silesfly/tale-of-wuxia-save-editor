#!/usr/bin/env python3
"""협객풍운전 한국어 패치 1.32 데이터 추출 및 무결성 검증 스크립트 (src/catalog-data.js)."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

HANZI_RE = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]")
KANA_RE = re.compile(r"[\u3040-\u30FF\u31F0-\u31FF\uFF66-\uFF9F]")
UI_TAG_RE = re.compile(r"\[[0-9A-Fa-f]{6,8}\]|\[-\]|<br\s*/?>", re.IGNORECASE)
PERSONAL_PATH_RE = re.compile(r"(?:/home/|c:\\users\\)", re.IGNORECASE)
UI_FIELDS = {"name", "tip", "desc", "title", "intro", "place"}

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "src" / "catalog-data.js"

FALLBACK_EXP = {"1": 23000, "2": 37000, "3": 55000, "4": 80000, "5": 100000}
DEVELOP_FALLBACK = {
    20006: "내공", 30001: "소요곡", 30002: "삼림", 30003: "호반", 30004: "망우곡",
    30005: "성진", 30006: "시집", 30007: "주관", 30008: "다관", 30009: "격투장",
    70014: "쌍무", 80001: "잡일", 80002: "기본공", 80003: "무예", 80004: "생산",
    80005: "망우곡", 80006: "휴식", 80007: "역참", 80008: "산책", 80009: "상점",
}
NPC_EXTRA_IDS = {
    100008, 100015, 100016, 100017, 100019, 100021, 100026, 100027, 100028,
    100029, 100030, 100031, 100033, 100035, 100036, 100037, 100043, 100054,
    100055, 100056, 100057, 100058, 100059, 100060, 100061, 100062, 100065,
    100066, 100072, 100075, 100078, 100081, 100082, 100085, 100089, 100091,
    100092, 100094, 100096, 100098, 100134, 100135, 100297, 100299, 100419,
    990013, 990031,
}
PROPERTY_GROUPS = [
    {"type": 0, "name": "기본 속성", "attrs": [
        {"index": 0, "name": "실전", "max": 500},
        {"index": 1, "name": "무학", "max": 500},
        {"index": 2, "name": "도덕", "max": 500},
        {"index": 3, "name": "명성", "max": 500},
        {"index": 4, "name": "오성", "max": 100},
        {"index": 5, "name": "기혈", "max": 9999},
        {"index": 6, "name": "내력", "max": 9999},
    ]},
    {"type": 1, "name": "기본공", "attrs": [
        {"index": 0, "name": "안공", "max": 100},
        {"index": 1, "name": "이공", "max": 100},
        {"index": 2, "name": "연공", "max": 100},
        {"index": 3, "name": "강공", "max": 100},
        {"index": 4, "name": "경공", "max": 100},
        {"index": 5, "name": "내공", "max": 100},
    ]},
    {"type": 2, "name": "초식 숙련", "attrs": [
        {"index": 0, "name": "권장", "max": 100},
        {"index": 1, "name": "지법", "max": 100},
        {"index": 2, "name": "퇴법", "max": 100},
        {"index": 3, "name": "검법", "max": 100},
        {"index": 4, "name": "도법", "max": 100},
        {"index": 5, "name": "곤법", "max": 100},
        {"index": 6, "name": "단병", "max": 100},
        {"index": 7, "name": "암기", "max": 100},
        {"index": 8, "name": "금공", "max": 100},
        {"index": 9, "name": "쌍무", "max": 100},
    ]},
    {"type": 3, "name": "생산 기술", "attrs": [
        {"index": 0, "name": "채광", "max": 100},
        {"index": 1, "name": "수렵", "max": 100},
        {"index": 2, "name": "낚시", "max": 100},
        {"index": 3, "name": "채집", "max": 100},
        {"index": 4, "name": "연단", "max": 100},
        {"index": 5, "name": "제련", "max": 100},
        {"index": 6, "name": "감정", "max": 100},
        {"index": 7, "name": "책략", "max": 100},
        {"index": 8, "name": "요리", "max": 100},
    ]},
    {"type": 4, "name": "문예 기예", "attrs": [
        {"index": 0, "name": "악리", "max": 100},
        {"index": 1, "name": "기예", "max": 100},
        {"index": 2, "name": "독술", "max": 100},
        {"index": 3, "name": "의술", "max": 100},
        {"index": 4, "name": "회화", "max": 100},
        {"index": 5, "name": "서법", "max": 100},
        {"index": 6, "name": "주예", "max": 100},
        {"index": 7, "name": "화훼", "max": 100},
        {"index": 8, "name": "다도", "max": 100},
    ]},
]
SHICHEN = [{"id": i + 1, "name": n} for i, n in enumerate(
    ["자시", "축시", "인시", "묘시", "진시", "사시", "오시", "미시", "신시", "유시", "술시", "해시"]
)]
DIFFICULTIES = [
    {"id": 0, "name": "유인원"}, {"id": 1, "name": "초심자"},
    {"id": 2, "name": "숙련자"}, {"id": 3, "name": "일대종사"},
]
SEASONS = [
    {"id": 0, "name": "봄"}, {"id": 1, "name": "여름"},
    {"id": 2, "name": "가을"}, {"id": 3, "name": "겨울"},
]
WEAR_AMS_TYPES = {
    "0": "기타", "1": "권장", "2": "지법", "3": "퇴법", "4": "검법",
    "5": "도법", "6": "곤법", "7": "단병", "8": "암기", "9": "금공", "10": "쌍무",
}
ITEM_KINDS = {
    "0": "특수·열쇠", "1": "장비(무기·방어구·장신구)",
    "2": "소모품·단약·음식", "3": "서책·골동·선물",
    "4": "수렵·채집 도구", "5": "광석·약재·재료",
}


def clean_text(s: Any, strip_tags: bool = True) -> str:
    if s is None:
        return ""
    text = str(s).replace("\r", "").replace("\u00a0", " ")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"\([^)]*" + HANZI_RE.pattern + r"[^)]*\)", "", text)
    text = re.sub(r"（[^）]*" + HANZI_RE.pattern + r"[^）]*）", "", text)
    text = HANZI_RE.sub("", text)
    text = KANA_RE.sub("", text)
    if strip_tags:
        text = re.sub(r"\[[0-9A-Fa-f]{6,8}\]", "", text)
        text = text.replace("[-]", "")
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = "\n".join(line.strip() for line in text.split("\n")).strip()
    return text


def to_int(v: Any, default: int = 0) -> int:
    if v is None:
        return default
    raw = str(v).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        try:
            return int(float(raw))
        except ValueError:
            return default


def read_tsv(path: Path) -> list[list[str]]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return []
    enc = None
    if raw.startswith(b"\xff\xfe"):
        enc = "utf-16-le"
    elif raw.startswith(b"\xfe\xff"):
        enc = "utf-16-be"
    elif raw.startswith(b"\xef\xbb\xbf"):
        enc = "utf-8-sig"
    text = None
    if enc:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            text = None
    if text is None:
        for candidate in ("utf-8", "utf-16-le", "cp949", "gb18030"):
            try:
                text = raw.decode(candidate)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = raw.decode("utf-8", errors="replace")
    rows: list[list[str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        cols = line.split("\t")
        if cols and "#" in cols[0]:
            continue
        rows.append(cols)
    return rows


def default_data_dir() -> Path:
    env = os.environ.get("TWX_DATA_DIR")
    if env:
        return Path(env).expanduser()
    for rel in (
        Path("data/Mods/1.0.3.2/Config/Textfiles"),
        Path("../tale-of-wuxia-data/patch_zip/Mods/1.0.3.2/Config/Textfiles"),
    ):
        if rel.exists():
            return rel
    return Path.home() / "workspace/무협위키/.local/graph/tale-of-wuxia-data/patch_zip/Mods/1.0.3.2/Config/Textfiles"


def parse_pairs(s: str, arity: int) -> list[list[int]]:
    if not s or s.strip() == "0":
        return []
    pat = r"\(" + r",".join([r"([^,()]+)"] * arity) + r"\)"
    return [[to_int(x) for x in m] for m in re.findall(pat, s)]


def parse_js_catalog(text: str) -> dict[str, Any]:
    marker = "root.TWX_CATALOG = "
    start = text.find(marker)
    if start < 0:
        raise ValueError("TWX_CATALOG 할당 구문을 찾을 수 없습니다.")
    start += len(marker)
    end = text.find("; if (typeof module", start)
    if end < 0:
        end = text.find(";\n", start)
    if end < 0:
        raise ValueError("TWX_CATALOG 종료 구분자를 찾을 수 없습니다.")
    return json.loads(text[start:end])


def iter_strings(obj: Any, key: str | None = None) -> Iterable[tuple[str | None, str]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield None, str(k)
            yield from iter_strings(v, str(k))
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_strings(v, key)
    elif isinstance(obj, str):
        yield key, obj


def check_catalog(path: Path) -> int:
    if not path.exists():
        print(f"오류: 카탈로그 파일이 없습니다: {path}", file=sys.stderr)
        return 1
    raw_js = path.read_text(encoding="utf-8")
    if PERSONAL_PATH_RE.search(raw_js):
        print("오류: 개인 경로 문자열이 카탈로그 파일에 포함되어 있습니다.", file=sys.stderr)
        return 1
    try:
        cat = parse_js_catalog(raw_js)
    except Exception as exc:
        print(f"오류: 카탈로그 파싱 실패: {exc}", file=sys.stderr)
        return 1
    required = {
        "items": (800, False),
        "routines": (150, False),
        "neigongs": (23, False),
        "talents": (25, True),
        "titles": (42, True),
        "achievements": (160, False),
        "maps": (34, False),
        "npcs": (45, False),
        "developBtns": (70, False),
    }
    for key, (minimum, exact) in required.items():
        value = cat.get(key, [])
        size = len(value) if isinstance(value, (list, dict)) else 0
        if exact and size != minimum:
            print(f"오류: {key} 개수 불일치 (기대: {minimum}, 실제: {size})", file=sys.stderr)
            return 1
        if not exact and size < minimum:
            print(f"오류: {key} 개수 부족 (최소: {minimum}, 실제: {size})", file=sys.stderr)
            return 1
    hanzi = kana = tags = paths = 0
    for key, value in iter_strings(cat):
        if HANZI_RE.search(value):
            hanzi += 1
        if KANA_RE.search(value):
            kana += 1
        if key in UI_FIELDS and UI_TAG_RE.search(value):
            tags += 1
        if PERSONAL_PATH_RE.search(value):
            paths += 1
    if hanzi or kana or tags or paths:
        print(f"오류: Hanzi={hanzi}, Kana={kana}, Tags={tags}, PersonalPaths={paths}", file=sys.stderr)
        return 1
    print(f"OK (Hanzi: 0, Kana: 0, Tags: 0, Items: {len(cat.get('items', []))}, Routines: {len(cat.get('routines', []))}, Neigongs: {len(cat.get('neigongs', []))}, Achievements: {len(cat.get('achievements', []))})")
    return 0


def build_catalog(data_dir: Path) -> dict[str, Any]:
    item_rows = read_tsv(data_dir / "ItemData.txt")
    ability_rows = read_tsv(data_dir / "AbilityBookData.txt")
    routine_rows = read_tsv(data_dir / "RoutineData.txt")
    neigong_rows = read_tsv(data_dir / "BattleNeigong.txt")
    neigong_up_rows = read_tsv(data_dir / "NeigongUpValue.txt")
    talent_rows = read_tsv(data_dir / "TalentData.txt")
    title_rows = read_tsv(data_dir / "TitleData.txt")
    npc_rows = read_tsv(data_dir / "NpcData.txt")
    battle_rows = read_tsv(data_dir / "BattleCharacterData.txt")
    map_rows = read_tsv(data_dir / "MapID.txt")
    develop_rows = read_tsv(data_dir / "DevelopBtnData.txt")
    chest_rows = read_tsv(data_dir / "TreasureBox.txt")
    achievement_rows = read_tsv(data_dir / "AchievementData.txt")
    string_rows = read_tsv(data_dir / "String_table.txt")
    exp_rows = read_tsv(data_dir / "RoutineExp.txt")

    routine_exp = dict(FALLBACK_EXP)
    for r in exp_rows:
        if r:
            vals = [to_int(x, 0) for x in r[1:11]]
            if vals and max(vals) > 0:
                routine_exp[str(to_int(r[0]))] = max(vals)

    string_map: dict[int, str] = {}
    for r in string_rows:
        if len(r) >= 3:
            string_map[to_int(r[0])] = clean_text(r[2])

    ability_books: list[dict[str, Any]] = []
    ability_tip_by_routine: dict[str, str] = {}
    ability_link_by_routine: set[str] = set()
    for r in ability_rows:
        if len(r) < 6:
            r = r + [""] * (6 - len(r))
        ab_type = to_int(r[1])
        link = str(r[5]).strip()
        tip_clean = clean_text(r[3]).replace("\n", " ")
        raw_msg = clean_text(r[3], strip_tags=True).replace("\n", "<br>")
        if ab_type >= 18:
            ability_books.append({
                "id": to_int(r[0]),
                "abilityType": ab_type,
                "name": clean_text(r[2]),
                "tip": tip_clean,
                "rawMsg": raw_msg,
                "image": clean_text(r[4]),
                "link": link,
            })
        if ab_type >= 19 and link:
            ability_link_by_routine.add(link)
            if link not in ability_tip_by_routine:
                ability_tip_by_routine[link] = tip_clean

    items: list[dict[str, Any]] = []
    item_name_by_id: dict[int, str] = {}
    for r in item_rows:
        if len(r) < 32:
            r = r + [""] * (32 - len(r))
        iid = to_int(r[0])
        if iid <= 0:
            continue
        name = clean_text(r[1])
        item_name_by_id[iid] = name
        tip = clean_text(r[5]).replace("\n", " ")
        status_tip = clean_text(r[30]).replace("\n", " ")
        effects = []
        for base in (13, 17, 21):
            if to_int(r[base]) != 0:
                effects.append({
                    "m_iItemType": to_int(r[base]),
                    "m_iRecoverType": to_int(r[base + 1]),
                    "m_iValue": to_int(r[base + 2]),
                    "m_iMsgID": to_int(r[base + 3]),
                })
        node = {
            "m_iItemID": iid,
            "m_strItemName": name,
            "m_iItemKind": to_int(r[2]),
            "m_iItemType": to_int(r[3]),
            "m_strIcon": clean_text(r[4]),
            "m_strTip": clean_text(r[5], strip_tags=False),
            "m_iItemBuy": to_int(r[6]),
            "m_iItemSell": to_int(r[7]),
            "m_iItemStack": to_int(r[8]),
            "m_iMixStack": to_int(r[9]),
            "m_iItemUse": to_int(r[10]),
            "m_iUseTime": to_int(r[11]),
            "m_iAddType": to_int(r[12]),
            "m_iUseMsgID": to_int(r[25]),
            "m_iArtistryID": to_int(r[26]),
            "m_iAmsType": to_int(r[27]),
            "m_strNpcLikeList": [
                {"m_iNpcID": a, "m_iValue": b} for a, b in parse_pairs(r[28], 2)
            ],
            "m_UseLimitNodeList": [
                {"m_iType": a, "m_iInde": b, "m_iValue": c} for a, b, c in parse_pairs(r[29], 3)
            ],
            "m_ItmeEffectNodeList": effects,
            "m_strStatusTip": clean_text(r[30], strip_tags=False) or "0",
            "m_iLock": to_int(r[31]),
        }
        items.append({
            "id": iid,
            "name": name,
            "kind": to_int(r[2]),
            "itemType": to_int(r[3]),
            "amsType": to_int(r[27]),
            "buy": to_int(r[6]),
            "sell": to_int(r[7]),
            "tip": tip,
            "statusTip": status_tip or "0",
            "node": node,
        })

    routines: list[dict[str, Any]] = []
    for r in routine_rows:
        if len(r) < 11:
            r = r + [""] * (11 - len(r))
        iid = to_int(r[0])
        if iid <= 0:
            continue
        model = r[2].strip()
        usable = (
            model == "Player"
            or iid >= 70000
            or iid == 10708
            or str(iid) in ability_link_by_routine
        )
        routines.append({
            "id": iid,
            "name": clean_text(r[1]),
            "wearAmsType": to_int(r[3]),
            "expCurve": to_int(r[9], 3) or 3,
            "icon": clean_text(r[10]),
            "playerUsable": bool(usable),
            "tip": ability_tip_by_routine.get(str(iid), ""),
        })

    neigong_up_ids = {to_int(r[0]) for r in neigong_up_rows if r}
    neigong_names: dict[str, str] = {}
    neigongs: list[dict[str, Any]] = []
    for r in neigong_rows:
        if len(r) < 7:
            r = r + [""] * (7 - len(r))
        iid = to_int(r[0])
        if iid <= 0:
            continue
        name = clean_text(r[1])
        neigong_names[str(iid)] = name
        sel_img = clean_text(r[5])
        stat_img = clean_text(r[6])
        neigongs.append({
            "id": iid,
            "name": name,
            "desc": clean_text(r[2]).replace("\n", " "),
            "expCurve": to_int(r[3], 1) or 1,
            "selectImage": sel_img if sel_img and sel_img != "0" else "NeigongImage02",
            "statusImage": stat_img if stat_img and stat_img != "0" else "NeigongImage22",
            "playerUsable": bool(iid in neigong_up_ids or (sel_img and sel_img != "0")),
        })

    talents = []
    for r in talent_rows:
        if len(r) >= 5 and to_int(r[0]) > 0:
            talents.append({
                "id": to_int(r[0]),
                "slot": to_int(r[1]),
                "name": clean_text(r[3]),
                "tip": clean_text(r[4]).replace("\n", " "),
            })

    titles = []
    for r in title_rows:
        if len(r) >= 3 and to_int(r[0]) > 0:
            titles.append({
                "id": to_int(r[0]),
                "name": clean_text(r[1]),
                "tip": clean_text(r[2]).replace("\n", " "),
            })

    npcs = []
    for r in npc_rows:
        if len(r) < 12:
            r = r + [""] * (12 - len(r))
        iid = to_int(r[0])
        if iid <= 0:
            continue
        if to_int(r[4]) == 1 or iid in NPC_EXTRA_IDS:
            npcs.append({
                "id": iid,
                "name": clean_text(r[5]),
                "title": clean_text(r[11]),
                "intro": clean_text(r[6]).replace("\n", " "),
                "gender": to_int(r[9]),
            })

    companions: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    has_protag = False
    for r in battle_rows:
        if len(r) < 6:
            r = r + [""] * (6 - len(r))
        cid = to_int(r[0])
        if cid <= 0:
            continue
        cname = clean_text(r[1])
        if cid == 10001401:
            has_protag = True
        elif cname in seen_names or len(companions) >= 90:
            continue
        seen_names.add(cname)
        companions.append({
            "charId": cid,
            "name": cname,
            "rank": clean_text(r[2]),
            "hp": to_int(r[4]),
            "sp": to_int(r[5]),
        })
    if not has_protag:
        companions.insert(0, {"charId": 10001401, "name": "동방미명", "rank": "인", "hp": 1200, "sp": 800})

    maps = []
    map_name_by_id: dict[str, str] = {}
    for r in map_rows:
        if len(r) >= 2 and r[0].strip():
            mid = r[0].strip()
            mname = clean_text(r[1])
            maps.append({"id": mid, "name": mname})
            map_name_by_id[mid] = mname

    develop_btns = []
    for r in develop_rows:
        if not r or to_int(r[0]) <= 0:
            continue
        iid = to_int(r[0])
        remark = r[1] if len(r) > 1 else ""
        m = re.search(r"\((\d+)\)", remark)
        if m and int(m.group(1)) in string_map:
            name = string_map[int(m.group(1))]
        elif str(iid) in neigong_names:
            name = neigong_names[str(iid)]
        elif iid in DEVELOP_FALLBACK:
            name = DEVELOP_FALLBACK[iid]
        else:
            name = clean_text(remark) or f"육성행동 {iid}"
        develop_btns.append({
            "id": iid,
            "name": name,
            "btnType": to_int(r[23]) if len(r) > 23 else 0,
        })

    chests = []
    for r in chest_rows:
        if not r or not r[0].strip():
            continue
        box_id = r[0].strip()
        item_name = ""
        for cell in r[1:]:
            t = cell.strip()
            if re.fullmatch(r"\d{6}", t) and int(t) in item_name_by_id:
                item_name = item_name_by_id[int(t)]
                break
        map_id = box_id[:5]
        map_label = map_name_by_id.get(map_id, map_id)
        label = f"{map_label} 상자 ({box_id})" + (f" · {item_name}" if item_name else "")
        chests.append({"id": box_id, "mapId": map_id, "name": label})

    achievements = []
    for r in achievement_rows:
        if len(r) < 9 or to_int(r[1]) <= 0:
            continue
        achievements.append({
            "id": to_int(r[1]),
            "type": to_int(r[0]),
            "name": clean_text(r[2]),
            "desc": clean_text(r[3]).replace("\n", " "),
            "endMove": to_int(r[5]),
            "targetCount": max(1, to_int(r[8], 1)),
        })

    return {
        "meta": {"game": "협객풍운전", "version": "1.0.3.2", "steamAppId": 377530},
        "propertyGroups": PROPERTY_GROUPS,
        "timeIntervals": ["초", "상순", "중순", "하순", "말"],
        "shichen": SHICHEN,
        "difficulties": DIFFICULTIES,
        "seasons": SEASONS,
        "wearAmsTypes": WEAR_AMS_TYPES,
        "itemKinds": ITEM_KINDS,
        "routineExp": routine_exp,
        "items": items,
        "abilityBooks": ability_books,
        "routines": routines,
        "neigongs": neigongs,
        "talents": talents,
        "titles": titles,
        "npcs": npcs,
        "companions": companions,
        "maps": maps,
        "developBtns": develop_btns,
        "chests": chests,
        "achievements": achievements,
    }


def write_catalog(catalog: dict[str, Any], out_path: Path) -> None:
    payload = json.dumps(catalog, ensure_ascii=True, separators=(",", ":"))
    text = (
        "/* 자동 생성 파일 — tools/extract_catalog.py */\n"
        '(function (root) { "use strict"; root.TWX_CATALOG = '
        + payload
        + '; if (typeof module === "object" && module.exports) { module.exports = root.TWX_CATALOG; } })(typeof globalThis !== "undefined" ? globalThis : window);\n'
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{out_path.name}.", dir=str(out_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fp:
            fp.write(text)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp, out_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv: list[str]) -> int:
    if "--check-only" in argv:
        return check_catalog(OUT_PATH)
    data_dir = Path(argv[1]).expanduser() if len(argv) > 1 and not argv[1].startswith("-") else default_data_dir()
    if not data_dir.exists():
        print(f"오류: 패치 데이터 경로를 찾을 수 없습니다: {data_dir}", file=sys.stderr)
        return 1
    catalog = build_catalog(data_dir)
    write_catalog(catalog, OUT_PATH)
    return check_catalog(OUT_PATH)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
