from __future__ import annotations
from app.db import 连接
from app.services.时间 import 此刻
from app.services import 抖动


def _抖动对账(conn) -> dict:
    """核对旁路账册：越界影子（原始越界却标成界内合法）必须揪出。

    越界影子 = 原始抖动毫秒落在界外，但 是否越界=0 且 处置≠拒绝回刷。
    另外核对点火队列的等待毫秒确有落在界内。
    """
    界 = 抖动.取界()
    账 = conn.execute("SELECT * FROM 抖动账册").fetchall()
    影子 = 0
    队列出界 = 0
    for r in 账:
        下, 上 = int(r["下界毫秒"]), int(r["上界毫秒"])
        if 抖动.越界(int(r["原始抖动毫秒"]), 下, 上):
            if int(r["是否越界"]) != 1 or str(r["处置"]) != "拒绝回刷":
                影子 += 1
        if not (下 <= int(r["钳后等待毫秒"]) <= 上):
            影子 += 1
    for r in conn.execute("SELECT 下界毫秒,上界毫秒,等待毫秒 FROM 重试排程").fetchall():
        if not (int(r["下界毫秒"]) <= int(r["等待毫秒"]) <= int(r["上界毫秒"])):
            队列出界 += 1
    对齐 = (影子 == 0 and 队列出界 == 0)
    return {
        "抖动对齐": 对齐,
        "越界影子数": 影子,
        "队列出界数": 队列出界,
        "账册条数": len(账),
        "下界毫秒": 界["下界毫秒"],
        "上界毫秒": 界["上界毫秒"],
    }


def 跑一次() -> dict:
    t = 此刻()
    conn = 连接()
    try:
        总 = conn.execute("SELECT COUNT(*) AS c FROM 事件").fetchone()["c"]
        已 = conn.execute("SELECT COUNT(*) AS c FROM 事件 WHERE 状态='已投递'").fetchone()["c"]
        死 = conn.execute("SELECT COUNT(*) AS c FROM 事件 WHERE 状态='死信'").fetchone()["c"]
        待 = conn.execute("SELECT COUNT(*) AS c FROM 事件 WHERE 状态 IN ('待投','投递中')").fetchone()["c"]
        匣 = conn.execute("SELECT COUNT(*) AS c FROM 死信 WHERE 状态='待处置'").fetchone()["c"]
        抖动报 = _抖动对账(conn)
        对齐 = 1 if (死 == 匣 and 已 + 死 + 待 <= 总) else 0
        抖动对齐 = 1 if 抖动报["抖动对齐"] else 0
        全对齐 = 1 if (对齐 and 抖动对齐) else 0
        if 抖动对齐 != 1:
            说明 = f"抖动对账不平：越界影子{抖动报['越界影子数']}条，点火队列出界{抖动报['队列出界数']}条"
        elif 对齐:
            说明 = "事件/投递/死信口径对齐；抖动账册与点火队列均落在界内"
        else:
            说明 = "死信匣与事件死信数不一致或水位异常"
        conn.execute(
            "INSERT INTO 互证批次(时刻,事件总数,已投递数,死信数,待投数,是否对齐,说明,"
            "抖动对齐,越界影子数) VALUES (?,?,?,?,?,?,?,?,?)",
            (t, 总, 已, 死, 待, 对齐, 说明, 抖动对齐, 抖动报["越界影子数"]),
        )
        conn.commit()
        return {
            "时刻": t,
            "事件总数": 总,
            "已投递数": 已,
            "死信数": 死,
            "待投数": 待,
            "死信匣待处置": 匣,
            "是否对齐": bool(对齐),
            "抖动对齐": bool(抖动对齐),
            "越界影子数": 抖动报["越界影子数"],
            "是否全部对齐": bool(全对齐),
            "说明": 说明,
            "明细": {"总": 总, "已": 已, "死": 死, "待": 待, "匣": 匣},
            "抖动明细": 抖动报,
        }
    finally:
        conn.close()
