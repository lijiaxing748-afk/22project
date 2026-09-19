# -*- coding: utf-8 -*-
"""登录页人机校验（验证码）：生成图形码 + 校验答案，**不需要 session / 数据库**。

为什么自己写而不是拉个 captcha 库：
    本平台的令牌是**无状态**的（serverside 不存会话，见 auth.issue_token），所以没有
    session / redis 可以放"这道题的答案"。这里的做法是把答案**签进一个带时限的 key**
    里交给前端，登录时验签 + 比对 —— 服务端一个字节状态都不用存，重启也不影响。

为什么需要它：
    登录接口没有失败次数限制，弱口令可以在线慢慢爆破。开了验证码之后，每次尝试都要
    先拿到一张新图，爆破成本立刻上一个量级。

开关：
    `MODEL_CAPTCHA=1` 打开（config.captcha_enabled）。**默认关闭**，关闭时
    `/api/captcha/` 回 `captcha_state=false`、登录页不显示输入框、`login()` 也不校验，
    与改造前的行为完全一致（不会因为加了这道校验把现有用户挡在门外）。

⚠️ 字段名的坑（这次修的就是它）：前端 `account.vue` 读的是 `ret.data.image_base`，
    而改造前后端返回的是 `image_base64` —— 名字对不上，一旦打开开关，验证码图就是空白，
    用户看不到码也就登不进来。现在统一成 `image_base`（见 dvadmin.captcha()）。
"""
from __future__ import annotations

import base64
import io
import secrets
import string

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import config

# 4 位：够挡脚本爆破，又不至于让人看不清。去掉 0/O/1/I/L 这些易混字符。
_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "01OIL")
_LENGTH = 4
# 一道题的有效期（秒）。给足"看错重输一次"的时间，又不至于被无限复用。
_TTL_SECONDS = 300
_SALT = "model-platform-captcha"
_IMG_W, _IMG_H = 132, 46


def _pillow_ok() -> bool:
    """能不能画图。⚠️ 这是"验证码到底生不生效"的**唯一判据**，登录与发图两边都问它，
    避免出现"发图失败但登录仍要求验证码"——那样用户会被彻底锁在门外。"""
    try:
        import PIL  # noqa: F401
        return True
    except Exception:
        return False


def active() -> bool:
    """本次进程里验证码是否真的生效（开关打开 **且** 画得出图）。"""
    return bool(config.captcha_enabled) and _pillow_ok()


def _serializer() -> URLSafeTimedSerializer:
    """用与令牌同一个密钥签名 —— 密钥换了，旧验证码自动失效（符合预期）。"""
    return URLSafeTimedSerializer(config.secret_key, salt=_SALT)


def _render(code: str) -> str:
    """把验证码画成 PNG，返回 `data:image/png;base64,...`（前端直接塞进 <img :src>）。

    只在 `active()` 为真时被调用；画不出来就让异常传出去，由调用方决定降级策略。
    """
    from PIL import Image, ImageDraw, ImageFont

    rng = secrets.SystemRandom()
    image = Image.new("RGB", (_IMG_W, _IMG_H), (245, 247, 250))
    draw = ImageDraw.Draw(image)

    # 背景噪点：让它不容易被阈值二值化后直接切出字符
    for _ in range(220):
        draw.point((rng.randrange(_IMG_W), rng.randrange(_IMG_H)),
                   fill=(rng.randrange(140, 210), rng.randrange(140, 210), rng.randrange(140, 210)))
    # 干扰线：颜色偏浅，别把字符糊掉
    for _ in range(4):
        draw.line(
            [(rng.randrange(_IMG_W), rng.randrange(_IMG_H)),
             (rng.randrange(_IMG_W), rng.randrange(_IMG_H))],
            fill=(rng.randrange(150, 200), rng.randrange(150, 200), rng.randrange(150, 200)), width=1)

    font = None
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(name, 30)
            break
        except Exception:
            continue
    if font is None:
        # 没有任何 TTF：用 Pillow 自带位图字体，字小但**仍然能看**
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

    step = _IMG_W // (_LENGTH + 1)
    for index, char in enumerate(code):
        x = step * (index + 1) - 10
        y = rng.randrange(4, 14)
        color = (rng.randrange(30, 90), rng.randrange(30, 90), rng.randrange(90, 150))
        try:
            draw.text((x, y), char, font=font, fill=color)
        except Exception:
            draw.text((x, y), char, fill=color)

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def new_challenge() -> tuple[str, str, str]:
    """生成一道题：返回 `(明文答案, 图片 data-uri, 签名 key)`。

    ⚠️ 明文答案**只**用于画图，绝不回给前端（返回体里只有图 + key）。
    只在 `active()` 为真时调用；画图抛异常由调用方兜（见 dvadmin.captcha()）。
    """
    code = "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))
    return code, _render(code), _serializer().dumps({"c": code})


def verify(body: dict) -> tuple[bool, str]:
    """校验前端回传的 `captcha` + `captchaKey`。返回 `(是否通过, 不通过的原因)`。

    比对**忽略大小写**：图里画的是大写，但不该要求用户必须按着大小写输。
    """
    answer = str(body.get("captcha") or "").strip().upper()
    key = str(body.get("captchaKey") or "").strip()
    if not key:
        return False, "验证码已失效，请点击图片刷新后重试"
    if not answer:
        return False, "请填写验证码"
    try:
        payload = _serializer().loads(key, max_age=_TTL_SECONDS)
    except SignatureExpired:
        return False, "验证码已过期，请点击图片刷新后重试"
    except BadSignature:
        # 签名不对 = 伪造的 key 或换了 MODEL_SECRET_KEY（重启后密钥变了就会这样）
        return False, "验证码无效，请点击图片刷新后重试"
    if not isinstance(payload, dict) or answer != str(payload.get("c") or "").upper():
        return False, "验证码错误，请重新输入"
    return True, ""
