from __future__ import annotations
from app.db import 连接
from app.services import 投递, 签名目录, 抖动
from app.services.时间 import 此刻


class 排程争用(Exception):
    """两路调度同时认领同一条的下次点火时刻；未抢到的一方必须报争用。"""


def 建待排(事件号: str) -> dict:
    """把事件放进点火队列（幂等）。已有排程不覆盖。"""
    界 = 抖动.取界()
    conn = 连接()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO 重试排程(事件号,调度方,排程版本,状态,下界毫秒,上界毫秒,"
            "原始抖动毫秒,等待毫秒,是否钳住,下次点火毫秒,排程时) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (事件号, "", 0, "待排", 界["下界毫秒"], 界["上界毫秒"], 0, 界["下界毫秒"], 0, 0, 此刻()),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM 重试排程 WHERE 事件号=?", (事件号,)).fetchone())
    finally:
        conn.close()


def 取排程(事件号: str) -> dict | None:
    conn = 连接()
    try:
        row = conn.execute("SELECT * FROM 重试排程 WHERE 事件号=?", (事件号,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def 排程列表() -> list:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM 重试排程 ORDER BY 排程时 DESC, 事件号"
        ).fetchall()]
    finally:
        conn.close()


def 排程重试(事件号: str, 抖动毫秒, 调度方: str = "") -> dict:
    """算出并认领下一次点火时刻。

    - 等待先钳进 [下界, 上界]，界外样本不提前开火。
    - 越界样本收进旁路账册，处置 ``拒绝回刷``；点火队列只收钳后等待。
    - 认领靠排程版本做原子比较交换：两路同时来只有一路成功，另一路报争用。
    """
    界 = 抖动.取界()
    下, 上 = 界["下界毫秒"], 界["上界毫秒"]
    等待, 是否钳住 = 抖动.钳(抖动毫秒, 下, 上)
    越界 = 抖动.越界(抖动毫秒, 下, 上)
    处置 = "拒绝回刷" if 越界 else "采纳"
    原文案 = 抖动.文案(是否钳住, 等待, 下, 上, 抖动毫秒)
    t = 此刻()

    conn = 连接()
    try:
        # 确保队列里有这一条（幂等），再读当前排程版本
        conn.execute(
            "INSERT OR IGNORE INTO 重试排程(事件号,调度方,排程版本,状态,下界毫秒,上界毫秒,"
            "原始抖动毫秒,等待毫秒,是否钳住,下次点火毫秒,排程时) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (事件号, "", 0, "待排", 下, 上, 0, 下, 0, 0, t),
        )
        conn.commit()
        行 = conn.execute("SELECT * FROM 重试排程 WHERE 事件号=?", (事件号,)).fetchone()
        if not 行:
            raise ValueError("无此排程")
        if str(行["状态"]) != "待排":
            conn.rollback()
            raise 排程争用(f"{事件号} 下次点火时刻已被另一路调度认领")
        版本 = int(行["排程版本"])
        新版本 = 版本 + 1
        # 原子认领：只有 待排 才能被改成 已排；两路同时来只有一路 rowcount=1
        cur = conn.execute(
            "UPDATE 重试排程 SET 调度方=?, 排程版本=?, 状态=?, 下界毫秒=?, 上界毫秒=?,"
            "原始抖动毫秒=?, 等待毫秒=?, 是否钳住=?, 下次点火毫秒=?, 排程时=? "
            "WHERE 事件号=? AND 排程版本=? AND 状态='待排'",
            (调度方, 新版本, "已排", 下, 上, int(抖动毫秒), 等待,
             1 if 是否钳住 else 0, t, t, 事件号, 版本),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise 排程争用(f"{事件号} 下次点火时刻已被另一路调度认领")
        conn.commit()
        新行 = dict(conn.execute("SELECT * FROM 重试排程 WHERE 事件号=?", (事件号,)).fetchone())
    finally:
        conn.close()

    # 账册：越界样本留档为拒绝回刷，界内样本采纳
    抖动.记入账册(事件号, 调度方, 下, 上, 抖动毫秒, 等待, 越界, 处置)

    return {
        "事件号": 事件号,
        "调度方": 调度方,
        "下界毫秒": 下,
        "上界毫秒": 上,
        "原始抖动毫秒": int(抖动毫秒),
        "等待毫秒": 等待,
        "是否钳住": bool(是否钳住),
        "是否越界": bool(越界),
        "处置": 处置,
        "排程版本": 新版本,
        "下次点火毫秒": t,
        "文案": 原文案,
    }


def 批量重试待投(限制: int = 20) -> dict:
    conn = 连接()
    try:
        rows = conn.execute(
            "SELECT 事件号 FROM 事件 WHERE 状态 IN ('待投','投递中') ORDER BY 入队时 LIMIT ?",
            (限制,),
        ).fetchall()
    finally:
        conn.close()
    outs = []
    for r in rows:
        try:
            outs.append(投递.投递一次(r["事件号"]))
        except ValueError as e:
            outs.append({"事件号": r["事件号"], "错误": str(e)})
    return {"条数": len(outs), "结果": outs, "签名规": 签名目录.签名规()}
