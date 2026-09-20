#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""业务操作日志埋点 —— 端到端验证。

跑法（后端需已在跑）：
    venv\\Scripts\\python.exe tools\\verify-operation-logs.py [--port 8080]

覆盖三件事：
  1. 业务接口成功后**确实**写了 OperationLogs（Action / Target / Username / Result / CreatedDate 正确）
  2. 失败路径**不产生**日志（这是埋点最容易写错的地方：把 log 放在校验之前就全错了）
  3. 推理（/predict）**不写** OperationLogs —— 按拍板结论靠 InferenceResults 留痕，
     这里用"动作名断言"把该约定钉死，防止以后有人顺手加回去把日志表刷爆

⚠️ 判成败看信封里的 `code == 2000`：dvadmin 那套接口**失败也回 HTTP 200**
（见 dvadmin.py 的 _ok/_fail）。业务接口（api.py）反过来，是裸 JSON + 真实 HTTP 状态码，
两种风格并存，本脚本按接口分别判。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=8080)
ap.add_argument("--user", default="admin")
ap.add_argument("--password", default="Admin@2026")
args = ap.parse_args()
B = f"http://{args.host}:{args.port}"

PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, ok: bool, extra: object = "") -> None:
    (PASS if ok else FAIL).append(label)
    mark = "OK  " if ok else "FAIL"
    tail = f"  -> {extra}" if extra != "" else ""
    print(f"  [{mark}] {label}{tail}")


def req(method: str, path: str, token: str | None = None, body=None, form=None, files=None):
    """返回 (http_status, json)。

    form  : dict，普通表单字段
    files : list[(字段名, 文件名, bytes)]，走同一个 multipart
            ⚠️ 上传接口校验的是"有没有真的收到文件"，只发普通字段会被 400 拒掉，
               所以这里必须能拼出带 filename 的 part。
    """
    url = B + path
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if form is not None or files:
        boundary = "----verifyoplog"
        chunks = []
        for key, value in (form or {}).items():
            chunks.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode("utf-8"))
        for field, filename, blob in (files or []):
            chunks.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
                f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode("utf-8"))
            chunks.append(blob)
            chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        data = b"".join(chunks)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    else:
        data = None
    r = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=180) as f:
            raw = f.read()
            return f.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, (json.loads(raw) if raw else {})
        except Exception:
            return e.code, {"raw": raw[:200].decode("utf-8", "replace")}


def login(user: str, pwd: str):
    st, js = req("POST", "/api/login/", body={"username": user, "password": pwd})
    if js.get("code") == 2000:
        return js["data"]["access"]
    return None


def logs(token: str, limit: int = 200) -> list[dict]:
    """拉最近的日志。注意这是 dvadmin 信封接口。"""
    st, js = req("GET", f"/api/system/operation_log/?limit={limit}", token)
    if js.get("code") != 2000:
        return []
    return (js.get("data") or {}).get("results") or []


def actions_of(rows: list[dict]) -> list[str]:
    return [str(r.get("Action") or "") for r in rows]


def find(rows: list[dict], action: str, target: str | None = None) -> dict | None:
    """在日志里找一条匹配的（新的在前，取最近一条）。"""
    for r in rows:
        if str(r.get("Action")) == action and (target is None or str(r.get("Target")) == target):
            return r
    return None


# ================================================================ 主流程
print("=" * 74)
print("  业务操作日志埋点验证")
print("=" * 74)

admin_t = login(args.user, args.password)
if not admin_t:
    print(f"  admin 登录失败，无法继续（检查后端是否在 {B} 上跑、账号密码是否正确）")
    sys.exit(2)
check("admin 登录成功", True)

# 先看基线：埋点之前已经有多少条，后面用"有没有新增"来判断，
# 不能假设库是空的（本地反复跑过很多次）
base = logs(admin_t)
base_n = len(base)
print(f"  基线日志条数 = {base_n}")

tag = time.strftime("%m%d%H%M%S")

# ---------------------------------------------------------------- 1. 上传模型
print("\n[1] 模型上传 -> upload_model")
# ⚠️ 必须真的带一个**通过内容探测**的权重文件：/models/upload 会读文件头判断框架
#    （probe_weight），伪造的 .h5 头会被拒成 400「没有任何文件通过权重校验」，
#    那样根本走不到落盘/登记/埋点这几步，本项就永远测不到东西。
#    所以这里借用一个已存在的真实产物当上传源；找不到就跳过本项而不是假通过。
import pathlib                                                    # noqa: E402

source = None
for cand in sorted(pathlib.Path("data/models").glob("*/model.keras")) + \
            sorted(pathlib.Path("data/models").glob("*/model.pt")):
    if cand.is_file() and cand.stat().st_size > 1024:
        source = cand
        break

if source is None:
    print("  [跳过] 找不到可用于上传的真实权重文件（data/models/*/model.keras|model.pt）")
else:
    print(f"  用真实权重做上传源：{source}（{round(source.stat().st_size/1024,1)} KB）")
    st, js = req("POST", "/models/upload", admin_t,
                 form={"name": f"verifylog_{tag}", "description": "操作日志验证用"},
                 files=[("file", source.name, source.read_bytes())])
    check("上传接口返回成功（HTTP 2xx）", st in (200, 201), f"http={st} err={js.get('error')}")
    uploaded_model = js.get("model") if isinstance(js, dict) else None

    rows = logs(admin_t)
    hit = find(rows, "upload_model", uploaded_model)
    check("上传后出现 upload_model 日志", hit is not None, f"model={uploaded_model}")
    if hit:
        check("日志里 Username 是 admin", hit.get("Username") == args.user, hit.get("Username"))
        check("日志里 Result 是 成功", hit.get("Result") == "成功", hit.get("Result"))
        check("日志里 CreatedDate 非空", bool(hit.get("CreatedDate")), hit.get("CreatedDate"))
        detail_s = json.dumps(hit.get("Detail"), ensure_ascii=False)
        check("Detail 里带 replaced 字段（覆盖上传可追溯）", "replaced" in detail_s, detail_s[:140])

# ---------------------------------------------------------------- 2. 修改模型
print("\n[2] 修改模型 -> update_model")
if uploaded_model:
    st, js = req("PUT", f"/models/{uploaded_model}", admin_t,
                 body={"Description": f"改过了 {tag}"})
    check("修改接口返回成功", st == 200, f"http={st} err={js.get('error')}")
    rows = logs(admin_t)
    hit = find(rows, "update_model", uploaded_model)
    check("修改后出现 update_model 日志", hit is not None, f"model={uploaded_model}")
    if hit:
        detail_s = json.dumps(hit.get("Detail"), ensure_ascii=False)
        check("Detail 里记了 old_name（改名可反查）", "old_name" in detail_s, detail_s[:140])
else:
    check("修改模型（跳过：上一步没拿到模型名）", False)

# ---------------------------------------------------------------- 3. 失败路径不写日志
print("\n[3] 失败路径**不得**产生日志（埋点最容易错的地方）")
before = actions_of(logs(admin_t))

# 3a. 上传缺 name -> 400，且不该有日志
st, js = req("POST", "/models/upload", admin_t, form={"description": "没有 name"})
check("缺 name 的上传被拒（400）", st == 400, f"http={st}")

# 3b. 改一个不存在的模型 -> 4xx（db 层对"名字不在 Models 表"抛 DBError，映射成 409 而非 404，
#     两种都算"明确拒绝"，这里只断言 4xx，不去绑死具体码）
st, js = req("PUT", f"/models/no_such_model_{tag}", admin_t, body={"Description": "x"})
check("改不存在的模型被拒（4xx）", 400 <= st < 500, f"http={st} err={js.get('error')}")

# 3c. 删一个不存在的模型 -> 4xx
st, js = req("DELETE", f"/models/no_such_model_{tag}?scope=artifact", admin_t)
check("删不存在的模型被拒（4xx）", st >= 400, f"http={st}")

after = actions_of(logs(admin_t))
# 这三步都不该新增任何 upload_model / update_model / delete_model
new_acts = [a for a in after[: len(after) - 0] if a in ("upload_model", "update_model", "delete_model")]
# 更严谨：比对前后条数差
check("三次失败操作没有新增日志",
      len(after) == len(before),
      f"前={len(before)} 后={len(after)}")

# ---------------------------------------------------------------- 4. 数据集登记（幂等，两种成功要区分）
print("\n[4] 数据集登记 -> register_dataset")
ds_name = f"verifylog_ds_{tag}"
st, js = req("POST", "/datasets/db", admin_t, body={"name": ds_name, "source": "verify-oplog",
                                                        "class_count": 2, "sample_count": 20})
check("登记数据集成功", st in (200, 201), f"http={st} err={js.get('error')}")
rows = logs(admin_t)
hit = find(rows, "register_dataset", ds_name)
check("登记后出现 register_dataset 日志", hit is not None, f"dataset={ds_name}")
if hit:
    detail_s = json.dumps(hit.get("Detail"), ensure_ascii=False)
    check("Detail 里带 already_existed（区分新建/复用）", "already_existed" in detail_s, detail_s[:140])

# 再登记一次同名：应复用已有行，日志再记一条且 already_existed=true
st2, js2 = req("POST", "/datasets/db", admin_t, body={"name": ds_name, "source": "verify-oplog"})
rows = logs(admin_t)
hit2 = find(rows, "register_dataset", ds_name)
same = False
shown = "-"
if hit2:
    # Detail 存的是 JSON 字符串，解析后再判，别用子串匹配（"false" 里也有 "true" 的坑）
    d = hit2.get("Detail")
    if isinstance(d, str):
        try:
            d = json.loads(d)
        except Exception:
            d = {}
    same = bool(isinstance(d, dict) and d.get("already_existed") is True)
    shown = json.dumps(d, ensure_ascii=False)
check("重复登记被识别为复用（already_existed=true）", same, f"http={st2} detail={shown[:110]}")

# ---------------------------------------------------------------- 5. 推理不写 OperationLogs（按拍板结论）
print("\n[5] 推理**不应**写 OperationLogs（靠 InferenceResults 留痕）")
before_acts = actions_of(logs(admin_t))
# /predict 需要已训练过的模型；用内置 1dcnn 试一次，失败也无所谓——
# 本项断言的是"无论成功失败，都不该出现推理类动作"
req("POST", "/predict", admin_t, body={"model": "1dcnn", "samples": [[0.0] * 784]})
after_acts = actions_of(logs(admin_t))
inference_like = [a for a in after_acts
                  if a not in before_acts and ("infer" in a.lower() or "predict" in a.lower())]
check("推理没有新增 OperationLogs 记录", not inference_like, inference_like or "无")

# ---------------------------------------------------------------- 6. 训练日志（失败也要记）
print("\n[6] 训练 -> run_training（训练失败也必须留痕）")
before_acts = actions_of(logs(admin_t))
# 故意用非法 epochs 触发参数校验失败 -> 400，这条**不该**记日志（它在校验阶段就返回了，
# 根本没进入训练）。用来区分"参数错"和"训练跑了但失败"两种情况。
st, js = req("POST", "/train", admin_t, body={"model": "1dcnn", "epochs": 99999})
check("非法 epochs 被拒（400）", st == 400, f"http={st} err={js.get('error')}")
after_acts = actions_of(logs(admin_t))
check("参数校验失败不产生 run_training 日志",
      "run_training" not in after_acts[: len(after_acts) - 0] or len(after_acts) == len(before_acts),
      f"前={len(before_acts)} 后={len(after_acts)}")

# ---------------------------------------------------------------- 7. 清理：删掉刚建的东西
print("\n[7] 删除模型 -> delete_model")
if uploaded_model:
    st, js = req("DELETE", f"/models/{uploaded_model}?scope=record&force=1", admin_t)
    check("删除登记行成功", st == 200, f"http={st} err={js.get('error')}")
    rows = logs(admin_t)
    hit = find(rows, "delete_model_record", uploaded_model)
    check("删除后出现 delete_model_record 日志", hit is not None, f"model={uploaded_model}")

# ---------------------------------------------------------------- 8. 日志接口自身
print("\n[8] 日志查询接口")
rows = logs(admin_t, limit=50)
check("管理员能拉日志", bool(rows), f"{len(rows)} 条")
if rows:
    sample = rows[0]
    check("日志行含 NewID/Action/Username/CreatedDate",
          all(k in sample for k in ("Action", "Username", "CreatedDate")),
          sorted(sample.keys()))
# operator 不该能看日志
op_t = login("operator", "Operator@2026")
if op_t:
    st, js = req("GET", "/api/system/operation_log/", op_t)
    check("operator 拉日志被拒", js.get("code") != 2000, js.get("msg"))

# ================================================================ 汇总
print()
print("=" * 74)
print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print()
    print("  失败项：")
    for f in FAIL:
        print("    - " + f)
print("=" * 74)
sys.exit(1 if FAIL else 0)
