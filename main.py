from astrbot.api.all import *
from astrbot.api.event.filter import command
import json
from astrbot.api.message_components import At
import os
import logging
import random
from typing import Dict, List, Any

logger = logging.getLogger("MahjongPlugin")

# 数据存储路径
DATA_DIR = os.path.join("data", "plugins", "astrbot_mahjong_plugin")
os.makedirs(DATA_DIR, exist_ok=True)
DATA_FILE = os.path.join(DATA_DIR, "mahjong_data.json")
EVENT_DATA_FILE = os.path.join(DATA_DIR, "event_data.json")

@register("N_league", "Vege", "日麻对局记录插件", "2.1.0")
class MahjongPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.data = self._load_data()
        self.active_matches = {}
        # --- 活动场独立变量 ---
        self.event_data = self._load_event_data()
        self.event_matches = {}

    def _load_data(self) -> dict:
        if not os.path.exists(DATA_FILE):
            return {}
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载数据失败: {e}")
            return {}

    def _save_data(self):
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存数据失败: {e}")

    def _get_context_id(self, event: AstrMessageEvent) -> str:
        if hasattr(event, 'group_id') and event.group_id:
            return f"group_{event.group_id}"
        if hasattr(event, 'user_id') and event.user_id:
            return f"private_{event.user_id}"
        return "default_ctx"
        
    def _get_user_match(self, ctx_id: str, user_id: str):
        if ctx_id not in self.active_matches:
            return None, None
        for mid, match in self.active_matches[ctx_id].items():
            if user_id in match["players"]:
                return mid, match
        return None, None

    def _calculate_pt_custom(self, score: int, rank: int) -> float:
        uma_map = {1: 50.0, 2: 10.0, 3: -10.0, 4: -30.0}
        pt = (score - 30000) / 1000.0 + (uma_map.get(rank, 0) - (20.0 if rank == 1 else 0))
        final_uma = {1: 50.0, 2: 10.0, 3: -10.0, 4: -30.0}
        return round((score - 30000) / 1000.0 + final_uma[rank], 1)

    @command("mj_start", alias=["对局开始", "开房"])
    async def start_match(self, event: AstrMessageEvent):
        """开始一场新的对局，自动分配桌号"""
        ctx_id = self._get_context_id(event)
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        
        mid, existing_match = self._get_user_match(ctx_id, user_id)
        if existing_match:
            yield event.plain_result(f"⚠️ 你已经在对局 #{mid} 中了，无法分身！")
            return

        if ctx_id not in self.active_matches:
            self.active_matches[ctx_id] = {}
            
        match_id = 1
        while str(match_id) in self.active_matches[ctx_id]:
            match_id += 1
        match_id = str(match_id)

        self.active_matches[ctx_id][match_id] = {
            "players": {user_id: user_name},
            "scores": {},
            "status": "recruiting"
        }
        
        yield event.plain_result(
            f"对局 #{match_id} 已建立！\n"
            f"选手 {user_name} 已加入！ (1/4)\n"
            f"请其他选手发送 /加入对局 加入。\n"
            f"(多桌同开时请输入 /加入对局 {match_id} 加入本桌）\n"
        )

    @command("mj_join", alias=["加入对局", "join"])
    async def join_match(self, event: AstrMessageEvent, match_id: str = ""):
        """加入当前招募中的对局（全阶段开放自由加入）"""
        ctx_id = self._get_context_id(event)
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        match_id = str(match_id).strip()

        mid, existing_match = self._get_user_match(ctx_id, user_id)
        if existing_match:
            yield event.plain_result(f"👉 {user_name} 已经在对局 #{mid} 中了。")
            return

        if ctx_id not in self.active_matches or not self.active_matches[ctx_id]:
            yield event.plain_result("⚠️ 当前没有正在招募的对局，请先发送 /对局开始")
            return

        target_match = None
        target_mid = None

        if match_id:
            if match_id in self.active_matches[ctx_id]:
                target_match = self.active_matches[ctx_id][match_id]
                target_mid = match_id
            else:
                yield event.plain_result(f"⚠️ 找不到对局 #{match_id}。")
                return
        else:
            recruiting_matches = {k: v for k, v in self.active_matches[ctx_id].items() if v["status"] == "recruiting"}
            if not recruiting_matches:
                yield event.plain_result("QAQ 当前所有的对局都已经人满开始了……")
                return
            elif len(recruiting_matches) == 1:
                target_mid, target_match = list(recruiting_matches.items())[0]
            else:
                match_list = ", ".join([f"#{k}" for k in recruiting_matches.keys()])
                yield event.plain_result(f"⚠️ 有多个正在招募的对局 ({match_list})，请指定桌号哦")
                return

        if target_match["status"] != "recruiting":
            yield event.plain_result(f"⚠️ 对局 #{target_mid} 正在进行，无法加入。")
            return

        if len(target_match["players"]) >= 4:
            yield event.plain_result(f"🚫 对局 #{target_mid} 人数已满！")
            return

        target_match["players"][user_id] = user_name
        current_count = len(target_match["players"])

        if current_count == 4:
            target_match["status"] = "playing"
            winds = ["东", "南", "西", "北"]
            player_list = list(target_match["players"].values())
            random.shuffle(player_list)
            players_list_str = "\n".join([f"{winds[i]}: {name}" for i, name in enumerate(player_list)])
            
            # 判断对局性质用于提示
            ctx_data = self.data.get(ctx_id, {})
            stage = ctx_data.get("stage", "regular")
            match_uids = list(target_match["players"].keys())
            stage_tip = ""
            if stage == "finals" and all(ctx_data.get(uid, {}).get("is_finalist") for uid in match_uids):
                stage_tip = "\n👑 本桌 4 人全为决赛选手：【总决赛对局】！"
            elif stage in ["playoffs", "finals"] and all(ctx_data.get(uid, {}).get("is_playoff_qualifier") for uid in match_uids):
                stage_tip = "\n🏆 本桌 4 人全为季后赛选手：【季后赛对局】！"
            elif stage in ["playoffs", "finals"]:
                stage_tip = "\n🀄 本桌含非晋级选手：【常规/段位对局】（不计入季后赛/决赛）"

            yield event.plain_result(
                f"✅ 对局 #{target_mid} 集结完毕，GAME START！\n{players_list_str}{stage_tip}\n\n"
                f"🏁 结束后请本桌选手发送：/得点 [点数]"
            )
        else:
            yield event.plain_result(f"选手 {user_name} 加入对局 #{target_mid} ！ ({current_count}/4)")

    @command("mj_cancel", alias=["取消对局", "撤销对局", "关闭对局"])
    async def cancel_match(self, event: AstrMessageEvent):
        ctx_id = self._get_context_id(event)
        user_id = event.get_sender_id()
        mid, match = self._get_user_match(ctx_id, user_id)
        
        if match:
            status = match["status"]
            del self.active_matches[ctx_id][mid]
            if not self.active_matches[ctx_id]:
                del self.active_matches[ctx_id]
                
            if status == "recruiting":
                yield event.plain_result(f"🚫 已关闭对局招募 (桌号 #{mid})。")
            else:
                yield event.plain_result(f"🚫 已中止对局 #{mid}，本局数据不记录。")
        else:
            yield event.plain_result("⚠️ 你当前不在任何进行中的对局哦")

    @command("mj_end", alias=["对局结束", "得点"])
    async def end_match(self, event: AstrMessageEvent, score: int):
        ctx_id = self._get_context_id(event)
        user_id = event.get_sender_id()
        mid, match = self._get_user_match(ctx_id, user_id)
        
        if not match:
            yield event.plain_result("⚠️ 你当前不在任何对局中")
            return

        if match["status"] != "playing":
            yield event.plain_result(f"⚠️ 对局 #{mid} 尚未开始")
            return

        match["scores"][user_id] = score
        submitted_count = len(match["scores"])
        
        if submitted_count == 4:
            total_score = sum(match["scores"].values())
            if total_score != 100000:
                diff = total_score - 100000
                diff_str = f"+{diff}" if diff > 0 else f"{diff}"
                details = [f"{match['players'][uid]}: {s}" for uid, s in match["scores"].items()]
                details_str = "\n".join(details)
                
                yield event.plain_result(
                    f"⚠️ 对局 #{mid} 点数核算不通过\n"
                    f"四家得点之和为 {total_score} (误差 {diff_str})\n"
                    f"目标: 100000\n----------------\n当前提交:\n{details_str}\n"
                    f"👉 请本桌发现错误的选手重新发送 /得点 [正确点数] 修正。"
                )
                return 

            yield event.plain_result(f"✅ 对局 #{mid} 点数核算通过 (100000)，正在结算...")
            for item in self._finalize_match(event, ctx_id, match, mid):
                yield item
        else:
            yield event.plain_result(f"💾 分数已记录 ({submitted_count}/4)")

    def _finalize_match(self, event, ctx_id, match, mid):
        """结算对局核心逻辑（自动识别：总决赛 / 季后赛 / 常规赛）"""
        sorted_scores = sorted(match["scores"].items(), key=lambda x: x[1], reverse=True)
        ctx_data = self.data.setdefault(ctx_id, {})
        
        # 1. 校验当前对局性质
        stage = ctx_data.get("stage", "regular")
        match_uids = [uid for uid, _ in sorted_scores]
        
        is_finals_match = (stage == "finals" and all(ctx_data.get(u, {}).get("is_finalist") for u in match_uids))
        is_playoffs_match = (not is_finals_match and stage in ["playoffs", "finals"] and all(ctx_data.get(u, {}).get("is_playoff_qualifier") for u in match_uids))
        
        if is_finals_match:
            header_str = f"🀄️ 对局结束 (总决赛 #{mid})"
        elif is_playoffs_match:
            header_str = f"🀄️ 对局结束 (季后赛 #{mid})"
        else:
            header_str = f"🀄️ 对局结束"

        result_msg = [header_str]
        UMA_SLOTS = [50.0, 10.0, -10.0, -30.0]
        ICONS = ["🥇", "🥈", "🥉", "💀"]

        # 2. 处理同分平分马点
        i = 0
        while i < len(sorted_scores):
            j = i + 1
            while j < len(sorted_scores) and sorted_scores[j][1] == sorted_scores[i][1]:
                j += 1
            
            current_umas = UMA_SLOTS[i:j]
            avg_uma = sum(current_umas) / len(current_umas)
            
            for k in range(i, j):
                uid, score = sorted_scores[k]
                username = match["players"][uid]
                
                base_pt = (score - 30000) / 1000.0
                final_pt = round(base_pt + avg_uma, 1)
                pt_str = f"+{final_pt}" if final_pt > 0 else f"{final_pt}"
                
                user_stat = ctx_data.setdefault(uid, {
                    "name": username, "total_pt": 0.0, "total_matches": 0,
                    "ranks": [0, 0, 0, 0], "max_score": 0, "total_score": 0, "avoid_4_rate": 0.0,
                    "regular_matches": 0, "regular_counted_pt": 0.0
                })
                
                if "total_score" not in user_stat: user_stat["total_score"] = 0
                if "regular_matches" not in user_stat: user_stat["regular_matches"] = user_stat["total_matches"]
                if "regular_counted_pt" not in user_stat: user_stat["regular_counted_pt"] = user_stat["total_pt"]

                # 生涯统计数据（始终累加更新，便于查鱼和段位系统捕获）
                user_stat["name"] = username
                user_stat["total_pt"] = round(user_stat["total_pt"] + final_pt, 1)
                user_stat["total_matches"] += 1
                user_stat["ranks"][i] += 1
                user_stat["total_score"] += score
                if score > user_stat["max_score"]: user_stat["max_score"] = score
                not_4th_count = sum(user_stat["ranks"][:3])
                user_stat["avoid_4_rate"] = round((not_4th_count / user_stat["total_matches"]) * 100, 2)
                
                extra_note = ""
                # --- 赛制积分路由 ---
                if is_finals_match:
                    user_stat["finals_matches"] = user_stat.get("finals_matches", 0) + 1
                    user_stat["finals_pt"] = round(user_stat.get("finals_pt", 0.0) + final_pt, 1)
                    extra_note = f" [决赛:{user_stat['finals_pt']}pt]"
                    
                elif is_playoffs_match:
                    user_stat["playoff_matches"] = user_stat.get("playoff_matches", 0) + 1
                    # 季后赛上限 10 回，超过 10 战不影响排位pt
                    if user_stat["playoff_matches"] <= 10:
                        user_stat["playoff_pt"] = round(user_stat.get("playoff_pt", 0.0) + final_pt, 1)
                        extra_note = f" [季后赛:{user_stat['playoff_matches']}/10战]"
                    else:
                        extra_note = f" [季后赛已满10战]"
                        
                else:
                    # 常规/段位对局：常规赛排位pt仅计入前 60 战
                    user_stat["regular_matches"] += 1
                    if user_stat["regular_matches"] <= 60:
                        user_stat["regular_counted_pt"] = round(user_stat["regular_counted_pt"] + final_pt, 1)
                    else:
                        extra_note = " (超60战不计排位)"

                result_msg.append(f"{ICONS[i]} {username}: {score} ({pt_str}pt){extra_note}")
            i = j
            
        self._save_data()
        del self.active_matches[ctx_id][mid]
        if not self.active_matches[ctx_id]:
            del self.active_matches[ctx_id]
        
        yield event.plain_result("\n".join(result_msg))

    @command("mj_chombo", alias=["冲和", "错和", "罚分", "chombo"])
    async def chombo(self, event: AstrMessageEvent):
        ctx_id = self._get_context_id(event)
        target_uid = None
        for comp in event.get_messages():
            if isinstance(comp, At):
                target_uid = str(comp.qq)
                break
        
        if not target_uid:
            yield event.plain_result("⚠️ 格式错误，请 @ 需要处罚的用户。\n示例: /chombo @某人 诈和")
            return

        reason_parts = []
        for comp in event.get_messages():
            if not isinstance(comp, At) and hasattr(comp, 'text'):
                reason_parts.append(comp.text)
                
        raw_text = " ".join(reason_parts).strip()
        for cmd in ["/mj_chombo", "/冲和", "/错和", "/罚分", "mj_chombo", "冲和", "错和", "罚分"]:
            if raw_text.startswith(cmd):
                raw_text = raw_text[len(cmd):].strip()
                break
                
        reason = raw_text if raw_text else "无备注"
        ctx_data = self.data.setdefault(ctx_id, {})
        
        if target_uid not in ctx_data:
            ctx_data[target_uid] = {
                "name": f"用户{target_uid}", "total_pt": 0.0, "total_matches": 0,
                "ranks": [0, 0, 0, 0], "max_score": 0, "total_score": 0, "avoid_4_rate": 0.0,
                "regular_matches": 0, "regular_counted_pt": 0.0
            }
        
        user_data = ctx_data[target_uid]
        user_data["total_pt"] = round(user_data["total_pt"] - 20.0, 1)
        # 如果还在前 60 战范围内，同样扣除常规赛排位pt
        if user_data.get("regular_matches", 0) <= 60:
            user_data["regular_counted_pt"] = round(user_data.get("regular_counted_pt", 0.0) - 20.0, 1)
        self._save_data()
        
        yield event.plain_result(
            f"🚫 **Chombo 处罚执行**\n"
            f"对象: {user_data['name']}\n"
            f"原因: {reason}\n"
            f"惩罚: -20 pt\n"
            f"当前总PT: {user_data['total_pt']}"
        )

    # -------------------------------------------------------
    # 📊 排行榜与个人数据面板
    # -------------------------------------------------------

    @command("mj_rank", alias=["rank", "排行", "Rank", "RANK"])
    async def show_rank(self, event: AstrMessageEvent, query_type: str):
        """查询常规赛排行榜"""
        ctx_id = self._get_context_id(event)
        ctx_data = self.data.get(ctx_id, {})
        
        if not ctx_data:
            yield event.plain_result("⚠️ 暂无对局记录。")
            return

        stage = ctx_data.get("stage", "regular")
        if stage == "finals":
            yield event.plain_result("👑 当前处于总决赛阶段，请使用 /决赛榜 查询总决赛战况。\n以下显示常规赛历史数据：")
        elif stage == "playoffs":
            yield event.plain_result("🏆 当前处于季后赛阶段，请使用 /季后赛榜 查询季后赛战况。\n以下显示常规赛历史数据：")

        users = [u for u in ctx_data.items() if isinstance(u[1], dict) and "total_pt" in u[1]]
        msg_lines = []

        # 1. 原始 PT 榜 (生涯总PT)
        if query_type.lower() in ["pt", "原始pt", "分数", "总分"]:
            msg_header = "📊 **常规赛 原始PT榜** (生涯总PT)"
            sorted_users = sorted(users, key=lambda x: x[1]["total_pt"], reverse=True)
            msg_lines = [msg_header]
            for i, (uid, data) in enumerate(sorted_users):
                msg_lines.append(f"{i+1}. {data['name']} — {data['total_pt']} pt [试合:{data['total_matches']}]")
            
        # 2. 排位 PT 榜 (前 60 战封顶，20 战门槛罚分)
        elif query_type in ["排位", "排名", "排位pt", "ranking"]:
            msg_header = "🏆 **赛季排位榜 (前60战封顶，门槛20战)**"
            ranked_list = []
            for uid, data in users:
                reg_matches = data.get("regular_matches", data.get("total_matches", 0))
                counted_pt = data.get("regular_counted_pt", data.get("total_pt", 0.0))
                # 门槛 20 战罚分
                penalty = max(0, 20 - reg_matches) * 50
                ranking_pt = round(counted_pt - penalty, 1)
                ranked_list.append((uid, data, ranking_pt, penalty, reg_matches, counted_pt))
            
            ranked_list.sort(key=lambda x: x[2], reverse=True)
            msg_lines = [msg_header]
            for i, (uid, data, r_pt, penalty, reg_m, c_pt) in enumerate(ranked_list):
                note = f"(罚:{penalty})" if penalty > 0 else ""
                cap_note = " (前60战已封顶)" if reg_m >= 60 else ""
                mark = ""
                if data.get("is_finalist"):
                    mark = " 👑"
                elif data.get("is_playoff_qualifier"):
                    mark = " 🔥"
                msg_lines.append(f"{i+1}. {data['name']}{mark} — {r_pt} pt {note} [{reg_m}/20战]{cap_note}")

        elif query_type in ["位次", "一位率"]:
            msg_header = "👑 **一位次数 排行榜**"
            sorted_users = sorted(users, key=lambda x: (x[1]["ranks"][0], -x[1]["total_matches"]), reverse=True)
            msg_lines = [msg_header]
            for i, (uid, data) in enumerate(sorted_users):
                msg_lines.append(f"{i+1}. {data['name']} — 一位 {data['ranks'][0]} 次 / {data['total_matches']} 场")
            
        elif query_type in ["最高得点", "最大得点"]:
            msg_header = "💥 **单场最高得点 排行榜**"
            sorted_users = sorted(users, key=lambda x: x[1]["max_score"], reverse=True)
            msg_lines = [msg_header]
            for i, (uid, data) in enumerate(sorted_users):
                msg_lines.append(f"{i+1}. {data['name']} — {data['max_score']} 点")
            
        elif query_type in ["避四率", "避四"]:
            msg_header = "🛡️ **避四率 排行榜** (至少5场)"
            valid_users = [u for u in users if u[1]["total_matches"] >= 5]
            sorted_users = sorted(valid_users, key=lambda x: x[1]["avoid_4_rate"], reverse=True)
            msg_lines = [msg_header]
            for i, (uid, data) in enumerate(sorted_users):
                msg_lines.append(f"{i+1}. {data['name']} — {data['avoid_4_rate']}% (共{data['total_matches']}场)")
            
        else:
            yield event.plain_result("❓ 未知查询类型。\n请使用: pt (原始分), 排位 (含前60战与门槛), 位次, 最高得点, 避四率")
            return

        yield event.plain_result("\n".join(msg_lines))

    @command("mj_stats", alias=["个人数据", "查数据", "战绩", "吃鱼"])
    async def my_stats(self, event: AstrMessageEvent):
        """查询个人生涯与赛季阶段数据"""
        ctx_id = self._get_context_id(event)
        ctx_data = self.data.get(ctx_id, {})
        
        if not ctx_data:
            yield event.plain_result("⚠️ 暂无对局记录。")
            return

        target_uid = event.get_sender_id()
        target_name = event.get_sender_name()
        
        for comp in event.get_messages():
            if isinstance(comp, At):
                target_uid = str(comp.qq)
                if target_uid in ctx_data:
                    target_name = ctx_data[target_uid]["name"]
                else:
                    target_name = f"用户{target_uid}"
                break

        if target_uid not in ctx_data or not isinstance(ctx_data[target_uid], dict):
            yield event.plain_result(f"⚠️ 未找到 {target_name} 的参赛记录。")
            return

        user = ctx_data[target_uid]
        total_games = user["total_matches"]
        
        if total_games == 0:
            yield event.plain_result(f"⚠️ {user['name']} 还没有完成过对局。")
            return

        # 1. 计算常规赛排位
        users_list = []
        for uid, data in ctx_data.items():
            if not isinstance(data, dict) or "total_pt" not in data: continue
            raw_pt = data["total_pt"]
            reg_m = data.get("regular_matches", data.get("total_matches", 0))
            c_pt = data.get("regular_counted_pt", raw_pt)
            penalty = max(0, 20 - reg_m) * 50
            ranking_pt = round(c_pt - penalty, 1)
            users_list.append({"uid": uid, "raw_pt": raw_pt, "ranking_pt": ranking_pt})
        
        users_list.sort(key=lambda x: x["raw_pt"], reverse=True)
        raw_rank = next((i + 1 for i, u in enumerate(users_list) if u["uid"] == target_uid), "N/A")
        users_list.sort(key=lambda x: x["ranking_pt"], reverse=True)
        ranking_rank = next((i + 1 for i, u in enumerate(users_list) if u["uid"] == target_uid), "N/A")
        
        ranks = user["ranks"]
        rates = [f"{r / total_games * 100:.2f}%" for r in ranks]
        rank_sum = sum((i + 1) * count for i, count in enumerate(ranks))
        avg_rank_val = rank_sum / total_games
        total_score = user.get("total_score", 0)
        avg_score = int(total_score / total_games)
        
        reg_m = user.get("regular_matches", total_games)
        c_pt = user.get("regular_counted_pt", user["total_pt"])
        current_penalty = max(0, 20 - reg_m) * 50
        current_ranking_pt = round(c_pt - current_penalty, 1)

        msg = [
            f"📊 {user['name']} 的赛季数据",
            f"------------------------",
            f"🔢 ===常规赛排位===",
            f"• 生涯总PT: {user['total_pt']} pt (第 {raw_rank} 名)",
            f"• 常规排位PT: {current_ranking_pt} pt (第 {ranking_rank} 名)",
            f"  *(有效前60战: {min(reg_m, 60)}/60 | 罚分: -{current_penalty} pt)*",
            f"",
            f"📈 ===对局详情=== (共 {total_games} 场)",
            f"🥇 一位率: {rates[0]} ({ranks[0]}回)",
            f"🥈 二位率: {rates[1]} ({ranks[1]}回)",
            f"🥉 三位率: {rates[2]} ({ranks[2]}回)",
            f"💀 四位率: {rates[3]} ({ranks[3]}回)",
            f"",
            f"📐 ===均值统计===",
            f"• 平均顺位: {avg_rank_val:.2f}",
            f"• 平均得点: {avg_score}",
            f"• 最高得点: {user['max_score']}",
            f"• 避四率: {user['avoid_4_rate']}%"
        ]
        
        # 季后赛与总决赛状态扩展面板
        if user.get("is_playoff_qualifier"):
            p_m = user.get("playoff_matches", 0)
            p_penalty = max(0, 10 - min(p_m, 10)) * 50
            p_rank_pt = round(user.get("playoff_pt", 0.0) - p_penalty, 1)
            msg.extend([
                f"",
                f"🏆 ===季后赛状态===",
                f"• 季后排位PT: {p_rank_pt} pt (当前:{user.get('playoff_pt', 0.0)} | 罚:{p_penalty})",
                f"• 试合进度: {p_m}/10 战 (起始折半分: {user.get('playoff_init_pt', 0.0)})"
            ])
            
        if user.get("is_finalist"):
            msg.extend([
                f"",
                f"👑 ===总决赛状态===",
                f"• 决赛当前PT: {user.get('finals_pt', 0.0)} pt (试合: {user.get('finals_matches', 0)} 场)",
                f"• 起始折半分: {user.get('finals_init_pt', 0.0)}"
            ])
        
        yield event.plain_result("\n".join(msg))

    # -------------------------------------------------------
    # 🏆 季后赛系统 (Top 6 争霸，10 战封顶+门槛)
    # -------------------------------------------------------

    @command("mj_playoffs_setup", alias=["进入季后赛", "季后赛初始化", "开启季后赛"])
    async def setup_playoffs(self, event: AstrMessageEvent):
        """
        [管理员] 初始化季后赛模式 (6人晋级)
        用法: /进入季后赛 @选手1 @选手2 @选手3 @选手4 @选手5 @选手6
        逻辑: 常规赛排位PT / 2 继承为季后赛初始分
        """
        ctx_id = self._get_context_id(event)
        ctx_data = self.data.setdefault(ctx_id, {})

        if ctx_data.get("stage") == "playoffs":
            yield event.plain_result("⚠️ 错误：当前已经是季后赛模式！请勿重复执行。")
            return

        target_uids = []
        for comp in event.get_messages():
            if isinstance(comp, At):
                target_uids.append(str(comp.qq))
        target_uids = list(set(target_uids))

        if len(target_uids) != 6:
            yield event.plain_result(f"⚠️ 必须指定 6 位晋级选手！当前检测到 {len(target_uids)} 人。")
            return

        msg_lines = ["🏆 **已正式进入季后赛（6强争霸）**", "----------------"]
        for uid in target_uids:
            if uid not in ctx_data:
                ctx_data[uid] = {
                    "name": f"选手{uid}", "total_pt": 0.0, "total_matches": 0,
                    "ranks": [0,0,0,0], "max_score": 0, "total_score": 0, "avoid_4_rate": 0.0,
                    "regular_matches": 0, "regular_counted_pt": 0.0
                }
            user = ctx_data[uid]
            
            # 计算常规赛最终排位PT (前60战封顶，不足20战扣罚)
            reg_m = user.get("regular_matches", user.get("total_matches", 0))
            c_pt = user.get("regular_counted_pt", user.get("total_pt", 0.0))
            penalty = max(0, 20 - reg_m) * 50
            reg_ranking_pt = round(c_pt - penalty, 1)
            
            # 季后赛初始分 = 常规排位PT / 2
            start_pt = round(reg_ranking_pt / 2, 1)
            user["playoff_init_pt"] = start_pt
            user["playoff_pt"] = start_pt
            user["playoff_matches"] = 0
            user["is_playoff_qualifier"] = True
            
            msg_lines.append(f"👤 {user['name']}: 常规排位 {reg_ranking_pt}pt ➔ 季后初始 {start_pt}pt")

        ctx_data["stage"] = "playoffs"
        ctx_data["playoff_uids"] = target_uids
        self._save_data()

        msg_lines.append("----------------")
        msg_lines.append("📌 规则：需打满 10 回（不足扣分，上限亦为 10 回）。")
        msg_lines.append("📌 注意：唯有 4 人全为晋级选手的对局才计入季后赛，其他对局自动作为常规/段位对局。")
        msg_lines.append("📊 请使用 /季后赛榜 查询实时战况。")
        yield event.plain_result("\n".join(msg_lines))

    @command("mj_playoffs_rank", alias=["季后赛榜", "playoffs_rank", "季后赛排行"])
    async def show_playoffs_rank(self, event: AstrMessageEvent):
        """显示季后赛 6 强排行榜"""
        ctx_id = self._get_context_id(event)
        ctx_data = self.data.get(ctx_id, {})
        
        if ctx_data.get("stage") not in ["playoffs", "finals"]:
            yield event.plain_result("⚠️ 当前未进行季后赛，请使用 /rank 查询常规排位。")
            return

        qualifiers = [d for d in ctx_data.values() if isinstance(d, dict) and d.get("is_playoff_qualifier")]
        ranked_list = []
        for u in qualifiers:
            p_m = u.get("playoff_matches", 0)
            penalty = max(0, 10 - min(p_m, 10)) * 50
            ranking_pt = round(u.get("playoff_pt", 0.0) - penalty, 1)
            ranked_list.append((u, ranking_pt, penalty, p_m))

        ranked_list.sort(key=lambda x: x[1], reverse=True)
        msg = ["🏆 **【季后赛 实时排位榜】** 🏆", "========================"]
        for i, (u, r_pt, penalty, p_m) in enumerate(ranked_list):
            note = f"(罚:{penalty})" if penalty > 0 else ""
            cap_note = " (满10战)" if p_m >= 10 else ""
            msg.append(f" {i+1}. {u['name']} — {r_pt} pt {note} [{p_m}/10战]{cap_note}")
        
        yield event.plain_result("\n".join(msg))

    # -------------------------------------------------------
    # 👑 总决赛系统 (Top 4 争冠，折半继承)
    # -------------------------------------------------------

    @command("mj_finals_setup", alias=["进入决赛", "决赛初始化", "开启决赛"])
    async def setup_finals(self, event: AstrMessageEvent):
        """
        [管理员] 初始化总决赛模式 (4人决战)
        用法: /进入决赛 @选手1 @选手2 @选手3 @选手4
        逻辑: 季后赛最终排位PT / 2 = 总决赛初始分
        """
        ctx_id = self._get_context_id(event)
        ctx_data = self.data.setdefault(ctx_id, {})

        if ctx_data.get("stage") == "finals":
            yield event.plain_result("⚠️ 错误：当前已经是总决赛模式！请勿重复执行。")
            return

        target_uids = []
        for comp in event.get_messages():
            if isinstance(comp, At):
                target_uids.append(str(comp.qq))
        target_uids = list(set(target_uids))

        if len(target_uids) != 4:
            yield event.plain_result(f"⚠️ 必须指定 4 位决赛选手！当前检测到 {len(target_uids)} 人。")
            return

        msg_lines = ["👑 **已正式进入总决赛（4强争冠）**", "----------------"]
        for uid in target_uids:
            if uid not in ctx_data:
                ctx_data[uid] = {
                    "name": f"选手{uid}", "total_pt": 0.0, "total_matches": 0,
                    "ranks": [0,0,0,0], "max_score": 0, "total_score": 0, "avoid_4_rate": 0.0
                }
            user = ctx_data[uid]
            
            # 计算季后赛最终排位PT (10战门槛扣罚)
            p_m = user.get("playoff_matches", 0)
            penalty = max(0, 10 - min(p_m, 10)) * 50
            p_ranking_pt = round(user.get("playoff_pt", 0.0) - penalty, 1)
            
            # 总决赛初始分 = 季后赛排位PT / 2
            start_pt = round(p_ranking_pt / 2, 1)
            user["finals_init_pt"] = start_pt
            user["finals_pt"] = start_pt
            user["finals_matches"] = 0
            user["is_finalist"] = True
            
            msg_lines.append(f"👤 {user['name']}: 季后排位 {p_ranking_pt}pt ➔ 决赛起始 {start_pt}pt")

        ctx_data["stage"] = "finals"
        ctx_data["finals_uids"] = target_uids
        self._save_data()

        msg_lines.append("----------------")
        msg_lines.append("✅ 总决赛席位已锁定。唯有 4 位决赛选手的对局才计入决赛战绩。")
        msg_lines.append("📊 请使用 /决赛榜 查询总冠军决逐情况。")
        yield event.plain_result("\n".join(msg_lines))

    @command("mj_finals_rank", alias=["决赛榜", "finals_rank", "决赛排行"])
    async def show_finals_rank(self, event: AstrMessageEvent):
        """显示总决赛 4 强排行榜"""
        ctx_id = self._get_context_id(event)
        ctx_data = self.data.get(ctx_id, {})
        
        if ctx_data.get("stage") != "finals":
            yield event.plain_result("⚠️ 当前未开启总决赛，请使用 /季后赛榜 或 /rank 查询。")
            return

        finalists = [d for d in ctx_data.values() if isinstance(d, dict) and d.get("is_finalist")]
        finalists.sort(key=lambda x: x.get("finals_pt", 0.0), reverse=True)

        msg = ["👑 **【总决赛 实时排位榜】** 👑", "========================"]
        for i, user in enumerate(finalists):
            msg.append(f" {i+1}. {user['name']} — {user.get('finals_pt', 0.0)} pt (出战: {user.get('finals_matches', 0)}战)")
            
        yield event.plain_result("\n".join(msg))

    @command("mj_reset", alias=["新赛季"])
    async def reset_season(self, event: AstrMessageEvent):
        """重置当前群组的所有数据并清除所有正在进行的对局"""
        ctx_id = self._get_context_id(event)
        
        if ctx_id in self.active_matches:
            del self.active_matches[ctx_id]

        if ctx_id in self.data:
            self.data[ctx_id] = {} 
            self._save_data()
            yield event.plain_result("🔄 赛季数据已完全重置！\n所有常规赛、季后赛、决赛积分均已清零，新赛季请加油！")
        else:
            yield event.plain_result("⚠️ 当前没有数据可重置。")

    # =======================================================
    # 🎉 活动专区 (超级加倍印第安麻将，完全原模原样套用)
    # =======================================================

    def _load_event_data(self) -> dict:
        if not os.path.exists(EVENT_DATA_FILE):
            return {"status": {}, "groups": {}}
        try:
            with open(EVENT_DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载活动数据失败: {e}")
            return {"status": {}, "groups": {}}

    def _save_event_data(self):
        try:
            with open(EVENT_DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(self.event_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存活动数据失败: {e}")

    def _get_user_event_match(self, ctx_id: str, user_id: str):
        if ctx_id not in self.event_matches:
            return None, None
        for mid, match in self.event_matches[ctx_id].items():
            if user_id in match["players"]:
                return mid, match
        return None, None

    @command("mj_event_toggle", alias=["event"])
    async def toggle_event(self, event: AstrMessageEvent):
        ctx_id = self._get_context_id(event)
        current_status = self.event_data.setdefault("status", {}).get(ctx_id, False)
        self.event_data["status"][ctx_id] = not current_status
        self._save_event_data()
        state_str = "🟢 已开启" if not current_status else "🔴 已关闭"
        yield event.plain_result(f"📢 活动场 {state_str}！")

    @command("mj_event_start", alias=["活动对局开始", "活动开始"])
    async def start_event_match(self, event: AstrMessageEvent):
        ctx_id = self._get_context_id(event)
        if not self.event_data.get("status", {}).get(ctx_id, False):
            yield event.plain_result("⚠️ 当前没有正在进行的活动")
            return

        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        
        mid, existing_match = self._get_user_event_match(ctx_id, user_id)
        if existing_match:
            yield event.plain_result(f"⚠️ 你已经在活动局 #{mid} 中了！")
            return

        if ctx_id not in self.event_matches:
            self.event_matches[ctx_id] = {}
            
        match_id = 1
        while str(match_id) in self.event_matches[ctx_id]:
            match_id += 1
        match_id = str(match_id)

        self.event_matches[ctx_id][match_id] = {
            "players": {user_id: user_name},
            "scores": {},
            "status": "recruiting"
        }
        
        yield event.plain_result(
            f"活动场 #{match_id} 已建立！\n"
            f"选手 {user_name} 已加入！ (1/4)\n"
            f"请其他选手发送 /活动加入 加入\n"
            f"(多桌同开时请发送 /活动加入 {match_id} 加入本桌)"
        )

    @command("mj_event_join", alias=["活动加入"])
    async def join_event_match(self, event: AstrMessageEvent, match_id: str = ""):
        ctx_id = self._get_context_id(event)
        if not self.event_data.get("status", {}).get(ctx_id, False):
            yield event.plain_result("⚠️ 活动场未开放。")
            return

        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        match_id = str(match_id).strip()

        mid, existing_match = self._get_user_event_match(ctx_id, user_id)
        if existing_match:
            yield event.plain_result(f"👉 {user_name} 已经在活动局 #{mid} 中了。")
            return

        if ctx_id not in self.event_matches or not self.event_matches[ctx_id]:
            yield event.plain_result("⚠️ 当前没有招募中的活动局，请发送 /活动对局开始")
            return

        target_match, target_mid = None, None
        if match_id:
            if match_id in self.event_matches[ctx_id]:
                target_match = self.event_matches[ctx_id][match_id]
                target_mid = match_id
            else:
                yield event.plain_result(f"⚠️ 找不到活动局 #{match_id}。")
                return
        else:
            recruiting_matches = {k: v for k, v in self.event_matches[ctx_id].items() if v["status"] == "recruiting"}
            if not recruiting_matches:
                yield event.plain_result("QAQ 所有的活动局都已经开始了……")
                return
            elif len(recruiting_matches) == 1:
                target_mid, target_match = list(recruiting_matches.items())[0]
            else:
                yield event.plain_result(f"⚠️ 有多个活动局在招募，请指定桌号，如 /活动加入 {list(recruiting_matches.keys())[0]}")
                return

        if target_match["status"] != "recruiting":
            yield event.plain_result(f"⚠️ 活动局 #{target_mid} 已开始。")
            return
        if len(target_match["players"]) >= 4:
            yield event.plain_result(f"🚫 活动局 #{target_mid} 人满了！")
            return

        target_match["players"][user_id] = user_name
        current_count = len(target_match["players"])

        if current_count == 4:
            target_match["status"] = "playing"
            winds = ["东", "南", "西", "北"]
            player_list = list(target_match["players"].values())
            random.shuffle(player_list)
            players_list_str = "\n".join([f"{winds[i]}家: {name}" for i, name in enumerate(player_list)])
            
            yield event.plain_result(
                f"✅ 活动局 #{target_mid} 集结完毕，GAME START！\n"
                f"{players_list_str}\n\n"
                f"每局开始前请重新抽取NG卡片！\n"
                f"🏁 对局结束后请发送：/活动得点 [点数]"
            )
        else:
            yield event.plain_result(f"选手 {user_name} 加入活动局 #{target_mid} ！ ({current_count}/4)")

    @command("mj_event_cancel", alias=["活动取消", "活动解散"])
    async def cancel_event_match(self, event: AstrMessageEvent):
        ctx_id = self._get_context_id(event)
        user_id = event.get_sender_id()
        mid, match = self._get_user_event_match(ctx_id, user_id)
        
        if match:
            del self.event_matches[ctx_id][mid]
            if not self.event_matches[ctx_id]:
                del self.event_matches[ctx_id]
            yield event.plain_result(f"🚫 已解散活动局 #{mid}。")
        else:
            yield event.plain_result("⚠️ 你当前不在活动局中。")

    @command("mj_event_ng", alias=["NG", "ng"])
    async def record_event_ng(self, event: AstrMessageEvent):
        ctx_id = self._get_context_id(event)
        ctx_data = self.event_data.setdefault("groups", {}).setdefault(ctx_id, {})
        
        target_uid = None
        for comp in event.get_messages():
            if isinstance(comp, At):
                target_uid = str(comp.qq)
                break
        
        if not target_uid:
            yield event.plain_result("⚠️ 请 @ 触犯了NG内容的选手。\n示例: /活动ng @某人")
            return
            
        if target_uid not in ctx_data:
            ctx_data[target_uid] = {"name": f"用户{target_uid}", "total_pt": 0.0, "total_matches": 0, "total_score": 0, "ng_count": 0}
            
        user_data = ctx_data[target_uid]
        if "ng_count" not in user_data:
            user_data["ng_count"] = 0
            
        user_data["ng_count"] += 1
        self._save_event_data()
        
        yield event.plain_result(f"🚨 NG 记录！\n选手 {user_data['name']} NG次数+1 \n当前累计NG次数：{user_data['ng_count']} 次 \n ohno")

    @command("mj_event_end", alias=["活动得点", "活动结束"])
    async def end_event_match(self, event: AstrMessageEvent, score: int):
        ctx_id = self._get_context_id(event)
        user_id = event.get_sender_id()
        
        mid, match = self._get_user_event_match(ctx_id, user_id)
        if not match:
            yield event.plain_result("⚠️ 你当前不在活动局中")
            return
        if match["status"] != "playing":
            yield event.plain_result(f"⚠️ 活动局 #{mid} 人未满")
            return

        match["scores"][user_id] = score
        submitted_count = len(match["scores"])
        
        if submitted_count == 4:
            total_score = sum(match["scores"].values())
            if total_score != 400000:
                diff = total_score - 400000
                diff_str = f"+{diff}" if diff > 0 else f"{diff}"
                details_str = "\n".join([f"{match['players'][uid]}: {s}" for uid, s in match["scores"].items()])
                yield event.plain_result(
                    f"⚠️ 活动局 #{mid} 点数核算不通过\n"
                    f"四家得点之和为 {total_score} (误差 {diff_str})\n"
                    f"目标: 400000\n----------------\n当前提交:\n{details_str}\n"
                    f"👉 请发送 /活动得点 [正确点数] 修正。"
                )
                return 

            sorted_scores = sorted(match["scores"].items(), key=lambda x: x[1], reverse=True)
            ctx_data = self.event_data.setdefault("groups", {}).setdefault(ctx_id, {})
            result_msg = [f"🃏 活动对局结束"]

            for rank_idx, (uid, s) in enumerate(sorted_scores):
                username = match["players"][uid]
                pt = round((s - 100000) / 1000.0, 1)
                pt_str = f"+{pt}" if pt > 0 else f"{pt}"

                user_stat = ctx_data.setdefault(uid, {
                    "name": username, "total_pt": 0.0, "total_matches": 0, "total_score": 0, "ng_count": 0
                })
                if "ng_count" not in user_stat: user_stat["ng_count"] = 0

                user_stat["name"] = username
                user_stat["total_pt"] = round(user_stat["total_pt"] + pt, 1)
                user_stat["total_matches"] += 1
                user_stat["total_score"] += s

                result_msg.append(f"{rank_idx+1}位 {username}: {s} ({pt_str}pt)")

            self._save_event_data()
            del self.event_matches[ctx_id][mid]
            if not self.event_matches[ctx_id]:
                del self.event_matches[ctx_id]
            
            yield event.plain_result("\n".join(result_msg))
        else:
            yield event.plain_result(f"💾 活动分数已记录 ({submitted_count}/4)")

    @command("mj_event_rank", alias=["活动榜", "活动排行", "活动rank"])
    async def show_event_rank(self, event: AstrMessageEvent):
        ctx_id = self._get_context_id(event)
        ctx_data = self.event_data.get("groups", {}).get(ctx_id, {})
        
        if not ctx_data:
            yield event.plain_result("⚠️ 暂无活动记录。")
            return

        users = list(ctx_data.values())
        if not users:
            return

        msg = ["🏆 **【超级加倍印第安】活动大赏** 🏆\n"]

        mvp_list = sorted(users, key=lambda x: x["total_pt"], reverse=True)
        msg.append("👑 【MVP赏】 (总PT排行)")
        for i, u in enumerate(mvp_list):
            msg.append(f"  {i+1}. {u['name']} — {u['total_pt']} pt")
        msg.append("")

        luck_list = sorted(users, key=lambda x: x["total_score"] / x["total_matches"] if x["total_matches"] > 0 else 0, reverse=True)
        msg.append("🍀 【手气最佳赏】 (均点排行)")
        for i, u in enumerate(luck_list):
            avg = int(u["total_score"] / u["total_matches"]) if u["total_matches"] > 0 else 0
            msg.append(f"  {i+1}. {u['name']} — {avg} 点 ({u['total_matches']}场)")
        msg.append("")

        ng_list = sorted(users, key=lambda x: x.get("ng_count", 0), reverse=True)
        msg.append("🚨 【NG赏】 (NG次数排行)")
        for i, u in enumerate(ng_list):
            msg.append(f"  {i+1}. {u['name']} — NG {u.get('ng_count', 0)} 次")

        yield event.plain_result("\n".join(msg))
