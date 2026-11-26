from __future__ import annotations
import os
from pathlib import Path
from flask import Flask, jsonify, redirect, request, send_from_directory

from app import seed
from app.services import 会话, 入队, 投递, 死信, 重试, 互证, 端点, 夹具, 说明, 签名目录, 抖动

_STATIC = Path(__file__).resolve().parent / "static"


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(_STATIC), static_url_path="")
    app.secret_key = os.environ.get("密钥", "hook-lab-dev")

    @app.before_request
    def _gate():
        if request.path.startswith("/api/") and request.path not in ("/api/登录",):
            if not 会话.已登录():
                return jsonify({"错误": "未登录"}), 401
        return None

    @app.route("/login")
    def 登录页():
        return send_from_directory(_STATIC, "login.html")

    @app.route("/")
    def 首页():
        return send_from_directory(_STATIC, "index.html")

    @app.route("/<path:name>")
    def 静态页(name):
        p = _STATIC / name
        if p.is_file():
            return send_from_directory(_STATIC, name)
        return redirect("/")

    @app.post("/api/登录")
    def api_登录():
        body = request.get_json(force=True, silent=True) or {}
        账号 = str(body.get("账号") or body.get("user") or "")
        密码 = str(body.get("密码") or body.get("password") or "")
        if 会话.校验登录(账号, 密码):
            会话.写入会话(账号)
            return jsonify({"ok": True, "用户": 账号})
        return jsonify({"ok": False, "错误": "账号或密码不对"}), 401

    @app.post("/api/登出")
    def api_登出():
        会话.登出()
        return jsonify({"ok": True})

    @app.get("/api/概览")
    def api_概览():
        return jsonify(签名目录.概览())

    @app.get("/api/仓情")
    def api_仓情():
        return jsonify(说明.仓情())

    @app.get("/api/签名规")
    def api_签名规_get():
        return jsonify(签名目录.签名规())

    @app.post("/api/签名规")
    def api_签名规_post():
        body = request.get_json(force=True, silent=True) or {}
        try:
            # 抖动界校验：保存前先定界，越界样本下一次等待立刻按新界钳住
            if "抖动下界毫秒" in body or "抖动上界毫秒" in body:
                界 = 抖动.取界()
                下 = body.get("抖动下界毫秒", 界["下界毫秒"])
                上 = body.get("抖动上界毫秒", 界["上界毫秒"])
                抖动.定界(下, 上)
                body = {k: v for k, v in body.items()
                        if k not in ("抖动下界毫秒", "抖动上界毫秒")}
            out = 签名目录.改签名规(body) if body else 签名目录.签名规()
            out["抖动界"] = 抖动.取界()
            return jsonify(out)
        except ValueError as e:
            return jsonify({"错误": str(e)}), 400

    @app.get("/api/事件")
    def api_事件():
        return jsonify(签名目录.事件列表())

    @app.get("/api/事件/<eid>")
    def api_事件一条(eid):
        row = 签名目录.事件一条(eid)
        if not row:
            return jsonify({"错误": "无此事件"}), 404
        return jsonify(row)

    @app.post("/api/事件/入队")
    def api_入队():
        body = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(入队.建事件(body))
        except ValueError as e:
            return jsonify({"错误": str(e)}), 400

    @app.get("/api/投递")
    def api_投递列表():
        return jsonify(签名目录.投递列表())

    @app.post("/api/投递")
    def api_投递():
        body = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(投递.投递一次(body["事件号"], bool(body.get("强制失败"))))
        except (KeyError, ValueError) as e:
            return jsonify({"错误": str(e)}), 400

    @app.post("/api/投递/批量重试")
    def api_批量重试():
        return jsonify(重试.批量重试待投())

    @app.get("/api/抖动界")
    def api_抖动界():
        return jsonify(抖动.取界())

    @app.get("/api/抖动账册")
    def api_抖动账册():
        return jsonify({"界": 抖动.取界(), "账册": 抖动.账册列表()})

    @app.post("/api/抖动试算")
    def api_抖动试算():
        body = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(抖动.试算(body.get("抖动毫秒")))
        except ValueError as e:
            return jsonify({"错误": str(e)}), 400

    @app.get("/api/重试排程")
    def api_重试排程():
        return jsonify({"界": 抖动.取界(), "排程": 重试.排程列表()})

    @app.post("/api/重试排程")
    def api_重试排程_post():
        body = request.get_json(force=True, silent=True) or {}
        try:
            事件号 = str(body["事件号"])
            if "抖动毫秒" in body:
                return jsonify(重试.排程重试(
                    事件号, body["抖动毫秒"], str(body.get("调度方") or "")
                ))
            return jsonify(重试.建待排(事件号))
        except KeyError:
            return jsonify({"错误": "缺事件号"}), 400
        except ValueError as e:
            return jsonify({"错误": str(e)}), 400
        except 重试.排程争用 as e:
            return jsonify({"错误": str(e), "争用": True}), 409

    @app.get("/api/死信")
    def api_死信():
        rows = 签名目录.死信列表()
        # 死信列表要看见上下界和实际等待
        for r in rows:
            if not r.get("抖动下界毫秒") and not r.get("抖动上界毫秒"):
                界 = 抖动.取界()
                r["抖动下界毫秒"] = 界["下界毫秒"]
                r["抖动上界毫秒"] = 界["上界毫秒"]
            r["界内"] = bool(
                (r.get("实际等待毫秒") or 0) == 0 or
                r["抖动下界毫秒"] <= (r.get("实际等待毫秒") or 0) <= r["抖动上界毫秒"]
            )
        return jsonify(rows)

    @app.post("/api/死信/重投")
    def api_死信重投():
        body = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(死信.重投(body["事件号"]))
        except (KeyError, ValueError) as e:
            return jsonify({"错误": str(e)}), 400

    @app.post("/api/死信/作废")
    def api_死信作废():
        body = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(死信.作废(body["事件号"], body.get("原因", "人工作废")))
        except (KeyError, ValueError) as e:
            return jsonify({"错误": str(e)}), 400

    @app.get("/api/端点")
    def api_端点():
        return jsonify(签名目录.端点列表())

    @app.post("/api/端点")
    def api_端点登记():
        body = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(端点.登记(body))
        except ValueError as e:
            return jsonify({"错误": str(e)}), 400

    @app.post("/api/端点/启用")
    def api_端点启用():
        body = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(端点.改启用(body["端点键"], bool(body.get("启用"))))
        except (KeyError, ValueError) as e:
            return jsonify({"错误": str(e)}), 400

    @app.get("/api/互证")
    def api_互证列表():
        return jsonify(签名目录.互证列表())

    @app.post("/api/互证/跑")
    def api_互证跑():
        return jsonify(互证.跑一次())

    @app.get("/api/夹具")
    def api_夹具():
        return jsonify(夹具.列表())

    @app.post("/api/夹具入队/<name>")
    def api_夹具入队(name):
        try:
            体 = 夹具.读取(name)
            out = [入队.建事件(item) for item in 体.get("事件", [])]
            return jsonify({"入队": out})
        except FileNotFoundError:
            return jsonify({"错误": name}), 404
        except ValueError as e:
            return jsonify({"错误": str(e)}), 400

    @app.get("/api/空桩")
    def api_空桩():
        root = Path(__file__).resolve().parent / "modules"
        out = []
        if root.is_dir():
            for p in sorted(root.iterdir()):
                if p.is_dir() and (p / "__init__.py").is_file():
                    out.append(p.name)
        return jsonify({"空桩": out, "条数": len(out)})

    with app.app_context():
        seed.初始化库()
    return app
