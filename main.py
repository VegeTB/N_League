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
                stage_tip = "\n👑 【决赛对局】"
            elif stage in ["playoffs", "finals"] and all(ctx_data.get(uid, {}).get("is_playoff_qualifier") for uid in match_uids):
                stage_tip = "\n🏆 【季后赛对局】"
            elif stage in ["playoffs", "finals"]:
                stage_tip = "\n🀄 本桌含非晋级选手：【常规对局】"

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
    # 🛠️ 常规赛管理运维工具 (手动补录战绩)
    # -------------------------------------------------------

    @command("mj_manual_record", alias=["补录", "对局补录", "录分", "常规补录", "手动录分", "强制录分"])
    async def record_regular_manual(self, event: AstrMessageEvent):
        """
        [管理员] 手动/强制补录一次常规赛(M规)成绩
        用法支持以下两种格式（点数按@的顺序对应）：
          格式1: /补录 @选手A 42000 @选手B 28000 @选手C 18000 @选手D 12000
          格式2: /补录 @选手A @选手B @选手C @选手D 42000 28000 18000 12000
        """
        ctx_id = self._get_context_id(event)
        
        # 1. 提取被 @ 的 4 位选手
        target_uids = []
        for comp in event.get_messages():
            if isinstance(comp, At):
                target_uids.append(str(comp.qq))
        
        unique_uids = list(dict.fromkeys(target_uids)) # 保持顺序去重
        if len(unique_uids) != 4:
            yield event.plain_result(
                "⚠️ 格式错误！必须同时 @ 4 位不同的选手。\n"
                "👉 正确示例：\n"
                "/补录 @选手1 42000 @选手2 28000 @选手3 18000 @选手4 12000\n"
                "或\n"
                "/补录 @选手1 @选手2 @选手3 @选手4 42000 28000 18000 12000"
            )
            return

        # 2. 从纯文本中提取 4 个点数
        plain_texts = []
        for comp in event.get_messages():
            if not isinstance(comp, At) and hasattr(comp, 'text'):
                plain_texts.append(comp.text)
        
        combined_text = " ".join(plain_texts)
        for cmd in ["/mj_manual_record", "/补录", "/对局补录", "/录分", "/常规补录", "/手动录分", "/强制录分"]:
            combined_text = combined_text.replace(cmd, "")
            
        scores_raw = re.findall(r'-?\d+', combined_text)
        if len(scores_raw) != 4:
            yield event.plain_result(f"⚠️ 点数数量不匹配！检测到 {len(scores_raw)} 个有效数值，必须依次提供 4 家的点数。")
            return

        scores = [int(s) for s in scores_raw]
        
        # 3. 校验总和 100000 (M规持点25000*4)
        total_score = sum(scores)
        if total_score != 100000:
            diff = total_score - 100000
            diff_str = f"+{diff}" if diff > 0 else f"{diff}"
            yield event.plain_result(
                f"⚠️ 点数核算失败！\n"
                f"四家得点总和为: {total_score} (误差 {diff_str})\n"
                f"目标总和: 100000 (2.5w持点*4)\n"
                f"👉 请检查点数是否有误并重新录入。"
            )
            return

        # 4. 获取选手昵称并配对
        ctx_data = self.data.setdefault(ctx_id, {})
        player_entries = []
        for uid, s in zip(unique_uids, scores):
            name = f"用户{uid}"
            if uid in ctx_data and ctx_data[uid].get("name"):
                name = ctx_data[uid]["name"]
            player_entries.append((uid, name, s))

        # 5. 校验当前对局性质 (自动识别：总决赛 / 季后赛 / 常规赛)
        stage = ctx_data.get("stage", "regular")
        match_uids = [uid for uid, _, _ in player_entries]
        
        is_finals_match = (stage == "finals" and all(ctx_data.get(u, {}).get("is_finalist") for u in match_uids))
        is_playoffs_match = (not is_finals_match and stage in ["playoffs", "finals"] and all(ctx_data.get(u, {}).get("is_playoff_qualifier") for u in match_uids))
        
        if is_finals_match:
            header_str = "🀄️ 对局结束 (总决赛补录)"
        elif is_playoffs_match:
            header_str = "🀄️ 对局结束 (季后赛补录)"
        else:
            header_str = "🀄️ 对局结束 (常规补录)"

        result_msg = [header_str]

        # 6. 排序与 M规 马点计算 (+50/+10/-10/-30，返点30000，同分平分马点)
        sorted_players = sorted(player_entries, key=lambda x: x[2], reverse=True)
        UMA_SLOTS = [50.0, 10.0, -10.0, -30.0]
        ICONS = ["🥇", "🥈", "🥉", "💀"]

        i = 0
        while i < len(sorted_players):
            j = i + 1
            while j < len(sorted_players) and sorted_players[j][2] == sorted_players[i][2]:
                j += 1
            
            current_umas = UMA_SLOTS[i:j]
            avg_uma = sum(current_umas) / len(current_umas)

            for k in range(i, j):
                uid, name, s = sorted_players[k]
                base_pt = (s - 30000) / 1000.0
                final_pt = round(base_pt + avg_uma, 1)
                pt_str = f"+{final_pt}" if final_pt > 0 else f"{final_pt}"

                user_stat = ctx_data.setdefault(uid, {
                    "name": name, "total_pt": 0.0, "total_matches": 0,
                    "ranks": [0, 0, 0, 0], "max_score": 0, "total_score": 0, "avoid_4_rate": 0.0,
                    "regular_matches": 0, "regular_counted_pt": 0.0
                })

                # 兼容历史缺漏字段
                if "total_score" not in user_stat: user_stat["total_score"] = 0
                if "regular_matches" not in user_stat: user_stat["regular_matches"] = user_stat["total_matches"]
                if "regular_counted_pt" not in user_stat: user_stat["regular_counted_pt"] = user_stat["total_pt"]
                if "ranks" not in user_stat or not isinstance(user_stat["ranks"], list): user_stat["ranks"] = [0, 0, 0, 0]
                if "max_score" not in user_stat: user_stat["max_score"] = 0

                # 始终更新生涯数据 (方便查鱼与天凤段位同步)
                user_stat["name"] = name
                user_stat["total_pt"] = round(user_stat["total_pt"] + final_pt, 1)
                user_stat["total_matches"] += 1
                user_stat["ranks"][i] += 1
                user_stat["total_score"] += s
                if s > user_stat["max_score"]: user_stat["max_score"] = s
                not_4th_count = sum(user_stat["ranks"][:3])
                user_stat["avoid_4_rate"] = round((not_4th_count / user_stat["total_matches"]) * 100, 2)

                extra_note = ""
                # 赛制逻辑分支
                if is_finals_match:
                    user_stat["finals_matches"] = user_stat.get("finals_matches", 0) + 1
                    user_stat["finals_pt"] = round(user_stat.get("finals_pt", 0.0) + final_pt, 1)
                    extra_note = f" [决赛:{user_stat['finals_pt']}pt]"
                elif is_playoffs_match:
                    user_stat["playoff_matches"] = user_stat.get("playoff_matches", 0) + 1
                    if user_stat["playoff_matches"] <= 10:
                        user_stat["playoff_pt"] = round(user_stat.get("playoff_pt", 0.0) + final_pt, 1)
                        extra_note = f" [季后赛:{user_stat['playoff_matches']}/10战]"
                    else:
                        extra_note = " [季后赛已满10战]"
                else:
                    # 常规赛：前 60 战计入排位
                    user_stat["regular_matches"] += 1
                    if user_stat["regular_matches"] <= 60:
                        user_stat["regular_counted_pt"] = round(user_stat["regular_counted_pt"] + final_pt, 1)
                    else:
                        extra_note = " (超60战不计排位)"

                result_msg.append(f"{ICONS[i]} {name}: {s} ({pt_str}pt){extra_note}")
            i = j

        self._save_data()
        yield event.plain_result("\n".join(result_msg))

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
            yield event.plain_result("👑 当前处于决赛阶段，请使用 /决赛榜 查询决赛战况。\n以下显示常规赛历史数据：")
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
            msg_header = "🏆 赛季排位榜"
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
            msg_header = "👑 一位次数 排行榜"
            sorted_users = sorted(users, key=lambda x: (x[1]["ranks"][0], -x[1]["total_matches"]), reverse=True)
            msg_lines = [msg_header]
            for i, (uid, data) in enumerate(sorted_users):
                msg_lines.append(f"{i+1}. {data['name']} — 一位 {data['ranks'][0]} 次 / {data['total_matches']} 场")
            
        elif query_type in ["最高得点", "最大得点"]:
            msg_header = "💥 单场最高得点 排行榜"
            sorted_users = sorted(users, key=lambda x: x[1]["max_score"], reverse=True)
            msg_lines = [msg_header]
            for i, (uid, data) in enumerate(sorted_users):
                msg_lines.append(f"{i+1}. {data['name']} — {data['max_score']} 点")
            
        elif query_type in ["避四率", "避四"]:
            msg_header = "🛡️ 避四率 排行榜 (至少5场)"
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
            f"  (有效前60战: {min(reg_m, 60)}/60 | 罚分: -{current_penalty} pt)",
            f"",
            f"📈 ===赛季对局详情=== (共 {total_games} 场)",
            f"🥇 一位率: {rates[0]} ({ranks[0]}回)",
            f"🥈 二位率: {rates[1]} ({ranks[1]}回)",
            f"🥉 三位率: {rates[2]} ({ranks[2]}回)",
            f"💀 四位率: {rates[3]} ({ranks[3]}回)",
            f"",
            f"📐 ===赛季统计===",
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

        msg_lines = ["👑 已正式进入总决赛（4强争冠）", "----------------"]
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
            yield event.plain_result("⚠️ 当前未开启决赛，请使用 /季后赛榜 或 /rank 查询。")
            return

        finalists = [d for d in ctx_data.values() if isinstance(d, dict) and d.get("is_finalist")]
        finalists.sort(key=lambda x: x.get("finals_pt", 0.0), reverse=True)

        msg = ["👑【决赛 实时排位榜】👑", "========================"]
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
    # 🎉 活动专区 (当前为：【声优吃的奇妙冒险】JOJO替身麻将)
    # =======================================================

    # 12 种「STAND POWER」替身能力一览表
    STAND_POWERS = [
        ("白金之星", "这巡内你的舍张不能被荣和。不构成振听"),
        ("世界", "这巡内的摸牌改为摸三枚，再依次打出，打出的牌可以被鸣或荣和，但不会打断你的回合（不破坏两立直、天和）"),
        ("隐者之紫", "指定一家，你可以用搓牌的方式检查他的听牌搭子（多面听则必须包括所有待牌可能），若那家实际未听，能力失效"),
        ("疯狂钻石", "允许一次立直后的手切，由此导致的未听不计为诈立直，也不破坏立直状态"),
        ("轰炸空间", "吃副露可以吃任何一家"),
        ("天堂之门", "你可以用一枚手牌和场上的任意一枚正面朝上的牌替换，若换的牌是副露，仍然视为合法生效的原副露。会构成振听"),
        ("败者食尘", "立直时使用。指定一家，同时公布你的待牌，当他摸到你的铳张时必须摸切，你不再能够荣和其他家或自摸，但对你自己不构成振听。"),
        ("绯红之王", "摸牌前使用。移除牌山中的接下来四枚牌，你可以查看这四枚牌，海底巡不可发动"),
        ("回音A.C.T.3", "现在起的两巡内，其他家不能副露鸣牌和立直"),
        ("天堂制造", "现在起的两巡内，其他家不能手切，可被除你以外的副露破坏"),
        ("黄金体验镇魂曲", "你始终不会振听，但流局始终视为未听"),
        ("天气预报", "切牌前使用。将你的一枚手牌和牌山里的一枚牌替换（宝牌指示牌除外）")
    ]

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

    @command("mj_event_toggle", alias=["event", "活动开关"])
    async def toggle_event(self, event: AstrMessageEvent):
        """[管理员] 开启或关闭本群的活动场"""
        ctx_id = self._get_context_id(event)
        current_status = self.event_data.setdefault("status", {}).get(ctx_id, False)
        self.event_data["status"][ctx_id] = not current_status
        self._save_event_data()
        state_str = "🟢 已开启" if not current_status else "🔴 已关闭"
        yield event.plain_result(f"📢 活动场【声优吃的奇妙冒险】 {state_str}！")

    @command("mj_event_start", alias=["活动对局开始", "活动开始"])
    async def start_event_match(self, event: AstrMessageEvent):
        """开始一场活动对局，并在开桌后独立推送本局抽取的6个替身"""
        ctx_id = self._get_context_id(event)
        if not self.event_data.get("status", {}).get(ctx_id, False):
            yield event.plain_result("⚠️ 当前没有正在进行的活动，请管理员使用 /活动开关 开启。")
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

        # 随机抽取 6 个候选替身能力
        selected_stands = random.sample(self.STAND_POWERS, 6)

        self.event_matches[ctx_id][match_id] = {
            "players": {user_id: user_name},
            "scores": {},
            "status": "recruiting",
            "stands": selected_stands
        }
        
        # 消息1：常规开桌信息
        yield event.plain_result(
            f"🃏 活动场 #{match_id} 已建立！\n"
            f"替身使者 {user_name} 已就位！ (1/4)\n"
            f"请其他选手发送 /活动加入 加入\n"
            f"(多桌同开时请发送 /活动加入 {match_id} 加入本桌)"
        )

        # 消息2：单独发送抽中的 6 个替身能力清单
        stand_lines = [
            f"🔮 **【活动场 #{match_id} 可选 STAND POWER】**",
            "----------------------------------------"
        ]
        for idx, (s_name, s_desc) in enumerate(selected_stands):
            stand_lines.append(f"{idx+1}. 「{s_name}」\n   {s_desc}")
        stand_lines.append("----------------------------------------")
        stand_lines.append("📌 挑选顺序：北家 ➔ 西家 ➔ 南家 ➔ 东家")
        stand_lines.append("（对局集结后依序选择，回合内喊出替身名即可发动！）")

        yield event.plain_result("\n".join(stand_lines))

    @command("mj_event_join", alias=["活动加入"])
    async def join_event_match(self, event: AstrMessageEvent, match_id: str = ""):
        """加入活动对局"""
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
            
            # 记录东南西北对应的选手名字
            wind_map = {winds[i]: player_list[i] for i in range(4)}
            players_list_str = "\n".join([f"{w}家: {wind_map[w]}" for w in winds])
            
            yield event.plain_result(
                f"✅ 活动局 #{target_mid} 集结完毕，GAME START！\n"
                f"{players_list_str}\n\n"
                f"⚡️ 请按替身选择顺序依次挑选能力：\n"
                f"👉 **北家 ({wind_map['北']}) ➔ 西家 ({wind_map['西']}) ➔ 南家 ({wind_map['南']}) ➔ 东家 ({wind_map['东']})**\n\n"
                f"🏁 对局结束后请发送：/活动得点 [点数]"
            )
        else:
            yield event.plain_result(f"替身使者 {user_name} 加入活动局 #{target_mid} ！ ({current_count}/4)")

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

    @command("mj_event_end", alias=["活动得点", "活动结束"])
    async def end_event_match(self, event: AstrMessageEvent, score: int):
        """记录活动局分数（25000持点，30000返点，马点+50/+15/-15/-30）"""
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
            # 25000持点，4家总计100000点
            if total_score != 100000:
                diff = total_score - 100000
                diff_str = f"+{diff}" if diff > 0 else f"{diff}"
                details_str = "\n".join([f"{match['players'][uid]}: {s}" for uid, s in match["scores"].items()])
                yield event.plain_result(
                    f"⚠️ 活动局 #{mid} 点数核算不通过\n"
                    f"四家得点之和为 {total_score} (误差 {diff_str})\n"
                    f"目标: 100000\n----------------\n当前提交:\n{details_str}\n"
                    f"👉 请发送 /活动得点 [正确点数] 修正。"
                )
                return 

            sorted_scores = sorted(match["scores"].items(), key=lambda x: x[1], reverse=True)
            ctx_data = self.event_data.setdefault("groups", {}).setdefault(ctx_id, {})
            result_msg = [f"🃏 **活动对局 #{mid} 结算**"]

            # 活动专用马点: +50 / +15 / -15 / -30 (30000返点)
            UMA_SLOTS = [50.0, 15.0, -15.0, -30.0]
            ICONS = ["🥇", "🥈", "🥉", "💀"]

            # 处理同分平分马点
            i = 0
            while i < len(sorted_scores):
                j = i + 1
                while j < len(sorted_scores) and sorted_scores[j][1] == sorted_scores[i][1]:
                    j += 1
                
                current_umas = UMA_SLOTS[i:j]
                avg_uma = sum(current_umas) / len(current_umas)

                for k in range(i, j):
                    uid, s = sorted_scores[k]
                    username = match["players"][uid]
                    
                    # 返点 30000: (得点 - 30000) / 1000 + 马点
                    base_pt = (s - 30000) / 1000.0
                    pt = round(base_pt + avg_uma, 1)
                    pt_str = f"+{pt}" if pt > 0 else f"{pt}"

                    user_stat = ctx_data.setdefault(uid, {
                        "name": username, "total_pt": 0.0, "total_matches": 0,
                        "total_score": 0, "max_score": 0, "ranks": [0, 0, 0, 0]
                    })

                    if "ranks" not in user_stat or not isinstance(user_stat["ranks", list]):
                        user_stat["ranks"] = [0,0,0,0]

                    if "max_score" not in user_stat:
                        user_stat["max_score"] = 0
                        
                    if "total_score" not in user_stat:
                        user_stat["total_score"] = 0

                    user_stat["name"] = username
                    user_stat["total_pt"] = round(user_stat["total_pt"] + pt, 1)
                    user_stat["total_matches"] += 1
                    user_stat["total_score"] += s
                    user_stat["ranks"][i] += 1
                    if s > user_stat.get("max_score", 0):
                        user_stat["max_score"] = s

                    result_msg.append(f"{ICONS[i]} {username}: {s} ({pt_str}pt)")
                i = j

            self._save_event_data()
            del self.event_matches[ctx_id][mid]
            if not self.event_matches[ctx_id]:
                del self.event_matches[ctx_id]
            
            yield event.plain_result("\n".join(result_msg))
        else:
            yield event.plain_result(f"💾 活动分数已记录 ({submitted_count}/4)")

    # -------------------------------------------------------
    # 🛠️ 活动管理运维工具 (清空数据 & 强制补录)
    # -------------------------------------------------------

    @command("mj_event_reset", alias=["活动清空", "活动重置", "清空活动数据"])
    async def reset_event_data(self, event: AstrMessageEvent):
        """[管理员] 完全清空当前群的活动场数据（清除旧活动残留）"""
        ctx_id = self._get_context_id(event)
        
        # 1. 清理内存中可能卡住的活动对局
        if ctx_id in self.event_matches:
            del self.event_matches[ctx_id]
            
        # 2. 清空该群持久化的活动战绩
        if "groups" in self.event_data and ctx_id in self.event_data["groups"]:
            self.event_data["groups"][ctx_id] = {}
            self._save_event_data()
            yield event.plain_result("🔄 本群【活动场】数据已完全清空！所有历史活动战绩已归零。")
        else:
            yield event.plain_result("⚠️ 当前群组暂无活动数据，无需清空。")

    @command("mj_event_manual", alias=["活动补录", "活动录分", "强制录分", "活动强制录分"])
    async def record_event_manual(self, event: AstrMessageEvent):
        """
        [管理员] 强制/手动录入一次活动场成绩
        用法支持以下两种格式（点数按@的顺序对应）：
          格式1: /活动补录 @选手A 35000 @选手B 30000 @选手C 20000 @选手D 15000
          格式2: /活动补录 @选手A @选手B @选手C @选手D 35000 30000 20000 15000
        """
        ctx_id = self._get_context_id(event)
        
        # 1. 提取被 @ 的 4 位选手
        target_uids = []
        for comp in event.get_messages():
            if isinstance(comp, At):
                target_uids.append(str(comp.qq))
        
        # 顺序去重
        unique_uids = list(dict.fromkeys(target_uids))
        if len(unique_uids) != 4:
            yield event.plain_result(
                "⚠️ 格式错误！必须同时 @ 4 位不同的选手。\n"
                "👉 正确示例：\n"
                "/活动补录 @选手1 35000 @选手2 30000 @选手3 20000 @选手4 15000\n"
                "或\n"
                "/活动补录 @选手1 @选手2 @选手3 @选手4 35000 30000 20000 15000"
            )
            return

        # 2. 从文本中提取 4 个点数
        plain_texts = []
        for comp in event.get_messages():
            if not isinstance(comp, At) and hasattr(comp, 'text'):
                plain_texts.append(comp.text)
        
        combined_text = " ".join(plain_texts)
        for cmd in ["/mj_event_manual", "/活动补录", "/活动录分", "/强制录分", "/活动强制录分"]:
            combined_text = combined_text.replace(cmd, "")
            
        scores_raw = re.findall(r'-?\d+', combined_text)
        if len(scores_raw) != 4:
            yield event.plain_result(f"⚠️ 点数数量不匹配！检测到 {len(scores_raw)} 个有效数值，必须依次提供 4 家的点数。")
            return

        scores = [int(s) for s in scores_raw]
        
        # 3. 校验总和 100000 (JOJO活动场: 25000持点*4)
        total_score = sum(scores)
        if total_score != 100000:
            diff = total_score - 100000
            diff_str = f"+{diff}" if diff > 0 else f"{diff}"
            yield event.plain_result(
                f"⚠️ 点数核对不通过！\n"
                f"四家点数总和为: {total_score} (误差 {diff_str})\n"
                f"目标总和: 100000 (2.5w持点*4)\n"
                f"👉 请检查点数是否有误。"
            )
            return

        # 4. 获取选手昵称并配对
        ctx_data = self.event_data.setdefault("groups", {}).setdefault(ctx_id, {})
        player_entries = []
        for uid, s in zip(unique_uids, scores):
            name = f"用户{uid}"
            if uid in ctx_data and ctx_data[uid].get("name"):
                name = ctx_data[uid]["name"]
            elif hasattr(self, "data") and ctx_id in self.data and uid in self.data[ctx_id]:
                name = self.data[ctx_id][uid].get("name", name)
            player_entries.append((uid, name, s))

        # 5. 排序与马点计算 (+50/+15/-15/-30，返点30000，同分平分马点)
        sorted_players = sorted(player_entries, key=lambda x: x[2], reverse=True)
        UMA_SLOTS = [50.0, 15.0, -15.0, -30.0]
        ICONS = ["🥇", "🥈", "🥉", "💀"]
        result_msg = ["🃏 **【活动场·成绩手动补录完成】**", "--------------------------------"]

        i = 0
        while i < len(sorted_players):
            j = i + 1
            while j < len(sorted_players) and sorted_players[j][2] == sorted_players[i][2]:
                j += 1
            
            current_umas = UMA_SLOTS[i:j]
            avg_uma = sum(current_umas) / len(current_umas)

            for k in range(i, j):
                uid, name, s = sorted_players[k]
                base_pt = (s - 30000) / 1000.0
                pt = round(base_pt + avg_uma, 1)
                pt_str = f"+{pt}" if pt > 0 else f"{pt}"

                user_stat = ctx_data.setdefault(uid, {
                    "name": name, "total_pt": 0.0, "total_matches": 0,
                    "total_score": 0, "max_score": 0, "ranks": [0, 0, 0, 0]
                })
                if "ranks" not in user_stat or not isinstance(user_stat["ranks"], list):
                    user_stat["ranks"] = [0, 0, 0, 0]
                if "max_score" not in user_stat:
                    user_stat["max_score"] = 0
                if "total_score" not in user_stat:
                    user_stat["total_score"] = 0

                user_stat["name"] = name
                user_stat["total_pt"] = round(user_stat["total_pt"] + pt, 1)
                user_stat["total_matches"] += 1
                user_stat["total_score"] += s
                user_stat["ranks"][i] += 1
                if s > user_stat.get("max_score", 0):
                    user_stat["max_score"] = s

                result_msg.append(f"{ICONS[i]} {name}: {s} ({pt_str}pt)")
            i = j

        self._save_event_data()
        result_msg.append("--------------------------------")
        result_msg.append("✅ 战绩已成功写入【声优吃的奇妙冒险】活动榜！")
        yield event.plain_result("\n".join(result_msg))

    @command("mj_event_rank", alias=["活动榜", "活动排行", "活动rank"])
    async def show_event_rank(self, event: AstrMessageEvent):
        """展示【声优吃的奇妙冒险】活动排行榜"""
        ctx_id = self._get_context_id(event)
        ctx_data = self.event_data.get("groups", {}).get(ctx_id, {})
        
        if not ctx_data:
            yield event.plain_result("⚠️ 暂无活动记录。")
            return

        users = list(ctx_data.values())
        if not users:
            return

        # 按活动总PT从高到低排序
        users.sort(key=lambda x: x["total_pt"], reverse=True)

        msg = ["🏆 **【声优吃的奇妙冒险】活动战力榜** 🏆\n"]
        for i, u in enumerate(users):
            avg_pts = int(u["total_score"] / u["total_matches"]) if u["total_matches"] > 0 else 0
            msg.append(f" {i+1}. {u['name']} — {u['total_pt']} pt [试合:{u['total_matches']} | 均点:{avg_pts} | 最高:{u.get('max_score', 0)}]")

        yield event.plain_result("\n".join(msg))
