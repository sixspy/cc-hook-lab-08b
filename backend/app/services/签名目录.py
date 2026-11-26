from __future__ import annotations
from app.db import 连接
from app.services import 校验, 抖动


def _重试详情(conn, 事件号: str, 死信行) -> dict:
    """重试策略连带的等待详情：上下界与本次实际等待。"""
    界 = 抖动.取界()
    排 = conn.execute("SELECT * FROM 重试排程 WHERE 事件号=?", (事件号,)).fetchone()
    下 = int(排["下界毫秒"]) if 排 else 界["下界毫秒"]
    上 = int(排["上界毫秒"]) if 排 else 界["上界毫秒"]
    原始 = int(排["原始抖动毫秒"]) if 排 else 0
    等待 = int(排["等待毫秒"]) if 排 else 下
    if 死信行 and int(死信行["实际等待毫秒"] or 0) > 0:
        下 = int(死信行["抖动下界毫秒"] or 下)
        上 = int(死信行["抖动上界毫秒"] or 上)
        等待 = int(死信行["实际等待毫秒"])
    return {
        "下界毫秒": 下,
        "上界毫秒": 上,
        "原始抖动毫秒": 原始,
        "实际等待毫秒": 等待,
        "是否钳住": bool(等待 != 原始) if 排 else False,
        "是否界内": bool(下 <= 等待 <= 上),
        "文案": 抖动.文案(等待 != 原始 if 排 else False, 等待, 下, 上, 原始),
    }


def 签名规() -> dict:
    conn = 连接()
    try:
        rows = conn.execute("SELECT 键,值 FROM 签名规").fetchall()
        return {r["键"]: r["值"] for r in rows}
    finally:
        conn.close()


def 改签名规(body: dict) -> dict:
    conn = 连接()
    try:
        for k, v in body.items():
            键 = 校验.非空("键", k)
            值 = 校验.非空("值", v)
            conn.execute(
                "INSERT INTO 签名规(键,值) VALUES (?,?) ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
                (键, 值),
            )
        conn.commit()
        return 签名规()
    finally:
        conn.close()


def 概览() -> dict:
    conn = 连接()
    try:
        def c(sql):
            return conn.execute(sql).fetchone()[0]
        return {
            "端点数": c("SELECT COUNT(*) FROM 投递端点"),
            "启用端点": c("SELECT COUNT(*) FROM 投递端点 WHERE 启用=1"),
            "事件总数": c("SELECT COUNT(*) FROM 事件"),
            "待投": c("SELECT COUNT(*) FROM 事件 WHERE 状态='待投'"),
            "投递中": c("SELECT COUNT(*) FROM 事件 WHERE 状态='投递中'"),
            "已投递": c("SELECT COUNT(*) FROM 事件 WHERE 状态='已投递'"),
            "死信": c("SELECT COUNT(*) FROM 事件 WHERE 状态='死信'"),
            "尝试数": c("SELECT COUNT(*) FROM 投递尝试"),
            "死信匣": c("SELECT COUNT(*) FROM 死信 WHERE 状态='待处置'"),
            "抖动下界毫秒": 抖动.取界()["下界毫秒"],
            "抖动上界毫秒": 抖动.取界()["上界毫秒"],
            "签名规": 签名规(),
        }
    finally:
        conn.close()


def 事件列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 事件 ORDER BY 入队时 DESC").fetchall()]
    finally:
        conn.close()


def 事件一条(事件号: str) -> dict | None:
    conn = 连接()
    try:
        row = conn.execute("SELECT * FROM 事件 WHERE 事件号=?", (事件号,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["尝试"] = [dict(x) for x in conn.execute(
            "SELECT * FROM 投递尝试 WHERE 事件号=? ORDER BY 投递时 DESC", (事件号,)
        ).fetchall()]
        dl = conn.execute("SELECT * FROM 死信 WHERE 事件号=?", (事件号,)).fetchone()
        d["死信"] = dict(dl) if dl else None
        # 重试等待详情：上下界与实际等待，界内/越界已钳住
        d["重试详情"] = _重试详情(conn, 事件号, d["死信"])
        return d
    finally:
        conn.close()


def 投递列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM 投递尝试 ORDER BY 投递时 DESC LIMIT 200"
        ).fetchall()]
    finally:
        conn.close()


def 死信列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 死信 ORDER BY 入匣时 DESC").fetchall()]
    finally:
        conn.close()


def 端点列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 投递端点 ORDER BY 端点键").fetchall()]
    finally:
        conn.close()


def 互证列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 互证批次 ORDER BY 批次号 DESC LIMIT 50").fetchall()]
    finally:
        conn.close()
