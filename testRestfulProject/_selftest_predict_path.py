# -*- coding: utf-8 -*-
"""推理链路自测：POST /predict 的路径解析、安全闸门、落库回执。

⚠️ 说明：这个文件在原磁盘上被误删过一次，而它当时**没有被 git 跟踪**（.gitignore 里
`testRestfulProject/_*.py` 把它一起忽略了），所以无法从 git 恢复。这里是**按它原来的断言重建**的
等价版本，不是原件。重建后已经强制入库（`.gitignore` 也加了例外），不会再丢。

覆盖：
  ① 文件口径推理（path=）能跑通、返回结构完整、窗口数对得上
  ② 默认 write_db=true 不炸（库里没有训练锚点时只给 warning，不 500）
  ③ 安全闸门回归：工作区外的绝对路径/越界相对路径必须被拒，且**文案不变**
  ④ project_dir 口径的绝对路径仍然可读（训练脚本的老写法，不能因为加严而误伤）
  ⑤ 表格数据集目录为空时不报错
"""
import sys
from pathlib import Path

sys.path.insert(0, r"D:\22project\testRestfulProject")

from main import app   # noqa: E402

client = app.test_client()
WORKSPACE = r"D:\22project"
FAULT = "testRestfulProject/1DCNN/0HP/48k_Drive_End_IR007_0_109.mat"
fails = []

# ⚠️ 2026-09-18 并入工厂线（发布 / 鉴权）之后，写接口全部加了 @require_perm：
#    不带令牌一律回 {"error": "请先登录"}。这里用 admin 拿一个真令牌，
#    再塞进 environ_base —— 它对**每个**请求都生效，下面 8 处调用不用各自加 headers。
#    种子账号是幂等的（Users 表非空时什么都不做），不会重复建号。
from model_service import auth as _auth                                # noqa: E402
from model_service.db import database as _db                           # noqa: E402

try:
    _db.bootstrap_users(_auth.hash_password("Admin@2026"), with_samples=True)
except Exception as _exc:                                              # noqa: BLE001
    print(f"（种子账号跳过：{type(_exc).__name__}: {_exc}）")
_login = client.post("/api/login/",
                     json={"username": "admin", "password": "Admin@2026"}).get_json() or {}
_TOKEN = (_login.get("data") or {}).get("access") or ""
if not _TOKEN:
    sys.exit(f"admin 登录失败，后续用例无法继续：{_login}")
client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {_TOKEN}"


def check(label, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}{('  — ' + str(detail)) if detail else ''}")
    if not cond:
        fails.append(label)


print("=== 1) 文件口径推理（path=）===")
r = client.post("/predict", json={"model": "1dcnn", "path": FAULT, "limit": 2, "write_db": False})
b = r.get_json() or {}
print(f"   status={r.status_code} keys={sorted(b)}")
check("POST /predict 返回 200", r.status_code == 200, r.status_code)
check("返回 2 条预测", b.get("count") == 2, b.get("count"))
check("响应里没有 version 字段（版本号已去掉）", "version" not in b)
check("第一条预测带类别/置信度/top_k",
      all(k in (b.get("predictions") or [{}])[0] for k in ("predicted_class", "predicted_label",
                                                          "confidence", "top_k")))
check("input 里回报了来源文件与点数",
      (b.get("input") or {}).get("source") == "path" and (b.get("input") or {}).get("signal_points") > 0,
      str(b.get("input"))[:120])
check("出了两张图且无 figures_error",
      len(b.get("figures") or []) == 2 and not b.get("figures_error"), b.get("figures_error"))

print("\n=== 2) 默认 write_db=true（不关库）===")
r = client.post("/predict", json={"model": "1dcnn", "path": FAULT, "limit": 2})
b = r.get_json() or {}
db = b.get("db") or {}
print(f"   status={r.status_code} db={db} warning={b.get('warning')}")
check("默认落库调用仍是 200（库不可用/无锚点也只给 warning，不 500）", r.status_code == 200, r.status_code)
check("落库结果有明确回执（written 字段存在）", "written" in db, db)
if db.get("written") is False:
    check("没写库时响应里带了 warning 说明原因", bool(b.get("warning")), b.get("warning"))

print("\n=== 3) 安全闸门：越界必须被拒且文案不变 ===")
r = client.post("/predict", json={"model": "1dcnn", "path": r"D:\Windows\win.ini", "write_db": False})
b = r.get_json() or {}
check("工作区外的绝对路径被拒（400）", r.status_code == 400, f"{r.status_code} {b}")
check("拒绝文案与 _guard_path 一致",
      "只允许读取工作区内的文件" in str(b.get("error")), b.get("error"))

r = client.post("/predict", json={"model": "1dcnn", "path": "../../secret.csv", "write_db": False})
check("越界相对路径仍被拒（400）", r.status_code == 400, r.get_json())

print("\n=== 4) project_dir 口径的绝对路径仍可读（老写法，不能误伤）===")
old_style = str(Path(WORKSPACE) / FAULT)
r = client.post("/predict", json={"model": "1dcnn", "path": old_style, "limit": 2, "write_db": False})
check("D:\\22project\\testRestfulProject\\... 这种写法仍能推理",
      r.status_code == 200, f"{r.status_code} {str(r.get_json())[:140]}")

print("\n=== 5) 内联 samples 与长度校验 ===")
# ⚠️ 不要写死 784：产物里的 input_len 取决于模型是怎么训的（当前 1dcnn 是 848），
#    从响应里读实际值再构造"长度不符"的样本，测试才不会因为换模型而假失败。
r = client.post("/predict", json={"model": "1dcnn", "path": FAULT, "limit": 1, "write_db": False})
want = (r.get_json() or {}).get("input_len")
print(f"   该产物的 input_len = {want}")
r = client.post("/predict", json={"model": "1dcnn", "samples": [[0.1, 0.2]], "write_db": False})
b = r.get_json() or {}
check("长度不符 → 400 且报出要求的长度",
      r.status_code == 400 and str(want) in str(b.get("error")), b.get("error"))
r = client.post("/predict", json={"model": "1dcnn", "samples": [], "write_db": False})
check("空样本 → 400", r.status_code == 400, r.get_json())
r = client.post("/predict", json={"model": "1dcnn", "samples": [[0.1] * int(want)], "write_db": False})
check("长度正确 → 200", r.status_code == 200, f"{r.status_code} {str(r.get_json())[:100]}")

print("\n=== 6) 表格数据集目录为空时不报错 ===")
up = Path(WORKSPACE) / "testRestfulProject" / "data" / "datasets"
tables = [p for p in up.iterdir() if p.suffix.lower() in (".csv", ".txt", ".xls", ".xlsx", ".xlsm")] \
    if up.is_dir() else []
if tables:
    print(f"   有 {len(tables)} 个表格文件，跳过这条")
else:
    r = client.get("/datasets")
    check("upload_dir 为空时 /datasets 仍返回 200", r.status_code == 200, r.status_code)

print()
if fails:
    print(f"失败 {len(fails)} 项：")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("全部通过 ✅")
