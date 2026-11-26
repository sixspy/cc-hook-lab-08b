"""抖动工程形态：旁路账册 + 拒回刷。

等待样本先经 ``钳`` 钳进 [下界毫秒, 上界毫秒]；越界样本收进旁路账册
（``抖动账册``），处置记为 ``拒绝回刷``，点火队列只接收钳后的等待。
上下界持久化在 ``签名规``，保存即生效，下一次排程立刻按新界计算。
"""
from __future__ import annotations
from app.db import 连接
from app.services.时间 import 此刻

默认下界毫秒 = 800
默认上界毫秒 = 3000


def _正整数(名: str, 值) -> int:
    try:
        n = int(值)
    except (TypeError, ValueError):
        raise ValueError(f"{名}必须是整数毫秒")
    if n < 0:
        raise ValueError(f"{名}不得为负")
    return n


def 取界() -> dict:
    conn = 连接()
    try:
        规 = {r["键"]: r["值"] for r in conn.execute("SELECT 键,值 FROM 签名规").fetchall()}
    finally:
        conn.close()
    try:
        下 = int(规.get("抖动下界毫秒", 默认下界毫秒))
    except (TypeError, ValueError):
        下 = 默认下界毫秒
    try:
        上 = int(规.get("抖动上界毫秒", 默认上界毫秒))
    except (TypeError, ValueError):
        上 = 默认上界毫秒
    if 下 < 0 or 上 < 0 or 上 < 下:
        return {"下界毫秒": 默认下界毫秒, "上界毫秒": 默认上界毫秒}
    return {"下界毫秒": 下, "上界毫秒": 上}


def 定界(下界毫秒, 上界毫秒) -> dict:
    下 = _正整数("抖动下界毫秒", 下界毫秒)
    上 = _正整数("抖动上界毫秒", 上界毫秒)
    if 上 < 下:
        raise ValueError("抖动上界不得小于下界")
    conn = 连接()
    try:
        for k, v in (("抖动下界毫秒", 下), ("抖动上界毫秒", 上)):
            conn.execute(
                "INSERT INTO 签名规(键,值) VALUES (?,?) ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
                (k, str(v)),
            )
        conn.execute("INSERT INTO 操作留痕(时刻,操作,事件号,详情) VALUES (?,?,?,?)",
                     (此刻(), "定抖动界", "", f"{下}-{上}ms"))
        conn.commit()
    finally:
        conn.close()
    return {"下界毫秒": 下, "上界毫秒": 上}


def 钳(样本毫秒, 下界毫秒: int | None = None, 上界毫秒: int | None = None) -> tuple[int, bool]:
    """把样本钳进界内。返回 (等待毫秒, 是否钳住)。

    负值、低于下界、高于上界一律钳住；界内样本原样返回。
    """
    界 = 取界()
    下 = 界["下界毫秒"] if 下界毫秒 is None else int(下界毫秒)
    上 = 界["上界毫秒"] if 上界毫秒 is None else int(上界毫秒)
    try:
        样本 = int(样本毫秒)
    except (TypeError, ValueError):
        raise ValueError("抖动样本必须是整数毫秒")
    等待 = min(max(样本, 下), 上)
    return 等待, (等待 != 样本)


def 越界(样本毫秒, 下界毫秒: int, 上界毫秒: int) -> bool:
    try:
        样本 = int(样本毫秒)
    except (TypeError, ValueError):
        return True
    return 样本 < 下界毫秒 or 样本 > 上界毫秒


def 试算(样本毫秒) -> dict:
    """只算不排：不改点火队列、不写账册。页面用来看本次钳后等待。"""
    界 = 取界()
    下, 上 = 界["下界毫秒"], 界["上界毫秒"]
    等待, 是否钳住 = 钳(样本毫秒, 下, 上)
    越 = 越界(样本毫秒, 下, 上)
    return {
        "下界毫秒": 下,
        "上界毫秒": 上,
        "原始抖动毫秒": int(样本毫秒),
        "等待毫秒": 等待,
        "是否钳住": bool(是否钳住),
        "是否越界": bool(越),
        "处置": "拒绝回刷" if 越 else "采纳",
        "文案": 文案(是否钳住, 等待, 下, 上, 样本毫秒),
    }


def 记入账册(事件号: str, 调度方: str, 下界毫秒: int, 上界毫秒: int,
             原始抖动毫秒, 钳后等待毫秒: int, 是否越界: bool, 处置: str) -> dict:
    conn = 连接()
    try:
        conn.execute(
            "INSERT INTO 抖动账册(事件号,调度方,下界毫秒,上界毫秒,原始抖动毫秒,"
            "钳后等待毫秒,是否越界,处置,时刻) VALUES (?,?,?,?,?,?,?,?,?)",
            (事件号, 调度方, 下界毫秒, 上界毫秒, int(原始抖动毫秒),
             钳后等待毫秒, 1 if 是否越界 else 0, 处置, 此刻()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM 抖动账册 ORDER BY 编号 DESC LIMIT 1").fetchone()
        return dict(row)
    finally:
        conn.close()


def 账册列表(限制: int = 200) -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM 抖动账册 ORDER BY 编号 DESC LIMIT ?", (限制,)
        ).fetchall()]
    finally:
        conn.close()


def 文案(是否钳住: bool, 等待毫秒: int, 下界毫秒: int, 上界毫秒: int, 原始抖动毫秒) -> str:
    if 是否钳住:
        return f"抖动越界已钳住：{原始抖动毫秒}ms → {等待毫秒}ms（界 {下界毫秒}-{上界毫秒}ms）"
    return f"等待落在界内：{等待毫秒}ms（界 {下界毫秒}-{上界毫秒}ms）"
