#!/usr/bin/env python3
"""협객풍운전 세이브 에디터 CLI 및 로컬 루프백 브리지 서버 (Python 3.10+ 표준 라이브러리 전용)."""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import datetime
import errno
import hashlib
import hmac
import json
import math
import os
import platform
import re
import secrets
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
CATALOG_PATH = BASE_DIR / "src" / "catalog-data.js"
DIST_HTML_PATH = BASE_DIR / "dist" / "TaleOfWuxiaSaveEditor-v1.0.html"
MAX_SAVE_BYTES = 16 * 1024 * 1024
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
RESERVED_DEVICES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

DEFAULT_PROPERTY_GROUPS = [
    {"type": 0, "name": "기본 속성", "attrs": [
        {"index": 0, "name": "실전", "max": 500}, {"index": 1, "name": "무학", "max": 500},
        {"index": 2, "name": "도덕", "max": 500}, {"index": 3, "name": "명성", "max": 500},
        {"index": 4, "name": "오성", "max": 100}, {"index": 5, "name": "기혈", "max": 9999},
        {"index": 6, "name": "내력", "max": 9999},
    ]},
    {"type": 1, "name": "기본공", "attrs": [
        {"index": i, "name": n, "max": 100}
        for i, n in enumerate(["안공", "이공", "연공", "강공", "경공", "내공"])
    ]},
    {"type": 2, "name": "초식 숙련", "attrs": [
        {"index": i, "name": n, "max": 100}
        for i, n in enumerate(["권장", "지법", "퇴법", "검법", "도법", "곤법", "단병", "암기", "금공", "쌍무"])
    ]},
    {"type": 3, "name": "생산 기술", "attrs": [
        {"index": i, "name": n, "max": 100}
        for i, n in enumerate(["채광", "수렵", "낚시", "채집", "연단", "제련", "감정", "책략", "요리"])
    ]},
    {"type": 4, "name": "문예 기예", "attrs": [
        {"index": i, "name": n, "max": 100}
        for i, n in enumerate(["악리", "기예", "독술", "의술", "회화", "서법", "주예", "화훼", "다도"])
    ]},
]

PRESETS = {
    "max_money": {"kind": "save", "name": "은전 최대 (9,999,999전)", "desc": "보유 금전을 9,999,999전으로 설정합니다."},
    "max_core_stats": {"kind": "save", "name": "기본 속성·기혈·내력 만능", "desc": "실전·무학·명성 500, 도덕·오성 100, 기혈·내력 9,999 및 기본 공방을 강화합니다."},
    "max_martial_arts": {"kind": "save", "name": "6대 기본공·10대 초식 숙련 100", "desc": "기본공 6종과 초식 숙련 10종을 모두 100으로 설정합니다."},
    "max_life_arts": {"kind": "save", "name": "생산·문예 18대 기예 100", "desc": "생산 기술·문예 기예 18종을 100으로 완성하고 육성 행동을 개방합니다."},
    "max_routines_neigongs": {"kind": "save", "name": "보유 투로·심법 전원 10성 만렙", "desc": "보유 중인 모든 투로와 내공 심법을 10성 최대 경험치로 설정합니다."},
    "max_friendship": {"kind": "save", "name": "등장 인물 전원 생사고락 (호감도 100)", "desc": "모든 주요 인물의 호감도를 100으로 설정합니다."},
    "unlock_all_achievements": {"kind": "round", "name": "전역 164종 업적·성당 특전 7점 해금", "desc": "공식 업적 164종을 모두 달성 처리하고 성당 특전 7점을 해금합니다."},
    "unlock_guid_talents_chests": {"kind": "guid", "name": "회차 천부·111개 보물상자 전체 개방", "desc": "회차 천부와 111개 보물상자를 모두 개방합니다."},
}


def _esc_ptr(seg: str) -> str:
    return seg.replace("~", "~0").replace("/", "~1")


def parse_json_lossless(raw_text: str) -> tuple[Any, dict[str, Any]]:
    has_bom = raw_text.startswith("\ufeff")
    text = raw_text[1:] if has_bom else raw_text
    if text.startswith("\ufeff"): raise ValueError("이중 UTF-8 BOM은 허용되지 않습니다.")
    if text.endswith("\r\n"):
        trailing_newline = "\r\n"
    elif text.endswith("\n"):
        trailing_newline = "\n"
    else:
        trailing_newline = ""

    raw_tokens: dict[str, tuple[type, Any, str]] = {}
    arr_tokens: dict[int, list[tuple[type, Any, str] | None]] = {}
    idx = 0
    length = len(text)

    def fail(msg: str, pos: int | None = None) -> ValueError:
        if pos is None:
            pos = idx
        return ValueError(f"{msg} (위치 {pos})")

    def skip_ws() -> None:
        nonlocal idx
        while idx < length and text[idx] in " \t\r\n":
            idx += 1

    def is_digit(ch: str) -> bool:
        return "0" <= ch <= "9"

    def hex_value(ch: str) -> int:
        if "0" <= ch <= "9":
            return ord(ch) - ord("0")
        if "a" <= ch <= "f":
            return ord(ch) - ord("a") + 10
        if "A" <= ch <= "F":
            return ord(ch) - ord("A") + 10
        raise fail("유니코드 이스케이프가 올바르지 않습니다.")

    def parse_string_value() -> tuple[str, str]:
        nonlocal idx
        start = idx
        if idx >= length or text[idx] != '"':
            raise fail("문자열이 필요합니다.")
        idx += 1
        parts: list[str] = []
        while idx < length:
            ch = text[idx]
            if ch == '"':
                idx += 1
                return "".join(parts), text[start:idx]
            if ch == "\\":
                idx += 1
                if idx >= length:
                    raise fail("문자열 이스케이프가 불완전합니다.", start)
                esc = text[idx]
                if esc == '"':
                    parts.append('"')
                    idx += 1
                elif esc == "\\":
                    parts.append("\\")
                    idx += 1
                elif esc == "/":
                    parts.append("/")
                    idx += 1
                elif esc == "b":
                    parts.append("\b")
                    idx += 1
                elif esc == "f":
                    parts.append("\f")
                    idx += 1
                elif esc == "n":
                    parts.append("\n")
                    idx += 1
                elif esc == "r":
                    parts.append("\r")
                    idx += 1
                elif esc == "t":
                    parts.append("\t")
                    idx += 1
                elif esc == "u":
                    if idx + 4 >= length:
                        raise fail("유니코드 이스케이프가 불완전합니다.", start)
                    code = 0
                    for k in range(1, 5):
                        code = (code << 4) | hex_value(text[idx + k])
                    idx += 5
                    if 0xD800 <= code <= 0xDBFF:
                        if idx + 1 >= length or text[idx] != "\\" or text[idx + 1] != "u":
                            raise fail("유니코드 대리쌍이 올바르지 않습니다.", start)
                        if idx + 6 > length:
                            raise fail("유니코드 이스케이프가 불완전합니다.", start)
                        low = 0
                        for k in range(2, 6):
                            low = (low << 4) | hex_value(text[idx + k])
                        if not (0xDC00 <= low <= 0xDFFF):
                            raise fail("유니코드 대리쌍이 올바르지 않습니다.", start)
                        code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
                        idx += 6
                    elif 0xDC00 <= code <= 0xDFFF:
                        raise fail("유니코드 대리쌍이 올바르지 않습니다.", start)
                    parts.append(chr(code))
                else:
                    raise fail("알 수 없는 문자열 이스케이프입니다.", idx)
            else:
                if ord(ch) < 0x20:
                    raise fail("문자열에 제어 문자가 포함되어 있습니다.", idx)
                if 0xD800 <= ord(ch) <= 0xDFFF:
                    raise fail("유니코드 대리쌍이 올바르지 않습니다.", idx)
                parts.append(ch)
                idx += 1
        raise fail("문자열이 닫히지 않았습니다.", start)

    def parse_number_value() -> tuple[int | float, str]:
        nonlocal idx
        start = idx
        if idx < length and text[idx] == "-":
            idx += 1
        if idx >= length:
            raise fail("숫자가 올바르지 않습니다.", start)
        if text[idx] == "0":
            idx += 1
            if idx < length and is_digit(text[idx]):
                raise fail("숫자 앞자리에 0이 올 수 없습니다.", start)
        elif "1" <= text[idx] <= "9":
            idx += 1
            while idx < length and is_digit(text[idx]):
                idx += 1
        else:
            raise fail("숫자가 올바르지 않습니다.", start)
        is_float = False
        if idx < length and text[idx] == ".":
            is_float = True
            idx += 1
            if idx >= length or not is_digit(text[idx]):
                raise fail("소수점 뒤에 숫자가 필요합니다.", start)
            while idx < length and is_digit(text[idx]):
                idx += 1
        if idx < length and text[idx] in "eE":
            is_float = True
            idx += 1
            if idx < length and text[idx] in "+-":
                idx += 1
            if idx >= length or not is_digit(text[idx]):
                raise fail("지수 표기가 올바르지 않습니다.", start)
            while idx < length and is_digit(text[idx]):
                idx += 1
        raw = text[start:idx]
        if is_float:
            return float(raw), raw
        return int(raw), raw

    def parse_value(ptr: str) -> Any:
        nonlocal idx
        skip_ws()
        if idx >= length:
            raise fail("JSON 값이 필요합니다.")
        ch = text[idx]
        if ch == "{":
            return parse_object(ptr)
        if ch == "[":
            return parse_array(ptr)
        if ch == '"':
            value, raw = parse_string_value()
            raw_tokens[ptr] = (str, value, raw)
            return value
        if ch == "t":
            if text.startswith("true", idx):
                raw_tokens[ptr] = (bool, True, "true")
                idx += 4
                return True
            raise fail("true 리터럴이 올바르지 않습니다.")
        if ch == "f":
            if text.startswith("false", idx):
                raw_tokens[ptr] = (bool, False, "false")
                idx += 5
                return False
            raise fail("false 리터럴이 올바르지 않습니다.")
        if ch == "n":
            if text.startswith("null", idx):
                raw_tokens[ptr] = (type(None), None, "null")
                idx += 4
                return None
            raise fail("null 리터럴이 올바르지 않습니다.")
        if ch == "-" or is_digit(ch):
            value, raw = parse_number_value()
            raw_tokens[ptr] = (type(value), value, raw)
            return value
        raise fail("알 수 없는 JSON 값입니다.")

    def parse_object(ptr: str) -> dict[str, Any]:
        nonlocal idx
        obj: dict[str, Any] = {}
        idx += 1
        skip_ws()
        if idx < length and text[idx] == "}":
            idx += 1
            return obj
        while True:
            skip_ws()
            if idx >= length or text[idx] != '"':
                raise fail("객체 키 문자열이 필요합니다.")
            key, _ = parse_string_value()
            skip_ws()
            if idx >= length or text[idx] != ":":
                raise fail("객체 키 뒤에 콜론이 필요합니다.")
            idx += 1
            child_ptr = ptr + "/" + _esc_ptr(key)
            obj[key] = parse_value(child_ptr)
            skip_ws()
            if idx >= length:
                raise fail("객체가 닫히지 않았습니다.")
            if text[idx] == "}":
                idx += 1
                return obj
            if text[idx] != ",":
                raise fail("객체 항목 구분에 쉼표가 필요합니다.")
            idx += 1

    def parse_array(ptr: str) -> list[Any]:
        nonlocal idx
        arr: list[Any] = []
        elem_tokens: list[tuple[type, Any, str] | None] = []
        idx += 1
        skip_ws()
        if idx < length and text[idx] == "]":
            idx += 1
            arr_tokens[id(arr)] = elem_tokens
            return arr
        pos = 0
        while True:
            elem_path = f"{ptr}/{pos}"
            arr.append(parse_value(elem_path))
            elem_tokens.append(raw_tokens.get(elem_path))
            pos += 1
            skip_ws()
            if idx >= length:
                raise fail("배열이 닫히지 않았습니다.")
            if text[idx] == "]":
                idx += 1
                arr_tokens[id(arr)] = elem_tokens
                return arr
            if text[idx] != ",":
                raise fail("배열 항목 구분에 쉼표가 필요합니다.")
            idx += 1

    skip_ws()
    if idx >= length:
        raise fail("JSON 값이 필요합니다.")
    data = parse_value("")
    skip_ws()
    if idx != length:
        raise fail("JSON 뒤에 추가 문자가 있습니다.")
    return data, {
        "has_bom": has_bom,
        "trailing_newline": trailing_newline,
        "raw_tokens": raw_tokens,
        "arr_tokens": arr_tokens,
    }


def encode_jsonfx_string(s: str) -> str:
    utf16 = s.encode("utf-16-le")
    out = ['"']
    for offset in range(0, len(utf16), 2):
        u16 = struct.unpack_from("<H", utf16, offset)[0]
        if u16 == 0x22:
            out.append('\\"')
        elif u16 == 0x5C:
            out.append("\\\\")
        elif u16 == 0x08:
            out.append("\\b")
        elif u16 == 0x0C:
            out.append("\\f")
        elif u16 == 0x0A:
            out.append("\\n")
        elif u16 == 0x0D:
            out.append("\\r")
        elif u16 == 0x09:
            out.append("\\t")
        elif u16 == 0x3C:
            out.append("\\u003C")
        elif u16 < 0x20 or u16 > 0x7E:
            out.append(f"\\u{u16:04X}")
        else:
            out.append(chr(u16))
    out.append('"')
    return "".join(out)


def serialize_json_lossless(data: Any, meta: dict[str, Any] | None = None) -> str:
    meta = meta or {}
    raw_tokens: dict[str, tuple[type, Any, str]] = meta.get("raw_tokens") or {}
    arr_tokens: dict[int, list[tuple[type, Any, str] | None]] = meta.get("arr_tokens") or {}

    def enc(val: Any, ptr: str) -> str:
        if isinstance(val, dict):
            return "{" + ",".join(
                f"{encode_jsonfx_string(k)}:{enc(v, ptr + '/' + _esc_ptr(k))}" for k, v in val.items()
            ) + "}"
        if isinstance(val, list):
            if id(val) not in arr_tokens:
                return "[" + ",".join(enc(v, f"{ptr}/{i}") for i, v in enumerate(val)) + "]"
            toks = arr_tokens[id(val)]
            used = [False] * len(toks)
            cursor = 0
            out: list[str] = []
            for i, v in enumerate(val):
                if isinstance(v, (dict, list)):
                    out.append(enc(v, f"{ptr}/{i}"))
                    continue
                found: int | None = None
                matched_raw: str | None = None
                m = len(toks)
                for j in range(cursor, m):
                    tok = toks[j]
                    if used[j] or tok is None:
                        continue
                    if tok[0] is not type(v) or tok[1] != v:
                        continue
                    if isinstance(v, float) and math.isfinite(v):
                        if math.copysign(1.0, tok[1]) != math.copysign(1.0, v):
                            continue
                    found = j
                    matched_raw = tok[2]
                    break
                if found is None:
                    for j in range(0, min(cursor, m)):
                        tok = toks[j]
                        if used[j] or tok is None:
                            continue
                        if tok[0] is not type(v) or tok[1] != v:
                            continue
                        if isinstance(v, float) and math.isfinite(v):
                            if math.copysign(1.0, tok[1]) != math.copysign(1.0, v):
                                continue
                        found = j
                        matched_raw = tok[2]
                        break
                if found is not None and matched_raw is not None:
                    used[found] = True
                    if found >= cursor:
                        cursor = found + 1
                    out.append(matched_raw)
                else:
                    if v is None:
                        out.append("null")
                    elif isinstance(v, bool):
                        out.append("true" if v else "false")
                    elif isinstance(v, int):
                        out.append(str(v))
                    elif isinstance(v, float):
                        if not math.isfinite(v):
                            raise ValueError("NaN 또는 무한대 실수는 직렬화할 수 없습니다.")
                        out.append(str(v))
                    elif isinstance(v, str):
                        out.append(encode_jsonfx_string(v))
                    else:
                        raise TypeError(f"지원하지 않는 JSON 값 타입입니다: {type(v).__name__}")
            return "[" + ",".join(out) + "]"
        entry = raw_tokens.get(ptr)
        if entry is not None and entry[0] is type(val) and entry[1] == val:
            if isinstance(val, float) and math.isfinite(val):
                if math.copysign(1.0, entry[1]) != math.copysign(1.0, val):
                    entry = None
            if entry is not None:
                return entry[2]
        if val is None:
            return "null"
        if isinstance(val, bool):
            return "true" if val else "false"
        if isinstance(val, int):
            return str(val)
        if isinstance(val, float):
            if not math.isfinite(val):
                raise ValueError("NaN 또는 무한대 실수는 직렬화할 수 없습니다.")
            return str(val)
        if isinstance(val, str):
            return encode_jsonfx_string(val)
        raise TypeError(f"지원하지 않는 JSON 값 타입입니다: {type(val).__name__}")

    prefix = "\ufeff" if meta.get("has_bom") else ""
    suffix = meta.get("trailing_newline") or ""
    return prefix + enc(data, "") + suffix


def is_strict_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _as_exact_int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and math.isfinite(v) and v.is_integer():
        if v == 0.0 and math.copysign(1.0, v) < 0.0:
            return None
        iv = int(v)
        if abs(iv) <= 9007199254740991:
            return iv
    return None


def detect_kind(data: Any) -> str:
    if isinstance(data, dict):
        if "m_PropertyGroupsNodeList" in data or "m_strPlayerName" in data or "m_BackpackList" in data:
            return "save"
        if "achiFinishList" in data or "finishGuidList" in data or "iMasterLevelCount" in data:
            return "round"
        if "guid" in data and ("openTalentList" in data or "openChestList" in data or "developQuestList" in data):
            return "guid"
    if isinstance(data, list) and (len(data) == 0 or (isinstance(data[0], dict) and "m_bHaveData" in data[0])):
        return "title"
    raise ValueError("지원하지 않는 협객풍운전 세이브 데이터 형식입니다.")


def validate_data(data: Any, expected_kind: str | None = None) -> str:
    if _contains_lone_surrogate(data):
        raise ValueError("유효하지 않은 유니코드 서로게이트가 포함되어 있습니다.")
    kind = detect_kind(data)
    if expected_kind and kind != expected_kind:
        raise ValueError(f"예상한 형식({expected_kind})과 실제 형식({kind})이 일치하지 않습니다.")

    def req_int(val: Any, low: int, high: int, label: str) -> None:
        iv = _as_exact_int(val)
        if iv is None or iv < low or iv > high:
            raise ValueError(f"{label} 수치 범위가 올바르지 않습니다 ({low}..{high}).")

    if kind == "save":
        req_int(data.get("m_iMoney"), 0, 999_999_999, "m_iMoney")
        req_int(data.get("m_iYear"), 1, 20, "m_iYear")
        req_int(data.get("m_iMonth"), 1, 12, "m_iMonth")
        req_int(data.get("m_iMonthInterval"), 0, 4, "m_iMonthInterval")
        req_int(data.get("m_iNowTime"), 1, 12, "m_iNowTime")
        req_int(data.get("m_iPhysical"), 0, 999, "m_iPhysical")
        req_int(data.get("m_iMood"), 0, 999, "m_iMood")
        if "m_iBattleDifficulty" in data:
            req_int(data.get("m_iBattleDifficulty"), 0, 3, "m_iBattleDifficulty")
        if not isinstance(data.get("m_strPlayerName"), str) or not isinstance(data.get("m_strPlayerLastName"), str):
            raise ValueError("주인공 성/이름 문자열 필드가 누락되었습니다.")
        pg_list = data.get("m_PropertyGroupsNodeList")
        if not isinstance(pg_list, list):
            raise ValueError("m_PropertyGroupsNodeList 배열이 누락되었습니다.")
        for g in pg_list:
            g_type = _as_exact_int(g.get("m_iType")) if isinstance(g, dict) else None
            if not isinstance(g, dict) or g_type is None or g_type < 0 or g_type > 99 or not isinstance(g.get("m_GroupsNodwList"), list):
                raise ValueError("속성 그룹(m_GroupsNodwList) 구조가 올바르지 않습니다.")
            for n in g["m_GroupsNodwList"]:
                if not isinstance(n, dict):
                    raise ValueError("속성 노드 객체 오류입니다.")
                for fk in ("m_iValue", "m_iIndex", "m_iExp", "m_iMax"):
                    req_int(n.get(fk), 0, 10**12, fk)
        for rk, idk in (("m_PlayerRoutineNodeList", "m_iRoutineID"), ("m_PlayerNeigongNodeList", "m_iNeigongID")):
            arr = data.get(rk)
            if not isinstance(arr, list):
                raise ValueError(f"{rk} 배열이 누락되었습니다.")
            for n in arr:
                if not isinstance(n, dict):
                    raise ValueError(f"{rk} 원소 객체 오류입니다.")
                req_int(n.get(idk), 1, 10**9, idk)
                req_int(n.get("m_iLV"), 1, 10, "m_iLV")
                req_int(n.get("m_iAccumulationExp"), 0, 10**12, "m_iAccumulationExp")
        bp = data.get("m_BackpackList")
        if not isinstance(bp, list):
            raise ValueError("m_BackpackList 배열이 누락되었습니다.")
        for entry in bp:
            if not isinstance(entry, dict):
                raise ValueError("행낭 항목 객체 오류입니다.")
            req_int(entry.get("m_iAmount"), 1, 10**9, "m_iAmount")
            inode = entry.get("_ItemDataNode")
            if not isinstance(inode, dict) or not isinstance(inode.get("m_ItmeEffectNodeList"), list):
                raise ValueError("_ItemDataNode 구조가 올바르지 않습니다.")
            req_int(inode.get("m_iItemID"), 1, 10**9, "m_iItemID")
        nf = data.get("m_NpcFriendlyNodeList")
        if not isinstance(nf, list):
            raise ValueError("m_NpcFriendlyNodeList 배열이 누락되었습니다.")
        for n in nf:
            if not isinstance(n, dict):
                raise ValueError("우호도 항목 객체 오류입니다.")
            req_int(n.get("m_iNpcID"), 1, 10**9, "m_iNpcID")
            req_int(n.get("m_iFriendly"), -1, 999, "m_iFriendly")
        if "m_teamMemberList" in data:
            tm = data["m_teamMemberList"]
            if not isinstance(tm, list):
                raise ValueError("m_teamMemberList 배열이 올바르지 않습니다.")
            if len(tm) > 9:
                raise ValueError("m_teamMemberList 항목 수가 너무 많습니다.")
            for x in tm:
                xiv = _as_exact_int(x)
                if xiv is None or xiv < 1:
                    raise ValueError("m_teamMemberList 항목이 올바르지 않습니다.")
    elif kind == "round":
        for fk in ("iMasterLevelCount", "iProLevelCount", "iNormalLevelCount", "iStartBegger"):
            req_int(data.get(fk), 0, 10**9, fk)
        if not isinstance(data.get("achiFinishList"), list) or not isinstance(data.get("achiCountList"), list):
            raise ValueError("업적 목록 배열이 누락되었습니다.")
        for a in data["achiCountList"]:
            if not isinstance(a, dict):
                raise ValueError("achiCountList 원소 객체 오류입니다.")
            req_int(a.get("m_iID"), 1, 10**9, "m_iID")
            req_int(a.get("m_iNow"), 0, 10**9, "m_iNow")
    elif kind == "guid":
        if not isinstance(data.get("guid"), str) or not data["guid"]:
            raise ValueError("guid 문자열이 비어 있습니다.")
        req_int(data.get("iDifficulty"), 0, 3, "iDifficulty")
        if not isinstance(data.get("openTalentList"), list) or not isinstance(data.get("openChestList"), list):
            raise ValueError("openTalentList / openChestList 배열이 누락되었습니다.")
    elif kind == "title":
        if not isinstance(data, list) or not (1 <= len(data) <= 20):
            raise ValueError("세이브 타이틀 배열 길이가 올바르지 않습니다.")
        for slot in data:
            if not isinstance(slot, dict) or not isinstance(slot.get("m_bHaveData"), bool):
                raise ValueError("타이틀 슬롯 m_bHaveData 불리언 값이 누락되었습니다.")
    return kind


def load_catalog() -> dict[str, Any]:
    if CATALOG_PATH.exists():
        text = CATALOG_PATH.read_bytes().decode("utf-8")
        marker = "root.TWX_CATALOG = "
        start = text.find(marker)
        if start >= 0:
            start += len(marker)
            end = text.find("; if (typeof module", start)
            if end > start:
                return json.loads(text[start:end])
    return {"propertyGroups": DEFAULT_PROPERTY_GROUPS, "routineExp": {"1": 23000, "2": 37000, "3": 55000, "4": 80000}}


def create_demo_data(kind: str, catalog: dict[str, Any] | None = None) -> Any:
    cat = catalog or load_catalog()
    if kind == "round":
        return {
            "finishGuidList": [],
            "iMasterLevelCount": 1,
            "iProLevelCount": 1,
            "iNormalLevelCount": 1,
            "iStartBegger": 0,
            "achiFinishList": [10001, 30001],
            "achiCountList": [{"m_iID": 10001, "m_iNow": 1}, {"m_iID": 30001, "m_iNow": 6}],
        }
    if kind == "guid":
        return {
            "guid": "00000000-0000-4000-8000-000000000001",
            "iDifficulty": 2,
            "openTalentList": [102, 213, 301],
            "openChestList": ["M000501"],
            "finishList": [],
            "movieList": [],
            "developQuestList": [],
            "collectionQuestList": [],
        }
    base_vals = [80, 150, 75, 120, 80, 2800, 1900]
    pg = []
    for g in cat.get("propertyGroups", DEFAULT_PROPERTY_GROUPS):
        nodes = []
        for idx, a in enumerate(g.get("attrs", [])):
            v = base_vals[idx] if g["type"] == 0 and idx < len(base_vals) else 45
            nodes.append({"m_iValue": v, "m_iIndex": a["index"], "m_iExp": 5000 if g["type"] else 0, "m_iMax": a["max"]})
        pg.append({"m_iType": g["type"], "m_GroupsNodwList": nodes})
    item_node = (cat.get("items") or [{}])[0].get("node") or {
        "m_iItemID": 100001, "m_strItemName": "철광석", "m_iItemKind": 5, "m_iItemType": 0,
        "m_strIcon": "i00001", "m_strTip": "", "m_iItemBuy": 60, "m_iItemSell": 30,
        "m_iItemStack": 0, "m_iMixStack": 999, "m_iItemUse": 0, "m_iUseTime": 4, "m_iAddType": 0,
        "m_iUseMsgID": 0, "m_iArtistryID": 10001, "m_iAmsType": 0,
        "m_strNpcLikeList": [], "m_UseLimitNodeList": [], "m_ItmeEffectNodeList": [],
        "m_strStatusTip": "0", "m_iLock": 0,
    }
    return {
        "m_strVersion": "1.0.3.1",
        "m_strPlayerName": "미명\r",
        "m_strPlayerLastName": "동방\r",
        "m_PlayerIconID": "900005",
        "m_iMoney": 52500,
        "m_strModelName": "Player",
        "m_fTalkRange": 2, "m_fStopRange": 0.1, "m_fWalkRange": 0.1,
        "m_fNowX": 0, "m_fNowY": 0, "m_fNowZ": 0,
        "m_iNowTime": 5, "m_fDir": 0, "m_fNowTime": 8,
        "m_strSceneName": "Develop", "m_iFre": 0,
        "m_iTalent1ID": 102, "m_iTalent2ID": 213, "m_iTalent3ID": 301,
        "m_iPlayBout": 1, "m_iMonth": 3, "m_iMonthInterval": 1, "m_iYear": 2, "m_iSeason": 0,
        "m_iPhysical": 10, "m_iMood": 4, "m_iPlotRound": 30,
        "m_iAttack": 180, "m_iDefense": 320, "m_iCritical": 5, "m_iDodge": 5, "m_iConter": 5,
        "m_iDefendCritical": 0, "m_iDefendConter": 0,
        "m_PropertyGroupsNodeList": pg,
        "m_BackpackList": [{"m_iAmount": 5, "_ItemDataNode": json.loads(json.dumps(item_node))}],
        "m_CollectionList": [], "m_QuestList": [], "m_EventList": [],
        "m_TitleIDList": [10001, 10002], "m_iTitleID": 10002,
        "m_iRoutineID": 70016,
        "m_PlayerRoutineNodeList": [{"m_iRoutineID": 70016, "m_strRoutineName": "독고구검", "m_iWearAmsType": 4, "m_iAccumulationExp": 35000, "m_iLV": 6}],
        "m_PlayerNeigongNodeList": [{"m_iNeigongID": 60001, "m_iLV": 8, "m_iAccumulationExp": 18000, "m_strStatusImage": "NeigongImage22", "m_strSelectImage": "NeigongImage02", "m_strNeigongName": "소요심법", "m_iExp": 1}],
        "m_iNeigongID": 60001,
        "m_DevelopQuestList": [], "m_LotusBtnIDList": [],
        "m_DevelopBtnStatusList": [{"m_iBtnID": 10001, "m_bStatus": False}],
        "m_YearCourdeNodeList": [{"m_iYear": y, "m_CourdeNodeList": []} for y in range(1, 7)],
        "m_MartialIDList": [], "m_AbilityIDList": [],
        "m_iWeaponsID": 0, "m_iEquipID": 0, "m_iAccessoriesID": 0,
        "m_NpcFriendlyNodeList": [{"m_iNpcID": 100015, "m_iFriendly": 50}],
        "m_TreasureBoxIDList": ["M000501"],
        "m_iAutomaticIndex": 0, "m_iAutomaticDIndex": 0,
        "m_StoreDataNodeList": [], "m_bInOutSideHouse": True,
        "m_fInSideAbLi_r": 0, "m_fInSideAbLi_g": 0, "m_fInSideAbLi_b": 0, "m_fInSideAbLi_a": 0,
        "m_iMusicIndex": 0, "m_teamMemberList": [10001401], "m_TimeQuestList": [],
        "m_iBattleArea": 0, "m_iBattleDifficulty": 2,
        "m_gGuid": "00000000-0000-4000-8000-000000000001",
    }


def apply_preset(data: Any, preset_id: str, catalog: dict[str, Any] | None = None) -> None:
    if preset_id not in PRESETS:
        raise ValueError(f"알 수 없는 프리셋입니다: {preset_id}")
    kind = detect_kind(data)
    if PRESETS[preset_id]["kind"] != kind:
        raise ValueError("현재 세이브 종류에 적용할 수 없는 프리셋입니다.")

    def _ei(val: Any, default: int = 0) -> int:
        iv = _as_exact_int(val)
        return iv if iv is not None else default

    cat = catalog or load_catalog()
    if preset_id == "max_money":
        data["m_iMoney"] = 9_999_999
    elif preset_id == "max_core_stats":
        targets = [500, 500, 100, 500, 100, 9999, 9999]
        for g in data.get("m_PropertyGroupsNodeList", []):
            if _ei(g.get("m_iType"), -1) == 0:
                for n in g.get("m_GroupsNodwList", []):
                    idx = _ei(n.get("m_iIndex"), -1)
                    if 0 <= idx < len(targets):
                        n["m_iValue"] = targets[idx]
                        if idx == 4:
                            n["m_iExp"] = max(_ei(n.get("m_iExp"), 0), 85700)
        data["m_iPhysical"] = 10
        data["m_iMood"] = 5
        data["m_iAttack"] = max(_ei(data.get("m_iAttack"), 0), 500)
        data["m_iDefense"] = max(_ei(data.get("m_iDefense"), 0), 800)
    elif preset_id == "max_martial_arts":
        for g in data.get("m_PropertyGroupsNodeList", []):
            if _ei(g.get("m_iType"), -1) in (1, 2):
                for n in g.get("m_GroupsNodwList", []):
                    n["m_iValue"] = max(100, _ei(n.get("m_iMax"), 100))
                    n["m_iExp"] = max(_ei(n.get("m_iExp"), 0), 169700)
    elif preset_id == "max_life_arts":
        for g in data.get("m_PropertyGroupsNodeList", []):
            if _ei(g.get("m_iType"), -1) in (3, 4):
                for n in g.get("m_GroupsNodwList", []):
                    n["m_iValue"] = max(100, _ei(n.get("m_iMax"), 100))
                    n["m_iExp"] = max(_ei(n.get("m_iExp"), 0), 85700)
        for b in data.get("m_DevelopBtnStatusList", []):
            b["m_bStatus"] = True
    elif preset_id == "max_routines_neigongs":
        for r in data.get("m_PlayerRoutineNodeList", []):
            r["m_iLV"] = 10
            r["m_iAccumulationExp"] = max(_ei(r.get("m_iAccumulationExp"), 0), 80000)
        for ng in data.get("m_PlayerNeigongNodeList", []):
            ng["m_iLV"] = 10
            ng["m_iAccumulationExp"] = max(_ei(ng.get("m_iAccumulationExp"), 0), 80000)
    elif preset_id == "max_friendship":
        seen: set[int] = set()
        nf = data.setdefault("m_NpcFriendlyNodeList", [])
        for n in nf:
            n["m_iFriendly"] = 100
            seen.add(_ei(n.get("m_iNpcID"), -1))
        for npc in cat.get("npcs", []):
            nid = int(npc["id"])
            if nid not in seen:
                nf.append({"m_iNpcID": nid, "m_iFriendly": 100})
                seen.add(nid)
    elif preset_id == "unlock_all_achievements":
        fin = data.setdefault("achiFinishList", [])
        cnt = data.setdefault("achiCountList", [])
        fin_seen = {_ei(x, -1) for x in fin}
        cnt_map: dict[int, dict[str, Any]] = {}
        for c in cnt:
            if isinstance(c, dict) and "m_iID" in c:
                cid = _as_exact_int(c.get("m_iID"))
                if cid is not None:
                    cnt_map[cid] = c
        for a in cat.get("achievements", []):
            aid = int(a["id"])
            if aid not in fin_seen:
                fin.append(aid)
                fin_seen.add(aid)
            t_cnt = int(a.get("targetCount", 1))
            if aid in cnt_map:
                cnt_map[aid]["m_iNow"] = max(_ei(cnt_map[aid].get("m_iNow"), 0), t_cnt)
            else:
                new_cn = {"m_iID": aid, "m_iNow": t_cnt}
                cnt.append(new_cn)
                cnt_map[aid] = new_cn
        data["iMasterLevelCount"] = max(_ei(data.get("iMasterLevelCount"), 0), 3)
        data["iProLevelCount"] = max(_ei(data.get("iProLevelCount"), 0), 2)
        data["iNormalLevelCount"] = max(_ei(data.get("iNormalLevelCount"), 0), 2)
        data["iStartBegger"] = max(_ei(data.get("iStartBegger"), 0), 1)
    elif preset_id == "unlock_guid_talents_chests":
        tal = data.setdefault("openTalentList", [])
        chs = data.setdefault("openChestList", [])
        tal_seen = {_ei(x, -1) for x in tal}
        for t in cat.get("talents", []):
            tid = int(t["id"])
            if tid not in tal_seen:
                tal.append(tid)
                tal_seen.add(tid)
        for c in cat.get("chests", []):
            if c["id"] not in chs:
                chs.append(c["id"])


def _is_safe_discovered_root(cand: Path) -> bool:
    try:
        if _is_reparse_or_symlink(cand):
            return False
        if not cand.is_dir():
            return False
    except OSError:
        return False

    h_or_fd = None
    try:
        _assert_no_reparse_in_ancestors(cand)
        h_or_fd, _ident, _pinned = _open_and_pin_dir_nofollow(cand, create_missing=False)
        return True
    except Exception:
        return False
    finally:
        if h_or_fd is not None:
            if os.name != "nt":
                os.close(h_or_fd)
            else:
                _CloseHandle(wintypes.HANDLE(h_or_fd))


def discover_roots() -> list[Path]:
    env = os.environ.get("TWX_SAVE_ROOT")
    if env and env.strip():
        return [Path(env.strip()).expanduser()]

    steam_bases: list[Path] = []
    steam_bases.append(Path.home() / ".local" / "share" / "Steam")

    legacy_steam = Path.home() / ".steam" / "steam"
    try:
        legacy_exists = legacy_steam.exists()
    except OSError:
        legacy_exists = False
    if legacy_exists:
        if not _is_reparse_or_symlink(legacy_steam):
            steam_bases.append(legacy_steam)
        else:
            real_steam = Path(os.path.realpath(legacy_steam))
            if _is_safe_discovered_root(real_steam):
                steam_bases.append(real_steam)

    for env_key in ("ProgramFiles(x86)", "ProgramFiles"):
        val = os.environ.get(env_key)
        if val:
            steam_bases.append(Path(val) / "Steam")

    roots: list[Path] = []
    seen_roots: set[str] = set()

    for base in steam_bases:
        userdata = base / "userdata"
        try:
            userdata_is_dir = userdata.is_dir()
        except OSError:
            userdata_is_dir = False

        if not _is_reparse_or_symlink(userdata) and userdata_is_dir:
            try:
                children = sorted(userdata.iterdir())
            except OSError:
                children = []
            for child in children:
                remote = child / "377530" / "remote"
                norm = os.path.normcase(str(remote))
                if norm not in seen_roots and _is_safe_discovered_root(remote):
                    seen_roots.add(norm)
                    roots.append(remote)

        local_cfg = base / "steamapps" / "common" / "Tale of Wuxia" / "Config" / "SaveData"
        norm = os.path.normcase(str(local_cfg))
        if norm not in seen_roots and _is_safe_discovered_root(local_cfg):
            seen_roots.add(norm)
            roots.append(local_cfg)

    return roots


def _is_reparse_or_symlink(p: Path) -> bool:
    try:
        if p.is_symlink():
            return True
    except OSError:
        return False
    try:
        if bool(hasattr(os.path, "isjunction") and os.path.isjunction(p)):
            return True
    except OSError:
        return False
    try:
        st = os.lstat(p)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & reparse)


def _assert_no_reparse_in_ancestors(p: Path) -> None:
    seen: set[str] = set()
    abs_p = Path(os.path.abspath(p))
    for cur in [p, *p.parents, abs_p, *abs_p.parents]:
        key = str(cur)
        if key in seen:
            continue
        seen.add(key)
        if _is_reparse_or_symlink(cur):
            raise ValueError("심볼릭 링크 또는 재분석 지점 디렉터리는 허용되지 않습니다.")


def list_slots(root: Path, expected_root_id: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
    def _collect(locked_dfd: int | None, locked_win_canon: str | None) -> list[dict[str, Any]]:
        if os.environ.get("TWX_SIMULATE_ROOT_SWAP_AFTER_LOCK") == "1" and os.name != "nt":
            moved = root.with_name(root.name + "_moved")
            decoy = root.with_name(root.name + "_decoy")
            if decoy.exists() and not moved.exists():
                os.rename(root, moved)
                os.rename(decoy, root)

        name_counts: dict[str, int] = {}
        raw_entries: list[tuple[str, int]] = []

        if locked_dfd is not None and locked_dfd >= 0:
            scan_fd = os.dup(locked_dfd)
            try:
                os.lseek(scan_fd, 0, os.SEEK_SET)
                with os.scandir(scan_fd) as it:
                    for entry in it:
                        if os.name != "nt" and "\\" in entry.name:
                            continue
                        lowered = entry.name.lower()
                        name_counts[lowered] = name_counts.get(lowered, 0) + 1
                        try:
                            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                                continue
                            st = entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        if getattr(st, "st_nlink", 1) > 1 or st.st_size > MAX_SAVE_BYTES:
                            continue
                        raw_entries.append((entry.name, int(st.st_size)))
            finally:
                try:
                    os.close(scan_fd)
                except OSError:
                    pass
        elif locked_win_canon is not None:
            with os.scandir(locked_win_canon) as it:
                for entry in it:
                    lowered = entry.name.lower()
                    name_counts[lowered] = name_counts.get(lowered, 0) + 1
                    try:
                        if _is_reparse_or_symlink(Path(entry.path)) or not entry.is_file(follow_symlinks=False):
                            continue
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if st.st_size > MAX_SAVE_BYTES:
                        continue
                    raw_entries.append((entry.name, int(st.st_size)))
        else:
            return []

        raw_entries.sort(key=lambda item: item[0])
        slots: list[dict[str, Any]] = []
        for name, size in raw_entries:
            if name_counts.get(name.lower(), 0) > 1:
                continue
            m_man = re.match(r"^Save(0|[1-9]|1[0-9])\.Save$", name, re.IGNORECASE)
            m_auto = re.match(r"^AutomaticSave(0|[1-9]|1[0-9])\.Save$", name, re.IGNORECASE)
            m_autod = re.match(r"^AutomaticDSave(0|[1-9]|1[0-9])\.Save$", name, re.IGNORECASE)
            if m_man:
                kind, label = "save", f"수동 슬롯 {int(m_man.group(1)) + 1} ({name})"
            elif m_auto:
                kind, label = "save", f"필드 자동 저장 {int(m_auto.group(1)) + 1} ({name})"
            elif m_autod:
                kind, label = "save", f"육성 자동 저장 {int(m_autod.group(1)) + 1} ({name})"
            elif name == "Round.dat":
                kind, label = "round", "전역 업적 · 다회차 기록 (Round.dat)"
            elif UUID_RE.match(name):
                kind, label = "guid", f"회차 고유 기록 ({name[:8]}…)"
            else:
                continue
            slots.append({"slot": name, "label": label, "kind": kind, "size": size})
        return slots

    if expected_root_id is not None:
        with _store_lock_guard(
            root, expected_root_id=expected_root_id, create_dir=False
        ) as (locked_dfd, locked_win_canon):
            return _collect(locked_dfd, locked_win_canon)

    _assert_no_reparse_in_ancestors(root)
    if _is_reparse_or_symlink(root):
        raise ValueError("심볼릭 링크 또는 재분석 지점 디렉터리는 허용되지 않습니다.")
    if not root.exists():
        _win32_assert_existing_ancestors_no_alias(root)
        return []
    if not root.is_dir():
        raise ValueError("세이브 루트가 디렉터리가 아닙니다.")
    try:
        with _store_lock_guard(root, create_dir=False) as (locked_dfd, locked_win_canon):
            return _collect(locked_dfd, locked_win_canon)
    except FileNotFoundError:
        return []


def is_game_running() -> bool:
    if os.environ.get("TWX_SIMULATE_GAME_RUNNING") == "1":
        return True
    try:
        if platform.system() == "Windows":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            cp = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq wuxia.exe", "/NH"],
                capture_output=True, timeout=3, creationflags=flags, check=False,
            )
            return b"wuxia.exe" in (cp.stdout or b"").lower()
        proc_dir = Path("/proc")
        if proc_dir.is_dir():
            for pid_dir in proc_dir.iterdir():
                if not pid_dir.name.isdigit():
                    continue
                try:
                    comm = (pid_dir / "comm").read_text(encoding="utf-8", errors="ignore").strip().lower()
                    if comm in ("wuxia", "wuxia.exe"):
                        return True
                except OSError:
                    continue
    except Exception:
        return False
    return False


def _to_rel_slot_posix_safe(rel_str: str) -> str:
    if os.name == "nt":
        return rel_str.replace("\\", "/")
    if "\\" in rel_str:
        raise ValueError("POSIX 슬롯 경로에는 역슬래시(\\)를 사용할 수 없습니다.")
    return rel_str


def resolve_safe_save_path(root: Path, rel_path: str) -> Path:
    if not rel_path or not isinstance(rel_path, str):
        raise ValueError("슬롯 파일 경로가 비어 있습니다.")
    if "\x00" in rel_path or any(ord(c) < 32 for c in rel_path):
        raise ValueError("경로에 제어 문자가 포함되어 있습니다.")
    if ":" in rel_path:
        raise ValueError("콜론(:) 또는 대체 데이터 스트림(ADS) 경로는 허용되지 않습니다.")
    if os.name != "nt" and "\\" in rel_path:
        raise ValueError("POSIX 슬롯 경로에는 역슬래시(\\)를 사용할 수 없습니다.")
    if rel_path.startswith(("/", "\\")) or Path(rel_path).is_absolute():
        raise ValueError("절대 경로는 허용되지 않습니다.")

    parts = (rel_path.replace("\\", "/") if os.name == "nt" else rel_path).split("/")
    for seg in parts:
        if not seg or seg in (".", ".."):
            raise ValueError("상위 디렉터리 이동(..) 세그먼트는 허용되지 않습니다.")
        if seg.startswith("."):
            raise ValueError("숨김 파일이나 잠금 파일(.twx_store.lock)은 슬롯 경로로 사용할 수 없습니다.")
        if seg.endswith((" ", ".")):
            raise ValueError("경로 세그먼트 끝에 공백이나 마침표를 사용할 수 없습니다.")
        stem = seg.rstrip(" .").split(".", 1)[0].upper()
        if stem in RESERVED_DEVICES:
            raise ValueError(f"예약된 시스템 장치 이름은 사용할 수 없습니다: {seg}")

    _assert_no_reparse_in_ancestors(root)
    if _is_reparse_or_symlink(root):
        raise ValueError("세이브 루트 경로가 심볼릭 링크입니다.")
    root_real = Path(os.path.realpath(root))
    candidate = root / Path(*parts)

    cur = root
    for seg in parts[:-1]:
        cur = cur / seg
        if _is_reparse_or_symlink(cur):
            raise ValueError("경로 중간에 심볼릭 링크 디렉터리가 포함되어 있습니다.")
    if _is_reparse_or_symlink(candidate):
        raise ValueError("심볼릭 링크 파일은 읽거나 쓸 수 없습니다.")

    cand_real = Path(os.path.realpath(candidate))
    if cand_real == root_real or root_real not in cand_real.parents:
        raise ValueError("세이브 루트 바깥의 경로에는 접근할 수 없습니다.")
    return candidate


if os.name == "nt":
    import ctypes
    import ctypes.wintypes as wintypes

    class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    class FILE_DISPOSITION_INFO(ctypes.Structure):
        _fields_ = [
            ("DeleteFile", ctypes.c_byte),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _SetFileInformationByHandle = _kernel32.SetFileInformationByHandle
    _SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _SetFileInformationByHandle.restype = wintypes.BOOL

    _GetFileInformationByHandle = _kernel32.GetFileInformationByHandle
    _GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(BY_HANDLE_FILE_INFORMATION),
    ]
    _GetFileInformationByHandle.restype = wintypes.BOOL

    _GetFinalPathNameByHandleW = _kernel32.GetFinalPathNameByHandleW
    _GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    _GetFinalPathNameByHandleW.restype = wintypes.DWORD

    _CreateFileW = _kernel32.CreateFileW
    _CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _CreateFileW.restype = ctypes.c_void_p

    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]
    _CloseHandle.restype = wintypes.BOOL

    _MoveFileExW = _kernel32.MoveFileExW
    _MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    _MoveFileExW.restype = wintypes.BOOL

    _ReadFile = _kernel32.ReadFile
    _ReadFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    _ReadFile.restype = wintypes.BOOL

    def _win32_read_handle_bytes(
        handle: int,
        max_bytes: int | None = MAX_SAVE_BYTES,
    ) -> bytes:
        chunks: list[bytes] = []
        total = 0
        buf = ctypes.create_string_buffer(65536)
        while True:
            read_n = wintypes.DWORD(0)
            ok = _ReadFile(
                wintypes.HANDLE(handle),
                ctypes.cast(buf, ctypes.c_void_p),
                wintypes.DWORD(len(buf)),
                ctypes.byref(read_n),
                None,
            )
            if not ok:
                raise ctypes.WinError(ctypes.get_last_error())
            n = int(read_n.value)
            if n == 0:
                break
            total += n
            if max_bytes is not None and total > max_bytes:
                raise ValueError("세이브 파일 크기가 허용 한도(16 MiB)를 초과합니다.")
            chunks.append(buf.raw[:n])
        return b"".join(chunks)

    def _win32_get_handle_file_id(handle: int) -> tuple[str, int, int, int]:
        info = BY_HANDLE_FILE_INFORMATION()
        if not _GetFileInformationByHandle(wintypes.HANDLE(handle), ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        return (
            "win32",
            int(info.dwVolumeSerialNumber),
            int(info.nFileIndexHigh),
            int(info.nFileIndexLow),
        )

    def _win32_inspect_dir_handle(handle: int) -> tuple[tuple[str, int, int, int], str]:
        info = BY_HANDLE_FILE_INFORMATION()
        if not _GetFileInformationByHandle(wintypes.HANDLE(handle), ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if (info.dwFileAttributes & 0x400) != 0:
            raise ValueError("심볼릭 링크 또는 재분석 지점 디렉터리는 허용되지 않습니다.")
        if (info.dwFileAttributes & 0x10) == 0:
            raise ValueError("디렉터리 핸들이 아닙니다.")

        buf_size = 512
        while True:
            buf = ctypes.create_unicode_buffer(buf_size)
            n = _GetFinalPathNameByHandleW(wintypes.HANDLE(handle), buf, buf_size, 0)
            if n == 0:
                raise ctypes.WinError(ctypes.get_last_error())
            if n < buf_size:
                final = buf.value
                break
            buf_size = n + 1

        if final.upper().startswith("\\\\?\\UNC\\"):
            raise ValueError("UNC 네트워크 경로는 허용되지 않습니다.")
        if final.startswith("\\\\?\\"):
            final = final[4:]
        ident = (
            "win32",
            int(info.dwVolumeSerialNumber),
            int(info.nFileIndexHigh),
            int(info.nFileIndexLow),
        )
        return ident, final

    def _win32_verify_open_handle(
        handle: int,
        root_real: Path,
        max_bytes: int | None = MAX_SAVE_BYTES,
        expected_leaf: str | None = None,
    ) -> str:
        info = BY_HANDLE_FILE_INFORMATION()
        if not _GetFileInformationByHandle(wintypes.HANDLE(handle), ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if (info.dwFileAttributes & 0x400) != 0:
            raise ValueError("심볼릭 링크 또는 재분석 지점 파일은 허용되지 않습니다.")
        if (info.dwFileAttributes & 0x10) != 0:
            raise ValueError("디렉터리 경로는 파일로 읽거나 쓸 수 없습니다.")
        if info.nNumberOfLinks > 1:
            raise ValueError("하드링크가 연결된 세이브 파일은 거부됩니다.")
        if max_bytes is not None:
            size = (info.nFileSizeHigh << 32) | info.nFileSizeLow
            if size > max_bytes:
                raise ValueError("세이브 파일 크기가 허용 한도(16 MiB)를 초과합니다.")

        buf_size = 512
        while True:
            buf = ctypes.create_unicode_buffer(buf_size)
            n = _GetFinalPathNameByHandleW(wintypes.HANDLE(handle), buf, buf_size, 0)
            if n == 0:
                raise ctypes.WinError(ctypes.get_last_error())
            if n < buf_size:
                final = buf.value
                break
            buf_size = n + 1

        if final.upper().startswith("\\\\?\\UNC\\"):
            raise ValueError("UNC 네트워크 경로는 허용되지 않습니다.")
        if final.startswith("\\\\?\\"):
            final = final[4:]
        root_prefix = os.path.normcase(str(root_real)).rstrip("\\") + "\\"
        if not os.path.normcase(final).startswith(root_prefix):
            raise ValueError("세이브 루트 바깥의 경로에는 접근할 수 없습니다.")
        if expected_leaf is not None and os.path.normcase(Path(final).name) != os.path.normcase(expected_leaf):
            raise ValueError("파일 별칭(8.3 단축 이름 등) 접근이 차단되었습니다.")
        return final

    def _win32_create_file(
        path: str,
        desired_access: int,
        share_mode: int,
        creation_disposition: int,
        flags_and_attributes: int,
    ) -> int:
        handle = _CreateFileW(
            path,
            desired_access,
            share_mode,
            None,
            creation_disposition,
            flags_and_attributes,
            None,
        )
        invalid = {
            None,
            0,
            ctypes.c_void_p(-1).value,
            0xFFFFFFFF,
            0xFFFFFFFFFFFFFFFF,
        }
        if handle in invalid:
            err = ctypes.get_last_error()
            if err == 2:
                raise FileNotFoundError(err, os.strerror(err), path)
            if err in (80, 183):
                raise FileExistsError(err, os.strerror(err), path)
            raise ctypes.WinError(err)
        return int(handle)

    def _win32_open_verified_exclusive_temp_for_rename(
        tmp_path: Path,
        parent_real: Path,
        expected_id: tuple[str, int, int, int] | None,
        expected_sha: str,
    ) -> int:
        vh: int | None = None
        try:
            vh = _win32_create_file(
                str(tmp_path),
                0x80000000 | 0x00010000,
                0,
                3,
                0x00200000,
            )
            _win32_verify_open_handle(
                vh,
                parent_real,
                MAX_SAVE_BYTES,
                expected_leaf=tmp_path.name,
            )
            if expected_id is not None and _win32_get_handle_file_id(vh) != expected_id:
                raise RuntimeError("CONFLICT_MODIFIED")
            raw = _win32_read_handle_bytes(vh, MAX_SAVE_BYTES)
            if hashlib.sha256(raw).hexdigest().lower() != expected_sha.lower():
                raise RuntimeError("CONFLICT_MODIFIED")
            return vh
        except BaseException as exc:
            if vh is not None:
                try:
                    _CloseHandle(wintypes.HANDLE(vh))
                except Exception:
                    pass
            if isinstance(exc, RuntimeError):
                raise
            if isinstance(exc, (FileNotFoundError, ValueError, OSError)):
                raise RuntimeError("CONFLICT_MODIFIED") from exc
            raise

    def _win32_rename_by_handle(
        h_tmp: int,
        target_path: Path,
        allow_replace: bool,
    ) -> None:
        name_bytes = str(target_path).encode("utf-16-le")
        ptr_sz = ctypes.sizeof(ctypes.c_void_p)
        root_offset = ptr_sz
        len_offset = root_offset + ptr_sz
        name_offset = len_offset + 4
        total_size = name_offset + len(name_bytes) + 2
        buf = ctypes.create_string_buffer(total_size)
        buf[0] = b"\x01" if allow_replace else b"\x00"
        ctypes.memmove(
            ctypes.byref(buf, len_offset),
            ctypes.byref(wintypes.DWORD(len(name_bytes))),
            4,
        )
        ctypes.memmove(
            ctypes.byref(buf, name_offset),
            name_bytes,
            len(name_bytes),
        )
        ok = _SetFileInformationByHandle(
            wintypes.HANDLE(h_tmp),
            3,
            ctypes.cast(buf, ctypes.c_void_p),
            wintypes.DWORD(total_size),
        )
        if not ok:
            err = ctypes.get_last_error()
            if not allow_replace and err in (80, 183):
                raise RuntimeError("CONFLICT_MODIFIED")
            raise ctypes.WinError(err)

    def _win32_assert_temp_exclusively_pinned(tmp_path: Path) -> None:
        probe_h: int | None = None
        try:
            probe_h = _win32_create_file(
                str(tmp_path),
                0x40000000,
                0x07,
                3,
                0x00200000,
            )
        except OSError:
            pass
        else:
            try:
                _CloseHandle(wintypes.HANDLE(probe_h))
            except Exception:
                pass
            raise RuntimeError("EXCLUSIVE_TEMP_PIN_NOT_ENFORCED")
        hijack_path = str(tmp_path) + ".hijack"
        if _MoveFileExW(str(tmp_path), hijack_path, 0x01):
            try:
                _MoveFileExW(hijack_path, str(tmp_path), 0x01)
            except Exception:
                pass
            raise RuntimeError("EXCLUSIVE_TEMP_PIN_NOT_ENFORCED")


_STORE_LOCK = threading.RLock()
_LOCK_DEPTH = threading.local()
_PINNED_WIN_CANON = threading.local()


def _win32_assert_dir_no_alias_or_case_mismatch(
    dir_path: Path, canon_from_handle: str | None = None
) -> None:
    if os.name != "nt":
        return
    abs_dir = Path(os.path.abspath(dir_path))
    if not abs_dir.anchor or abs_dir == Path(abs_dir.anchor):
        return
    canon = canon_from_handle
    if canon is None:
        h = _win32_create_file(str(abs_dir), 0x80000000, 0x03, 3, 0x02200000)
        try:
            canon = _win32_inspect_dir_handle(h)[1]
        finally:
            _CloseHandle(wintypes.HANDLE(h))
    if os.path.normcase(canon.rstrip("\\")) != os.path.normcase(str(abs_dir).rstrip("\\")):
        raise ValueError("상위 디렉터리 경로에 별칭(8.3 단축 이름 등)이 포함되어 차단되었습니다.")
    cur = Path(abs_dir.anchor)
    for seg in abs_dir.parts[1:]:
        if not cur.is_dir():
            break
        try:
            entries = os.listdir(cur)
        except PermissionError:
            entries = None
        if entries is not None:
            if any(e.lower() == seg.lower() and e != seg for e in entries) or (
                seg not in entries and os.path.lexists(cur / seg)
            ):
                raise ValueError("상위 디렉터리 경로에 별칭(8.3 단축 이름 등)이 포함되어 차단되었습니다.")
        cur = cur / seg


def _win32_assert_existing_ancestors_no_alias(p: Path) -> None:
    if os.name != "nt":
        return
    abs_p = Path(os.path.abspath(p))
    anc = abs_p if abs_p.is_dir() else abs_p.parent
    while not anc.exists() and anc != anc.parent:
        anc = anc.parent
    if anc.exists():
        _win32_assert_dir_no_alias_or_case_mismatch(anc)


def _open_and_pin_dir_nofollow(
    root: Path, create_missing: bool = False
) -> tuple[int, tuple[Any, ...], Path]:
    abs_str = os.path.abspath(root)
    if str(root) != abs_str:
        for cand_raw in (root, *root.parents):
            if _is_reparse_or_symlink(cand_raw):
                raise ValueError("심볼릭 링크 또는 재분석 지점 디렉터리는 허용되지 않습니다.")
    abs_root = Path(abs_str)

    if os.name != "nt":
        root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
        seg_flags = root_flags | getattr(os, "O_NOFOLLOW", 0)
        eloop_codes = {
            errno.ELOOP,
            errno.ENOTDIR,
            getattr(errno, "EMLINK", errno.ELOOP),
            getattr(errno, "EFTYPE", errno.ELOOP),
        }
        segs = [s for s in abs_root.parts[1:] if s and s != "/"]
        swap_seg = os.environ.get("TWX_SIMULATE_ANCESTOR_SWAP_DURING_ROOT_PIN", "")
        cur_fd = os.open("/", root_flags)
        try:
            for idx, seg in enumerate(segs):
                is_last = idx == len(segs) - 1
                if swap_seg and swap_seg == seg:
                    swap_target = os.environ.get("TWX_SIMULATE_ANCESTOR_SWAP_TARGET", "/tmp")
                    try:
                        st_sim = os.lstat(seg, dir_fd=cur_fd)
                    except FileNotFoundError:
                        os.symlink(swap_target, seg, dir_fd=cur_fd)
                    else:
                        if not stat.S_ISLNK(st_sim.st_mode):
                            os.rename(
                                seg,
                                seg + "_moved",
                                src_dir_fd=cur_fd,
                                dst_dir_fd=cur_fd,
                            )
                            os.symlink(swap_target, seg, dir_fd=cur_fd)

                try:
                    next_fd = os.open(seg, seg_flags, dir_fd=cur_fd)
                except FileNotFoundError:
                    if not create_missing:
                        raise
                    try:
                        os.mkdir(seg, 0o755, dir_fd=cur_fd)
                    except FileExistsError:
                        pass
                    else:
                        _fsync_dir_fd(cur_fd)
                    try:
                        next_fd = os.open(seg, seg_flags, dir_fd=cur_fd)
                    except (OSError, NotADirectoryError) as exc2:
                        if getattr(exc2, "errno", None) in eloop_codes or isinstance(exc2, NotADirectoryError):
                            raise ValueError("심볼릭 링크 또는 재분석 지점 디렉터리는 허용되지 않습니다.") from exc2
                        raise
                except PermissionError:
                    o_path = getattr(os, "O_PATH", 0)
                    if is_last or not o_path:
                        raise
                    path_flags = (
                        o_path
                        | getattr(os, "O_DIRECTORY", 0)
                        | getattr(os, "O_NOFOLLOW", 0)
                        | getattr(os, "O_CLOEXEC", 0)
                    )
                    try:
                        next_fd = os.open(seg, path_flags, dir_fd=cur_fd)
                    except (OSError, NotADirectoryError) as exc_p:
                        if getattr(exc_p, "errno", None) in eloop_codes or isinstance(exc_p, NotADirectoryError):
                            raise ValueError("심볼릭 링크 또는 재분석 지점 디렉터리는 허용되지 않습니다.") from exc_p
                        raise
                except (OSError, NotADirectoryError) as exc:
                    if getattr(exc, "errno", None) in eloop_codes or isinstance(exc, NotADirectoryError):
                        raise ValueError("심볼릭 링크 또는 재분석 지점 디렉터리는 허용되지 않습니다.") from exc
                    raise

                try:
                    st_next = os.fstat(next_fd)
                    if not stat.S_ISDIR(st_next.st_mode):
                        raise ValueError("심볼릭 링크 또는 재분석 지점 디렉터리는 허용되지 않습니다.")
                except BaseException:
                    os.close(next_fd)
                    raise

                os.close(cur_fd)
                cur_fd = next_fd

            st_final = os.fstat(cur_fd)
            if not stat.S_ISDIR(st_final.st_mode):
                raise ValueError("세이브 루트가 디렉터리가 아닙니다.")
            ident_posix: tuple[Any, ...] = ("posix", int(st_final.st_dev), int(st_final.st_ino))
            ret_fd = cur_fd
            cur_fd = -1
            return ret_fd, ident_posix, abs_root
        finally:
            if cur_fd >= 0:
                try:
                    os.close(cur_fd)
                except OSError:
                    pass

    if not abs_root.anchor:
        raise ValueError("유효하지 않은 루트 경로입니다.")
    prev_h: int | None = None
    try:
        cur = Path(abs_root.anchor)
        try:
            prev_h = _win32_create_file(str(cur), 0x80000000, 0x03, 3, 0x02200000)
        except PermissionError:
            if len(abs_root.parts) <= 1:
                raise
            prev_h = _win32_create_file(str(cur), 0, 0x03, 3, 0x02200000)
        ident_win, canon = _win32_inspect_dir_handle(prev_h)
        if os.path.normcase(canon.rstrip("\\")) != os.path.normcase(str(cur).rstrip("\\")):
            raise ValueError("상위 디렉터리 경로에 별칭(8.3 단축 이름 등)이 포함되어 차단되었습니다.")

        win_segs = list(abs_root.parts[1:])
        for idx, seg in enumerate(win_segs):
            is_last = idx == len(win_segs) - 1
            try:
                entries = os.listdir(cur)
            except PermissionError:
                entries = None
            if entries is not None:
                if any(e.lower() == seg.lower() and e != seg for e in entries) or (
                    seg not in entries and os.path.lexists(cur / seg)
                ):
                    raise ValueError("상위 디렉터리 경로에 별칭(8.3 단축 이름 등)이 포함되어 차단되었습니다.")

            next_cur = cur / seg
            try:
                next_h = _win32_create_file(str(next_cur), 0x80000000, 0x03, 3, 0x02200000)
            except PermissionError:
                if is_last:
                    raise
                next_h = _win32_create_file(str(next_cur), 0, 0x03, 3, 0x02200000)
            except FileNotFoundError:
                if not create_missing:
                    raise
                if _is_reparse_or_symlink(next_cur):
                    raise ValueError("심볼릭 링크 또는 재분석 지점 디렉터리는 허용되지 않습니다.")
                try:
                    next_cur.mkdir(parents=False, exist_ok=False)
                except FileExistsError:
                    pass
                next_h = _win32_create_file(str(next_cur), 0x80000000, 0x03, 3, 0x02200000)

            try:
                next_ident, next_canon = _win32_inspect_dir_handle(next_h)
                if os.path.normcase(next_canon.rstrip("\\")) != os.path.normcase(str(next_cur).rstrip("\\")):
                    raise ValueError("상위 디렉터리 경로에 별칭(8.3 단축 이름 등)이 포함되어 차단되었습니다.")
            except BaseException:
                _CloseHandle(wintypes.HANDLE(next_h))
                raise

            _CloseHandle(wintypes.HANDLE(prev_h))
            prev_h = next_h
            ident_win = next_ident
            canon = next_canon
            cur = next_cur

        ret_h = prev_h
        prev_h = None
        return ret_h, ident_win, Path(canon)
    finally:
        if prev_h is not None:
            try:
                _CloseHandle(wintypes.HANDLE(prev_h))
            except Exception:
                pass


def _capture_root_identity(root: Path) -> tuple[Any, ...]:
    h_or_fd, ident, _pinned_path = _open_and_pin_dir_nofollow(root, create_missing=False)
    try:
        return ident
    finally:
        if os.name != "nt":
            os.close(h_or_fd)
        else:
            _CloseHandle(wintypes.HANDLE(h_or_fd))


def _ensure_safe_dir_nofollow(target_dir: Path) -> Path:
    h_or_fd, _ident, pinned_path = _open_and_pin_dir_nofollow(target_dir, create_missing=True)
    try:
        return pinned_path
    finally:
        if os.name != "nt":
            os.close(h_or_fd)
        else:
            _CloseHandle(wintypes.HANDLE(h_or_fd))


def _norm_local_path_str(p: Path | str) -> str:
    ab = os.path.abspath(p)
    if os.name != "nt" and ab.startswith("//"):
        ab = "/" + ab.lstrip("/")
    return os.path.normcase(ab)


def _current_locked_root_dfd(root: Path) -> int | None:
    fd_map = getattr(_LOCK_DEPTH, "fd_map", None)
    if not fd_map:
        return None
    dfd = fd_map.get(_norm_local_path_str(root))
    if isinstance(dfd, int) and dfd >= 0:
        return dfd
    return None


@contextlib.contextmanager
def _store_lock_guard(
    root: Path,
    expected_root_id: tuple[Any, ...] | None = None,
    create_dir: bool = True,
):
    _STORE_LOCK.acquire()
    fd = -1
    root_dir_fd = -1
    root_dir_h: int | None = None
    root_canon: str | None = None
    os_locked = False
    depth_map: dict[str, int] | None = None
    id_map: dict[str, tuple[Any, ...]] | None = None
    fd_map: dict[str, int] | None = None
    canon_map: dict[str, str] | None = None
    id_depth_map: dict[tuple[Any, ...], tuple[int, int | None, str | None]] | None = None
    root_key = ""
    incremented = False
    locked_actual_id: tuple[Any, ...] | None = None
    id_incremented = False
    try:
        root_key = _norm_local_path_str(root)
        depth_map = getattr(_LOCK_DEPTH, "depth_map", None)
        if depth_map is None:
            depth_map = {}
            _LOCK_DEPTH.depth_map = depth_map
        id_map = getattr(_LOCK_DEPTH, "id_map", None)
        if id_map is None:
            id_map = {}
            _LOCK_DEPTH.id_map = id_map
        fd_map = getattr(_LOCK_DEPTH, "fd_map", None)
        if fd_map is None:
            fd_map = {}
            _LOCK_DEPTH.fd_map = fd_map
        canon_map = getattr(_LOCK_DEPTH, "canon_map", None)
        if canon_map is None:
            canon_map = {}
            _LOCK_DEPTH.canon_map = canon_map
        id_depth_map = getattr(_LOCK_DEPTH, "id_depth_map", None)
        if id_depth_map is None:
            id_depth_map = {}
            _LOCK_DEPTH.id_depth_map = id_depth_map

        depth = depth_map.get(root_key, 0)
        if depth > 0:
            active_id = id_map.get(root_key)
            if expected_root_id is not None and active_id != expected_root_id:
                raise ValueError("세이브 루트 디렉터리 식별자가 변경되었습니다.")
            if active_id is not None:
                try:
                    cur_ident = _capture_root_identity(root)
                except FileNotFoundError as exc:
                    raise ValueError("세이브 루트 디렉터리 식별자가 변경되었습니다.") from exc
                if cur_ident != active_id:
                    raise ValueError("세이브 루트 디렉터리 식별자가 변경되었습니다.")
            depth_map[root_key] = depth + 1
            incremented = True
            if active_id is not None and active_id in id_depth_map:
                prev_id_depth, existing_dfd, existing_canon = id_depth_map[active_id]
                id_depth_map[active_id] = (prev_id_depth + 1, existing_dfd, existing_canon)
                locked_actual_id = active_id
                id_incremented = True
            yield (fd_map.get(root_key), canon_map.get(root_key))
            return

        try:
            pinned_h_or_fd, actual_id, pinned_root_path = _open_and_pin_dir_nofollow(
                root,
                create_missing=(create_dir and expected_root_id is None),
            )
        except FileNotFoundError as exc:
            if expected_root_id is not None:
                raise ValueError("세이브 루트 디렉터리 식별자가 변경되었습니다.") from exc
            raise

        if os.name != "nt":
            root_dir_fd = pinned_h_or_fd
        else:
            root_dir_h = pinned_h_or_fd

        if expected_root_id is not None and actual_id != expected_root_id:
            raise ValueError("세이브 루트 디렉터리 식별자가 변경되었습니다.")

        if actual_id in id_depth_map:
            if os.name != "nt":
                if root_dir_fd >= 0:
                    os.close(root_dir_fd)
                    root_dir_fd = -1
            else:
                if root_dir_h is not None:
                    _CloseHandle(wintypes.HANDLE(root_dir_h))
                    root_dir_h = None
            prev_id_depth, existing_dfd, existing_canon = id_depth_map[actual_id]
            id_depth_map[actual_id] = (prev_id_depth + 1, existing_dfd, existing_canon)
            locked_actual_id = actual_id
            id_incremented = True
            id_map[root_key] = actual_id
            if existing_dfd is not None:
                fd_map[root_key] = existing_dfd
            if existing_canon is not None:
                canon_map[root_key] = existing_canon
            depth_map[root_key] = 1
            incremented = True
            yield (existing_dfd, existing_canon)
            return

        if os.name != "nt":
            import fcntl

            matched_lock = False
            for _attempt in range(16):
                try:
                    st_lk = os.lstat(".twx_store.lock", dir_fd=root_dir_fd)
                except FileNotFoundError:
                    pass
                else:
                    if stat.S_ISLNK(st_lk.st_mode):
                        raise ValueError("잠금 파일이 심볼릭 링크이거나 정션입니다.")
                try:
                    fd = os.open(
                        ".twx_store.lock",
                        os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
                        0o600,
                        dir_fd=root_dir_fd,
                    )
                except OSError as exc:
                    if getattr(exc, "errno", None) in (errno.ELOOP, errno.ENXIO):
                        raise ValueError("잠금 파일이 일반 파일이 아닙니다.") from exc
                    raise
                st_fd = os.fstat(fd)
                if not stat.S_ISREG(st_fd.st_mode):
                    raise ValueError("잠금 파일이 일반 파일이 아닙니다.")
                if getattr(st_fd, "st_nlink", 1) > 1:
                    raise ValueError("하드링크가 연결된 잠금 파일은 거부됩니다.")
                if getattr(os, "O_NONBLOCK", 0):
                    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
                    fcntl.fcntl(fd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)
                fcntl.flock(fd, fcntl.LOCK_EX)
                os_locked = True
                st_after = os.fstat(fd)
                try:
                    st_entry = os.lstat(".twx_store.lock", dir_fd=root_dir_fd)
                except FileNotFoundError:
                    st_entry = None
                if st_entry is not None:
                    if stat.S_ISLNK(st_entry.st_mode):
                        raise ValueError("잠금 파일이 심볼릭 링크이거나 정션입니다.")
                    if not stat.S_ISREG(st_entry.st_mode):
                        raise ValueError("잠금 파일이 일반 파일이 아닙니다.")
                    if getattr(st_entry, "st_nlink", 1) > 1:
                        raise ValueError("하드링크가 연결된 잠금 파일은 거부됩니다.")
                if getattr(st_after, "st_nlink", 1) > 1:
                    raise ValueError("하드링크가 연결된 잠금 파일은 거부됩니다.")
                if (
                    st_entry is not None
                    and not stat.S_ISLNK(st_entry.st_mode)
                    and stat.S_ISREG(st_entry.st_mode)
                    and getattr(st_after, "st_nlink", 1) == 1
                    and getattr(st_entry, "st_nlink", 1) == 1
                    and (int(st_after.st_dev), int(st_after.st_ino)) == (int(st_entry.st_dev), int(st_entry.st_ino))
                ):
                    matched_lock = True
                    break
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
                os_locked = False
                old_fd = fd
                fd = -1
                try:
                    os.close(old_fd)
                except OSError:
                    pass
            if not matched_lock:
                raise RuntimeError("잠금 파일 inode 일치를 확인하지 못했습니다.")
            id_map[root_key] = actual_id
            fd_map[root_key] = root_dir_fd
        else:
            import msvcrt

            root_dir_h = pinned_h_or_fd
            root_canon = str(pinned_root_path)
            if expected_root_id is not None and actual_id != expected_root_id:
                raise ValueError("세이브 루트 디렉터리 식별자가 변경되었습니다.")
            lock_path_str = root_canon.rstrip("\\") + "\\.twx_store.lock"
            if _is_reparse_or_symlink(Path(lock_path_str)):
                raise ValueError("잠금 파일이 심볼릭 링크이거나 정션입니다.")
            deadline = time.monotonic() + 10.0
            while True:
                lock_h: int | None = None
                try:
                    lock_h = _win32_create_file(
                        lock_path_str,
                        0x80000000 | 0x40000000,
                        0x03,
                        4,
                        0x80 | 0x00200000,
                    )
                    lock_final = _win32_verify_open_handle(lock_h, Path(root_canon), max_bytes=None)
                    if os.path.normcase(lock_final) != os.path.normcase(lock_path_str):
                        raise ValueError("잠금 파일 경로가 예상 위치와 일치하지 않습니다.")
                    fd = msvcrt.open_osfhandle(lock_h, os.O_RDWR)
                    lock_h = None
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    os_locked = True
                    break
                except ValueError:
                    if lock_h is not None:
                        _CloseHandle(wintypes.HANDLE(lock_h))
                    if fd >= 0:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                        fd = -1
                    raise
                except TimeoutError:
                    raise
                except (PermissionError, OSError):
                    if lock_h is not None:
                        _CloseHandle(wintypes.HANDLE(lock_h))
                    if fd >= 0:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                        fd = -1
                    if time.monotonic() >= deadline:
                        raise TimeoutError("잠금 파일을 획득하지 못했습니다.")
                    time.sleep(0.05)
            id_map[root_key] = actual_id
            canon_map[root_key] = root_canon

        id_depth_map[actual_id] = (
            1,
            root_dir_fd if os.name != "nt" else None,
            root_canon if os.name == "nt" else None,
        )
        locked_actual_id = actual_id
        id_incremented = True
        depth_map[root_key] = 1
        incremented = True
        yield (
            root_dir_fd if os.name != "nt" else None,
            root_canon if os.name == "nt" else None,
        )
    finally:
        try:
            if id_incremented and id_depth_map is not None and locked_actual_id is not None:
                cur_id_entry = id_depth_map.get(locked_actual_id)
                if cur_id_entry is not None:
                    prev_id_depth, existing_dfd, existing_canon = cur_id_entry
                    new_id_depth = prev_id_depth - 1
                    if new_id_depth > 0:
                        id_depth_map[locked_actual_id] = (
                            new_id_depth,
                            existing_dfd,
                            existing_canon,
                        )
                    else:
                        id_depth_map.pop(locked_actual_id, None)
            if incremented and depth_map is not None:
                new_depth = depth_map.get(root_key, 1) - 1
                if new_depth > 0:
                    depth_map[root_key] = new_depth
                else:
                    depth_map.pop(root_key, None)
                    if id_map is not None:
                        id_map.pop(root_key, None)
                    if fd_map is not None:
                        fd_map.pop(root_key, None)
                    if canon_map is not None:
                        canon_map.pop(root_key, None)
            if fd >= 0:
                try:
                    if os_locked:
                        if os.name != "nt":
                            import fcntl
                            try:
                                fcntl.flock(fd, fcntl.LOCK_UN)
                            except OSError:
                                pass
                        else:
                            import msvcrt
                            try:
                                os.lseek(fd, 0, os.SEEK_SET)
                                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                            except OSError:
                                pass
                finally:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            if root_dir_fd >= 0:
                try:
                    os.close(root_dir_fd)
                except OSError:
                    pass
            if root_dir_h is not None and os.name == "nt":
                try:
                    _CloseHandle(wintypes.HANDLE(root_dir_h))
                except Exception:
                    pass
        finally:
            _STORE_LOCK.release()


def _normalize_rel_slot_parts(rel_slot: str) -> str:
    if not isinstance(rel_slot, str) or not rel_slot:
        raise ValueError("슬롯 경로가 비어 있거나 문자열이 아닙니다.")
    if any(ord(c) < 32 or ord(c) == 127 for c in rel_slot):
        raise ValueError("슬롯 경로에 제어 문자가 포함되어 있습니다.")
    if ":" in rel_slot:
        raise ValueError("슬롯 경로에 콜론이 포함되어 있습니다.")
    if os.name != "nt" and "\\" in rel_slot:
        raise ValueError("POSIX 슬롯 경로에는 역슬래시(\\)를 사용할 수 없습니다.")
    if rel_slot.startswith(("/", "\\")) or Path(rel_slot).is_absolute():
        raise ValueError("슬롯 경로는 상대 경로여야 합니다.")
    parts = (rel_slot.replace("\\", "/") if os.name == "nt" else rel_slot).split("/")
    if any(not part or part in (".", "..") for part in parts):
        raise ValueError("슬롯 경로에 유효하지 않은 세그먼트가 있습니다.")
    if any(part.endswith((" ", ".")) for part in parts):
        raise ValueError("슬롯 경로 세그먼트 끝에 공백이나 마침표를 사용할 수 없습니다.")
    return "/".join(parts)


def _ascii_lower(s: str) -> str:
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in s)


def _normalize_rel_slot_key(rel_slot: str) -> str:
    return _ascii_lower(_normalize_rel_slot_parts(rel_slot))


def _assert_not_reserved_slot(rel_path: str) -> None:
    parts = _normalize_rel_slot_parts(rel_path).split("/")
    if parts[0].lower() == "backups" or any(seg.startswith(".") for seg in parts):
        raise ValueError("백업 전용 폴더(backups)나 내부 파일은 슬롯 대상으로 사용할 수 없습니다.")


def _assert_no_case_collision(root: Path, rel_slot: str) -> None:
    parts = _normalize_rel_slot_parts(rel_slot).split("/")
    cur = root
    for seg in parts:
        if not cur.is_dir():
            return
        entries = os.listdir(cur)
        if any(e.lower() == seg.lower() and e != seg for e in entries):
            raise ValueError("대소문자만 다른 동일 이름의 슬롯이 존재하여 모호한 접근이 차단되었습니다.")
        if os.name == "nt" and seg not in entries and os.path.lexists(cur / seg):
            raise ValueError("파일 또는 디렉터리 별칭(8.3 단축 이름 등) 접근이 차단되었습니다.")
        cur = cur / seg
        if not cur.is_dir():
            break


def _clean_local_dir_path(p: Path | str) -> Path:
    ab_raw = os.path.abspath(p)
    if os.name != "nt" and ab_raw.startswith("//"):
        return Path("/" + ab_raw.lstrip("/"))
    return Path(ab_raw)


@contextlib.contextmanager
def _slot_lock_guard(
    root: Path,
    rel_slot: str,
    create_dirs: bool = False,
    expected_root_id: tuple[Any, ...] | None = None,
):
    parts = _normalize_rel_slot_parts(rel_slot).split("/")
    if len(parts) == 1 or parts[0].lower() == "backups" or any(seg.startswith(".") for seg in parts):
        with _store_lock_guard(root, expected_root_id=expected_root_id, create_dir=create_dirs):
            _assert_not_reserved_slot(rel_slot)
            resolve_safe_save_path(root, rel_slot)
            yield
        return
    _assert_not_reserved_slot(rel_slot)

    for _attempt in range(4):
        r_h: int | None = None
        try:
            try:
                r_h, r_id, _ = _open_and_pin_dir_nofollow(
                    root,
                    create_missing=(create_dirs and expected_root_id is None),
                )
            except FileNotFoundError as exc:
                if expected_root_id is not None:
                    raise ValueError("세이브 루트 디렉터리 식별자가 변경되었습니다.") from exc
                raise
            if expected_root_id is not None and r_id != expected_root_id:
                raise ValueError("세이브 루트 디렉터리 식별자가 변경되었습니다.")
        finally:
            if r_h is not None:
                if os.name != "nt":
                    os.close(r_h)
                else:
                    _CloseHandle(wintypes.HANDLE(r_h))

        target = resolve_safe_save_path(root, rel_slot)
        sub_dir = target.parent

        if not sub_dir.exists():
            if not create_dirs:
                with _store_lock_guard(root, expected_root_id=r_id, create_dir=False):
                    target_chk = resolve_safe_save_path(root, rel_slot)
                    if not target_chk.parent.exists():
                        yield
                        return
            else:
                with _store_lock_guard(root, expected_root_id=r_id, create_dir=False):
                    _assert_no_case_collision(root, rel_slot)
                    with _open_pinned_parent(
                        root,
                        rel_slot,
                        create_dirs=True,
                        expected_root_id=r_id,
                    ):
                        pass

        root_clean = _clean_local_dir_path(root)
        try:
            with _open_pinned_parent(
                root,
                rel_slot,
                create_dirs=False,
                expected_root_id=r_id,
            ) as (cand_p, _leaf_n, sub_dfd):
                if sub_dfd is not None:
                    st_sub = os.fstat(sub_dfd)
                    s_id: tuple[Any, ...] = ("posix", int(st_sub.st_dev), int(st_sub.st_ino))
                else:
                    s_id = _capture_root_identity(_current_pinned_win_parent(cand_p.parent))
        except FileNotFoundError as exc:
            if expected_root_id is not None:
                try:
                    cur_r = _capture_root_identity(root_clean)
                except Exception:
                    raise ValueError("세이브 루트 디렉터리 식별자가 변경되었습니다.") from exc
                if cur_r != expected_root_id:
                    raise ValueError("세이브 루트 디렉터리 식별자가 변경되었습니다.") from exc
            if _attempt == 3:
                raise
            continue

        sub_clean = _clean_local_dir_path(sub_dir)
        ordered = (
            [(r_id, root_clean)]
            if r_id == s_id
            else sorted([(r_id, root_clean), (s_id, sub_clean)], key=lambda item: item[0])
        )
        stack = contextlib.ExitStack()
        try:
            try:
                for lock_ident, lock_path in ordered:
                    stack.enter_context(
                        _store_lock_guard(
                            lock_path,
                            expected_root_id=lock_ident,
                            create_dir=False,
                        )
                    )
                resolve_safe_save_path(root, rel_slot)
            except (FileNotFoundError, ValueError) as exc:
                stack.close()
                if expected_root_id is not None:
                    try:
                        cur_r = _capture_root_identity(root_clean)
                    except Exception:
                        raise ValueError("세이브 루트 디렉터리 식별자가 변경되었습니다.") from exc
                    if cur_r != expected_root_id:
                        raise ValueError("세이브 루트 디렉터리 식별자가 변경되었습니다.") from exc
                msg = str(exc)
                if _attempt == 3 or any(
                    tok in msg
                    for tok in (
                        "심볼릭 링크",
                        "재분석 지점",
                        "별칭",
                        "대소문자",
                        "예약된",
                        "제어 문자",
                        "바깥",
                        "역슬래시",
                        "잠금 파일",
                        "하드링크",
                    )
                ):
                    raise
                continue
            yield
            return
        finally:
            stack.close()


def _slot_backup_prefix(rel_slot: str) -> str:
    key = _normalize_rel_slot_key(rel_slot)
    slot_tag = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    safe_stem = re.sub(r"[^a-z0-9._-]", "_", Path(key).stem).lstrip(".") or "slot"
    return f"{safe_stem}__s{slot_tag}"


def is_backup_for_slot(backup_name: str, rel_slot: str) -> bool:
    if not isinstance(backup_name, str) or not backup_name:
        return False
    if Path(backup_name).name != backup_name or "/" in backup_name or "\\" in backup_name:
        return False
    try:
        prefix = _slot_backup_prefix(rel_slot)
    except ValueError:
        return False
    pattern = rf"{re.escape(prefix)}_\d{{8}}T\d+Z(?:_[0-9a-fA-F]{{4}})?_[0-9a-fA-F]{{8}}\.bak"
    return bool(re.fullmatch(pattern, backup_name, re.IGNORECASE))


def expected_slot_kind(slot_name: str) -> str | None:
    base = Path(slot_name).name
    m_save = re.match(r"^(?:Save|AutomaticSave|AutomaticDSave)(0|[1-9]|1[0-9])\.Save$", base, re.IGNORECASE)
    if m_save:
        return "save"
    if base.lower() == "round.dat":
        return "round"
    if UUID_RE.match(base):
        return "guid"
    if base.lower().endswith(".savetitle"):
        return "title"
    return None


def _current_pinned_win_parent(fallback: Path) -> Path:
    stack = getattr(_PINNED_WIN_CANON, "stack", None)
    if stack:
        fb_key = _norm_local_path_str(fallback)
        for p_key, p_canon in reversed(stack):
            if fb_key == p_key or fb_key == os.path.normcase(p_canon):
                return Path(p_canon)
        return Path(stack[-1][1])
    return Path(os.path.abspath(fallback))


@contextlib.contextmanager
def _open_pinned_parent(
    root: Path,
    rel_path: str,
    create_dirs: bool = False,
    expected_root_id: tuple[Any, ...] | None = None,
):
    _assert_no_reparse_in_ancestors(root)
    if expected_root_id is None:
        id_map = getattr(_LOCK_DEPTH, "id_map", None)
        if id_map:
            rk = _norm_local_path_str(root)
            if rk in id_map:
                expected_root_id = id_map[rk]

    if os.name != "nt" and "\\" in rel_path:
        raise ValueError("POSIX 슬롯 경로에는 역슬래시(\\)를 사용할 수 없습니다.")
    cand_path = resolve_safe_save_path(root, rel_path)
    parts = (rel_path.replace("\\", "/") if os.name == "nt" else rel_path).split("/")
    leaf_name = parts[-1]
    if _is_reparse_or_symlink(cand_path):
        raise ValueError("심볼릭 링크 파일은 읽거나 쓸 수 없습니다.")

    if os.name != "nt" and hasattr(os, "O_DIRECTORY"):
        dir_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        cur_fd: int | None = None
        try:
            cur_fd, got_root_id, _ = _open_and_pin_dir_nofollow(
                root, create_missing=(create_dirs and expected_root_id is None)
            )
            if expected_root_id is not None and got_root_id != expected_root_id:
                raise ValueError("세이브 루트 디렉터리 식별자가 변경되었습니다.")

            for seg in parts[:-1]:
                if seg in ("", "."):
                    continue
                if create_dirs:
                    try:
                        os.mkdir(seg, 0o700, dir_fd=cur_fd)
                    except FileExistsError:
                        pass
                    else:
                        _fsync_dir_fd(cur_fd)
                try:
                    next_fd = os.open(seg, dir_flags, dir_fd=cur_fd)
                except (OSError, NotADirectoryError) as exc:
                    if getattr(exc, "errno", None) in (errno.ELOOP, errno.ENOTDIR) or isinstance(exc, NotADirectoryError):
                        raise ValueError("심볼릭 링크 디렉터리는 허용되지 않습니다.") from exc
                    raise
                try:
                    if not stat.S_ISDIR(os.fstat(next_fd).st_mode):
                        raise ValueError("심볼릭 링크 디렉터리는 허용되지 않습니다.")
                except BaseException:
                    os.close(next_fd)
                    raise
                os.close(cur_fd)
                cur_fd = next_fd

            try:
                st_leaf = os.lstat(leaf_name, dir_fd=cur_fd)
            except FileNotFoundError:
                pass
            else:
                if stat.S_ISLNK(st_leaf.st_mode):
                    raise ValueError("심볼릭 링크 파일은 읽거나 쓸 수 없습니다.")

            id_map = getattr(_LOCK_DEPTH, "id_map", None)
            if id_map:
                parent_key = _norm_local_path_str(cand_path.parent)
                if parent_key in id_map:
                    expected_parent_id = id_map[parent_key]
                    st_final = os.fstat(cur_fd)
                    if ("posix", int(st_final.st_dev), int(st_final.st_ino)) != expected_parent_id:
                        raise ValueError("슬롯 부모 디렉터리 식별자가 변경되었습니다.")

            yield cand_path, leaf_name, cur_fd
        finally:
            if cur_fd is not None:
                try:
                    os.close(cur_fd)
                except OSError:
                    pass
    else:
        handles: list[int] = []
        stack = getattr(_PINNED_WIN_CANON, "stack", None)
        if stack is None:
            stack = []
            _PINNED_WIN_CANON.stack = stack
        pushed = False
        try:
            root_h, got_root_id, root_pinned_path = _open_and_pin_dir_nofollow(
                root, create_missing=(create_dirs and expected_root_id is None)
            )
            handles.append(root_h)
            if expected_root_id is not None and got_root_id != expected_root_id:
                raise ValueError("세이브 루트 디렉터리 식별자가 변경되었습니다.")
            _, root_canon = _win32_inspect_dir_handle(root_h)
            root_prefix = os.path.normcase(root_canon).rstrip("\\") + "\\"
            parent_canon = root_canon
            parent_dir_id: tuple[Any, ...] | None = got_root_id
            cur_dir = Path(root_canon)

            for seg in parts[:-1]:
                if seg in ("", "."):
                    continue
                entries = os.listdir(cur_dir)
                if any(e.lower() == seg.lower() and e != seg for e in entries):
                    raise ValueError("대소문자만 다른 동일 이름의 슬롯이 존재하여 모호한 접근이 차단되었습니다.")
                if seg not in entries and os.path.lexists(cur_dir / seg):
                    raise ValueError("디렉터리 별칭(8.3 단축 이름 등) 접근이 차단되었습니다.")
                next_dir = cur_dir / seg
                if create_dirs and seg not in entries:
                    try:
                        os.mkdir(next_dir)
                    except FileExistsError:
                        pass
                if _is_reparse_or_symlink(next_dir):
                    raise ValueError("심볼릭 링크 디렉터리는 허용되지 않습니다.")
                h = _win32_create_file(str(next_dir), 0x80000000, 0x03, 3, 0x02200000)
                handles.append(h)
                dir_id, canon = _win32_inspect_dir_handle(h)
                if not os.path.normcase(canon).startswith(root_prefix):
                    raise ValueError("심볼릭 링크 디렉터리는 허용되지 않습니다.")
                if os.path.normcase(Path(canon).name) != os.path.normcase(seg):
                    raise ValueError("디렉터리 별칭(8.3 단축 이름 등) 접근이 차단되었습니다.")
                parent_canon = canon
                parent_dir_id = dir_id
                cur_dir = Path(canon)

            if _is_reparse_or_symlink(cand_path) or _is_reparse_or_symlink(cur_dir / leaf_name):
                raise ValueError("심볼릭 링크 파일은 읽거나 쓸 수 없습니다.")

            id_map = getattr(_LOCK_DEPTH, "id_map", None)
            if id_map:
                parent_key = _norm_local_path_str(cand_path.parent)
                if parent_key in id_map:
                    expected_parent_id = id_map[parent_key]
                    if parent_dir_id != expected_parent_id:
                        raise ValueError("슬롯 부모 디렉터리 식별자가 변경되었습니다.")

            stack.append((_norm_local_path_str(cand_path.parent), parent_canon))
            pushed = True
            yield cand_path, leaf_name, None
        finally:
            if pushed and stack:
                stack.pop()
            for h in reversed(handles):
                try:
                    _CloseHandle(wintypes.HANDLE(h))
                except Exception:
                    pass


def _read_verified_with_id_in_parent(
    dfd: int | None,
    target: Path,
    leaf_name: str,
) -> tuple[bytes, tuple[Any, ...] | None]:
    if dfd is None and os.name == "nt":
        h = _win32_create_file(str(target), 0x80000000, 0x01, 3, 0x00200000)
        try:
            _win32_verify_open_handle(
                h,
                _current_pinned_win_parent(target.parent),
                MAX_SAVE_BYTES,
                expected_leaf=leaf_name,
            )
            return (
                _win32_read_handle_bytes(h, MAX_SAVE_BYTES),
                _win32_get_handle_file_id(h),
            )
        finally:
            _CloseHandle(wintypes.HANDLE(h))

    st_leaf = os.lstat(leaf_name if dfd is not None else str(target), dir_fd=dfd)
    if stat.S_ISLNK(st_leaf.st_mode):
        raise ValueError("심볼릭 링크 파일은 읽거나 쓸 수 없습니다.")

    flags = (
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        fd = os.open(leaf_name if dfd is not None else str(target), flags, dir_fd=dfd)
    except OSError as exc:
        if getattr(exc, "errno", None) == errno.ELOOP:
            raise ValueError("심볼릭 링크 파일은 읽거나 쓸 수 없습니다.") from exc
        raise
    try:
        st1 = os.fstat(fd)
        if not stat.S_ISREG(st1.st_mode):
            raise ValueError("일반 파일이 아닌 경로는 읽을 수 없습니다.")
        if getattr(st1, "st_nlink", 1) > 1:
            raise ValueError("하드링크가 연결된 세이브 파일은 거부됩니다.")
        if st1.st_size > MAX_SAVE_BYTES:
            raise ValueError("세이브 파일 크기가 허용 한도(16 MiB)를 초과합니다.")
        if os.name != "nt" and getattr(os, "O_NONBLOCK", 0):
            import fcntl

            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)
        chunks: list[bytes] = []
        total = 0
        while True:
            buf = os.read(fd, 65536)
            if not buf:
                break
            total += len(buf)
            if total > MAX_SAVE_BYTES:
                raise ValueError("세이브 파일 크기가 허용 한도(16 MiB)를 초과합니다.")
            chunks.append(buf)
        raw = b"".join(chunks)
        fd_id = (int(st1.st_dev), int(st1.st_ino))
        if dfd is not None:
            st2 = os.fstat(fd)
            try:
                st_path = os.lstat(leaf_name, dir_fd=dfd)
            except OSError as exc:
                raise RuntimeError("CONFLICT_MODIFIED") from exc
            expected_meta = (st1.st_mtime_ns, st1.st_ctime_ns, len(raw))
            if (
                stat.S_ISLNK(st_path.st_mode)
                or not stat.S_ISREG(st_path.st_mode)
                or getattr(st2, "st_nlink", 1) > 1
                or getattr(st_path, "st_nlink", 1) > 1
                or (int(st_path.st_dev), int(st_path.st_ino)) != fd_id
                or (st2.st_mtime_ns, st2.st_ctime_ns, st2.st_size) != expected_meta
                or (st_path.st_mtime_ns, st_path.st_ctime_ns, st_path.st_size) != expected_meta
            ):
                raise RuntimeError("CONFLICT_MODIFIED")
            return raw, fd_id
        return raw, fd_id
    finally:
        os.close(fd)


def _read_verified_in_parent(dfd: int | None, target: Path, leaf_name: str) -> bytes:
    return _read_verified_with_id_in_parent(dfd, target, leaf_name)[0]


def _verify_posix_leaf_unchanged_in_parent(
    dfd: int,
    leaf_name: str,
    expected_sha: str,
    expected_id: tuple[int, int] | None = None,
    after_read_hook: Callable[[], None] | None = None,
) -> tuple[int, int]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        fd = os.open(leaf_name, flags, dir_fd=dfd)
    except (FileNotFoundError, OSError) as exc:
        raise RuntimeError("CONFLICT_MODIFIED") from exc
    try:
        try:
            st1 = os.fstat(fd)
        except OSError as exc:
            raise RuntimeError("CONFLICT_MODIFIED") from exc
        if (
            not stat.S_ISREG(st1.st_mode)
            or getattr(st1, "st_nlink", 1) > 1
            or st1.st_size > MAX_SAVE_BYTES
        ):
            raise RuntimeError("CONFLICT_MODIFIED")
        fd_id = (int(st1.st_dev), int(st1.st_ino))
        if expected_id is not None and fd_id != expected_id:
            raise RuntimeError("CONFLICT_MODIFIED")
        if os.name != "nt" and getattr(os, "O_NONBLOCK", 0):
            import fcntl

            try:
                fl = fcntl.fcntl(fd, fcntl.F_GETFL)
                fcntl.fcntl(fd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)
            except OSError as exc:
                raise RuntimeError("CONFLICT_MODIFIED") from exc
        chunks: list[bytes] = []
        total = 0
        try:
            while True:
                buf = os.read(fd, 65536)
                if not buf:
                    break
                total += len(buf)
                if total > MAX_SAVE_BYTES:
                    raise RuntimeError("CONFLICT_MODIFIED")
                chunks.append(buf)
        except OSError as exc:
            raise RuntimeError("CONFLICT_MODIFIED") from exc
        raw = b"".join(chunks)
        if hashlib.sha256(raw).hexdigest().lower() != expected_sha.lower():
            raise RuntimeError("CONFLICT_MODIFIED")
        if after_read_hook is not None:
            after_read_hook()
        try:
            st2 = os.fstat(fd)
            st_path = os.lstat(leaf_name, dir_fd=dfd)
        except (FileNotFoundError, OSError) as exc:
            raise RuntimeError("CONFLICT_MODIFIED") from exc
        expected_meta = (st1.st_mtime_ns, st1.st_ctime_ns, len(raw))
        if (
            stat.S_ISLNK(st_path.st_mode)
            or not stat.S_ISREG(st_path.st_mode)
            or getattr(st2, "st_nlink", 1) > 1
            or getattr(st_path, "st_nlink", 1) > 1
            or (int(st_path.st_dev), int(st_path.st_ino)) != fd_id
            or (st2.st_mtime_ns, st2.st_ctime_ns, st2.st_size) != expected_meta
            or (st_path.st_mtime_ns, st_path.st_ctime_ns, st_path.st_size) != expected_meta
        ):
            raise RuntimeError("CONFLICT_MODIFIED")
        return fd_id
    finally:
        os.close(fd)


def _verify_tmp_and_target_before_posix_replace(
    dfd: int,
    tmp_name: str,
    written_id: tuple[int, int] | None,
    expected_new_sha: str,
    target_leaf: str,
    existed: bool,
    orig_id: tuple[int, int] | None,
    expected_orig_sha: str,
    post_tmp_verify_hook: Callable[[], None] | None = None,
    after_target_read_hook: Callable[[], None] | None = None,
) -> None:
    def conflict() -> None:
        raise RuntimeError("CONFLICT_MODIFIED")

    def read_all(rfd: int) -> bytes:
        parts: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(rfd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_SAVE_BYTES:
                conflict()
            parts.append(chunk)
        return b"".join(parts)

    def clear_nonblock(rfd: int) -> None:
        if os.name != "nt" and getattr(os, "O_NONBLOCK", 0):
            import fcntl

            fl = fcntl.fcntl(rfd, fcntl.F_GETFL)
            fcntl.fcntl(rfd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)

    flags = (
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )

    orig_fd: int | None = None
    orig_st1 = None
    orig_raw = b""
    tmp_vfd: int | None = None
    try:
        tmp_vfd = os.open(tmp_name, flags, dir_fd=dfd)
        try:
            tmp_st1 = os.fstat(tmp_vfd)
            if not stat.S_ISREG(tmp_st1.st_mode):
                conflict()
            if getattr(tmp_st1, "st_nlink", 1) != 1:
                conflict()
            if tmp_st1.st_size > MAX_SAVE_BYTES:
                conflict()
            if written_id is not None and (int(tmp_st1.st_dev), int(tmp_st1.st_ino)) != written_id:
                conflict()

            clear_nonblock(tmp_vfd)
            tmp_raw1 = read_all(tmp_vfd)
            if hashlib.sha256(tmp_raw1).hexdigest().lower() != expected_new_sha.lower():
                conflict()

            if post_tmp_verify_hook is not None:
                post_tmp_verify_hook()

            if existed:
                orig_fd = os.open(target_leaf, flags, dir_fd=dfd)
                orig_st1 = os.fstat(orig_fd)
                if not stat.S_ISREG(orig_st1.st_mode):
                    conflict()
                if getattr(orig_st1, "st_nlink", 1) != 1:
                    conflict()
                if orig_st1.st_size > MAX_SAVE_BYTES:
                    conflict()
                if orig_id is not None and (int(orig_st1.st_dev), int(orig_st1.st_ino)) != orig_id:
                    conflict()

                clear_nonblock(orig_fd)
                orig_raw = read_all(orig_fd)
                if hashlib.sha256(orig_raw).hexdigest().lower() != expected_orig_sha.lower():
                    conflict()

                if after_target_read_hook is not None:
                    after_target_read_hook()

            if existed and orig_fd is not None and orig_st1 is not None:
                orig_st2 = os.fstat(orig_fd)
                orig_path_st = os.lstat(target_leaf, dir_fd=dfd)
                if stat.S_ISLNK(orig_path_st.st_mode):
                    conflict()
                if not stat.S_ISREG(orig_path_st.st_mode):
                    conflict()
                if getattr(orig_st2, "st_nlink", 1) != 1:
                    conflict()
                if getattr(orig_path_st, "st_nlink", 1) != 1:
                    conflict()
                if (int(orig_st2.st_dev), int(orig_st2.st_ino)) != (
                    int(orig_path_st.st_dev),
                    int(orig_path_st.st_ino),
                ):
                    conflict()
                if orig_id is not None and (int(orig_st2.st_dev), int(orig_st2.st_ino)) != orig_id:
                    conflict()
                if (orig_st2.st_mtime_ns, orig_st2.st_ctime_ns, orig_st2.st_size) != (
                    orig_st1.st_mtime_ns,
                    orig_st1.st_ctime_ns,
                    len(orig_raw),
                ):
                    conflict()
                if (orig_st1.st_mtime_ns, orig_st1.st_ctime_ns, len(orig_raw)) != (
                    orig_path_st.st_mtime_ns,
                    orig_path_st.st_ctime_ns,
                    orig_path_st.st_size,
                ):
                    conflict()

            os.lseek(tmp_vfd, 0, os.SEEK_SET)
            tmp_raw2 = read_all(tmp_vfd)
            if hashlib.sha256(tmp_raw2).hexdigest().lower() != expected_new_sha.lower():
                conflict()

            tmp_st2 = os.fstat(tmp_vfd)
            tmp_path_st = os.lstat(tmp_name, dir_fd=dfd)
            if stat.S_ISLNK(tmp_path_st.st_mode):
                conflict()
            if not stat.S_ISREG(tmp_path_st.st_mode):
                conflict()
            if getattr(tmp_st2, "st_nlink", 1) != 1:
                conflict()
            if getattr(tmp_path_st, "st_nlink", 1) != 1:
                conflict()
            if (int(tmp_st2.st_dev), int(tmp_st2.st_ino)) != (
                int(tmp_path_st.st_dev),
                int(tmp_path_st.st_ino),
            ):
                conflict()
            if written_id is not None and (int(tmp_st2.st_dev), int(tmp_st2.st_ino)) != written_id:
                conflict()
            if (tmp_st2.st_mtime_ns, tmp_st2.st_ctime_ns, tmp_st2.st_size) != (
                tmp_st1.st_mtime_ns,
                tmp_st1.st_ctime_ns,
                len(tmp_raw2),
            ):
                conflict()
            if (tmp_st1.st_mtime_ns, tmp_st1.st_ctime_ns, len(tmp_raw2)) != (
                tmp_path_st.st_mtime_ns,
                tmp_path_st.st_ctime_ns,
                tmp_path_st.st_size,
            ):
                conflict()
        finally:
            try:
                if orig_fd is not None:
                    os.close(orig_fd)
            finally:
                if tmp_vfd is not None:
                    os.close(tmp_vfd)
    except (FileNotFoundError, OSError) as exc:
        raise RuntimeError("CONFLICT_MODIFIED") from exc


_POSIX_RENAMEAT2_FUNC: tuple[str, Any] | None = None


def _posix_try_rename_exchange(dfd: int, src_name: str, dst_name: str) -> str:
    global _POSIX_RENAMEAT2_FUNC

    if os.name == "nt":
        return "UNSUPPORTED"

    if _POSIX_RENAMEAT2_FUNC is None:
        libc = ctypes.CDLL(None, use_errno=True)
        fn = getattr(libc, "renameat2", None)
        if fn is not None:
            fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            fn.restype = ctypes.c_int
            _POSIX_RENAMEAT2_FUNC = ("renameat2", fn)
        elif platform.system() == "Linux":
            machine = platform.machine().lower()
            if machine in ("x86_64", "amd64"):
                sysno = 316
            elif machine in ("aarch64", "arm64"):
                sysno = 276
            else:
                sysno = -1
            if sysno >= 0 and getattr(libc, "syscall", None) is not None:
                sc = libc.syscall
                sc.argtypes = [ctypes.c_long, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
                sc.restype = ctypes.c_long
                _POSIX_RENAMEAT2_FUNC = ("syscall", (sc, sysno))
            else:
                _POSIX_RENAMEAT2_FUNC = ("none", None)
        else:
            _POSIX_RENAMEAT2_FUNC = ("none", None)

    kind, func = _POSIX_RENAMEAT2_FUNC
    if kind == "none":
        return "UNSUPPORTED"

    src_b = os.fsencode(src_name)
    dst_b = os.fsencode(dst_name)
    flags = 2
    ctypes.set_errno(0)
    if kind == "renameat2":
        rc = func(dfd, src_b, dfd, dst_b, flags)
    else:
        sc, sysno = func
        rc = sc(sysno, dfd, src_b, dfd, dst_b, flags)

    if rc == 0:
        return "EXCHANGED"

    err = ctypes.get_errno()
    if err == errno.ENOENT:
        raise RuntimeError("CONFLICT_MODIFIED")
    if err in (errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.EINVAL)):
        return "UNSUPPORTED"
    raise OSError(err, os.strerror(err))


def _posix_supports_rename_exchange(dir_path: Path) -> bool:
    if os.name == "nt":
        return False
    dfd = -1
    probe_a = ""
    probe_b = ""
    try:
        dfd = os.open(
            dir_path,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        suffix = os.urandom(8).hex()
        probe_a = f".twx_rex_a.{suffix}.tmp"
        probe_b = f".twx_rex_b.{suffix}.tmp"
        fd_a = os.open(probe_a, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o600, dir_fd=dfd)
        try:
            os.write(fd_a, b"x")
        finally:
            os.close(fd_a)
        fd_b = os.open(probe_b, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o600, dir_fd=dfd)
        try:
            os.write(fd_b, b"x")
        finally:
            os.close(fd_b)
        return _posix_try_rename_exchange(dfd, probe_a, probe_b) == "EXCHANGED"
    except OSError:
        return False
    finally:
        if dfd != -1:
            if probe_a:
                try:
                    os.unlink(probe_a, dir_fd=dfd)
                except OSError:
                    pass
            if probe_b:
                try:
                    os.unlink(probe_b, dir_fd=dfd)
                except OSError:
                    pass
            try:
                os.close(dfd)
            except OSError:
                pass


def _unlink_posix_tmp_if_id_matches(
    dfd: int,
    tmp_name: str,
    expected_id: tuple[int, int] | None,
) -> bool:
    if expected_id is None:
        return False
    try:
        st_u = os.lstat(tmp_name, dir_fd=dfd)
    except OSError:
        return False
    if (
        not stat.S_ISLNK(st_u.st_mode)
        and stat.S_ISREG(st_u.st_mode)
        and (int(st_u.st_dev), int(st_u.st_ino)) == expected_id
    ):
        try:
            os.unlink(tmp_name, dir_fd=dfd)
        except OSError:
            return False
        return True
    return False


def _posix_link_verified_new_slot(
    dfd: int,
    tmp_name: str,
    expected_tmp_id: tuple[int, int] | None,
    expected_tmp_sha: str,
    target_leaf: str,
    on_state: Callable[[bool, str | None, bool], None] | None = None,
) -> None:
    if expected_tmp_id is None:
        raise RuntimeError("CONFLICT_MODIFIED")

    def _read_verified_fd_sha(rfd: int) -> str:
        if getattr(os, "O_NONBLOCK", 0) and hasattr(os, "set_blocking"):
            try:
                os.set_blocking(rfd, True)
            except OSError:
                pass
        os.lseek(rfd, 0, os.SEEK_SET)
        bufs: list[bytes] = []
        seen = 0
        while True:
            piece = os.read(rfd, 65536)
            if not piece:
                break
            seen += len(piece)
            if seen > MAX_SAVE_BYTES:
                raise RuntimeError("CONFLICT_MODIFIED")
            bufs.append(piece)
        return hashlib.sha256(b"".join(bufs)).hexdigest().lower()

    def _apply_new_slot_swap_sim(env_key: str) -> None:
        sim_mode = os.environ.get(env_key, "")
        if sim_mode == "ext_symlink":
            os.unlink(tmp_name, dir_fd=dfd)
            os.symlink(
                os.environ["TWX_SIMULATE_POSIX_NEW_SLOT_EXT_TARGET"],
                tmp_name,
                dir_fd=dfd,
            )
        elif sim_mode == "other_reg":
            os.unlink(tmp_name, dir_fd=dfd)
            fd_sw = os.open(
                tmp_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=dfd,
            )
            try:
                os.write(fd_sw, b'{"swapped_new_slot":1}')
            finally:
                os.close(fd_sw)

    exp_sha_lc = expected_tmp_sha.lower()
    fd_new: int | None = None
    link_created = False
    try:
        try:
            fd_new = os.open(
                tmp_name,
                os.O_RDONLY
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=dfd,
            )
            st1 = os.fstat(fd_new)
            if (
                not stat.S_ISREG(st1.st_mode)
                or getattr(st1, "st_nlink", 0) != 1
                or int(st1.st_size) > MAX_SAVE_BYTES
                or (int(st1.st_dev), int(st1.st_ino)) != expected_tmp_id
            ):
                raise RuntimeError("CONFLICT_MODIFIED")
            if _read_verified_fd_sha(fd_new) != exp_sha_lc:
                raise RuntimeError("CONFLICT_MODIFIED")
            st2 = os.fstat(fd_new)
            st_p1 = os.lstat(tmp_name, dir_fd=dfd)
            if (
                stat.S_ISLNK(st_p1.st_mode)
                or not stat.S_ISREG(st_p1.st_mode)
                or getattr(st2, "st_nlink", 0) != 1
                or getattr(st_p1, "st_nlink", 0) != 1
                or (int(st2.st_dev), int(st2.st_ino)) != expected_tmp_id
                or (int(st_p1.st_dev), int(st_p1.st_ino)) != expected_tmp_id
                or (st2.st_mtime_ns, st2.st_ctime_ns, st2.st_size)
                != (st1.st_mtime_ns, st1.st_ctime_ns, st1.st_size)
                or (st_p1.st_mtime_ns, st_p1.st_ctime_ns, st_p1.st_size)
                != (st1.st_mtime_ns, st1.st_ctime_ns, st1.st_size)
            ):
                raise RuntimeError("CONFLICT_MODIFIED")
        except (FileNotFoundError, OSError) as exc:
            raise RuntimeError("CONFLICT_MODIFIED") from exc

        _apply_new_slot_swap_sim("TWX_SIMULATE_POSIX_NEW_SLOT_TMP_SWAP")

        proc_fd_path = f"/proc/self/fd/{fd_new}"
        if (
            os.environ.get("TWX_FORCE_POSIX_NO_PROC_FD") == "1"
            or not os.path.exists(proc_fd_path)
        ):
            raise RuntimeError("ATOMIC_FD_LINK_UNSUPPORTED")

        try:
            os.link(
                proc_fd_path,
                target_leaf,
                dst_dir_fd=dfd,
                follow_symlinks=True,
            )
        except (FileExistsError, OSError) as exc:
            raise RuntimeError("CONFLICT_MODIFIED") from exc
        link_created = True

        try:
            if os.environ.get("TWX_SIMULATE_POSIX_NEW_SLOT_POST_LINK_TARGET_REPLACE") == "1":
                os.replace(
                    os.environ["TWX_SIMULATE_POSIX_NEW_SLOT_REPLACE_SRC"],
                    target_leaf,
                    dst_dir_fd=dfd,
                )
            if os.environ.get("TWX_SIMULATE_POSIX_NEW_SLOT_POST_LINK_SAME_INODE_WRITE") == "1":
                ext_new_obj = create_demo_data("save")
                ext_new_obj["m_iMoney"] = 919191
                ext_new_obj["m_strPlayerName"] = "EXT_NEW_SLOT_INPLACE\r"
                ext_new_bytes = serialize_json_lossless(ext_new_obj).encode("utf-8")
                fd_ext_w = os.open(target_leaf, os.O_WRONLY | os.O_TRUNC, dir_fd=dfd)
                try:
                    os.write(fd_ext_w, ext_new_bytes)
                finally:
                    os.close(fd_ext_w)

            st_leaf = os.lstat(target_leaf, dir_fd=dfd)
            if (
                stat.S_ISLNK(st_leaf.st_mode)
                or not stat.S_ISREG(st_leaf.st_mode)
                or (int(st_leaf.st_dev), int(st_leaf.st_ino)) != expected_tmp_id
            ):
                raise RuntimeError("CONFLICT_MODIFIED")

            if _read_verified_fd_sha(fd_new) != exp_sha_lc:
                raise RuntimeError("CONFLICT_MODIFIED")
            st_fd_after = os.fstat(fd_new)
            if (
                (int(st_fd_after.st_dev), int(st_fd_after.st_ino)) != expected_tmp_id
                or getattr(st_fd_after, "st_nlink", 0) != 2
            ):
                raise RuntimeError("CONFLICT_MODIFIED")

            _apply_new_slot_swap_sim("TWX_SIMULATE_POSIX_NEW_SLOT_POST_LINK_TMP_SWAP")

            if os.environ.get("TWX_SIMULATE_POSIX_LINK_TMP_UNLINK_FAIL") == "1":
                raise OSError(errno.EIO, "SIMULATED_POSIX_LINK_TMP_UNLINK_FAIL")

            st_link_tmp = os.lstat(tmp_name, dir_fd=dfd)
            if (
                stat.S_ISLNK(st_link_tmp.st_mode)
                or not stat.S_ISREG(st_link_tmp.st_mode)
                or (int(st_link_tmp.st_dev), int(st_link_tmp.st_ino)) != expected_tmp_id
            ):
                raise RuntimeError("CONFLICT_MODIFIED")

            os.unlink(tmp_name, dir_fd=dfd)
            if getattr(os.fstat(fd_new), "st_nlink", 0) != 1:
                raise RuntimeError("CONFLICT_MODIFIED")
            if on_state is not None:
                on_state(True, None, False)
        except BaseException as exc:
            if link_created:
                st_c = None
                init_lstat_err = False
                try:
                    st_c = os.lstat(target_leaf, dir_fd=dfd)
                except FileNotFoundError:
                    st_c = None
                except OSError:
                    st_c = None
                    init_lstat_err = True

                if init_lstat_err:
                    try:
                        assert fd_new is not None
                        if getattr(os.fstat(fd_new), "st_nlink", 0) >= 2:
                            _unlink_posix_tmp_if_id_matches(dfd, tmp_name, expected_tmp_id)
                            try:
                                _fsync_dir_fd(dfd)
                            except OSError:
                                pass
                    except OSError:
                        pass
                    if on_state is not None:
                        on_state(True, tmp_name, True)
                elif (
                    st_c is not None
                    and not stat.S_ISLNK(st_c.st_mode)
                    and stat.S_ISREG(st_c.st_mode)
                    and (int(st_c.st_dev), int(st_c.st_ino)) == expected_tmp_id
                ):
                    target_check_err = False
                    try:
                        assert fd_new is not None
                        st_chk1 = os.fstat(fd_new)
                        cur_sha = _read_verified_fd_sha(fd_new)
                        st_chk2 = os.fstat(fd_new)
                        st_c2 = os.lstat(target_leaf, dir_fd=dfd)
                        target_unmodified = (
                            cur_sha == exp_sha_lc
                            and not stat.S_ISLNK(st_c2.st_mode)
                            and stat.S_ISREG(st_c2.st_mode)
                            and (int(st_c2.st_dev), int(st_c2.st_ino)) == expected_tmp_id
                            and (st_chk2.st_mtime_ns, st_chk2.st_ctime_ns, st_chk2.st_size)
                            == (st_chk1.st_mtime_ns, st_chk1.st_ctime_ns, st_chk1.st_size)
                            and (st_c2.st_mtime_ns, st_c2.st_ctime_ns, st_c2.st_size)
                            == (st_chk1.st_mtime_ns, st_chk1.st_ctime_ns, st_chk1.st_size)
                            and getattr(st_c2, "st_nlink", 0) in (1, 2)
                        )
                    except FileNotFoundError:
                        target_unmodified = False
                        st_c = None
                    except Exception:
                        target_unmodified = False
                        target_check_err = True

                    if st_c is None and not target_check_err:
                        if on_state is not None:
                            on_state(False, tmp_name, False)
                    elif target_unmodified:
                        unlink_done = False
                        fsync_failed = False
                        post_lstat_err = False
                        absent_confirmed = False
                        try:
                            os.unlink(target_leaf, dir_fd=dfd)
                            unlink_done = True
                        except FileNotFoundError:
                            unlink_done = True
                        except OSError:
                            unlink_done = False

                        if unlink_done:
                            try:
                                _fsync_dir_fd(dfd)
                            except OSError:
                                fsync_failed = True
                            try:
                                os.lstat(target_leaf, dir_fd=dfd)
                                absent_confirmed = False
                            except FileNotFoundError:
                                absent_confirmed = True
                            except OSError:
                                absent_confirmed = False
                                post_lstat_err = True

                        if unlink_done and not fsync_failed and absent_confirmed:
                            if on_state is not None:
                                on_state(False, tmp_name, False)
                        else:
                            try:
                                assert fd_new is not None
                                if getattr(os.fstat(fd_new), "st_nlink", 0) >= 2:
                                    _unlink_posix_tmp_if_id_matches(dfd, tmp_name, expected_tmp_id)
                                    try:
                                        _fsync_dir_fd(dfd)
                                    except OSError:
                                        pass
                            except OSError:
                                pass
                            if on_state is not None:
                                on_state(
                                    not absent_confirmed,
                                    tmp_name,
                                    fsync_failed or post_lstat_err,
                                )
                    else:
                        try:
                            assert fd_new is not None
                            if getattr(os.fstat(fd_new), "st_nlink", 0) >= 2:
                                _unlink_posix_tmp_if_id_matches(dfd, tmp_name, expected_tmp_id)
                                _fsync_dir_fd(dfd)
                        except OSError:
                            pass
                        if on_state is not None:
                            on_state(target_check_err, None, True)
                else:
                    if on_state is not None:
                        on_state(False, tmp_name, False)

            if isinstance(exc, RuntimeError):
                raise
            if (
                isinstance(exc, OSError)
                and getattr(exc, "errno", None) == errno.EIO
                and "SIMULATED_POSIX_LINK_TMP_UNLINK_FAIL" in str(exc)
            ):
                raise
            if isinstance(exc, (FileNotFoundError, OSError)):
                raise RuntimeError("CONFLICT_MODIFIED") from exc
            raise
    finally:
        if fd_new is not None:
            try:
                os.close(fd_new)
            except OSError:
                pass


def _posix_exchange_or_replace_verified(
    dfd: int,
    tmp_name: str,
    expected_tmp_id: tuple[int, int] | None,
    expected_tmp_sha: str,
    target_name: str,
    expected_orig_id: tuple[int, int] | None,
    expected_orig_sha: str,
    on_state: Callable[[bool, str | None, bool], None],
    role: str = "",
    after_preverify_hook: Callable[[], None] | None = None,
) -> None:
    if after_preverify_hook is not None:
        after_preverify_hook()
    if role and os.environ.get("TWX_SIMULATE_POST_PREVERIFY_TMP_TAMPER") == role:
        fd_tamper = os.open(tmp_name, os.O_WRONLY | os.O_TRUNC, dir_fd=dfd)
        try:
            os.write(fd_tamper, b'{"post_pv_tmp_tampered":1}')
        finally:
            os.close(fd_tamper)
    if role and os.environ.get("TWX_SIMULATE_POST_PREVERIFY_TMP_SWAP") == role:
        os.unlink(tmp_name, dir_fd=dfd)
        fd_swap = os.open(tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=dfd)
        try:
            os.write(fd_swap, b'{"post_pv_tmp_swapped":1}')
        finally:
            os.close(fd_swap)

    pre_flags = (
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        fd_pre = os.open(tmp_name, pre_flags, dir_fd=dfd)
        try:
            st_pre_fd = os.fstat(fd_pre)
            if (
                not stat.S_ISREG(st_pre_fd.st_mode)
                or getattr(st_pre_fd, "st_nlink", 1) != 1
                or st_pre_fd.st_size > MAX_SAVE_BYTES
            ):
                raise RuntimeError("CONFLICT_MODIFIED")
            pre_fd_id = (int(st_pre_fd.st_dev), int(st_pre_fd.st_ino))
            if expected_tmp_id is not None and pre_fd_id != expected_tmp_id:
                raise RuntimeError("CONFLICT_MODIFIED")
            if os.name != "nt" and getattr(os, "O_NONBLOCK", 0):
                import fcntl

                fl_pre = fcntl.fcntl(fd_pre, fcntl.F_GETFL)
                fcntl.fcntl(fd_pre, fcntl.F_SETFL, fl_pre & ~os.O_NONBLOCK)
            pre_chunks: list[bytes] = []
            pre_total = 0
            while True:
                pre_buf = os.read(fd_pre, 65536)
                if not pre_buf:
                    break
                pre_total += len(pre_buf)
                if pre_total > MAX_SAVE_BYTES:
                    raise RuntimeError("CONFLICT_MODIFIED")
                pre_chunks.append(pre_buf)
            pre_tmp_bytes = b"".join(pre_chunks)
            st_pre_fd2 = os.fstat(fd_pre)
            st_pre_path = os.lstat(tmp_name, dir_fd=dfd)
            pre_meta = (st_pre_fd.st_mtime_ns, st_pre_fd.st_ctime_ns, len(pre_tmp_bytes))
            if (
                stat.S_ISLNK(st_pre_path.st_mode)
                or not stat.S_ISREG(st_pre_path.st_mode)
                or getattr(st_pre_fd2, "st_nlink", 1) != 1
                or getattr(st_pre_path, "st_nlink", 1) != 1
                or (int(st_pre_fd2.st_dev), int(st_pre_fd2.st_ino)) != pre_fd_id
                or (int(st_pre_path.st_dev), int(st_pre_path.st_ino)) != pre_fd_id
                or (st_pre_fd2.st_mtime_ns, st_pre_fd2.st_ctime_ns, st_pre_fd2.st_size) != pre_meta
                or (st_pre_path.st_mtime_ns, st_pre_path.st_ctime_ns, st_pre_path.st_size) != pre_meta
            ):
                raise RuntimeError("CONFLICT_MODIFIED")
            pre_exchange_tmp_sha = hashlib.sha256(pre_tmp_bytes).hexdigest().lower()
        finally:
            os.close(fd_pre)
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        on_state(False, None, False)
        raise RuntimeError("CONFLICT_MODIFIED") from exc

    if pre_exchange_tmp_sha != expected_tmp_sha.lower():
        _unlink_posix_tmp_if_id_matches(dfd, tmp_name, expected_tmp_id)
        on_state(False, None, False)
        _fsync_dir_fd(dfd)
        raise RuntimeError("CONFLICT_MODIFIED")

    def _target_is_unmodified_own_tmp() -> bool:
        if expected_tmp_id is None:
            return False
        try:
            _verify_posix_leaf_unchanged_in_parent(
                dfd, target_name, pre_exchange_tmp_sha, expected_id=expected_tmp_id
            )
            return True
        except Exception:
            return False

    def _unlink_only_if_unmodified_own_tmp() -> bool:
        if expected_tmp_id is None:
            return False
        try:
            _verify_posix_leaf_unchanged_in_parent(
                dfd, tmp_name, pre_exchange_tmp_sha, expected_id=expected_tmp_id
            )
        except Exception:
            return False
        return _unlink_posix_tmp_if_id_matches(dfd, tmp_name, expected_tmp_id)

    mode = _posix_try_rename_exchange(dfd, tmp_name, target_name)
    if mode == "UNSUPPORTED":
        _unlink_posix_tmp_if_id_matches(dfd, tmp_name, expected_tmp_id)
        on_state(False, None, False)
        _fsync_dir_fd(dfd)
        raise RuntimeError("ATOMIC_EXCHANGE_UNSUPPORTED")

    on_state(True, None, False)

    if role and os.environ.get("TWX_SIMULATE_POST_EXCHANGE_EXT_REPLACE") == role:
        if role == "slot":
            ext_post_obj = create_demo_data("save")
            ext_post_obj["m_iMoney"] = 888888
            ext_post_bytes = serialize_json_lossless(ext_post_obj).encode("utf-8")
            ext_tmp_n, _ = _stage_temp_in_parent(dfd, target_name, ext_post_bytes)
            os.replace(ext_tmp_n, target_name, src_dir_fd=dfd, dst_dir_fd=dfd)
        elif role == "title":
            fd_cur_disp = os.open(
                tmp_name,
                os.O_RDONLY
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=dfd,
            )
            try:
                st_cur_disp = os.fstat(fd_cur_disp)
                if st_cur_disp.st_size > MAX_SAVE_BYTES:
                    raise RuntimeError("CONFLICT_MODIFIED")
                chunks = []
                total = 0
                while True:
                    chunk = os.read(fd_cur_disp, 1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_SAVE_BYTES:
                        raise RuntimeError("CONFLICT_MODIFIED")
                    chunks.append(chunk)
                cur_disp_b = b"".join(chunks)
            finally:
                os.close(fd_cur_disp)
            ext_t_data, ext_t_meta = parse_json_lossless(cur_disp_b.decode("utf-8"))
            if cur_disp_b.startswith(b"\xef\xbb\xbf"):
                ext_t_meta["has_bom"] = True
            if isinstance(ext_t_data, list) and ext_t_data and isinstance(ext_t_data[0], dict):
                ext_t_data[0]["m_strPlayerName"] = "EXT_POST_EXCHANGE_TITLE"
            ext_t_bytes = serialize_json_lossless(ext_t_data, ext_t_meta).encode("utf-8")
            ext_tmp_n, _ = _stage_temp_in_parent(dfd, target_name, ext_t_bytes)
            os.replace(ext_tmp_n, target_name, src_dir_fd=dfd, dst_dir_fd=dfd)

    if role and os.environ.get("TWX_SIMULATE_POST_EXCHANGE_EXT_INPLACE") == role:
        if role == "slot":
            ext_ip_obj = create_demo_data("save")
            ext_ip_obj["m_iMoney"] = 765432
            ext_ip_obj["m_strPlayerName"] = "EXT_INPLACE_SLOT\r"
            ext_ip_bytes = serialize_json_lossless(ext_ip_obj).encode("utf-8")
            fd_ip = os.open(target_name, os.O_WRONLY | os.O_TRUNC, dir_fd=dfd)
            try:
                ip_view = memoryview(ext_ip_bytes)
                while ip_view:
                    written_n = os.write(fd_ip, ip_view)
                    ip_view = ip_view[written_n:]
            finally:
                os.close(fd_ip)
        elif role == "title":
            fd_cur_disp = os.open(
                tmp_name,
                os.O_RDONLY
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=dfd,
            )
            try:
                st_cur_disp = os.fstat(fd_cur_disp)
                if st_cur_disp.st_size > MAX_SAVE_BYTES:
                    raise RuntimeError("CONFLICT_MODIFIED")
                chunks = []
                total = 0
                while True:
                    chunk = os.read(fd_cur_disp, 1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_SAVE_BYTES:
                        raise RuntimeError("CONFLICT_MODIFIED")
                    chunks.append(chunk)
                cur_disp_b = b"".join(chunks)
            finally:
                os.close(fd_cur_disp)
            ext_t_data, ext_t_meta = parse_json_lossless(cur_disp_b.decode("utf-8"))
            if cur_disp_b.startswith(b"\xef\xbb\xbf"):
                ext_t_meta["has_bom"] = True
            if isinstance(ext_t_data, list) and ext_t_data and isinstance(ext_t_data[0], dict):
                ext_t_data[0]["m_strPlayerName"] = "EXT_POST_EXCHANGE_INPLACE_TITLE"
            ext_t_bytes = serialize_json_lossless(ext_t_data, ext_t_meta).encode("utf-8")
            fd_ip = os.open(target_name, os.O_WRONLY | os.O_TRUNC, dir_fd=dfd)
            try:
                ip_view = memoryview(ext_t_bytes)
                while ip_view:
                    written_n = os.write(fd_ip, ip_view)
                    ip_view = ip_view[written_n:]
            finally:
                os.close(fd_ip)

    displaced_id: tuple[int, int] | None = None
    try:
        st_disp0 = os.lstat(tmp_name, dir_fd=dfd)
    except OSError:
        displaced_id = None
    else:
        if not stat.S_ISLNK(st_disp0.st_mode) and stat.S_ISREG(st_disp0.st_mode):
            displaced_id = (int(st_disp0.st_dev), int(st_disp0.st_ino))

    def _simulate_displaced_inplace_write(env_var: str) -> None:
        if not role or os.environ.get(env_var) != role:
            return
        if role == "slot":
            ext_disp_obj = create_demo_data("save")
            ext_disp_obj["m_iMoney"] = 642000
            ext_disp_obj["m_strPlayerName"] = "EXT_DISPLACED_SLOT\r"
            ext_disp_bytes = serialize_json_lossless(ext_disp_obj).encode("utf-8")
            fd_dw = os.open(tmp_name, os.O_WRONLY | os.O_TRUNC, dir_fd=dfd)
            try:
                dw_view = memoryview(ext_disp_bytes)
                while dw_view:
                    written_n = os.write(fd_dw, dw_view)
                    dw_view = dw_view[written_n:]
            finally:
                os.close(fd_dw)
        elif role == "title":
            fd_cur_disp = os.open(
                tmp_name,
                os.O_RDONLY
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=dfd,
            )
            try:
                st_cur_disp = os.fstat(fd_cur_disp)
                if st_cur_disp.st_size > MAX_SAVE_BYTES:
                    raise RuntimeError("CONFLICT_MODIFIED")
                chunks = []
                total = 0
                while True:
                    chunk = os.read(fd_cur_disp, 1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_SAVE_BYTES:
                        raise RuntimeError("CONFLICT_MODIFIED")
                    chunks.append(chunk)
                cur_disp_b = b"".join(chunks)
            finally:
                os.close(fd_cur_disp)
            ext_t_data, ext_t_meta = parse_json_lossless(cur_disp_b.decode("utf-8"))
            if cur_disp_b.startswith(b"\xef\xbb\xbf"):
                ext_t_meta["has_bom"] = True
            if isinstance(ext_t_data, list) and ext_t_data and isinstance(ext_t_data[0], dict):
                ext_t_data[0]["m_strPlayerName"] = "EXT_DISPLACED_ORIG_TITLE"
            ext_t_bytes = serialize_json_lossless(ext_t_data, ext_t_meta).encode("utf-8")
            fd_dw = os.open(tmp_name, os.O_WRONLY | os.O_TRUNC, dir_fd=dfd)
            try:
                dw_view = memoryview(ext_t_bytes)
                while dw_view:
                    written_n = os.write(fd_dw, dw_view)
                    dw_view = dw_view[written_n:]
            finally:
                os.close(fd_dw)

    try:
        _verify_posix_leaf_unchanged_in_parent(dfd, target_name, expected_tmp_sha, expected_id=expected_tmp_id)
        installed_ok = True
    except Exception:
        installed_ok = False

    _simulate_displaced_inplace_write("TWX_SIMULATE_POST_INSTALL_DISPLACED_WRITE")

    try:
        _verify_posix_leaf_unchanged_in_parent(dfd, tmp_name, expected_orig_sha, expected_id=expected_orig_id)
        displaced_ok = True
    except Exception:
        displaced_ok = False

    def _try_verified_swapback() -> bool:
        if role and os.environ.get("TWX_SIMULATE_SWAPBACK_FAIL") == role:
            return False
        if displaced_id is None or expected_tmp_id is None:
            return False
        st_disp = os.lstat(tmp_name, dir_fd=dfd)
        if stat.S_ISLNK(st_disp.st_mode) or not stat.S_ISREG(st_disp.st_mode):
            return False
        if (int(st_disp.st_dev), int(st_disp.st_ino)) != displaced_id:
            return False
        if displaced_id == expected_tmp_id or not _target_is_unmodified_own_tmp():
            return False
        if role and os.environ.get("TWX_SIMULATE_SWAPBACK_RACE_EXT_REPLACE") == role:
            race_obj = create_demo_data("save")
            race_obj["m_iMoney"] = 963852
            race_obj["m_strPlayerName"] = "SWAPBACK_RACE_EXT\r"
            race_tmp, _ = _stage_temp_in_parent(
                dfd, target_name, serialize_json_lossless(race_obj).encode("utf-8")
            )
            os.replace(race_tmp, target_name, src_dir_fd=dfd, dst_dir_fd=dfd)
        if _posix_try_rename_exchange(dfd, tmp_name, target_name) != "EXCHANGED":
            return False
        st_restored = os.lstat(target_name, dir_fd=dfd)
        if (
            stat.S_ISLNK(st_restored.st_mode)
            or not stat.S_ISREG(st_restored.st_mode)
            or (int(st_restored.st_dev), int(st_restored.st_ino)) != displaced_id
        ):
            return False
        try:
            _verify_posix_leaf_unchanged_in_parent(
                dfd, tmp_name, pre_exchange_tmp_sha, expected_id=expected_tmp_id
            )
        except Exception:
            try:
                st_cur_t = os.lstat(target_name, dir_fd=dfd)
                if (
                    not stat.S_ISLNK(st_cur_t.st_mode)
                    and stat.S_ISREG(st_cur_t.st_mode)
                    and (int(st_cur_t.st_dev), int(st_cur_t.st_ino)) == displaced_id
                ):
                    if _posix_try_rename_exchange(dfd, tmp_name, target_name) == "EXCHANGED":
                        try:
                            _fsync_dir_fd(dfd)
                        except OSError:
                            pass
            except Exception:
                pass
            return False
        if displaced_ok:
            _verify_posix_leaf_unchanged_in_parent(dfd, target_name, expected_orig_sha, expected_id=expected_orig_id)
        return True

    def _rollback_on_conflict() -> None:
        swapped_back = False
        try:
            swapped_back = _try_verified_swapback()
        except Exception:
            swapped_back = False
        if swapped_back:
            unlinked_own = _unlink_only_if_unmodified_own_tmp()
            keep_bak_after_sync = (not unlinked_own) or (not displaced_ok)
            try:
                if role and os.environ.get("TWX_SIMULATE_POST_SWAPBACK_SYNC_FAIL") == role:
                    raise OSError(errno.EIO, "SIMULATED_POST_SWAPBACK_SYNC_FAIL")
                _fsync_dir_fd(dfd)
            except BaseException:
                on_state(False, None, True)
                raise
            on_state(False, None, keep_bak_after_sync)
            raise RuntimeError("CONFLICT_MODIFIED")
        if not _target_is_unmodified_own_tmp():
            _unlink_only_if_unmodified_own_tmp()
            on_state(False, None, True)
            _fsync_dir_fd(dfd)
            raise RuntimeError("CONFLICT_MODIFIED")
        rec_tmp: str | None = None
        rec_id: tuple[int, int] | None = None
        restored_via_replace = False
        fd_disp: int | None = None
        try:
            fd_disp = os.open(
                tmp_name,
                os.O_RDONLY
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=dfd,
            )
            st_df1 = os.fstat(fd_disp)
            st_dp1 = os.lstat(tmp_name, dir_fd=dfd)
            if (
                stat.S_ISLNK(st_dp1.st_mode)
                or not stat.S_ISREG(st_df1.st_mode)
                or not stat.S_ISREG(st_dp1.st_mode)
                or getattr(st_df1, "st_nlink", 0) != 1
                or getattr(st_dp1, "st_nlink", 0) != 1
                or st_df1.st_size > MAX_SAVE_BYTES
                or displaced_id is None
                or (int(st_df1.st_dev), int(st_df1.st_ino)) != displaced_id
                or (int(st_dp1.st_dev), int(st_dp1.st_ino)) != displaced_id
                or (st_dp1.st_mtime_ns, st_dp1.st_ctime_ns, st_dp1.st_size)
                != (st_df1.st_mtime_ns, st_df1.st_ctime_ns, st_df1.st_size)
            ):
                raise RuntimeError("CONFLICT_MODIFIED")
            expected_disp_meta = (st_df1.st_mtime_ns, st_df1.st_ctime_ns, st_df1.st_size)
            if getattr(os, "O_NONBLOCK", 0):
                try:
                    os.set_blocking(fd_disp, True)
                except Exception:
                    pass
            chunks = []
            total = 0
            while True:
                chunk = os.read(fd_disp, 2048)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_SAVE_BYTES:
                    raise RuntimeError("CONFLICT_MODIFIED")
                chunks.append(chunk)
                if len(chunks) == 1 and role and os.environ.get("TWX_SIMULATE_TORN_DISPLACED_READ") == role:
                    torn_obj = create_demo_data("save")
                    torn_obj["m_iMoney"] = 543210
                    torn_obj["m_strPlayerName"] = "EXT_TORN_SLOT\r"
                    torn_b = serialize_json_lossless(torn_obj).encode("utf-8")
                    wfd = os.open(tmp_name, os.O_WRONLY | os.O_TRUNC, dir_fd=dfd)
                    try:
                        wv = memoryview(torn_b)
                        while wv:
                            wv = wv[os.write(wfd, wv):]
                    finally:
                        os.close(wfd)
            disp_bytes = b"".join(chunks)
            st_df2 = os.fstat(fd_disp)
            st_dp2 = os.lstat(tmp_name, dir_fd=dfd)
            if (
                stat.S_ISLNK(st_dp2.st_mode)
                or not stat.S_ISREG(st_dp2.st_mode)
                or getattr(st_df2, "st_nlink", 0) != 1
                or getattr(st_dp2, "st_nlink", 0) != 1
                or (int(st_df2.st_dev), int(st_df2.st_ino)) != displaced_id
                or (int(st_dp2.st_dev), int(st_dp2.st_ino)) != displaced_id
                or (st_df2.st_mtime_ns, st_df2.st_ctime_ns, len(disp_bytes)) != expected_disp_meta
                or (st_dp2.st_mtime_ns, st_dp2.st_ctime_ns, st_dp2.st_size) != expected_disp_meta
            ):
                raise RuntimeError("CONFLICT_MODIFIED")
            disp_sha = hashlib.sha256(disp_bytes).hexdigest().lower()
            rec_tmp, rec_id = _stage_temp_in_parent(dfd, target_name, disp_bytes)
            os.lseek(fd_disp, 0, os.SEEK_SET)
            re_chunks: list[bytes] = []
            re_total = 0
            while True:
                re_buf = os.read(fd_disp, 65536)
                if not re_buf:
                    break
                re_total += len(re_buf)
                if re_total > MAX_SAVE_BYTES:
                    raise RuntimeError("CONFLICT_MODIFIED")
                re_chunks.append(re_buf)
            re_bytes = b"".join(re_chunks)
            st_df3 = os.fstat(fd_disp)
            st_dp3 = os.lstat(tmp_name, dir_fd=dfd)
            if (
                hashlib.sha256(re_bytes).hexdigest().lower() != disp_sha
                or stat.S_ISLNK(st_dp3.st_mode)
                or not stat.S_ISREG(st_dp3.st_mode)
                or getattr(st_df3, "st_nlink", 0) != 1
                or getattr(st_dp3, "st_nlink", 0) != 1
                or (int(st_df3.st_dev), int(st_df3.st_ino)) != displaced_id
                or (int(st_dp3.st_dev), int(st_dp3.st_ino)) != displaced_id
                or (st_df3.st_mtime_ns, st_df3.st_ctime_ns, len(re_bytes)) != expected_disp_meta
                or (st_dp3.st_mtime_ns, st_dp3.st_ctime_ns, st_dp3.st_size) != expected_disp_meta
            ):
                raise RuntimeError("CONFLICT_MODIFIED")
            _verify_tmp_and_target_before_posix_replace(
                dfd,
                rec_tmp,
                rec_id,
                disp_sha,
                target_name,
                existed=True,
                orig_id=expected_tmp_id,
                expected_orig_sha=pre_exchange_tmp_sha,
            )
            if role and os.environ.get("TWX_SIMULATE_TARGET_SWAP_DURING_DISP_RECHECK") == role:
                sim_ext_obj = create_demo_data("save")
                sim_ext_obj["m_iMoney"] = 951753
                sim_ext_obj["m_strPlayerName"] = "LATEST_EXT_TARGET\r"
                sim_ext_tmp, _ = _stage_temp_in_parent(
                    dfd, target_name, serialize_json_lossless(sim_ext_obj).encode("utf-8")
                )
                os.replace(sim_ext_tmp, target_name, src_dir_fd=dfd, dst_dir_fd=dfd)
            if _posix_try_rename_exchange(dfd, rec_tmp, target_name) != "EXCHANGED":
                raise RuntimeError("CONFLICT_MODIFIED")
            exchanged_was_own_tmp = False
            try:
                _verify_posix_leaf_unchanged_in_parent(
                    dfd, rec_tmp, pre_exchange_tmp_sha, expected_id=expected_tmp_id
                )
                exchanged_was_own_tmp = True
            except Exception:
                exchanged_was_own_tmp = False
            if exchanged_was_own_tmp:
                _unlink_posix_tmp_if_id_matches(dfd, rec_tmp, expected_tmp_id)
                rec_tmp = None
                _fsync_dir_fd(dfd)
                _verify_posix_leaf_unchanged_in_parent(dfd, target_name, disp_sha, expected_id=rec_id)
                restored_via_replace = True
            else:
                ext_saved = rec_tmp
                rec_tmp = None
                try:
                    _verify_posix_leaf_unchanged_in_parent(
                        dfd, target_name, disp_sha, expected_id=rec_id
                    )
                except Exception:
                    pass
                else:
                    if _posix_try_rename_exchange(dfd, ext_saved, target_name) == "EXCHANGED":
                        try:
                            _verify_posix_leaf_unchanged_in_parent(
                                dfd, ext_saved, disp_sha, expected_id=rec_id
                            )
                        except Exception:
                            pass
                        else:
                            _unlink_posix_tmp_if_id_matches(dfd, ext_saved, rec_id)
                try:
                    _fsync_dir_fd(dfd)
                except OSError:
                    pass
                raise RuntimeError("CONFLICT_MODIFIED")
        except Exception:
            if rec_tmp is not None and rec_id is not None:
                _unlink_posix_tmp_if_id_matches(dfd, rec_tmp, rec_id)
            restored_via_replace = False
        finally:
            if fd_disp is not None:
                try:
                    os.close(fd_disp)
                except OSError:
                    pass
        if restored_via_replace:
            on_state(False, None, True)
        else:
            on_state(
                bool(
                    _target_is_unmodified_own_tmp()
                    and pre_exchange_tmp_sha == expected_tmp_sha.lower()
                ),
                None,
                True,
            )
        _fsync_dir_fd(dfd)
        raise RuntimeError("CONFLICT_MODIFIED")

    if not displaced_ok or not installed_ok:
        _rollback_on_conflict()

    _simulate_displaced_inplace_write("TWX_SIMULATE_PRE_UNLINK_DISPLACED_WRITE")

    try:
        st_pre_u = os.lstat(tmp_name, dir_fd=dfd)
    except FileNotFoundError:
        st_pre_u = None
    if st_pre_u is not None:
        if displaced_id is None:
            displaced_ok = False
            _rollback_on_conflict()
        try:
            _verify_posix_leaf_unchanged_in_parent(
                dfd, tmp_name, expected_orig_sha, expected_id=displaced_id
            )
        except FileNotFoundError:
            st_pre_u = None
        except Exception:
            displaced_ok = False
            _rollback_on_conflict()

    try:
        if role and os.environ.get("TWX_SIMULATE_POST_EXCHANGE_UNLINK_FAIL") == role:
            raise OSError(errno.EIO, "SIMULATED_POST_EXCHANGE_UNLINK_FAIL")
        if st_pre_u is not None:
            try:
                os.unlink(tmp_name, dir_fd=dfd)
            except FileNotFoundError:
                pass
    except BaseException:
        swapped_back = False
        try:
            swapped_back = _try_verified_swapback()
        except Exception:
            swapped_back = False
        if swapped_back:
            unlinked_own = _unlink_only_if_unmodified_own_tmp()
            keep_bak_after_sync = (not unlinked_own) or (not displaced_ok)
            try:
                if role and os.environ.get("TWX_SIMULATE_POST_SWAPBACK_SYNC_FAIL") == role:
                    raise OSError(errno.EIO, "SIMULATED_POST_SWAPBACK_SYNC_FAIL")
                _fsync_dir_fd(dfd)
            except BaseException:
                on_state(False, None, True)
                raise
            on_state(False, None, keep_bak_after_sync)
        else:
            on_state(
                bool(
                    _target_is_unmodified_own_tmp()
                    and pre_exchange_tmp_sha == expected_tmp_sha.lower()
                ),
                None,
                True,
            )
        raise


def read_safe_bytes(
    root: Path,
    rel_path: str,
    expected_root_id: tuple[Any, ...] | None = None,
) -> bytes:
    with _open_pinned_parent(
        root,
        rel_path,
        create_dirs=False,
        expected_root_id=expected_root_id,
    ) as (target, leaf_name, dfd):
        return _read_verified_in_parent(dfd, target, leaf_name)


def read_safe_bytes_with_id(
    root: Path,
    rel_path: str,
    expected_root_id: tuple[Any, ...] | None = None,
) -> tuple[bytes, tuple[Any, ...] | None]:
    with _open_pinned_parent(
        root,
        rel_path,
        create_dirs=False,
        expected_root_id=expected_root_id,
    ) as (target, leaf_name, dfd):
        return _read_verified_with_id_in_parent(dfd, target, leaf_name)


def _fsync_dir_fd(dfd: int | None) -> None:
    if dfd is not None:
        try:
            os.fsync(dfd)
        except OSError as exc:
            if getattr(exc, "errno", None) not in (errno.EINVAL, errno.EBADF):
                raise


def _stage_and_replace_in_parent(dfd: int | None, target_path: Path, leaf_name: str, payload: bytes) -> None:
    tmp_name = f".{leaf_name}.{secrets.token_hex(6)}.tmp"
    tmp_path = target_path.parent / tmp_name
    if dfd is None and os.name == "nt":
        import msvcrt

        parent_real = _current_pinned_win_parent(target_path.parent)
        if os.path.lexists(target_path):
            try:
                eh = _win32_create_file(str(target_path), 0, 0x07, 3, 0x00200000)
            except FileNotFoundError:
                pass
            else:
                try:
                    _win32_verify_open_handle(eh, parent_real, max_bytes=None, expected_leaf=leaf_name)
                finally:
                    _CloseHandle(wintypes.HANDLE(eh))

        h: int | None = None
        try:
            h = _win32_create_file(str(tmp_path), 0x40000000, 0, 1, 0x80 | 0x00200000)
            _win32_verify_open_handle(h, parent_real, max_bytes=None)
            fd = msvcrt.open_osfhandle(h, os.O_WRONLY)
            h = None
            with os.fdopen(fd, "wb") as fp:
                fp.write(payload)
                fp.flush()
                os.fsync(fp.fileno())
            if not _MoveFileExW(str(tmp_path), str(target_path), 0x01 | 0x08):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            if h is not None:
                _CloseHandle(wintypes.HANDLE(h))
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return

    fd = os.open(
        tmp_name if dfd is not None else str(tmp_path),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=dfd,
    )
    try:
        with os.fdopen(fd, "wb") as fp:
            fp.write(payload)
            fp.flush()
            os.fsync(fp.fileno())
        if dfd is not None:
            os.replace(tmp_name, leaf_name, src_dir_fd=dfd, dst_dir_fd=dfd)
        else:
            os.replace(str(tmp_path), str(target_path))
    except BaseException:
        try:
            if dfd is not None:
                os.unlink(tmp_name, dir_fd=dfd)
            else:
                os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _atomic_write_in_parent(dfd: int | None, target_path: Path, leaf_name: str, payload: bytes) -> None:
    _stage_and_replace_in_parent(dfd, target_path, leaf_name, payload)
    _fsync_dir_fd(dfd)


def _write_new_exclusive_in_parent(dfd: int | None, target_path: Path, leaf_name: str, payload: bytes) -> None:
    expected_sha = hashlib.sha256(payload).hexdigest().lower()
    if dfd is None and os.name == "nt":
        if os.path.lexists(target_path):
            raise FileExistsError(str(target_path))
        parent_real = _current_pinned_win_parent(target_path.parent)
        tmp_path, written_win_id = _stage_win_temp_bytes_with_id(
            parent_real, target_path.parent, target_path.name, payload
        )
        renamed = False
        try:
            if os.environ.get("TWX_SIMULATE_DEMO_TMP_SWAP") == "1":
                os.unlink(tmp_path)
                tmp_path.write_bytes(b'{"foreign_demo_tmp":1}')
            if os.environ.get("TWX_SIMULATE_DEMO_WRITE_FAIL") == "1":
                raise OSError(errno.EIO, "SIMULATED_DEMO_WRITE_FAIL")
            vh = _win32_open_verified_exclusive_temp_for_rename(
                tmp_path, parent_real, written_win_id, expected_sha
            )
            try:
                _win32_rename_by_handle(vh, target_path, False)
                renamed = True
            except BaseException:
                if os.path.lexists(target_path):
                    raise FileExistsError(str(target_path))
                raise
            finally:
                _CloseHandle(wintypes.HANDLE(vh))
            post_win_b, post_win_id = _read_verified_with_id_in_parent(
                None, target_path, target_path.name
            )
            if (
                post_win_id != written_win_id
                or hashlib.sha256(post_win_b).hexdigest().lower() != expected_sha
            ):
                raise RuntimeError("CONFLICT_MODIFIED")
        except BaseException:
            if not renamed:
                _unlink_win_tmp_if_id_matches(tmp_path, parent_real, written_win_id)
            raise
        return

    if dfd is not None:
        try:
            os.lstat(leaf_name, dir_fd=dfd)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(str(target_path))
        tmp_name: str | None = None
        tmp_id: tuple[int, int] | None = None
        fd_new: int | None = None
        linked = False
        try:
            tmp_name, tmp_id = _stage_temp_in_parent(dfd, leaf_name, payload)
            flags = (
                os.O_RDONLY
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0)
            )
            fd_new = os.open(tmp_name, flags, dir_fd=dfd)
            st0 = os.fstat(fd_new)
            if (
                not stat.S_ISREG(st0.st_mode)
                or getattr(st0, "st_nlink", 0) != 1
                or st0.st_size > MAX_SAVE_BYTES
                or (int(st0.st_dev), int(st0.st_ino)) != tmp_id
            ):
                raise RuntimeError("CONFLICT_MODIFIED")
            if getattr(os, "O_NONBLOCK", 0) and hasattr(os, "set_blocking"):
                try:
                    os.set_blocking(fd_new, True)
                except OSError:
                    pass
            chunks: list[bytes] = []
            seen = 0
            while True:
                b = os.read(fd_new, 65536)
                if not b:
                    break
                seen += len(b)
                if seen > MAX_SAVE_BYTES:
                    raise RuntimeError("CONFLICT_MODIFIED")
                chunks.append(b)
            if hashlib.sha256(b"".join(chunks)).hexdigest().lower() != expected_sha:
                raise RuntimeError("CONFLICT_MODIFIED")
            st1 = os.fstat(fd_new)
            if (
                getattr(st1, "st_nlink", 0) != 1
                or (int(st1.st_dev), int(st1.st_ino)) != tmp_id
                or (st1.st_mtime_ns, st1.st_ctime_ns, st1.st_size)
                != (st0.st_mtime_ns, st0.st_ctime_ns, st0.st_size)
            ):
                raise RuntimeError("CONFLICT_MODIFIED")
            proc_fd = f"/proc/self/fd/{fd_new}"
            if os.environ.get("TWX_FORCE_POSIX_NO_PROC_FD") == "1" or not os.path.exists(proc_fd):
                raise RuntimeError("ATOMIC_FD_LINK_UNSUPPORTED")
            os.link(proc_fd, leaf_name, dst_dir_fd=dfd, follow_symlinks=True)
            linked = True
            if os.environ.get("TWX_SIMULATE_DEMO_TMP_UNLINK_FAIL") == "1":
                raise OSError(errno.EIO, "SIMULATED_DEMO_TMP_UNLINK_FAIL")
            if not _unlink_posix_tmp_if_id_matches(dfd, tmp_name, tmp_id):
                raise OSError(errno.EIO, "DEMO_TMP_UNLINK_FAILED")
            tmp_name = None
            if os.environ.get("TWX_SIMULATE_DEMO_FOREIGN_REPLACE") == "1":
                ext_t, _ = _stage_temp_in_parent(dfd, leaf_name, b'{"foreign_at_demo":1}')
                os.replace(ext_t, leaf_name, src_dir_fd=dfd, dst_dir_fd=dfd)
            if os.environ.get("TWX_SIMULATE_DEMO_WRITE_FAIL") == "1":
                raise OSError(errno.EIO, "SIMULATED_DEMO_WRITE_FAIL")
            _fsync_dir_fd(dfd)
            os.close(fd_new)
            fd_new = None
            post_posix_b, post_posix_id = _read_verified_with_id_in_parent(
                dfd, target_path, leaf_name
            )
            if (
                post_posix_id != tmp_id
                or hashlib.sha256(post_posix_b).hexdigest().lower() != expected_sha
            ):
                raise RuntimeError("CONFLICT_MODIFIED")
        except BaseException:
            if tmp_name is not None:
                _unlink_posix_tmp_if_id_matches(dfd, tmp_name, tmp_id)
            if linked and fd_new is not None and tmp_id is not None:
                try:
                    stf1 = os.fstat(fd_new)
                    os.lseek(fd_new, 0, os.SEEK_SET)
                    re_chunks: list[bytes] = []
                    re_seen = 0
                    while True:
                        rb = os.read(fd_new, 65536)
                        if not rb:
                            break
                        re_seen += len(rb)
                        if re_seen > MAX_SAVE_BYTES:
                            break
                        re_chunks.append(rb)
                    re_b = b"".join(re_chunks)
                    stf2 = os.fstat(fd_new)
                    stp = os.lstat(leaf_name, dir_fd=dfd)
                    if (
                        re_seen <= MAX_SAVE_BYTES
                        and not stat.S_ISLNK(stp.st_mode)
                        and stat.S_ISREG(stp.st_mode)
                        and (int(stp.st_dev), int(stp.st_ino)) == tmp_id
                        and getattr(stp, "st_nlink", 0) in (1, 2)
                        and (int(stf1.st_dev), int(stf1.st_ino)) == tmp_id
                        and (stf2.st_mtime_ns, stf2.st_ctime_ns, len(re_b))
                        == (stf1.st_mtime_ns, stf1.st_ctime_ns, stf1.st_size)
                        and (stp.st_mtime_ns, stp.st_ctime_ns, stp.st_size)
                        == (stf1.st_mtime_ns, stf1.st_ctime_ns, stf1.st_size)
                        and hashlib.sha256(re_b).hexdigest().lower() == expected_sha
                    ):
                        os.unlink(leaf_name, dir_fd=dfd)
                        try:
                            _fsync_dir_fd(dfd)
                        except OSError:
                            pass
                except OSError:
                    pass
            raise
        finally:
            if fd_new is not None:
                try:
                    os.close(fd_new)
                except OSError:
                    pass
        return

    fd_fb: int | None = None
    created_id: tuple[int, int] | None = None
    try:
        fd_fb = os.open(
            str(target_path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        st_fb = os.fstat(fd_fb)
        created_id = (int(st_fb.st_dev), int(st_fb.st_ino))
        fb_view = memoryview(payload)
        while fb_view:
            fb_view = fb_view[os.write(fd_fb, fb_view):]
        os.fsync(fd_fb)
        os.close(fd_fb)
        fd_fb = None
    except BaseException:
        if fd_fb is not None:
            try:
                os.close(fd_fb)
            except OSError:
                pass
        if created_id is not None:
            try:
                st_cur = os.lstat(str(target_path))
                if (
                    not stat.S_ISLNK(st_cur.st_mode)
                    and stat.S_ISREG(st_cur.st_mode)
                    and getattr(st_cur, "st_nlink", 0) == 1
                    and (int(st_cur.st_dev), int(st_cur.st_ino)) == created_id
                ):
                    os.unlink(str(target_path))
            except OSError:
                pass
        raise


def _atomic_write_bytes(target: Path, payload: bytes) -> None:
    parent = target.parent if str(target.parent) else Path(".")
    with _open_pinned_parent(parent, target.name, create_dirs=True) as (cand, leaf, dfd):
        _atomic_write_in_parent(dfd, cand, leaf, payload)


def _write_new_exclusive_bytes(target: Path, payload: bytes) -> None:
    parent = target.parent if str(target.parent) else Path(".")
    with _open_pinned_parent(parent, target.name, create_dirs=True) as (cand, leaf, dfd):
        _write_new_exclusive_in_parent(dfd, cand, leaf, payload)


def _write_backup_in_pinned_dir(
    bdfd: int | None,
    backups_dir: Path,
    rel_slot: str,
    orig_bytes: bytes,
) -> tuple[str, tuple[Any, ...] | None, str]:
    sha_full = hashlib.sha256(orig_bytes).hexdigest()
    sha8 = sha_full[:8]
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    prefix = _slot_backup_prefix(rel_slot)

    for attempt in range(33):
        bak_name = (
            f"{prefix}_{ts}_{sha8}.bak"
            if attempt == 0
            else f"{prefix}_{ts}_{secrets.token_hex(2)}_{sha8}.bak"
        )
        leaf = bak_name
        cand = backups_dir / leaf

        if bdfd is not None:
            try:
                os.lstat(leaf, dir_fd=bdfd)
                continue
            except FileNotFoundError:
                pass

            tmp_name, tmp_id = _stage_temp_in_parent(bdfd, leaf, orig_bytes)
            if attempt == 0 and os.environ.get("TWX_SIMULATE_BACKUP_NAME_RACE") == "1":
                try:
                    rfd = os.open(
                        leaf,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                        0o600,
                        dir_fd=bdfd,
                    )
                    try:
                        os.write(rfd, b'{"preexisting_backup":1}')
                    finally:
                        os.close(rfd)
                except FileExistsError:
                    pass

            b_fd: int | None = None
            linked = False
            try:
                b_fd = os.open(
                    tmp_name,
                    os.O_RDONLY
                    | getattr(os, "O_NONBLOCK", 0)
                    | getattr(os, "O_BINARY", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=bdfd,
                )
                if getattr(os, "O_NONBLOCK", 0) and hasattr(os, "set_blocking"):
                    try:
                        os.set_blocking(b_fd, True)
                    except OSError:
                        pass
                st_b1 = os.fstat(b_fd)
                if (
                    not stat.S_ISREG(st_b1.st_mode)
                    or getattr(st_b1, "st_nlink", 0) != 1
                    or int(st_b1.st_size) > MAX_SAVE_BYTES
                    or (int(st_b1.st_dev), int(st_b1.st_ino)) != tmp_id
                ):
                    raise RuntimeError("CONFLICT_MODIFIED")
                b_chunks: list[bytes] = []
                b_seen = 0
                while True:
                    b_piece = os.read(b_fd, 65536)
                    if not b_piece:
                        break
                    b_seen += len(b_piece)
                    if b_seen > MAX_SAVE_BYTES:
                        raise RuntimeError("CONFLICT_MODIFIED")
                    b_chunks.append(b_piece)
                if hashlib.sha256(b"".join(b_chunks)).hexdigest() != sha_full:
                    raise RuntimeError("CONFLICT_MODIFIED")
                st_b2 = os.fstat(b_fd)
                if (
                    getattr(st_b2, "st_nlink", 0) != 1
                    or (int(st_b2.st_dev), int(st_b2.st_ino)) != tmp_id
                    or (st_b2.st_mtime_ns, st_b2.st_ctime_ns, st_b2.st_size)
                    != (st_b1.st_mtime_ns, st_b1.st_ctime_ns, st_b1.st_size)
                ):
                    raise RuntimeError("CONFLICT_MODIFIED")
                proc_b = f"/proc/self/fd/{b_fd}"
                if (
                    os.environ.get("TWX_FORCE_POSIX_NO_PROC_FD") == "1"
                    or not os.path.exists(proc_b)
                ):
                    raise RuntimeError("ATOMIC_FD_LINK_UNSUPPORTED")
                try:
                    os.link(proc_b, leaf, dst_dir_fd=bdfd, follow_symlinks=True)
                except FileExistsError:
                    _unlink_posix_tmp_if_id_matches(bdfd, tmp_name, tmp_id)
                    continue
                linked = True
                st_bleaf = os.lstat(leaf, dir_fd=bdfd)
                if (
                    stat.S_ISLNK(st_bleaf.st_mode)
                    or not stat.S_ISREG(st_bleaf.st_mode)
                    or (int(st_bleaf.st_dev), int(st_bleaf.st_ino)) != tmp_id
                    or getattr(os.fstat(b_fd), "st_nlink", 0) != 2
                ):
                    raise RuntimeError("CONFLICT_MODIFIED")
                _unlink_posix_tmp_if_id_matches(bdfd, tmp_name, tmp_id)
                if getattr(os.fstat(b_fd), "st_nlink", 0) != 1:
                    raise RuntimeError("CONFLICT_MODIFIED")
            except BaseException:
                _unlink_posix_tmp_if_id_matches(bdfd, tmp_name, tmp_id)
                if linked:
                    _unlink_posix_tmp_if_id_matches(bdfd, leaf, tmp_id)
                raise
            finally:
                if b_fd is not None:
                    try:
                        os.close(b_fd)
                    except OSError:
                        pass

            _fsync_dir_fd(bdfd)
            rb_bytes, bak_file_id = _read_verified_with_id_in_parent(bdfd, cand, leaf)
            if bak_file_id != tmp_id or hashlib.sha256(rb_bytes).hexdigest() != sha_full:
                raise RuntimeError("백업 파일 SHA-256 무결성 검증에 실패했습니다.")
            return bak_name, bak_file_id, sha_full

        if os.name == "nt":
            if os.path.lexists(cand):
                continue
            b_parent_real = _current_pinned_win_parent(backups_dir)
            if attempt == 0 and os.environ.get("TWX_SIMULATE_BACKUP_NAME_RACE") == "1":
                if not os.path.lexists(cand):
                    cand.write_bytes(b'{"preexisting_backup":1}')
            try:
                win_bak_id = _commit_win_temp_replace(cand, b_parent_real, orig_bytes, [None], False)
            except RuntimeError as exc:
                if str(exc) == "CONFLICT_MODIFIED":
                    continue
                raise
            rb_bytes, bak_file_id = _read_verified_with_id_in_parent(None, cand, leaf)
            if bak_file_id != win_bak_id or hashlib.sha256(rb_bytes).hexdigest() != sha_full:
                raise RuntimeError("백업 파일 SHA-256 무결성 검증에 실패했습니다.")
            return bak_name, bak_file_id, sha_full

        if os.path.lexists(cand):
            continue
        try:
            _write_new_exclusive_in_parent(None, cand, leaf, orig_bytes)
        except FileExistsError:
            continue
        rb_bytes, bak_file_id = _read_verified_with_id_in_parent(None, cand, leaf)
        if hashlib.sha256(rb_bytes).hexdigest() != sha_full:
            raise RuntimeError("백업 파일 SHA-256 무결성 검증에 실패했습니다.")
        return bak_name, bak_file_id, sha_full

    raise RuntimeError("백업 파일 이름 충돌을 해소하지 못했습니다.")


def _write_backup_verified(
    root: Path,
    rel_slot: str,
    orig_bytes: bytes,
    expected_root_id: tuple[Any, ...] | None = None,
) -> str:
    with _open_pinned_parent(
        root,
        "backups/_probe",
        create_dirs=True,
        expected_root_id=expected_root_id,
    ) as (bcand_probe, _bleaf, bdfd):
        bak_name, _bak_id, _bak_sha = _write_backup_in_pinned_dir(
            bdfd, bcand_probe.parent, rel_slot, orig_bytes
        )
        return bak_name


def _companion_title_spec(slot_name: str) -> tuple[str, int] | None:
    base = Path(slot_name).name
    for pat, title_file in (
        (r"^Save(0|[1-9]|1[0-9])\.Save$", "SaveTitle.SaveTitle"),
        (r"^AutomaticSave(0|[1-9]|1[0-9])\.Save$", "SaveAutomaticTitle.SaveTitle"),
        (r"^AutomaticDSave(0|[1-9]|1[0-9])\.Save$", "SaveAutomaticDTitle.SaveTitle"),
    ):
        m = re.match(pat, base, re.IGNORECASE)
        if m:
            return title_file, int(m.group(1))
    return None


def _update_title_slot_lossless(raw_title_text: str, slot_idx: int, updates: list[tuple[str, Any]]) -> str:
    had_bom = raw_title_text.startswith("\ufeff")
    text = raw_title_text[1:] if had_bom else raw_title_text
    if text.startswith("\ufeff"): raise ValueError("이중 UTF-8 BOM은 허용되지 않습니다.")
    ws_chars = " \t\r\n"

    def skip_ws(s: str, pos: int) -> int:
        while pos < len(s) and s[pos] in ws_chars:
            pos += 1
        return pos

    def scan_string(s: str, start: int) -> tuple[str, int]:
        if start >= len(s) or s[start] != '"':
            raise ValueError("JSON 문자열 시작 위치가 올바르지 않습니다.")
        i = start + 1
        escaped = False
        while i < len(s):
            ch = s[i]
            if escaped:
                escaped = False
                i += 1
                continue
            if ch == "\\":
                escaped = True
                i += 1
                continue
            if ch == '"':
                end = i + 1
                return json.loads(s[start:end]), end
            i += 1
        raise ValueError("JSON 문자열이 종료되지 않았습니다.")

    def scan_value(s: str, start: int) -> tuple[int, int]:
        if start >= len(s):
            raise ValueError("JSON 값 위치가 올바르지 않습니다.")
        ch = s[start]
        if ch == '"':
            _, end = scan_string(s, start)
            return start, end
        if ch in "[{":
            stack = [ch]
            i = start + 1
            while i < len(s):
                c = s[i]
                if c == '"':
                    _, i = scan_string(s, i)
                    continue
                if c in "[{":
                    stack.append(c)
                elif c in "]}":
                    if not stack:
                        raise ValueError("JSON 괄호 구조가 올바르지 않습니다.")
                    stack.pop()
                    if not stack:
                        return start, i + 1
                i += 1
            raise ValueError("JSON 값이 종료되지 않았습니다.")
        i = start
        while i < len(s) and s[i] not in ",}] \t\r\n":
            i += 1
        if i == start:
            raise ValueError("JSON 기본 값이 올바르지 않습니다.")
        return start, i

    arr_pos = skip_ws(text, 0)
    if arr_pos >= len(text) or text[arr_pos] != "[":
        raise ValueError("타이틀 JSON 최상위 배열을 찾을 수 없습니다.")
    pos = skip_ws(text, arr_pos + 1)
    idx = 0
    elem_start = elem_end = -1
    while pos < len(text) and text[pos] != "]":
        val_start, val_end = scan_value(text, pos)
        if idx == slot_idx:
            if text[pos] != "{":
                raise ValueError(f"타이틀 슬롯 인덱스 {slot_idx} 항목이 객체가 아닙니다.")
            elem_start, elem_end = pos, val_end
            break
        pos = skip_ws(text, val_end)
        if pos < len(text) and text[pos] == ",":
            pos = skip_ws(text, pos + 1)
            idx += 1
            continue
        if pos < len(text) and text[pos] == "]":
            break
        raise ValueError("타이틀 JSON 배열 구조가 올바르지 않습니다.")
    if elem_start < 0 or elem_end < 0:
        raise ValueError(f"동반 타이틀 파일에 슬롯 인덱스 {slot_idx} 항목이 없습니다.")

    elem_json = text[elem_start:elem_end]
    if not elem_json.startswith("{") or not elem_json.endswith("}"):
        raise ValueError(f"타이틀 슬롯 인덱스 {slot_idx} 항목이 객체가 아닙니다.")

    member_spans: dict[str, tuple[int, int]] = {}
    has_members = False
    pos = skip_ws(elem_json, 1)
    if pos < len(elem_json) and elem_json[pos] == "}":
        has_members = False
    else:
        while pos < len(elem_json):
            if elem_json[pos] != '"':
                raise ValueError("타이틀 JSON 객체 키 구조가 올바르지 않습니다.")
            key, key_end = scan_string(elem_json, pos)
            pos = skip_ws(elem_json, key_end)
            if pos >= len(elem_json) or elem_json[pos] != ":":
                raise ValueError("타이틀 JSON 객체 키 구분자가 올바르지 않습니다.")
            pos = skip_ws(elem_json, pos + 1)
            val_start, val_end = scan_value(elem_json, pos)
            member_spans[key] = (val_start, val_end)
            has_members = True
            pos = skip_ws(elem_json, val_end)
            if pos < len(elem_json) and elem_json[pos] == "}":
                break
            if pos >= len(elem_json) or elem_json[pos] != ",":
                raise ValueError("타이틀 JSON 객체 멤버 구분자가 올바르지 않습니다.")
            pos = skip_ws(elem_json, pos + 1)

    def encode_update_value(v: Any) -> str:
        if isinstance(v, str):
            return encode_jsonfx_string(v)
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v)

    replacements: list[tuple[int, int, str]] = []
    missing: list[tuple[str, str]] = []
    for key, value in updates:
        encoded = encode_update_value(value)
        span = member_spans.get(key)
        if span is not None:
            replacements.append((span[0], span[1], encoded))
        else:
            missing.append((key, encoded))

    updated_elem = elem_json
    for start, end, encoded in sorted(replacements, key=lambda x: x[0], reverse=True):
        updated_elem = updated_elem[:start] + encoded + updated_elem[end:]

    if missing:
        close_pos = updated_elem.rfind("}")
        if close_pos < 0:
            raise ValueError("타이틀 JSON 객체 종료 위치를 찾을 수 없습니다.")
        before_close = updated_elem[:close_pos]
        after_close = updated_elem[close_pos:]
        insert_pos = len(before_close)
        while insert_pos > 0 and before_close[insert_pos - 1] in ws_chars:
            insert_pos -= 1
        trailing_ws = before_close[insert_pos:]
        parts: list[str] = []
        for key, encoded in missing:
            key_json = encode_jsonfx_string(key)
            parts.append(f"{key_json}: {encoded}")
        if has_members:
            addition = ", " + ", ".join(parts)
        else:
            addition = ", ".join(parts)
        updated_elem = before_close[:insert_pos] + addition + trailing_ws + after_close

    return ("\ufeff" if had_bom else "") + text[:elem_start] + updated_elem + text[elem_end:]


def _prepare_companion_title_in_parent(
    dfd: int | None,
    parent_dir: Path,
    root: Path,
    rel_slot: str,
    save_data: dict[str, Any],
) -> tuple[Path, str, bytes, bytes, tuple[int, int] | None] | None:
    base_name = Path(_to_rel_slot_posix_safe(rel_slot)).name
    spec = _companion_title_spec(base_name)
    if not spec:
        return None
    title_file, slot_idx = spec
    parent_rel = os.path.dirname(_to_rel_slot_posix_safe(rel_slot))
    rel_title = f"{parent_rel}/{title_file}" if parent_rel else title_file

    if dfd is not None:
        try:
            os.lseek(dfd, 0, os.SEEK_SET)
        except OSError:
            pass
        with os.scandir(dfd) as it:
            entries = [e.name for e in it]
        if any(e.lower() == title_file.lower() and e != title_file for e in entries):
            raise ValueError("대소문자만 다른 동일 이름의 슬롯이 존재하여 모호한 접근이 차단되었습니다.")
    elif parent_dir.is_dir():
        entries = os.listdir(parent_dir)
        if any(e.lower() == title_file.lower() and e != title_file for e in entries):
            raise ValueError("대소문자만 다른 동일 이름의 슬롯이 존재하여 모호한 접근이 차단되었습니다.")

    title_path = parent_dir / title_file
    try:
        orig_bytes, orig_title_id = _read_verified_with_id_in_parent(dfd, title_path, title_file)
    except FileNotFoundError:
        return None

    raw_title_text = orig_bytes.decode("utf-8")
    t_data, _ = parse_json_lossless(raw_title_text)
    if validate_data(t_data) != "title":
        raise ValueError(f"동반 타이틀 파일({rel_title})의 스키마가 손상되었습니다.")
    if not isinstance(t_data, list) or not (0 <= slot_idx < len(t_data)) or not isinstance(t_data[slot_idx], dict):
        raise ValueError(f"동반 타이틀 파일({rel_title})에 슬롯 인덱스 {slot_idx} 항목이 없습니다.")

    entry = t_data[slot_idx]
    scene = str(save_data.get("m_strSceneName") or "Develop")
    intervals = ["초", "상순", "중순", "하순", "말"]
    yr_val = _as_exact_int(save_data.get("m_iYear"))
    updates: list[tuple[str, Any]] = [
        ("m_bHaveData", True),
        ("m_strPlayerName", str(save_data.get("m_strPlayerLastName") or "") + str(save_data.get("m_strPlayerName") or "")),
        ("m_strPlaceName", scene),
        ("m_strYear", str(yr_val if yr_val is not None else 1)),
        ("m_strPlayerIconName", str(save_data.get("m_PlayerIconID") or "900005")),
    ]
    if scene == "Develop":
        updates.append(("m_strTime", ""))
        iv = _as_exact_int(save_data.get("m_iMonthInterval", 0))
        mo = _as_exact_int(save_data.get("m_iMonth", 1))
        iv_str = intervals[iv] if iv is not None and 0 <= iv < len(intervals) else "초"
        updates.append(("m_strMonth", f"{mo if mo is not None else 1}월\r{iv_str}\r"))
    if not entry.get("m_strTrueTime"):
        updates.append(("m_strTrueTime", "12\uff1a00"))
    if not entry.get("m_strTrueYear"):
        updates.append(("m_strTrueYear", "2026/11/18"))

    new_title_bytes = _update_title_slot_lossless(raw_title_text, slot_idx, updates).encode("utf-8")
    return title_path, rel_title, orig_bytes, new_title_bytes, orig_title_id


def _prepare_companion_title(
    root: Path,
    rel_slot: str,
    save_data: dict[str, Any],
    expected_root_id: tuple[Any, ...] | None = None,
) -> tuple[Path, str, bytes, bytes, tuple[int, int] | None] | None:
    rel_norm = _to_rel_slot_posix_safe(rel_slot)
    try:
        with _open_pinned_parent(
            root,
            rel_norm,
            create_dirs=False,
            expected_root_id=expected_root_id,
        ) as (cand, _leaf, dfd):
            return _prepare_companion_title_in_parent(dfd, cand.parent, root, rel_norm, save_data)
    except FileNotFoundError:
        return None


def _stage_temp_in_parent(dfd: int, leaf_name: str, payload: bytes) -> tuple[str, tuple[int, int]]:
    tmp_name = f".{leaf_name}.{secrets.token_hex(6)}.tmp"
    tfd = os.open(
        tmp_name,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
        dir_fd=dfd,
    )
    created_id: tuple[int, int] | None = None
    try:
        st_init = os.fstat(tfd)
        created_id = (int(st_init.st_dev), int(st_init.st_ino))
        with os.fdopen(tfd, "wb") as fp:
            tfd = -1
            fp.write(payload)
            fp.flush()
            os.fsync(fp.fileno())
            st_tmp = os.fstat(fp.fileno())
            tmp_id = (int(st_tmp.st_dev), int(st_tmp.st_ino))
    except BaseException:
        if tfd >= 0:
            try:
                os.close(tfd)
            except OSError:
                pass
        _unlink_posix_tmp_if_id_matches(dfd, tmp_name, created_id)
        raise
    return tmp_name, tmp_id


def _unlink_win_tmp_if_id_matches(
    tmp_path: Path,
    parent_real: Path | None,
    expected_win_id: tuple[str, int, int, int] | None,
) -> bool:
    if os.name != "nt" or expected_win_id is None or parent_real is None:
        return False
    th_del: int | None = None
    try:
        th_del = _win32_create_file(
            str(tmp_path),
            0x80000000 | 0x00010000,
            0,
            3,
            0x00200000,
        )
        _win32_verify_open_handle(
            th_del, parent_real, max_bytes=None, expected_leaf=tmp_path.name
        )
        if _win32_get_handle_file_id(th_del) != expected_win_id:
            return False
        disp = FILE_DISPOSITION_INFO(1)
        if not _SetFileInformationByHandle(
            wintypes.HANDLE(th_del),
            4,
            ctypes.byref(disp),
            wintypes.DWORD(ctypes.sizeof(disp)),
        ):
            return False
        _CloseHandle(wintypes.HANDLE(th_del))
        th_del = None
        return True
    except Exception:
        return False
    finally:
        if th_del is not None:
            try:
                _CloseHandle(wintypes.HANDLE(th_del))
            except Exception:
                pass


def _stage_win_temp_bytes_with_id(
    parent_real: Path,
    target_dir: Path,
    leaf_name: str,
    payload: bytes,
) -> tuple[Path, tuple[str, int, int, int]]:
    import msvcrt

    tmp_path = target_dir / f".{leaf_name}.{secrets.token_hex(6)}.tmp"
    th: int | None = None
    created_win_id: tuple[str, int, int, int] | None = None
    written_win_id: tuple[str, int, int, int]
    try:
        th = _win32_create_file(str(tmp_path), 0x40000000, 0, 1, 0x80 | 0x00200000)
        created_win_id = _win32_get_handle_file_id(th)
        _win32_verify_open_handle(th, parent_real, max_bytes=None)
        tfd = msvcrt.open_osfhandle(th, os.O_WRONLY)
        th = None
        with os.fdopen(tfd, "wb") as fp:
            fp.write(payload)
            fp.flush()
            os.fsync(fp.fileno())
            written_win_id = _win32_get_handle_file_id(msvcrt.get_osfhandle(fp.fileno()))
    except BaseException:
        if th is not None:
            try:
                _CloseHandle(wintypes.HANDLE(th))
            except Exception:
                pass
        _unlink_win_tmp_if_id_matches(tmp_path, parent_real, created_win_id)
        raise
    return tmp_path, written_win_id


def _stage_win_temp_bytes(
    parent_real: Path,
    target_dir: Path,
    leaf_name: str,
    payload: bytes,
) -> Path:
    tmp_path, _ = _stage_win_temp_bytes_with_id(parent_real, target_dir, leaf_name, payload)
    return tmp_path


def _rollback_replaced_in_parent(
    dfd: int | None,
    cand: Path,
    leaf: str,
    existed: bool,
    prev_slot_bytes: bytes,
    written_slot_bytes: bytes,
    written_slot_id: tuple[int, int] | None,
    slot_replaced: bool,
    title_plan: tuple[Path, str, bytes, bytes, tuple[int, int] | None] | None,
    written_title_id: tuple[int, int] | None,
    title_replaced: bool,
    written_win_slot_id: tuple[str, int, int, int] | None = None,
    written_win_title_id: tuple[str, int, int, int] | None = None,
) -> bool:
    def _simulate_rb_ext_slot_write(expected_sha: str) -> None:
        ext_state = create_demo_data("save")
        ext_state["m_iMoney"] = 919191
        ext_bytes = serialize_json_lossless(ext_state).encode("utf-8")
        if hashlib.sha256(ext_bytes).hexdigest().lower() == expected_sha.lower():
            ext_state["m_iMoney"] = 919192
            ext_bytes = serialize_json_lossless(ext_state).encode("utf-8")
        _stage_and_replace_in_parent(dfd, cand, leaf, ext_bytes)

    def _simulate_rb_ext_title_write(t_path: Path, prev_t_bytes: bytes, expected_sha: str) -> None:
        ext_t_data, ext_t_meta = parse_json_lossless(prev_t_bytes.decode("utf-8"))
        if prev_t_bytes.startswith(b"\xef\xbb\xbf"):
            ext_t_meta["has_bom"] = True
        if isinstance(ext_t_data, list) and ext_t_data and isinstance(ext_t_data[0], dict):
            ext_t_data[0]["m_strPlayerName"] = "EXT_RB_STAGE_TITLE"
        ext_t_bytes = serialize_json_lossless(ext_t_data, ext_t_meta).encode("utf-8")
        if hashlib.sha256(ext_t_bytes).hexdigest().lower() == expected_sha.lower():
            if isinstance(ext_t_data, list) and ext_t_data and isinstance(ext_t_data[0], dict):
                ext_t_data[0]["m_strPlayerName"] = "EXT_RB_STAGE_TITLE_2"
            ext_t_bytes = serialize_json_lossless(ext_t_data, ext_t_meta).encode("utf-8")
        _stage_and_replace_in_parent(dfd, t_path, t_path.name, ext_t_bytes)

    def _simulate_win_rb_same_bytes_replace(parent_real: Path, target_p: Path, same_bytes: bytes) -> None:
        ext_tmp, ext_tmp_id = _stage_win_temp_bytes_with_id(parent_real, target_p.parent, target_p.name, same_bytes)
        try:
            if not _MoveFileExW(str(ext_tmp), str(target_p), 0x01 | 0x08):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            _unlink_win_tmp_if_id_matches(ext_tmp, parent_real, ext_tmp_id)
            raise

    rb_stage_hook = os.environ.get("TWX_SIMULATE_EXT_WRITE_DURING_RB_STAGE", "")
    rb_same_bytes_hook = os.environ.get("TWX_SIMULATE_EXT_SAME_BYTES_DURING_RB_STAGE", "")
    title_rb_ok = not title_replaced
    slot_rb_ok = not slot_replaced

    def _verify_win_rb_file(
        p_real: Path,
        fpath: Path,
        expected_leaf: str,
        exp_id: tuple[str, int, int, int] | None,
        exp_sha: str,
    ) -> None:
        vh: int | None = None
        try:
            vh = _win32_create_file(str(fpath), 0x80000000, 0x01, 3, 0x00200000)
            _win32_verify_open_handle(
                vh, p_real, MAX_SAVE_BYTES, expected_leaf=expected_leaf
            )
            if exp_id is not None and _win32_get_handle_file_id(vh) != exp_id:
                raise RuntimeError("CONFLICT_MODIFIED")
            raw_b = _win32_read_handle_bytes(vh, MAX_SAVE_BYTES)
            if hashlib.sha256(raw_b).hexdigest().lower() != exp_sha.lower():
                raise RuntimeError("CONFLICT_MODIFIED")
        finally:
            if vh is not None:
                try:
                    _CloseHandle(wintypes.HANDLE(vh))
                except Exception:
                    pass

    if title_replaced and title_plan is not None:
        t_path = title_plan[0]
        t_leaf = t_path.name
        prev_title_bytes = title_plan[2]
        written_title_sha = hashlib.sha256(title_plan[3]).hexdigest().lower()
        role = "title"
        target_p = t_path
        target_leaf = t_leaf
        prev_bytes = prev_title_bytes
        written_sha = written_title_sha
        if dfd is None and os.name == "nt":
            rb_tmp_win: Path | None = None
            rb_win_id: tuple[str, int, int, int] | None = None
            parent_real_rb: Path | None = None
            rb_vh: int | None = None
            th_pin: int | None = None
            try:
                parent_real = _current_pinned_win_parent(t_path.parent)
                parent_real_rb = parent_real
                prev_sha = hashlib.sha256(prev_bytes).hexdigest().lower()
                rb_tmp_win, rb_win_id = _stage_win_temp_bytes_with_id(
                    parent_real, target_p.parent, target_leaf, prev_bytes
                )
                if os.environ.get("TWX_SIMULATE_RB_TEMP_TAMPER", "") == role:
                    rb_tmp_win.write_bytes(b'{"rb_tampered":1}')
                rb_vh = _win32_open_verified_exclusive_temp_for_rename(
                    rb_tmp_win, parent_real, rb_win_id, prev_sha
                )
                if rb_stage_hook == "title":
                    _simulate_rb_ext_title_write(t_path, prev_title_bytes, written_title_sha)
                if rb_same_bytes_hook == "title":
                    _simulate_win_rb_same_bytes_replace(parent_real, t_path, title_plan[3])
                th_pin = _win32_create_file(str(target_p), 0x80000000, 0x01, 3, 0x00200000)
                _win32_verify_open_handle(
                    th_pin, parent_real, MAX_SAVE_BYTES, expected_leaf=target_leaf
                )
                title_id_ok = (
                    written_win_title_id is None
                    or _win32_get_handle_file_id(th_pin) == written_win_title_id
                )
                cur_t = _win32_read_handle_bytes(th_pin, MAX_SAVE_BYTES)
                if os.environ.get("TWX_VERIFY_EXCLUSIVE_TEMP_RENAME") == "1":
                    _win32_assert_temp_exclusively_pinned(rb_tmp_win)
                if title_id_ok and hashlib.sha256(cur_t).hexdigest().lower() == written_sha:
                    h_tpin = th_pin
                    th_pin = None
                    _CloseHandle(wintypes.HANDLE(h_tpin))
                    _win32_rename_by_handle(rb_vh, target_p, True)
                    rb_tmp_win = None
                    _CloseHandle(wintypes.HANDLE(rb_vh))
                    rb_vh = None
                    if os.environ.get("TWX_SIMULATE_POST_RB_TAMPER", "") == role:
                        target_p.write_bytes(b'{"post_rb_tampered":1}')
                    _verify_win_rb_file(
                        parent_real, target_p, target_leaf, rb_win_id, prev_sha
                    )
                    title_rb_ok = True
            except Exception as exc:
                if str(exc) == "EXCLUSIVE_TEMP_PIN_NOT_ENFORCED":
                    raise
                title_rb_ok = False
            finally:
                if th_pin is not None:
                    try:
                        _CloseHandle(wintypes.HANDLE(th_pin))
                    except Exception:
                        pass
                if rb_vh is not None:
                    try:
                        _CloseHandle(wintypes.HANDLE(rb_vh))
                    except Exception:
                        pass
                if rb_tmp_win is not None:
                    _unlink_win_tmp_if_id_matches(rb_tmp_win, parent_real_rb, rb_win_id)
        elif dfd is not None:
            rb_tmp_name: str | None = None
            rb_posix_id: tuple[int, int] | None = None
            try:
                prev_sha = hashlib.sha256(prev_bytes).hexdigest().lower()
                rb_tmp_name, rb_posix_id = _stage_temp_in_parent(dfd, target_leaf, prev_bytes)
                if os.environ.get("TWX_SIMULATE_RB_TEMP_TAMPER", "") == role:
                    tfd: int | None = None
                    try:
                        tfd = os.open(rb_tmp_name, os.O_WRONLY | os.O_TRUNC, dir_fd=dfd)
                        os.write(tfd, b'{"rb_tampered":1}')
                    finally:
                        if tfd is not None:
                            os.close(tfd)
                def _rb_title_post_tmp_hook() -> None:
                    if rb_stage_hook == "title":
                        _simulate_rb_ext_title_write(t_path, prev_title_bytes, written_title_sha)

                def _on_rb_title_state(_rep: bool, exp_tmp: str | None, _keep_bak: bool) -> None:
                    nonlocal rb_tmp_name
                    rb_tmp_name = exp_tmp

                _verify_tmp_and_target_before_posix_replace(
                    dfd,
                    rb_tmp_name,
                    rb_posix_id,
                    prev_sha,
                    target_leaf,
                    existed=True,
                    orig_id=written_title_id,
                    expected_orig_sha=written_sha,
                    post_tmp_verify_hook=_rb_title_post_tmp_hook,
                )
                _posix_exchange_or_replace_verified(
                    dfd,
                    rb_tmp_name,
                    rb_posix_id,
                    prev_sha,
                    target_leaf,
                    written_title_id,
                    written_sha,
                    on_state=_on_rb_title_state,
                    role="rb_title",
                )
                rb_tmp_name = None
                _fsync_dir_fd(dfd)
                if os.environ.get("TWX_SIMULATE_POST_RB_TAMPER", "") == role:
                    pfd: int | None = None
                    try:
                        pfd = os.open(target_leaf, os.O_WRONLY | os.O_TRUNC, dir_fd=dfd)
                        os.write(pfd, b'{"post_rb_tampered":1}')
                    finally:
                        if pfd is not None:
                            os.close(pfd)
                _verify_posix_leaf_unchanged_in_parent(
                    dfd,
                    target_leaf,
                    prev_sha,
                    expected_id=rb_posix_id,
                )
                title_rb_ok = True
            except Exception:
                title_rb_ok = False
            finally:
                if rb_tmp_name is not None:
                    _unlink_posix_tmp_if_id_matches(dfd, rb_tmp_name, rb_posix_id)
        else:
            try:
                cur_t = _read_verified_in_parent(dfd, t_path, t_leaf)
                if hashlib.sha256(cur_t).hexdigest().lower() == written_title_sha:
                    _stage_and_replace_in_parent(dfd, t_path, t_leaf, prev_title_bytes)
                    _fsync_dir_fd(dfd)
                    title_rb_ok = True
            except Exception:
                title_rb_ok = False

    if slot_replaced:
        written_slot_sha = hashlib.sha256(written_slot_bytes).hexdigest().lower()
        if existed:
            role = "slot"
            target_p = cand
            target_leaf = leaf
            prev_bytes = prev_slot_bytes
            written_sha = written_slot_sha
            if dfd is None and os.name == "nt":
                rb_tmp_win = None
                rb_win_id = None
                parent_real_rb = None
                rb_vh = None
                sh_pin: int | None = None
                try:
                    parent_real = _current_pinned_win_parent(cand.parent)
                    parent_real_rb = parent_real
                    prev_sha = hashlib.sha256(prev_bytes).hexdigest().lower()
                    rb_tmp_win, rb_win_id = _stage_win_temp_bytes_with_id(
                        parent_real, target_p.parent, target_leaf, prev_bytes
                    )
                    if os.environ.get("TWX_SIMULATE_RB_TEMP_TAMPER", "") == role:
                        rb_tmp_win.write_bytes(b'{"rb_tampered":1}')
                    rb_vh = _win32_open_verified_exclusive_temp_for_rename(
                        rb_tmp_win, parent_real, rb_win_id, prev_sha
                    )
                    if rb_stage_hook == "slot":
                        _simulate_rb_ext_slot_write(written_slot_sha)
                    if rb_same_bytes_hook == "slot":
                        _simulate_win_rb_same_bytes_replace(
                            parent_real, cand, written_slot_bytes
                        )
                    sh_pin = _win32_create_file(str(target_p), 0x80000000, 0x01, 3, 0x00200000)
                    _win32_verify_open_handle(
                        sh_pin, parent_real, MAX_SAVE_BYTES, expected_leaf=target_leaf
                    )
                    slot_id_ok = (
                        written_win_slot_id is None
                        or _win32_get_handle_file_id(sh_pin) == written_win_slot_id
                    )
                    cur_s = _win32_read_handle_bytes(sh_pin, MAX_SAVE_BYTES)
                    if os.environ.get("TWX_VERIFY_EXCLUSIVE_TEMP_RENAME") == "1":
                        _win32_assert_temp_exclusively_pinned(rb_tmp_win)
                    if slot_id_ok and hashlib.sha256(cur_s).hexdigest().lower() == written_sha:
                        h_spin = sh_pin
                        sh_pin = None
                        _CloseHandle(wintypes.HANDLE(h_spin))
                        _win32_rename_by_handle(rb_vh, target_p, True)
                        rb_tmp_win = None
                        _CloseHandle(wintypes.HANDLE(rb_vh))
                        rb_vh = None
                        if os.environ.get("TWX_SIMULATE_POST_RB_TAMPER", "") == role:
                            target_p.write_bytes(b'{"post_rb_tampered":1}')
                        _verify_win_rb_file(
                            parent_real, target_p, target_leaf, rb_win_id, prev_sha
                        )
                        slot_rb_ok = True
                except Exception as exc:
                    if str(exc) == "EXCLUSIVE_TEMP_PIN_NOT_ENFORCED":
                        raise
                    slot_rb_ok = False
                finally:
                    if sh_pin is not None:
                        try:
                            _CloseHandle(wintypes.HANDLE(sh_pin))
                        except Exception:
                            pass
                    if rb_vh is not None:
                        try:
                            _CloseHandle(wintypes.HANDLE(rb_vh))
                        except Exception:
                            pass
                    if rb_tmp_win is not None:
                        _unlink_win_tmp_if_id_matches(rb_tmp_win, parent_real_rb, rb_win_id)
            elif dfd is not None:
                rb_tmp_name = None
                rb_posix_id = None
                try:
                    prev_sha = hashlib.sha256(prev_bytes).hexdigest().lower()
                    rb_tmp_name, rb_posix_id = _stage_temp_in_parent(
                        dfd, target_leaf, prev_bytes
                    )
                    if os.environ.get("TWX_SIMULATE_RB_TEMP_TAMPER", "") == role:
                        tfd: int | None = None
                        try:
                            tfd = os.open(rb_tmp_name, os.O_WRONLY | os.O_TRUNC, dir_fd=dfd)
                            os.write(tfd, b'{"rb_tampered":1}')
                        finally:
                            if tfd is not None:
                                os.close(tfd)
                    def _rb_slot_post_tmp_hook() -> None:
                        if rb_stage_hook == "slot":
                            _simulate_rb_ext_slot_write(written_slot_sha)

                    def _on_rb_slot_state(_rep: bool, exp_tmp: str | None, _keep_bak: bool) -> None:
                        nonlocal rb_tmp_name
                        rb_tmp_name = exp_tmp

                    _verify_tmp_and_target_before_posix_replace(
                        dfd,
                        rb_tmp_name,
                        rb_posix_id,
                        prev_sha,
                        target_leaf,
                        existed=True,
                        orig_id=written_slot_id,
                        expected_orig_sha=written_sha,
                        post_tmp_verify_hook=_rb_slot_post_tmp_hook,
                    )
                    _posix_exchange_or_replace_verified(
                        dfd,
                        rb_tmp_name,
                        rb_posix_id,
                        prev_sha,
                        target_leaf,
                        written_slot_id,
                        written_sha,
                        on_state=_on_rb_slot_state,
                        role="rb_slot",
                    )
                    rb_tmp_name = None
                    _fsync_dir_fd(dfd)
                    if os.environ.get("TWX_SIMULATE_POST_RB_TAMPER", "") == role:
                        pfd: int | None = None
                        try:
                            pfd = os.open(
                                target_leaf, os.O_WRONLY | os.O_TRUNC, dir_fd=dfd
                            )
                            os.write(pfd, b'{"post_rb_tampered":1}')
                        finally:
                            if pfd is not None:
                                os.close(pfd)
                    _verify_posix_leaf_unchanged_in_parent(
                        dfd,
                        target_leaf,
                        prev_sha,
                        expected_id=rb_posix_id,
                    )
                    slot_rb_ok = True
                except Exception:
                    slot_rb_ok = False
                finally:
                    if rb_tmp_name is not None:
                        _unlink_posix_tmp_if_id_matches(dfd, rb_tmp_name, rb_posix_id)
            else:
                try:
                    cur_s = _read_verified_in_parent(dfd, cand, leaf)
                    if hashlib.sha256(cur_s).hexdigest().lower() == written_slot_sha:
                        _stage_and_replace_in_parent(dfd, cand, leaf, prev_slot_bytes)
                        _fsync_dir_fd(dfd)
                        slot_rb_ok = True
                except Exception:
                    slot_rb_ok = False
        else:
            if dfd is None and os.name == "nt":
                sh_del: int | None = None
                try:
                    parent_real = _current_pinned_win_parent(cand.parent)
                    if rb_stage_hook == "slot_new":
                        _simulate_rb_ext_slot_write(written_slot_sha)
                    if rb_same_bytes_hook == "slot_new":
                        _simulate_win_rb_same_bytes_replace(
                            parent_real, cand, written_slot_bytes
                        )
                    sh_del = _win32_create_file(
                        str(cand),
                        0x80000000 | 0x00010000,
                        0x01,
                        3,
                        0x00200000,
                    )
                    _win32_verify_open_handle(
                        sh_del, parent_real, MAX_SAVE_BYTES, expected_leaf=leaf
                    )
                    slot_id_ok = (
                        written_win_slot_id is None
                        or _win32_get_handle_file_id(sh_del) == written_win_slot_id
                    )
                    cur_s = _win32_read_handle_bytes(sh_del, MAX_SAVE_BYTES)
                    if slot_id_ok and hashlib.sha256(cur_s).hexdigest().lower() == written_slot_sha:
                        disp = FILE_DISPOSITION_INFO(1)
                        if not _SetFileInformationByHandle(
                            wintypes.HANDLE(sh_del),
                            4,
                            ctypes.byref(disp),
                            wintypes.DWORD(ctypes.sizeof(disp)),
                        ):
                            raise ctypes.WinError(ctypes.get_last_error())
                        _CloseHandle(wintypes.HANDLE(sh_del))
                        sh_del = None
                        if not os.path.lexists(cand):
                            slot_rb_ok = True
                except Exception:
                    slot_rb_ok = False
                finally:
                    if sh_del is not None:
                        try:
                            _CloseHandle(wintypes.HANDLE(sh_del))
                        except Exception:
                            pass
            elif dfd is not None:
                try:
                    if rb_stage_hook == "slot_new":
                        _simulate_rb_ext_slot_write(written_slot_sha)
                    _verify_posix_leaf_unchanged_in_parent(
                        dfd,
                        leaf,
                        written_slot_sha,
                        expected_id=written_slot_id,
                    )
                    os.unlink(leaf, dir_fd=dfd)
                    _fsync_dir_fd(dfd)
                    try:
                        os.lstat(leaf, dir_fd=dfd)
                    except FileNotFoundError:
                        slot_rb_ok = True
                    else:
                        slot_rb_ok = False
                except Exception:
                    slot_rb_ok = False
            else:
                try:
                    cur_s = _read_verified_in_parent(dfd, cand, leaf)
                    if hashlib.sha256(cur_s).hexdigest().lower() == written_slot_sha:
                        os.unlink(cand)
                        _fsync_dir_fd(dfd)
                        slot_rb_ok = True
                except Exception:
                    slot_rb_ok = False

    return bool(title_rb_ok and slot_rb_ok)


def _commit_win_temp_replace(
    target_path: Path,
    parent_real: Path,
    payload: bytes,
    pinned_box: list[int | None],
    allow_replace: bool,
    tamper_role: str = "",
) -> tuple[str, int, int, int]:
    expected_sha = hashlib.sha256(payload).hexdigest().lower()
    tmp_path, written_win_id = _stage_win_temp_bytes_with_id(
        parent_real, target_path.parent, target_path.name, payload
    )
    renamed = False
    try:
        if tamper_role and os.environ.get("TWX_SIMULATE_STAGED_TEMP_TAMPER") == tamper_role:
            tmp_path.write_bytes(b'{"tampered":1}')
        if tamper_role and os.environ.get("TWX_SIMULATE_STAGED_TEMP_SWAP") == tamper_role:
            os.unlink(tmp_path)
            tmp_path.write_bytes(b'{"foreign_at_tmp":1}')

        vh = _win32_open_verified_exclusive_temp_for_rename(
            tmp_path, parent_real, written_win_id, expected_sha
        )
        try:
            if (
                tamper_role
                and os.environ.get("TWX_SIMULATE_EXT_WRITE_DURING_STAGED_VERIFY") == tamper_role
                and pinned_box[0] is not None
            ):
                ext_h: int | None = None
                try:
                    ext_h = _win32_create_file(
                        str(target_path), 0x40000000, 0x03, 3, 0x00200000
                    )
                except OSError:
                    pass
                else:
                    _CloseHandle(wintypes.HANDLE(ext_h))
                    raise RuntimeError("TARGET_PIN_NOT_HELD_DURING_STAGED_VERIFY")

            if os.environ.get("TWX_VERIFY_EXCLUSIVE_TEMP_RENAME") == "1":
                _win32_assert_temp_exclusively_pinned(tmp_path)

            h_pin = pinned_box[0]
            pinned_box[0] = None
            if h_pin is not None:
                _CloseHandle(wintypes.HANDLE(h_pin))
            _win32_rename_by_handle(vh, target_path, allow_replace)
            renamed = True
        finally:
            _CloseHandle(wintypes.HANDLE(vh))
    except BaseException:
        if not renamed:
            _unlink_win_tmp_if_id_matches(tmp_path, parent_real, written_win_id)
        raise
    return written_win_id


def _commit_slot_and_title_with_backup(
    root: Path,
    rel_norm: str,
    parsed: Any,
    kind: str,
    build_payload_fn: Callable[[bytes, bool], bytes],
    expected_orig_sha256: str | None,
    enforce_slot_cas: bool,
    simulate_ext_slot_write: bool,
    expected_root_id: tuple[Any, ...] | None,
    source_file_guard: tuple[tuple[Any, ...], str] | None = None,
) -> tuple[str, bytes]:
    _assert_no_case_collision(root, "backups")
    with _open_pinned_parent(root, rel_norm, create_dirs=True, expected_root_id=expected_root_id) as (cand, leaf, dfd):
        with contextlib.ExitStack() as bak_stack:
            win_orig_box: list[int | None] = [None]
            win_title_box: list[int | None] = [None]
            slot_tmp_name: str | None = None
            title_tmp_name: str | None = None
            written_slot_id: tuple[int, int] | None = None
            written_title_id: tuple[int, int] | None = None
            written_win_slot_id: tuple[str, int, int, int] | None = None
            written_win_title_id: tuple[str, int, int, int] | None = None
            created_backups: list[tuple[str, tuple[Any, ...] | None, str]] = []
            bdfd: int | None = None
            bcand_dir: Path | None = None
            b_win_dir: Path | None = None
            backups_dir_id: tuple[int, int] | None = None
            orig_stat_id: tuple[int, int] | None = None
            backup_name = ""
            out_bytes = b""
            verified_slot_bytes = b""
            existed = False
            orig_bytes = b""
            title_plan: tuple[Path, str, bytes, bytes, tuple[Any, ...] | None] | None = None
            slot_replaced = False
            title_replaced = False
            preserve_backups_on_error = False

            def _on_slot_state(rep: bool, exp_tmp: str | None, keep_bak: bool) -> None:
                nonlocal slot_replaced, slot_tmp_name, preserve_backups_on_error
                slot_replaced = rep
                slot_tmp_name = exp_tmp
                if keep_bak:
                    preserve_backups_on_error = True

            def _on_title_state(rep: bool, exp_tmp: str | None, keep_bak: bool) -> None:
                nonlocal title_replaced, title_tmp_name, preserve_backups_on_error
                title_replaced = rep
                title_tmp_name = exp_tmp
                if keep_bak:
                    preserve_backups_on_error = True

            def _verify_pinned_backups_intact() -> None:
                if not created_backups:
                    return
                if bdfd is not None:
                    r_dfd = _current_locked_root_dfd(root)
                    try:
                        if r_dfd is not None:
                            st_pub = os.lstat("backups", dir_fd=r_dfd)
                        else:
                            st_pub = os.lstat(root / "backups")
                    except (FileNotFoundError, OSError) as exc:
                        raise RuntimeError("CONFLICT_MODIFIED") from exc
                    if stat.S_ISLNK(st_pub.st_mode) or not stat.S_ISDIR(st_pub.st_mode):
                        raise RuntimeError("CONFLICT_MODIFIED")
                    if (
                        backups_dir_id is not None
                        and (int(st_pub.st_dev), int(st_pub.st_ino)) != backups_dir_id
                    ):
                        raise RuntimeError("CONFLICT_MODIFIED")
                    for bname_i, bid_i, bsha_i in created_backups:
                        exp_posix_id = (
                            (int(bid_i[0]), int(bid_i[1]))
                            if isinstance(bid_i, tuple) and len(bid_i) == 2
                            else None
                        )
                        _verify_posix_leaf_unchanged_in_parent(
                            bdfd, bname_i, bsha_i, expected_id=exp_posix_id
                        )
                elif os.name == "nt" and b_win_dir is not None:
                    for bname_i, bid_i, bsha_i in created_backups:
                        bh_chk: int | None = None
                        try:
                            btarget = b_win_dir / bname_i
                            bh_chk = _win32_create_file(
                                str(btarget), 0x80000000, 0x01, 3, 0x00200000
                            )
                            _win32_verify_open_handle(
                                bh_chk, b_win_dir, MAX_SAVE_BYTES, expected_leaf=bname_i
                            )
                            if bid_i is not None and _win32_get_handle_file_id(bh_chk) != bid_i:
                                raise RuntimeError("CONFLICT_MODIFIED")
                            braw = _win32_read_handle_bytes(bh_chk, MAX_SAVE_BYTES)
                            if hashlib.sha256(braw).hexdigest().lower() != bsha_i.lower():
                                raise RuntimeError("CONFLICT_MODIFIED")
                        except RuntimeError:
                            raise
                        except (FileNotFoundError, ValueError, OSError) as exc:
                            raise RuntimeError("CONFLICT_MODIFIED") from exc
                        finally:
                            if bh_chk is not None:
                                _CloseHandle(wintypes.HANDLE(bh_chk))

            def _cleanup_created_backups() -> None:
                if not created_backups:
                    return
                if bdfd is not None:
                    for bname_i, bid_i, bsha_i in created_backups:
                        try:
                            exp_posix_id = (
                                (int(bid_i[0]), int(bid_i[1]))
                                if isinstance(bid_i, tuple) and len(bid_i) == 2
                                else None
                            )
                            _verify_posix_leaf_unchanged_in_parent(
                                bdfd, bname_i, bsha_i, expected_id=exp_posix_id
                            )
                            os.unlink(bname_i, dir_fd=bdfd)
                        except Exception:
                            pass
                    try:
                        _fsync_dir_fd(bdfd)
                    except Exception:
                        pass
                elif os.name == "nt" and b_win_dir is not None:
                    for bname_i, bid_i, bsha_i in created_backups:
                        bh_del: int | None = None
                        try:
                            btarget = b_win_dir / bname_i
                            bh_del = _win32_create_file(
                                str(btarget),
                                0x80000000 | 0x00010000,
                                0x01,
                                3,
                                0x00200000,
                            )
                            _win32_verify_open_handle(
                                bh_del, b_win_dir, MAX_SAVE_BYTES, expected_leaf=bname_i
                            )
                            if bid_i is not None and _win32_get_handle_file_id(bh_del) != bid_i:
                                continue
                            bcur = _win32_read_handle_bytes(bh_del, MAX_SAVE_BYTES)
                            if hashlib.sha256(bcur).hexdigest().lower() != bsha_i.lower():
                                continue
                            disp = FILE_DISPOSITION_INFO(1)
                            if _SetFileInformationByHandle(
                                wintypes.HANDLE(bh_del),
                                4,
                                ctypes.byref(disp),
                                wintypes.DWORD(ctypes.sizeof(disp)),
                            ):
                                _CloseHandle(wintypes.HANDLE(bh_del))
                                bh_del = None
                        except Exception:
                            pass
                        finally:
                            if bh_del is not None:
                                try:
                                    _CloseHandle(wintypes.HANDLE(bh_del))
                                except Exception:
                                    pass

            try:
                parent_real: Path | None = None
                if dfd is None and os.name == "nt":
                    parent_real = _current_pinned_win_parent(cand.parent)
                    try:
                        win_orig_box[0] = _win32_create_file(str(cand), 0x80000000, 0x01, 3, 0x00200000)
                    except FileNotFoundError:
                        win_orig_box[0] = None
                        orig_bytes = b""
                        existed = False
                    else:
                        _win32_verify_open_handle(win_orig_box[0], parent_real, MAX_SAVE_BYTES, expected_leaf=leaf)
                        orig_bytes = _win32_read_handle_bytes(win_orig_box[0], MAX_SAVE_BYTES)
                        existed = True
                else:
                    orig_raw_res = None
                    try:
                        orig_raw_res = _read_verified_with_id_in_parent(dfd, cand, leaf)
                        existed = True
                    except FileNotFoundError:
                        orig_bytes = b""
                        existed = False
                        orig_stat_id = None
                    if orig_raw_res is not None:
                        orig_bytes = orig_raw_res[0]
                        sid = orig_raw_res[1]
                        orig_stat_id = (
                            (int(sid[0]), int(sid[1]))
                            if isinstance(sid, tuple) and len(sid) == 2
                            else None
                        )

                cur_orig_file_id: tuple[Any, ...] | None = (
                    _win32_get_handle_file_id(win_orig_box[0])
                    if (dfd is None and os.name == "nt" and existed and win_orig_box[0] is not None)
                    else orig_stat_id
                )
                actual_sha = hashlib.sha256(orig_bytes).hexdigest() if existed else ""
                if expected_orig_sha256 is not None:
                    if actual_sha.lower() != expected_orig_sha256.lower():
                        raise RuntimeError("CONFLICT_MODIFIED")
                elif (
                    source_file_guard is not None
                    and existed
                    and cur_orig_file_id is not None
                    and cur_orig_file_id == source_file_guard[0]
                ):
                    if actual_sha.lower() != source_file_guard[1].lower():
                        raise RuntimeError("CONFLICT_MODIFIED")

                out_bytes = build_payload_fn(orig_bytes, existed)
                expected_out_sha = hashlib.sha256(out_bytes).hexdigest()
                title_plan = (
                    _prepare_companion_title_in_parent(dfd, cand.parent, root, rel_norm, parsed)
                    if kind == "save" and isinstance(parsed, dict)
                    else None
                )
                expected_title_sha = (
                    hashlib.sha256(title_plan[2]).hexdigest() if title_plan is not None else ""
                )
                expected_new_title_sha = (
                    hashlib.sha256(title_plan[3]).hexdigest() if title_plan is not None else ""
                )
                orig_title_posix_id = (
                    (int(title_plan[4][0]), int(title_plan[4][1]))
                    if (
                        title_plan is not None
                        and isinstance(title_plan[4], tuple)
                        and len(title_plan[4]) == 2
                    )
                    else None
                )

                if dfd is None and os.name == "nt" and title_plan is not None:
                    assert parent_real is not None
                    try:
                        win_title_box[0] = _win32_create_file(
                            str(title_plan[0]), 0x80000000, 0x01, 3, 0x00200000
                        )
                    except FileNotFoundError as exc:
                        raise RuntimeError("CONFLICT_MODIFIED") from exc
                    _win32_verify_open_handle(
                        win_title_box[0],
                        parent_real,
                        MAX_SAVE_BYTES,
                        expected_leaf=title_plan[0].name,
                    )
                    orig_title_win = _win32_read_handle_bytes(win_title_box[0], MAX_SAVE_BYTES)
                    if orig_title_win != title_plan[2]:
                        raise RuntimeError("CONFLICT_MODIFIED")

                if existed or title_plan is not None:
                    bcand_probe, _bleaf_probe, bdfd = bak_stack.enter_context(
                        _open_pinned_parent(
                            root,
                            "backups/_probe",
                            create_dirs=True,
                            expected_root_id=expected_root_id,
                        )
                    )
                    bcand_dir = bcand_probe.parent
                    if bdfd is not None:
                        st_bdir = os.fstat(bdfd)
                        backups_dir_id = (int(st_bdir.st_dev), int(st_bdir.st_ino))
                    elif os.name == "nt":
                        b_win_dir = _current_pinned_win_parent(bcand_dir)

                if existed:
                    assert bcand_dir is not None
                    backup_name, sbak_id, sbak_sha = _write_backup_in_pinned_dir(
                        bdfd, bcand_dir, rel_norm, orig_bytes
                    )
                    created_backups.append((backup_name, sbak_id, sbak_sha))
                if title_plan is not None:
                    assert bcand_dir is not None
                    tbak, tbak_id, tbak_sha = _write_backup_in_pinned_dir(
                        bdfd, bcand_dir, title_plan[1], title_plan[2]
                    )
                    created_backups.append((tbak, tbak_id, tbak_sha))

                if (
                    os.environ.get("TWX_SIMULATE_BACKUPS_RENAME_BEFORE_COMMIT") == "1"
                    and os.name != "nt"
                    and created_backups
                ):
                    moved_bdir = root / "backups_moved"
                    pub_bdir = root / "backups"
                    os.rename(pub_bdir, moved_bdir)
                    pub_bdir.mkdir()
                    for bname_i, _bid_i, _bsha_i in created_backups:
                        (pub_bdir / bname_i).write_bytes(b"DECOY_BACKUP")

                def _simulate_ext_slot_swap() -> None:
                    ext_state = create_demo_data("save")
                    ext_state["m_iMoney"] = 777777
                    ext_bytes = serialize_json_lossless(ext_state).encode("utf-8")
                    if hashlib.sha256(ext_bytes).hexdigest().lower() == actual_sha.lower():
                        ext_state["m_iMoney"] = 777778
                        ext_bytes = serialize_json_lossless(ext_state).encode("utf-8")
                    _stage_and_replace_in_parent(dfd, cand, leaf, ext_bytes)

                def _simulate_ext_title_swap() -> None:
                    if title_plan is None:
                        return
                    ext_t_data, ext_t_meta = parse_json_lossless(title_plan[2].decode("utf-8"))
                    if title_plan[2].startswith(b"\xef\xbb\xbf"):
                        ext_t_meta["has_bom"] = True
                    if isinstance(ext_t_data, list) and ext_t_data and isinstance(ext_t_data[0], dict):
                        cur_pname = str(ext_t_data[0].get("m_strPlayerName") or "")
                        ext_t_data[0]["m_strPlayerName"] = (
                            "EXT_TITLE_WRITER_2"
                            if cur_pname == "EXT_TITLE_WRITER"
                            else "EXT_TITLE_WRITER"
                        )
                    ext_t_bytes = serialize_json_lossless(ext_t_data, ext_t_meta).encode("utf-8")
                    _stage_and_replace_in_parent(dfd, title_plan[0], title_plan[0].name, ext_t_bytes)

                _verify_pinned_backups_intact()

                if dfd is None and os.name == "nt":
                    assert parent_real is not None
                    written_win_slot_id = _commit_win_temp_replace(
                        cand,
                        parent_real,
                        out_bytes,
                        win_orig_box,
                        existed or not enforce_slot_cas,
                        tamper_role="slot",
                    )
                    slot_replaced = True
                elif dfd is not None:
                    slot_tmp_name, written_slot_id = _stage_temp_in_parent(dfd, leaf, out_bytes)
                    if title_plan is not None:
                        title_tmp_name, written_title_id = _stage_temp_in_parent(
                            dfd, title_plan[0].name, title_plan[3]
                        )

                    tamper_mode = os.environ.get("TWX_SIMULATE_STAGED_TEMP_TAMPER", "")
                    if tamper_mode == "slot" and slot_tmp_name is not None:
                        t_fd = os.open(slot_tmp_name, os.O_WRONLY | os.O_TRUNC, dir_fd=dfd)
                        try:
                            os.write(t_fd, b'{"tampered":1}')
                        finally:
                            os.close(t_fd)
                    elif tamper_mode == "title" and title_tmp_name is not None:
                        t_fd = os.open(title_tmp_name, os.O_WRONLY | os.O_TRUNC, dir_fd=dfd)
                        try:
                            os.write(t_fd, b'{"tampered":1}')
                        finally:
                            os.close(t_fd)

                    if (
                        simulate_ext_slot_write
                        and os.environ.get("TWX_SIMULATE_EXTERNAL_WRITE_DURING_SAVE") == "1"
                        and os.name != "nt"
                    ):
                        _simulate_ext_slot_swap()

                    if (
                        os.environ.get("TWX_SIMULATE_EXTERNAL_TITLE_WRITE_DURING_SAVE") == "1"
                        and os.name != "nt"
                        and title_plan is not None
                    ):
                        _simulate_ext_title_swap()

                    swap_mode = os.environ.get("TWX_SIMULATE_EXTERNAL_SWAP_DURING_VERIFY", "")
                    _verify_pinned_backups_intact()
                    if title_plan is not None:
                        _verify_posix_leaf_unchanged_in_parent(
                            dfd,
                            title_plan[0].name,
                            expected_title_sha,
                            expected_id=orig_title_posix_id,
                            after_read_hook=(
                                _simulate_ext_title_swap
                                if (os.name != "nt" and swap_mode == "title_pre")
                                else None
                            ),
                        )
                        if title_tmp_name is not None:
                            _verify_posix_leaf_unchanged_in_parent(
                                dfd,
                                title_tmp_name,
                                expected_new_title_sha,
                                expected_id=written_title_id,
                            )
                    swap_during_tmp = os.environ.get("TWX_SIMULATE_EXT_SWAP_DURING_TMP_VERIFY", "")
                    post_verify_tamper = os.environ.get("TWX_SIMULATE_POST_VERIFY_TMP_TAMPER", "")
                    s_tmp = slot_tmp_name
                    assert s_tmp is not None

                    def _slot_post_tmp_hook() -> None:
                        if swap_during_tmp == "slot" and os.name != "nt":
                            _simulate_ext_slot_swap()
                        if post_verify_tamper == "slot_inplace":
                            fd = os.open(s_tmp, os.O_WRONLY | os.O_TRUNC, dir_fd=dfd)
                            try:
                                os.write(fd, b'{"pv_tampered":1}')
                            finally:
                                os.close(fd)
                        elif post_verify_tamper == "slot_swap":
                            os.unlink(s_tmp, dir_fd=dfd)
                            fd = os.open(
                                s_tmp,
                                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                                0o600,
                                dir_fd=dfd,
                            )
                            try:
                                os.write(fd, b'{"pv_swapped":1}')
                            finally:
                                os.close(fd)

                    _verify_tmp_and_target_before_posix_replace(
                        dfd,
                        s_tmp,
                        written_slot_id,
                        expected_out_sha,
                        leaf,
                        existed=existed,
                        orig_id=orig_stat_id,
                        expected_orig_sha=actual_sha,
                        post_tmp_verify_hook=_slot_post_tmp_hook,
                        after_target_read_hook=(
                            _simulate_ext_slot_swap
                            if (os.name != "nt" and swap_mode == "slot" and existed)
                            else None
                        ),
                    )
                    if not existed:
                        _posix_link_verified_new_slot(
                            dfd,
                            s_tmp,
                            written_slot_id,
                            expected_out_sha,
                            leaf,
                            on_state=_on_slot_state,
                        )
                    else:
                        _posix_exchange_or_replace_verified(
                            dfd,
                            s_tmp,
                            written_slot_id,
                            expected_out_sha,
                            leaf,
                            orig_stat_id,
                            actual_sha,
                            after_preverify_hook=(_simulate_ext_slot_swap if (os.name != "nt" and os.environ.get("TWX_SIMULATE_POST_PREVERIFY_EXT_SWAP", "") == "slot") else None),
                            on_state=_on_slot_state,
                            role="slot",
                        )
                        slot_tmp_name = None
                        slot_replaced = True
                else:
                    _stage_and_replace_in_parent(dfd, cand, leaf, out_bytes)
                    slot_replaced = True

                if os.environ.get("TWX_SIMULATE_POST_SLOT_SYNC_FAIL") == "1":
                    raise OSError("SIMULATED_POST_SLOT_SYNC_FAIL")
                _fsync_dir_fd(dfd)

                if title_plan is not None:
                    if os.environ.get("TWX_SIMULATE_TITLE_WRITE_FAIL") == "1":
                        raise OSError("SIMULATED_TITLE_WRITE_FAIL")
                    if dfd is None and os.name == "nt":
                        assert parent_real is not None
                        written_win_title_id = _commit_win_temp_replace(
                            title_plan[0],
                            parent_real,
                            title_plan[3],
                            win_title_box,
                            True,
                            tamper_role="title",
                        )
                        title_replaced = True
                    elif dfd is not None and title_tmp_name is not None:
                        swap_mode = os.environ.get("TWX_SIMULATE_EXTERNAL_SWAP_DURING_VERIFY", "")
                        post_verify_tamper = os.environ.get("TWX_SIMULATE_POST_VERIFY_TMP_TAMPER", "")
                        t_tmp = title_tmp_name

                        def _title_post_tmp_hook() -> None:
                            if (
                                os.environ.get("TWX_SIMULATE_EXT_SWAP_DURING_TMP_VERIFY", "") == "title"
                                and os.name != "nt"
                            ):
                                _simulate_ext_title_swap()
                            if post_verify_tamper == "title_inplace":
                                fd = os.open(t_tmp, os.O_WRONLY | os.O_TRUNC, dir_fd=dfd)
                                try:
                                    os.write(fd, b'{"pv_title_tampered":1}')
                                finally:
                                    os.close(fd)
                            elif post_verify_tamper == "title_swap":
                                os.unlink(t_tmp, dir_fd=dfd)
                                fd = os.open(
                                    t_tmp,
                                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                                    0o600,
                                    dir_fd=dfd,
                                )
                                try:
                                    os.write(fd, b'{"pv_title_swapped":1}')
                                finally:
                                    os.close(fd)

                        _verify_tmp_and_target_before_posix_replace(
                            dfd,
                            t_tmp,
                            written_title_id,
                            expected_new_title_sha,
                            title_plan[0].name,
                            existed=True,
                            orig_id=orig_title_posix_id,
                            expected_orig_sha=expected_title_sha,
                            post_tmp_verify_hook=_title_post_tmp_hook,
                            after_target_read_hook=(
                                _simulate_ext_title_swap
                                if (os.name != "nt" and swap_mode == "title_post")
                                else None
                            ),
                        )
                        _posix_exchange_or_replace_verified(
                            dfd,
                            t_tmp,
                            written_title_id,
                            expected_new_title_sha,
                            title_plan[0].name,
                            orig_title_posix_id,
                            expected_title_sha,
                            after_preverify_hook=(_simulate_ext_title_swap if (os.name != "nt" and os.environ.get("TWX_SIMULATE_POST_PREVERIFY_EXT_SWAP", "") == "title") else None),
                            on_state=_on_title_state,
                            role="title",
                        )
                        title_tmp_name = None
                        title_replaced = True
                    else:
                        _stage_and_replace_in_parent(dfd, title_plan[0], title_plan[0].name, title_plan[3])
                        title_replaced = True
                    if os.environ.get("TWX_SIMULATE_POST_TITLE_SYNC_FAIL") == "1":
                        raise OSError("SIMULATED_POST_TITLE_SYNC_FAIL")
                    _fsync_dir_fd(dfd)

                _verify_pinned_backups_intact()

                if dfd is None and os.name == "nt":
                    assert parent_real is not None
                    post_sh: int | None = None
                    try:
                        post_sh = _win32_create_file(
                            str(cand), 0x80000000, 0x01, 3, 0x00200000
                        )
                        _win32_verify_open_handle(
                            post_sh, parent_real, MAX_SAVE_BYTES, expected_leaf=leaf
                        )
                        if (
                            written_win_slot_id is not None
                            and _win32_get_handle_file_id(post_sh) != written_win_slot_id
                        ):
                            raise RuntimeError("CONFLICT_MODIFIED")
                        verified_slot_bytes = _win32_read_handle_bytes(post_sh, MAX_SAVE_BYTES)
                        if (
                            hashlib.sha256(verified_slot_bytes).hexdigest().lower()
                            != expected_out_sha.lower()
                        ):
                            raise RuntimeError("CONFLICT_MODIFIED")
                    except RuntimeError:
                        raise
                    except (FileNotFoundError, ValueError, OSError) as exc:
                        raise RuntimeError("CONFLICT_MODIFIED") from exc
                    finally:
                        if post_sh is not None:
                            _CloseHandle(wintypes.HANDLE(post_sh))

                    if title_plan is not None:
                        post_th: int | None = None
                        try:
                            post_th = _win32_create_file(
                                str(title_plan[0]), 0x80000000, 0x01, 3, 0x00200000
                            )
                            _win32_verify_open_handle(
                                post_th,
                                parent_real,
                                MAX_SAVE_BYTES,
                                expected_leaf=title_plan[0].name,
                            )
                            if (
                                written_win_title_id is not None
                                and _win32_get_handle_file_id(post_th) != written_win_title_id
                            ):
                                raise RuntimeError("CONFLICT_MODIFIED")
                            verified_title_bytes = _win32_read_handle_bytes(
                                post_th, MAX_SAVE_BYTES
                            )
                            if (
                                hashlib.sha256(verified_title_bytes).hexdigest().lower()
                                != expected_new_title_sha.lower()
                            ):
                                raise RuntimeError("CONFLICT_MODIFIED")
                        except RuntimeError:
                            raise
                        except (FileNotFoundError, ValueError, OSError) as exc:
                            raise RuntimeError("CONFLICT_MODIFIED") from exc
                        finally:
                            if post_th is not None:
                                _CloseHandle(wintypes.HANDLE(post_th))
                elif dfd is not None:
                    try:
                        verified_slot_bytes, post_slot_id = _read_verified_with_id_in_parent(
                            dfd, cand, leaf
                        )
                    except RuntimeError:
                        raise
                    except (FileNotFoundError, ValueError, OSError) as exc:
                        raise RuntimeError("CONFLICT_MODIFIED") from exc
                    if (
                        written_slot_id is not None and post_slot_id != written_slot_id
                    ) or (
                        hashlib.sha256(verified_slot_bytes).hexdigest().lower()
                        != expected_out_sha.lower()
                    ):
                        raise RuntimeError("CONFLICT_MODIFIED")

                    if title_plan is not None:
                        try:
                            verified_title_bytes, post_title_id = (
                                _read_verified_with_id_in_parent(
                                    dfd, title_plan[0], title_plan[0].name
                                )
                            )
                        except RuntimeError:
                            raise
                        except (FileNotFoundError, ValueError, OSError) as exc:
                            raise RuntimeError("CONFLICT_MODIFIED") from exc
                        if (
                            written_title_id is not None and post_title_id != written_title_id
                        ) or (
                            hashlib.sha256(verified_title_bytes).hexdigest().lower()
                            != expected_new_title_sha.lower()
                        ):
                            raise RuntimeError("CONFLICT_MODIFIED")
                else:
                    verified_slot_bytes = _read_verified_in_parent(dfd, cand, leaf)
                    if (
                        hashlib.sha256(verified_slot_bytes).hexdigest().lower()
                        != expected_out_sha.lower()
                    ):
                        raise RuntimeError("CONFLICT_MODIFIED")
            except BaseException:
                if os.name == "nt":
                    for box in (win_orig_box, win_title_box):
                        if box[0] is not None:
                            try:
                                _CloseHandle(wintypes.HANDLE(box[0]))
                            except Exception:
                                pass
                            box[0] = None
                if slot_tmp_name is not None:
                    try:
                        if dfd is not None:
                            _unlink_posix_tmp_if_id_matches(dfd, slot_tmp_name, written_slot_id)
                        else:
                            os.unlink(cand.parent / slot_tmp_name)
                    except OSError:
                        pass
                    slot_tmp_name = None
                if title_tmp_name is not None:
                    try:
                        if dfd is not None:
                            _unlink_posix_tmp_if_id_matches(dfd, title_tmp_name, written_title_id)
                        else:
                            os.unlink(cand.parent / title_tmp_name)
                    except OSError:
                        pass
                    title_tmp_name = None

                if not slot_replaced and not title_replaced:
                    if not preserve_backups_on_error:
                        _cleanup_created_backups()
                else:
                    rb_ok = _rollback_replaced_in_parent(
                        dfd,
                        cand,
                        leaf,
                        existed,
                        orig_bytes,
                        out_bytes,
                        written_slot_id,
                        slot_replaced,
                        title_plan,
                        written_title_id,
                        title_replaced,
                        written_win_slot_id=written_win_slot_id,
                        written_win_title_id=written_win_title_id,
                    )
                    if rb_ok:
                        if not preserve_backups_on_error:
                            _cleanup_created_backups()
                raise
            finally:
                for tmp_name, exp_tmp_id in (
                    (slot_tmp_name, written_slot_id),
                    (title_tmp_name, written_title_id),
                ):
                    if tmp_name is not None:
                        try:
                            if dfd is not None:
                                _unlink_posix_tmp_if_id_matches(dfd, tmp_name, exp_tmp_id)
                            else:
                                os.unlink(cand.parent / tmp_name)
                        except OSError:
                            pass
                if os.name == "nt":
                    for box in (win_orig_box, win_title_box):
                        if box[0] is not None:
                            try:
                                _CloseHandle(wintypes.HANDLE(box[0]))
                            except Exception:
                                pass
                            box[0] = None
            return backup_name, verified_slot_bytes


def atomic_save_with_backup(
    root: Path,
    rel_slot: str,
    new_text: str,
    expected_orig_sha256: str | None = None,
    expected_root_id: tuple[Any, ...] | None = None,
    source_file_guard: tuple[tuple[Any, ...], str] | None = None,
) -> dict[str, Any]:
    with _slot_lock_guard(root, rel_slot, create_dirs=True, expected_root_id=expected_root_id):
        if is_game_running():
            raise RuntimeError("GAME_RUNNING")
        _assert_not_reserved_slot(rel_slot)
        _assert_no_case_collision(root, rel_slot)
        _assert_no_case_collision(root, "backups")
        target = resolve_safe_save_path(root, rel_slot)
        parsed, meta = parse_json_lossless(new_text)
        kind = validate_data(parsed)
        exp_kind = expected_slot_kind(target.name)
        if exp_kind is not None and kind != exp_kind:
            raise ValueError(f"대상 슬롯({target.name})의 예상 형식({exp_kind})과 데이터 형식({kind})이 일치하지 않습니다.")

        rel_norm = _to_rel_slot_posix_safe(os.path.relpath(os.path.abspath(target), os.path.abspath(root)))

        def _build_out(orig_b: bytes, ex: bool) -> bytes:
            if ex and orig_b.startswith(b"\xef\xbb\xbf"):
                meta["has_bom"] = True
            b = serialize_json_lossless(parsed, meta).encode("utf-8")
            if len(b) > MAX_SAVE_BYTES:
                raise ValueError("직렬화된 세이브 크기가 16 MiB를 초과합니다.")
            return b

        backup_name, out_bytes = _commit_slot_and_title_with_backup(
            root=root,
            rel_norm=rel_norm,
            parsed=parsed,
            kind=kind,
            build_payload_fn=_build_out,
            expected_orig_sha256=expected_orig_sha256,
            enforce_slot_cas=True,
            simulate_ext_slot_write=True,
            expected_root_id=expected_root_id,
            source_file_guard=source_file_guard,
        )
        return {"ok": True, "slot": rel_slot, "backup": backup_name, "sha256": hashlib.sha256(out_bytes).hexdigest()}


def restore_backup(
    root: Path,
    backup_name: str,
    rel_slot: str,
    expected_root_id: tuple[Any, ...] | None = None,
) -> dict[str, Any]:
    with _slot_lock_guard(root, rel_slot, create_dirs=True, expected_root_id=expected_root_id):
        if is_game_running():
            raise RuntimeError("GAME_RUNNING")
        _assert_not_reserved_slot(rel_slot)
        _assert_no_case_collision(root, rel_slot)
        bak_only = Path(backup_name).name
        if bak_only != backup_name or "/" in backup_name or "\\" in backup_name:
            raise ValueError("백업 파일 이름에는 경로 구분자를 포함할 수 없습니다.")
        _assert_no_case_collision(root, f"backups/{bak_only}")
        target = resolve_safe_save_path(root, rel_slot)
        rel_norm = _to_rel_slot_posix_safe(os.path.relpath(os.path.abspath(target), os.path.abspath(root)))
        if not is_backup_for_slot(bak_only, rel_norm):
            raise ValueError("백업 파일의 원본 슬롯이 대상 슬롯과 일치하지 않습니다.")
        bak_bytes = read_safe_bytes(root, f"backups/{bak_only}", expected_root_id=expected_root_id)
        m_sha = re.search(r"_([0-9a-fA-F]{8})\.bak$", bak_only)
        if not m_sha or not hashlib.sha256(bak_bytes).hexdigest().lower().startswith(m_sha.group(1).lower()):
            raise ValueError("백업 파일의 SHA-256 해시 접미사가 누락되었거나 손상되었습니다.")
        parsed, _ = parse_json_lossless(bak_bytes.decode("utf-8"))
        kind = validate_data(parsed)

        exp_kind = expected_slot_kind(target.name)
        if exp_kind is not None and kind != exp_kind:
            raise ValueError(f"대상 슬롯({target.name})의 예상 형식({exp_kind})과 백업 형식({kind})이 일치하지 않습니다.")

        _commit_slot_and_title_with_backup(
            root=root,
            rel_norm=rel_norm,
            parsed=parsed,
            kind=kind,
            build_payload_fn=lambda _orig_b, _ex: bak_bytes,
            expected_orig_sha256=None,
            enforce_slot_cas=True,
            simulate_ext_slot_write=False,
            expected_root_id=expected_root_id,
        )
        return {"ok": True, "slot": rel_slot, "restoredFrom": bak_only}


def _contains_lone_surrogate(obj: Any) -> bool:
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, str):
            if any(0xD800 <= ord(ch) <= 0xDFFF for ch in cur):
                return True
        elif isinstance(cur, dict):
            for k, v in cur.items():
                stack.append(k)
                stack.append(v)
        elif isinstance(cur, list):
            for item in cur:
                stack.append(item)
    return False


def create_bridge_server(root: Path, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("루프백 주소(127.0.0.1 또는 localhost)에만 바인딩할 수 있습니다.")
    pin_h_or_fd, approved_root_id, root_resolved = _open_and_pin_dir_nofollow(
        Path(root), create_missing=True
    )
    if os.name != "nt":
        os.close(pin_h_or_fd)
    else:
        _CloseHandle(wintypes.HANDLE(pin_h_or_fd))
    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, obj: dict[str, Any]) -> None:
            raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _check_request_guards(self) -> bool:
            srv_port = self.server.server_port

            host_hdr = self.headers.get("Host")
            if host_hdr is None:
                self._send_json(403, {"error": "허용되지 않은 Host 헤더입니다."})
                return False
            host_hdr = host_hdr.strip().lower()
            if host_hdr not in (f"127.0.0.1:{srv_port}", f"localhost:{srv_port}"):
                self._send_json(403, {"error": "허용되지 않은 Host 헤더입니다."})
                return False

            origin = self.headers.get("Origin")
            if origin is not None:
                if origin != f"http://127.0.0.1:{srv_port}" and origin.lower() != f"http://localhost:{srv_port}":
                    self._send_json(403, {"error": "허용되지 않은 Origin 헤더입니다."})
                    return False

            sfs = self.headers.get("Sec-Fetch-Site")
            if sfs is not None and sfs not in ("same-origin", "none"):
                self._send_json(403, {"error": "교차 출처 요청이 차단되었습니다."})
                return False
            return True

        def _require_token(self) -> bool:
            got = self.headers.get("X-TWX-Token", "")
            if not got or not hmac.compare_digest(got, token):
                self._send_json(403, {"error": "유효한 세션 토큰이 필요합니다."})
                return False
            return True

        def do_GET(self) -> None:
            if not self._check_request_guards():
                return
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            if path in ("/", "/index.html"):
                if DIST_HTML_PATH.exists():
                    html = DIST_HTML_PATH.read_bytes().decode("utf-8")
                else:
                    import build as html_builder
                    html = html_builder.build()
                html = html.replace("connect-src 'none'", "connect-src 'self'")
                meta_tag = f'<meta name="twx-bridge-token" content="{token}">'
                html = html.replace('<meta charset="utf-8">', f'<meta charset="utf-8">\n{meta_tag}', 1)
                raw = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return

            if path == "/api/health":
                self._send_json(200, {"ok": True, "gameRunning": is_game_running()})
                return

            if not self._require_token():
                return

            if path == "/api/slots":
                try:
                    slots = list_slots(root_resolved, expected_root_id=approved_root_id)
                except (ValueError, OSError) as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                self._send_json(200, {"ok": True, "slots": slots})
                return

            if path == "/api/load":
                slot = (qs.get("slot") or [""])[0]
                try:
                    with _slot_lock_guard(root_resolved, slot, create_dirs=False, expected_root_id=approved_root_id):
                        _assert_no_case_collision(root_resolved, slot)
                        raw = read_safe_bytes(root_resolved, slot, expected_root_id=approved_root_id)
                        decoded_load = raw.decode("utf-8")
                        parsed_load, _ = parse_json_lossless(decoded_load)
                        kind_load = validate_data(parsed_load)
                        exp_k = expected_slot_kind(Path(slot).name)
                        if exp_k is not None and kind_load != exp_k:
                            raise ValueError(f"대상 슬롯({Path(slot).name})의 예상 형식({exp_k})과 데이터 형식({kind_load})이 일치하지 않습니다.")
                        sha = hashlib.sha256(raw).hexdigest()
                except FileNotFoundError:
                    self._send_json(404, {"error": "슬롯 파일을 찾을 수 없습니다."})
                    return
                except RuntimeError as exc:
                    if str(exc) == "CONFLICT_MODIFIED":
                        self._send_json(409, {"error": str(exc)})
                    else:
                        self._send_json(400, {"error": str(exc)})
                    return
                except UnicodeDecodeError:
                    self._send_json(400, {"error": "유효하지 않은 UTF-8 인코딩 세이브 파일입니다."})
                    return
                except (ValueError, OSError) as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-TWX-Sha256", sha)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return

            if path == "/api/backups":
                slot = (qs.get("slot") or [""])[0]
                rel_norm = ""
                items = []
                try:
                    if slot:
                        with _slot_lock_guard(root_resolved, slot, create_dirs=False, expected_root_id=approved_root_id):
                            _assert_no_case_collision(root_resolved, slot)
                            _assert_no_case_collision(root_resolved, "backups")
                            target = resolve_safe_save_path(root_resolved, slot)
                            rel_norm = _to_rel_slot_posix_safe(
                                os.path.relpath(
                                    os.path.abspath(target), os.path.abspath(root_resolved)
                                )
                            )
                            try:
                                with _open_pinned_parent(
                                    root_resolved,
                                    "backups/_probe",
                                    create_dirs=False,
                                    expected_root_id=approved_root_id,
                                ) as (bcand, _bleaf, bdfd):
                                    if bdfd is not None:
                                        with os.scandir(bdfd) as it:
                                            for entry in it:
                                                if not entry.name.lower().endswith(".bak"):
                                                    continue
                                                if not is_backup_for_slot(entry.name, rel_norm):
                                                    continue
                                                if not entry.is_symlink() and entry.is_file(follow_symlinks=False):
                                                    items.append(
                                                        {
                                                            "name": entry.name,
                                                            "size": entry.stat(follow_symlinks=False).st_size,
                                                        }
                                                    )
                                    else:
                                        with os.scandir(_current_pinned_win_parent(bcand.parent)) as it:
                                            for entry in it:
                                                if not entry.name.lower().endswith(".bak"):
                                                    continue
                                                if not is_backup_for_slot(entry.name, rel_norm):
                                                    continue
                                                if not _is_reparse_or_symlink(Path(entry.path)) and entry.is_file(
                                                    follow_symlinks=False
                                                ):
                                                    items.append(
                                                        {
                                                            "name": entry.name,
                                                            "size": entry.stat(follow_symlinks=False).st_size,
                                                        }
                                                    )
                            except (FileNotFoundError, NotADirectoryError):
                                pass
                    else:
                        with _store_lock_guard(
                            root_resolved,
                            expected_root_id=approved_root_id,
                            create_dir=False,
                        ):
                            if _capture_root_identity(root_resolved) != approved_root_id:
                                raise ValueError("세이브 루트 디렉터리 식별자가 변경되었습니다.")
                            _assert_no_case_collision(root_resolved, "backups")
                            try:
                                with _open_pinned_parent(
                                    root_resolved,
                                    "backups/_probe",
                                    create_dirs=False,
                                    expected_root_id=approved_root_id,
                                ) as (bcand, _bleaf, bdfd):
                                    if bdfd is not None:
                                        with os.scandir(bdfd) as it:
                                            for entry in it:
                                                if not entry.name.lower().endswith(".bak"):
                                                    continue
                                                if not entry.is_symlink() and entry.is_file(follow_symlinks=False):
                                                    items.append(
                                                        {
                                                            "name": entry.name,
                                                            "size": entry.stat(follow_symlinks=False).st_size,
                                                        }
                                                    )
                                    else:
                                        with os.scandir(_current_pinned_win_parent(bcand.parent)) as it:
                                            for entry in it:
                                                if not entry.name.lower().endswith(".bak"):
                                                    continue
                                                if not _is_reparse_or_symlink(Path(entry.path)) and entry.is_file(
                                                    follow_symlinks=False
                                                ):
                                                    items.append(
                                                        {
                                                            "name": entry.name,
                                                            "size": entry.stat(follow_symlinks=False).st_size,
                                                        }
                                                    )
                            except (FileNotFoundError, NotADirectoryError):
                                pass
                except (ValueError, OSError) as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                items.sort(key=lambda item: item["name"], reverse=True)
                self._send_json(200, {"ok": True, "backups": items})
                return

            self._send_json(404, {"error": "알 수 없는 경로입니다."})

        def do_POST(self) -> None:
            if not self._check_request_guards() or not self._require_token():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_json(400, {"error": "잘못된 Content-Length입니다."})
                return
            if length <= 0 or length > MAX_SAVE_BYTES * 6 + 1024 * 1024:
                self._send_json(400, {"error": "요청 본문 크기가 허용 범위를 벗어났습니다."})
                return
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8", errors="strict"))
            except Exception:
                self._send_json(400, {"error": "유효하지 않은 JSON 본문입니다."})
                return
            if not isinstance(body, dict):
                self._send_json(400, {"error": "요청 본문은 객체여야 합니다."})
                return
            if _contains_lone_surrogate(body):
                self._send_json(400, {"error": "유효하지 않은 유니코드 서로게이트가 포함되어 있습니다."})
                return

            path = urlparse(self.path).path
            if path == "/api/save":
                slot = str(body.get("slot") or "")
                text = body.get("text")
                if not slot or not isinstance(text, str):
                    self._send_json(400, {"error": "slot과 text 필드가 필요합니다."})
                    return
                if not isinstance(body.get("baseSha256"), str):
                    self._send_json(400, {"error": "MISSING_BASE_SHA256"})
                    return
                try:
                    res = atomic_save_with_backup(
                        root_resolved,
                        slot,
                        text,
                        expected_orig_sha256=body["baseSha256"],
                        expected_root_id=approved_root_id,
                    )
                    self._send_json(200, res)
                except RuntimeError as exc:
                    if str(exc) in ("GAME_RUNNING", "CONFLICT_MODIFIED"):
                        self._send_json(409, {"error": str(exc)})
                    else:
                        self._send_json(400, {"error": str(exc)})
                except (ValueError, OSError) as exc:
                    self._send_json(400, {"error": str(exc)})
                return

            if path == "/api/restore":
                slot = str(body.get("slot") or "")
                backup = str(body.get("backup") or "")
                if not slot or not backup:
                    self._send_json(400, {"error": "slot과 backup 필드가 필요합니다."})
                    return
                try:
                    res = restore_backup(
                        root_resolved,
                        backup,
                        slot,
                        expected_root_id=approved_root_id,
                    )
                    self._send_json(200, res)
                except RuntimeError as exc:
                    if str(exc) in ("GAME_RUNNING", "CONFLICT_MODIFIED"):
                        self._send_json(409, {"error": str(exc)})
                    else:
                        self._send_json(400, {"error": str(exc)})
                except (ValueError, FileNotFoundError, OSError) as exc:
                    self._send_json(400, {"error": str(exc)})
                return

            self._send_json(404, {"error": "알 수 없는 경로입니다."})

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    srv = ThreadingHTTPServer((host, port), Handler)
    srv.bridge_token = token  # type: ignore[attr-defined]
    return srv


def _assert_cli_safe_path(raw_arg: str, p: Path) -> None:
    if not raw_arg or not isinstance(raw_arg, str):
        raise ValueError("CLI 경로가 비어 있거나 올바르지 않습니다.")
    for c in raw_arg:
        if ord(c) < 32:
            raise ValueError("CLI 경로에 제어 문자를 사용할 수 없습니다.")
    if os.name != "nt" and "\\" in raw_arg:
        raise ValueError("POSIX CLI 경로 인자에 역슬래시(\\)를 사용할 수 없습니다.")
    for idx, c in enumerate(raw_arg):
        if c != ":":
            continue
        is_drive = (
            idx == 1
            and raw_arg[0].isalpha()
            and (os.name == "nt" or (len(raw_arg) > 2 and raw_arg[2] in ("/", "\\")))
        )
        if not is_drive:
            raise ValueError("CLI 경로에 허용되지 않은 콜론이 포함되어 있습니다.")
    for raw_seg in re.split(r"[\\/]", raw_arg):
        if raw_seg and raw_seg not in (".", "..") and raw_seg.endswith((" ", ".")):
            raise ValueError("CLI 경로 세그먼트 끝에 공백이나 마침표를 사용할 수 없습니다.")
    if p.name.startswith("."):
        raise ValueError("숨김 파일이나 잠금 파일(.twx_store.lock)은 CLI 대상으로 사용할 수 없습니다.")
    for seg in p.parts:
        if not seg or seg == p.anchor:
            continue
        if seg not in (".", "..") and seg.endswith((" ", ".")):
            raise ValueError("CLI 경로 세그먼트 끝에 공백이나 마침표를 사용할 수 없습니다.")
        stem = seg.rstrip(" .").split(".", 1)[0].upper()
        if stem in RESERVED_DEVICES:
            raise ValueError("예약된 장치 이름은 경로에 사용할 수 없습니다.")
    abs_p = Path(os.path.abspath(p))
    for base in (p, abs_p):
        if _is_reparse_or_symlink(base):
            raise ValueError("심볼릭 링크 또는 재분석 지점은 사용할 수 없습니다.")
        for parent in base.parents:
            if _is_reparse_or_symlink(parent):
                raise ValueError("심볼릭 링크 또는 재분석 지점은 사용할 수 없습니다.")
        cur_dir = Path(base.anchor) if base.anchor else Path(".")
        seg_parts = base.parts[1:] if base.anchor else base.parts
        for seg in seg_parts:
            if seg in ("", "."):
                continue
            if seg == "..":
                cur_dir = cur_dir / seg
                continue
            try:
                if cur_dir.is_dir():
                    entries = os.listdir(cur_dir)
                    if any(e.lower() == seg.lower() and e != seg for e in entries):
                        raise ValueError("대소문자만 다른 동일 이름의 경로가 존재하여 모호한 접근이 차단되었습니다.")
            except PermissionError:
                pass
            cur_dir = cur_dir / seg
    _win32_assert_existing_ancestors_no_alias(abs_p)


def _read_cli_safe_bytes(raw_arg: str) -> bytes:
    raw, _ = _read_cli_safe_bytes_with_id(raw_arg)
    return raw


def _read_cli_safe_bytes_with_id(raw_arg: str) -> tuple[bytes, tuple[Any, ...] | None]:
    p = Path(raw_arg)
    _assert_cli_safe_path(raw_arg, p)
    parent = p.parent if str(p.parent) else Path(".")
    if not parent.exists():
        raise FileNotFoundError(raw_arg)
    with _store_lock_guard(parent, create_dir=False):
        _assert_no_case_collision(parent, p.name)
        return read_safe_bytes_with_id(parent, p.name)


def _probe_verified_file_id_in_dir(
    dir_path: Path, leaf_name: str
) -> tuple[Any, ...] | None:
    _assert_no_case_collision(dir_path, leaf_name)
    try:
        _, file_id = read_safe_bytes_with_id(dir_path, leaf_name)
    except FileNotFoundError:
        return None
    return file_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="협객풍운전 세이브 에디터 CLI 및 로컬 서버")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_demo = sub.add_parser("demo", help="예시 세이브 파일을 생성합니다.")
    p_demo.add_argument("--kind", choices=["save", "round", "guid"], default="save")
    p_demo.add_argument("--out", required=True)

    p_disc = sub.add_parser("discover", help="설치된 협객풍운전 세이브 경로와 슬롯을 탐색합니다.")
    p_disc.add_argument("--root")
    p_disc.add_argument("--json", action="store_true")

    p_insp = sub.add_parser("inspect", help="세이브 파일 요약 정보를 출력합니다.")
    p_insp.add_argument("file")
    p_insp.add_argument("--json", action="store_true")

    p_val = sub.add_parser("validate", help="세이브 파일 무결성을 검증합니다.")
    p_val.add_argument("file")

    p_pre = sub.add_parser("presets", help="사용 가능한 원클릭 프리셋 목록을 출력합니다.")
    p_pre.add_argument("--json", action="store_true")

    p_app = sub.add_parser("apply", help="프리셋 또는 금전 변경을 적용합니다.")
    p_app.add_argument("file")
    p_app.add_argument("--preset", choices=list(PRESETS.keys()))
    p_app.add_argument("--set-money", type=int)
    p_app.add_argument("--out")
    p_app.add_argument("--root")

    p_res = sub.add_parser("restore", help="백업 파일로부터 슬롯을 복원합니다.")
    p_res.add_argument("--root", required=True)
    p_res.add_argument("--slot", required=True)
    p_res.add_argument("--backup", required=True)

    p_srv = sub.add_parser("serve", help="로컬 루프백 웹 에디터 서버를 실행합니다.")
    p_srv.add_argument("--root")
    p_srv.add_argument("--host", default="127.0.0.1")
    p_srv.add_argument("--port", type=int, default=8765)

    args = parser.parse_args(argv)

    try:
        if args.cmd == "demo":
            data = create_demo_data(args.kind)
            out_p = Path(args.out)
            _assert_cli_safe_path(args.out, out_p)
            out_parent = out_p.parent if str(out_p.parent) else Path(".")
            with _store_lock_guard(out_parent):
                if is_game_running():
                    raise RuntimeError("GAME_RUNNING")
                _assert_no_case_collision(out_parent, out_p.name)
                _write_new_exclusive_bytes(out_p, serialize_json_lossless(data).encode("utf-8"))
            print(f"[완료] 예시 데이터({args.kind}) 생성: {out_p}")
            return 0

        if args.cmd == "discover":
            if args.root:
                _assert_cli_safe_path(args.root, Path(args.root))
            roots = [Path(args.root)] if args.root else discover_roots()
            payload = [{"root": str(r), "slots": list_slots(r)} for r in roots]
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                for item in payload:
                    print(f"경로: {item['root']} (슬롯 {len(item['slots'])}개)")
                    for s in item["slots"]:
                        print(f"  - {s['slot']}: {s['label']} ({s['size']:,} B)")
            return 0

        if args.cmd == "inspect":
            p = Path(args.file)
            raw = _read_cli_safe_bytes(args.file).decode("utf-8")
            data, _ = parse_json_lossless(raw)
            kind = validate_data(data)
            info: dict[str, Any] = {"file": str(p), "kind": kind}
            if kind == "save":
                info["player"] = (data.get("m_strPlayerLastName", "") + data.get("m_strPlayerName", "")).replace("\r", "")
                m_val = _as_exact_int(data.get("m_iMoney", 0))
                y_val = _as_exact_int(data.get("m_iYear", 1))
                mo_val = _as_exact_int(data.get("m_iMonth", 1))
                info["money"] = m_val if m_val is not None else 0
                info["year"] = y_val if y_val is not None else 1
                info["month"] = mo_val if mo_val is not None else 1
                info["scene"] = data.get("m_strSceneName", "")
            elif kind == "round":
                info["achievements"] = len(data.get("achiFinishList", []))
            elif kind == "guid":
                info["guid"] = data.get("guid", "")
            if args.json:
                print(json.dumps(info, ensure_ascii=False, indent=2))
            else:
                for k, v in info.items():
                    print(f"{k}: {v}")
            return 0

        if args.cmd == "validate":
            p = Path(args.file)
            raw = _read_cli_safe_bytes(args.file).decode("utf-8")
            data, _ = parse_json_lossless(raw)
            kind = validate_data(data)
            print(f"[검증 통과] {p} (형식: {kind})")
            return 0

        if args.cmd == "presets":
            if args.json:
                print(json.dumps(PRESETS, ensure_ascii=False, indent=2))
            else:
                for pid, meta in PRESETS.items():
                    print(f"- {pid} [{meta['kind']}]: {meta['name']} — {meta['desc']}")
            return 0

        if args.cmd == "apply":
            src_p = Path(args.file)
            _assert_cli_safe_path(args.file, src_p)
            out_p = Path(args.out) if args.out else None
            if out_p is not None:
                _assert_cli_safe_path(args.out, out_p)
            if args.root:
                _assert_cli_safe_path(args.root, Path(args.root))
            if is_game_running():
                raise RuntimeError("GAME_RUNNING")
            if not src_p.exists():
                raise FileNotFoundError(f"세이브 파일을 찾을 수 없습니다: {src_p}")

            src_root = src_p.parent if str(src_p.parent) else Path(".")
            cfg_root = Path(args.root) if args.root else None
            out_dir = (out_p.parent if str(out_p.parent) else Path(".")) if out_p is not None else None

            if cfg_root is not None and out_p is not None:
                rel_out_pre = _to_rel_slot_posix_safe(os.path.relpath(
                    os.path.abspath(out_p), os.path.abspath(cfg_root)
                ))
                _assert_not_reserved_slot(rel_out_pre)
                resolve_safe_save_path(cfg_root, rel_out_pre)
                with _open_pinned_parent(cfg_root, rel_out_pre, create_dirs=True):
                    pass
            elif cfg_root is not None and out_p is None:
                rel_src_pre = _to_rel_slot_posix_safe(os.path.relpath(
                    os.path.abspath(src_p), os.path.abspath(cfg_root)
                ))
                _assert_not_reserved_slot(rel_src_pre)
                resolve_safe_save_path(cfg_root, rel_src_pre)
            elif out_dir is not None:
                _ensure_safe_dir_nofollow(out_dir)

            lock_dirs: list[Path] = [src_root]
            if cfg_root is not None:
                lock_dirs.append(cfg_root)
            if out_dir is not None:
                lock_dirs.append(out_dir)

            lock_by_ident: dict[tuple[Any, ...], tuple[str, Path]] = {}
            for d in lock_dirs:
                _assert_no_reparse_in_ancestors(d)
                d_clean = _clean_local_dir_path(d)
                ab_norm = _norm_local_path_str(d_clean)
                dir_ident = _capture_root_identity(d_clean)
                prev_entry = lock_by_ident.get(dir_ident)
                if prev_entry is None or ab_norm < prev_entry[0]:
                    lock_by_ident[dir_ident] = (ab_norm, d_clean)

            src_dir_ident = _capture_root_identity(_clean_local_dir_path(src_root))
            out_dir_ident = (
                _capture_root_identity(_clean_local_dir_path(out_dir))
                if out_dir is not None
                else None
            )

            with contextlib.ExitStack() as stack:
                for lock_ident, (_norm, lock_root) in sorted(lock_by_ident.items(), key=lambda item: item[0]):
                    stack.enter_context(
                        _store_lock_guard(lock_root, expected_root_id=lock_ident, create_dir=False)
                    )

                pre_out_id: tuple[Any, ...] | None = None
                if out_dir is not None and out_p is not None:
                    pre_out_id = _probe_verified_file_id_in_dir(out_dir, out_p.name)

                orig_bytes, src_file_id = _read_cli_safe_bytes_with_id(args.file)
                data, meta = parse_json_lossless(orig_bytes.decode("utf-8"))
                if orig_bytes.startswith(b"\xef\xbb\xbf"):
                    meta["has_bom"] = True
                if args.preset:
                    apply_preset(data, args.preset)
                if args.set_money is not None:
                    if detect_kind(data) != "save":
                        raise ValueError("--set-money 옵션은 캐릭터 세이브(.Save)에만 사용할 수 있습니다.")
                    if args.set_money < 0 or args.set_money > 999_999_999:
                        raise ValueError("금전 수치는 0 이상 999,999,999 이하여야 합니다.")
                    data["m_iMoney"] = args.set_money
                kind = validate_data(data)
                serialized = serialize_json_lossless(data, meta)
                orig_sha = hashlib.sha256(orig_bytes).hexdigest()

                if out_p is not None:
                    exp_kind = expected_slot_kind(out_p.name)
                    if exp_kind is not None and kind != exp_kind:
                        raise ValueError(
                            f"대상 파일({out_p.name})의 예상 형식({exp_kind})과 데이터 형식({kind})이 일치하지 않습니다."
                        )
                    out_parent = Path(args.root) if args.root else (out_p.parent if str(out_p.parent) else Path("."))
                    rel_out = _to_rel_slot_posix_safe(os.path.relpath(
                        os.path.abspath(out_p), os.path.abspath(out_parent)
                    ))
                    _assert_no_case_collision(out_parent, rel_out)
                    same_dir_slot = (
                        out_dir_ident == src_dir_ident
                        and os.path.normcase(out_p.name) == os.path.normcase(src_p.name)
                    )
                    same_inode = (
                        src_file_id is not None
                        and pre_out_id is not None
                        and pre_out_id == src_file_id
                    )
                    same_realpath = out_p.exists() and (
                        os.path.normcase(os.path.realpath(out_p))
                        == os.path.normcase(os.path.realpath(src_p))
                    )
                    same_file = same_dir_slot or same_inode or same_realpath
                    res = atomic_save_with_backup(
                        out_parent,
                        rel_out,
                        serialized,
                        expected_orig_sha256=(orig_sha if same_file else None),
                        source_file_guard=(
                            (src_file_id, orig_sha) if src_file_id is not None else None
                        ),
                    )
                    print(f"[백업 및 저장 완료] {out_p} (백업: {res['backup'] or '신규'})")
                else:
                    root_dir = Path(args.root) if args.root else src_root
                    rel_name = _to_rel_slot_posix_safe(os.path.relpath(
                        os.path.abspath(src_p), os.path.abspath(root_dir)
                    ))
                    res = atomic_save_with_backup(
                        root_dir,
                        rel_name,
                        serialized,
                        expected_orig_sha256=orig_sha,
                    )
                    print(f"[백업 및 저장 완료] {src_p} (백업: {res['backup'] or '신규'})")
            return 0

        if args.cmd == "restore":
            _assert_cli_safe_path(args.root, Path(args.root))
            if os.name != "nt" and ("\\" in args.slot or "\\" in args.backup):
                raise ValueError("POSIX CLI 경로 인자에 역슬래시(\\)를 사용할 수 없습니다.")
            res = restore_backup(Path(args.root), args.backup, args.slot)
            print(json.dumps(res, ensure_ascii=False))
            return 0

        if args.cmd == "serve":
            if args.root:
                _assert_cli_safe_path(args.root, Path(args.root))
                root_dir = Path(args.root)
            else:
                roots = discover_roots()
                if roots:
                    root_dir = roots[0]
                else:
                    default_saves = BASE_DIR / "saves"
                    if _is_reparse_or_symlink(default_saves):
                        raise ValueError("심볼릭 링크 또는 재분석 지점 디렉터리는 허용되지 않습니다.")
                    root_dir = default_saves
            srv = create_bridge_server(root_dir, args.host, args.port)
            actual_port = srv.server_address[1]
            print(f"협객풍운전 로컬 브리지 서버 실행 중: http://{args.host}:{actual_port}/ (경로: {root_dir})", flush=True)
            try:
                srv.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                srv.server_close()
            return 0
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
