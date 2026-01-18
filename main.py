from astrbot.api.all import *
from astrbot.api.event.filter import command
import json
from astrbot.api.message_components import At
import os
import logging
from typing import Dict, List, Any

logger = logging.getLogger("MahjongPlugin")

# 数据存储路径
DATA_DIR = os.path.join("data", "plugins", "astrbot_mahjong_plugin")
os.makedirs(DATA_DIR, exist_ok=True)
DATA_FILE = os.path.join(DATA_DIR, "mahjong_data.json")

@register("N_league", "Vege", "日麻对局记录插件", "1.1.0")
class MahjongPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.data = self._load_data()
        # 运行时缓存，用于存储当前正在进行的对局状态
        # 结构: { ctx_id: { "players": {uid: name}, "scores": {uid: score}, "status": "waiting/playing" } }
        self.active_matches = {}

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
        """获取上下文ID（群组ID或私聊ID）"""
        if hasattr(event, 'group_id') and event.group_id:
            return f"group_{event.group_id}"
        if hasattr(event, 'user_id') and event.user_id:
            return f"private_{event.user_id}"
        return "default_ctx"

    def _calculate_pt_custom(self, score: int, rank: int) -> float:
        """
        计算PT逻辑
        """
        # M-League 规则: (Score - 30000) / 1000 + Uma
        uma_map = {1: 50.0, 2: 10.0, 3: -10.0, 4: -30.0}
        
        # M-League计算公式：((得分 - 30000) / 1000) + 马点
        pt = (score - 30000) / 1000.0 + (uma_map.get(rank, 0) - (20.0 if rank == 1 else 0))
        
        final_uma = {1: 50.0, 2: 10.0, 3: -10.0, 4: -30.0}
        return round((score - 30000) / 1000.0 + final_uma[rank], 1)

    @command("mj_start", alias=["对局开始", "开房"])
    async def start_match(self, event: AstrMessageEvent):
        """开始一场新的对局，等待4人加入"""
        ctx_id = self._get_context_id(event)
        
        self.active_matches[ctx_id] = {
            "players": {}, # {uid: username}
            "scores": {},  # {uid: score}
            "status": "recruiting"
        }
        
        yield event.plain_result(
            "🀄️ 对局已建立！\n"
            "请4位参赛者发送 /加入对局 加入比赛。\n"
            "人满后自动开始记录。"
        )

    @command("mj_join", alias=["加入对局", "join"])
    async def join_match(self, event: AstrMessageEvent):
        """加入当前对局"""
        ctx_id = self._get_context_id(event)
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        ctx_data = self.data.get(ctx_id, {})

        if ctx_id not in self.active_matches:
            yield event.plain_result("⚠️ 当前没有正在招募的对局，请先发送 /mj_start")
            return

        match = self.active_matches[ctx_id]
        
        if match["status"] != "recruiting":
            yield event.plain_result("⚠️ 对局已经开始或正在结算，无法加入。")
            return

        if user_id in match["players"]:
            yield event.plain_result(f"👉 {user_name} 已经在对局中了。")
            return

        if len(match["players"]) >= 4:
            yield event.plain_result("🚫 人数已满！")
            return

        # --- 决赛模式检查 ---
        if ctx_data.get("is_playoffs", False):
            # 获取用户数据，检查是否有决赛资格
            user_data = ctx_data.get(user_id)
            if not user_data or not user_data.get("is_finalist"):
                yield event.plain_result(f"🔒 决赛进行中！{user_name} 不是决赛选手，无法加入。")
                return
        # ------------------

        match["players"][user_id] = user_name
        current_count = len(match["players"])

        if current_count == 4:
            match["status"] = "playing"
            players_list = "\n".join([f"- {name}" for name in match["players"].values()])
            yield event.plain_result(
                f"✅ 4人集结完毕，对局开始！\n{players_list}\n\n"
                "🏁 对局结束后，请每位玩家发送：\n"
                "/得点 [点数] (例如: /得点 35000)\n"
                "当4人都提交后将自动结算。"
            )
        else:
            yield event.plain_result(f"👋 {user_name} 加入成功 ({current_count}/4)")

    @command("mj_cancel", alias=["取消对局", "撤销对局", "关闭对局"])
    async def cancel_match(self, event: AstrMessageEvent):
        """取消当前正在招募或进行的对局"""
        ctx_id = self._get_context_id(event)

        if ctx_id in self.active_matches:
            status = self.active_matches[ctx_id]["status"]
            del self.active_matches[ctx_id]
            
            if status == "recruiting":
                yield event.plain_result("🚫 已关闭当前的对局招募。")
            else:
                yield event.plain_result("🚫 已强制中止当前对局，本局数据不予记录。")
        else:
            yield event.plain_result("⚠️ 当前没有正在进行的对局。")

    @command("mj_end", alias=["对局结束", "得点"])
    async def end_match(self, event: AstrMessageEvent, score: int):
        """提交点数并尝试结算"""
        ctx_id = self._get_context_id(event)
        user_id = event.get_sender_id()
        
        if ctx_id not in self.active_matches:
            yield event.plain_result("⚠️ 当前没有进行中的对局。")
            return
            
        match = self.active_matches[ctx_id]
        
        if match["status"] != "playing":
            yield event.plain_result("⚠️ 对局尚未开始，请等待4人加入。")
            return

        if user_id not in match["players"]:
            yield event.plain_result("⚠️ 你不是本局参赛者，无法提交成绩。")
            return

        # 记录分数 (允许覆盖)
        match["scores"][user_id] = score
        submitted_count = len(match["scores"])
        
        # 检查是否满4人数据
        if submitted_count == 4:
            # --- 新增：10万点检查逻辑 ---
            total_score = sum(match["scores"].values())
            
            if total_score != 100000:
                diff = total_score - 100000
                diff_str = f"+{diff}" if diff > 0 else f"{diff}"
                
                # 构建当前提交详情，方便查错
                details = []
                for uid, s in match["scores"].items():
                    name = match["players"][uid]
                    details.append(f"{name}: {s}")
                details_str = "\n".join(details)
                
                yield event.plain_result(
                    f"⚠️ **点数核算失败**\n"
                    f"四家得点之和为 {total_score} (误差 {diff_str})\n"
                    f"目标: 100000\n"
                    f"----------------\n"
                    f"当前提交:\n{details_str}\n"
                    f"----------------\n"
                    f"👉 请发现输入错误的玩家重新发送 /mj_end [正确点数] 进行修正。"
                )
                return # 终止结算，保留 active_matches 状态

            # --- 校验通过，开始结算 ---
            yield event.plain_result("✅ 点数校验无误 (100000)，正在结算...")
            
            for item in self._finalize_match(event, ctx_id, match):
                yield item
        else:
            yield event.plain_result(f"💾 分数已记录 ({submitted_count}/4)")

    def _finalize_match(self, event, ctx_id, match):
        """结算对局核心逻辑"""
        sorted_scores = sorted(match["scores"].items(), key=lambda x: x[1], reverse=True)
        
        ctx_data = self.data.setdefault(ctx_id, {})
        result_msg = ["🀄️ **本局结算**"]
        
        for rank_idx, (uid, score) in enumerate(sorted_scores):
            rank = rank_idx + 1
            username = match["players"][uid]
            
            pt_change = self._calculate_pt_custom(score, rank)
            pt_str = f"+{pt_change}" if pt_change > 0 else f"{pt_change}"
            
            user_stat = ctx_data.setdefault(uid, {
                "name": username,
                "total_pt": 0.0,
                "total_matches": 0,
                "ranks": [0, 0, 0, 0],
                "max_score": 0,
                "avoid_4_rate": 0.0
            })
            
            user_stat["name"] = username
            user_stat["total_pt"] = round(user_stat["total_pt"] + pt_change, 1)
            user_stat["total_matches"] += 1
            user_stat["ranks"][rank-1] += 1
            
            if score > user_stat["max_score"]:
                user_stat["max_score"] = score
            
            not_4th_count = sum(user_stat["ranks"][:3])
            user_stat["avoid_4_rate"] = round((not_4th_count / user_stat["total_matches"]) * 100, 2)
            
            icon = ["🥇", "🥈", "🥉", "💀"][rank-1]
            result_msg.append(f"{icon} {username}: {score} ({pt_str}pt)")

        self._save_data()
        del self.active_matches[ctx_id]
        
        yield event.plain_result("\n".join(result_msg))

    @command("mj_chombo", alias=["冲和", "错和", "罚分", "chombo"])
    async def chombo(self, event: AstrMessageEvent):
        """
        错和处罚：扣除指定用户 20pt
        用法: /mj_chombo @用户
        """
        ctx_id = self._get_context_id(event)
        
        # 1. 解析被 @ 的用户
        target_uid = None
        for comp in event.get_messages():
            if isinstance(comp, At):
                target_uid = str(comp.qq)
                break
        
        if not target_uid:
            yield event.plain_result("⚠️ 格式错误，请 @ 需要处罚的用户。\n示例: /chombo @某人")
            return

        # 2. 获取数据 (如果不存在则初始化，防止报错)
        ctx_data = self.data.setdefault(ctx_id, {})
        
        if target_uid not in ctx_data:
            # 初始化新用户
            ctx_data[target_uid] = {
                "name": f"用户{target_uid}", # 没玩过对局的人没有记录名字，用ID暂代
                "total_pt": 0.0,
                "total_matches": 0,
                "ranks": [0, 0, 0, 0],
                "max_score": 0,
                "avoid_4_rate": 0.0
            }
        
        user_data = ctx_data[target_uid]
        
        # 3. 执行处罚 (-20pt)
        user_data["total_pt"] = round(user_data["total_pt"] - 20.0, 1)
        
        self._save_data()
        
        yield event.plain_result(
            f"🚫 **Chombo 处罚执行**\n"
            f"对象: {user_data['name']}\n"
            f"惩罚: -20 pt\n"
            f"当前 PT: {user_data['total_pt']}"
        )

    @command("mj_rank", alias=["rank", "排行", "Rank", "RANK"])
    async def show_rank(self, event: AstrMessageEvent, query_type: str):
        """
        查询排行榜
        参数: pt / 排位 / 位次 / 最高得点 / 避四率
        """
        ctx_id = self._get_context_id(event)
        ctx_data = self.data.get(ctx_id, {})
        
        if not ctx_data:
            yield event.plain_result("⚠️ 暂无对局记录。")
            return

        # 决赛模式提示
        if ctx_data.get("is_playoffs"):
             yield event.plain_result("🏆 当前处于季后赛，请使用 /finals_rank 或 /决赛榜 查询决赛战况。\n以下显示常规赛历史数据：")

        users = list(ctx_data.items())
        msg_lines = []

        # --- 1. 原始PT榜 (Total PT) ---
        if query_type.lower() in ["pt", "原始pt", "分数", "总分"]:
            msg_header = "📊 **常规赛 PT榜** "
            # 按 total_pt 排序
            sorted_users = sorted(users, key=lambda x: x[1]["total_pt"], reverse=True)
            
            msg_lines = [msg_header]
            for i, (uid, data) in enumerate(sorted_users):
                msg_lines.append(f"{i+1}. {data['name']} — {data['total_pt']} pt [试合:{data['total_matches']}]")
            
        # --- 2. 排位PT榜 (Ranking PT, 含罚分) ---
        elif query_type in ["排位", "排名", "排位pt", "ranking"]:
            msg_header = "🏆 **赛季排位榜**"
            
            # 临时列表用于排序: (uid, data, ranking_pt, penalty)
            ranked_list = []
            for uid, data in users:
                raw_pt = data["total_pt"]
                matches = data["total_matches"]
                penalty = max(0, 18 - matches) * 50
                ranking_pt = raw_pt - penalty
                ranked_list.append((uid, data, ranking_pt, penalty))
            
            # 按计算后的排位分排序
            ranked_list.sort(key=lambda x: x[2], reverse=True)
            
            msg_lines = [msg_header]
            for i, (uid, data, r_pt, penalty) in enumerate(ranked_list):
                # 显示: 排名. 名字 — 排位分 (罚:xxx)
                note = f"(罚:{penalty})" if penalty > 0 else ""
                # 如果是决赛选手，可以加个标记（可选）
                mark = "🔥" if data.get("is_finalist") else ""
                
                msg_lines.append(f"{i+1}. {data['name']} {mark} — {round(r_pt, 1)} pt {note} [{data['total_matches']}/18]")

        # --- 3. 其他常规榜单 ---
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
            yield event.plain_result("❓ 未知查询类型。\n请使用: pt (原始分), 排位 (含罚分), 位次, 最高得点, 避四率")
            return

        yield event.plain_result("\n".join(msg_lines))

    @command("mj_finals_setup", alias=["进入决赛", "季后赛初始化"])
    async def setup_finals(self, event: AstrMessageEvent):
        """
        [管理员] 初始化决赛模式
        用法: /mj_finals_setup @选手1 @选手2 @选手3 @选手4
        逻辑: (原始PT - 缺席罚分) / 2 = 决赛初始分
        """
        ctx_id = self._get_context_id(event)
        ctx_data = self.data.setdefault(ctx_id, {})

        if ctx_data.get("is_playoffs"):
            yield event.plain_result("⚠️ 错误：当前已经是决赛模式！请勿重复执行。")
            return

        # 解析 4 位决赛选手
        target_uids = []
        for comp in event.get_messages():
            if isinstance(comp, At):
                target_uids.append(str(comp.qq))
        target_uids = list(set(target_uids))

        if len(target_uids) != 4:
            yield event.plain_result(f"⚠️ 必须指定 4 位选手！当前检测到 {len(target_uids)} 人。")
            return

        msg_lines = ["🏆 **已进入季后赛**", "----------------"]
        
        for uid in target_uids:
            if uid not in ctx_data:
                ctx_data[uid] = {"name": f"选手{uid}", "total_pt": 0.0, "total_matches": 0, "ranks": [0,0,0,0], "max_score": 0, "avoid_4_rate": 0.0}
            
            user = ctx_data[uid]
            
            # 1. 计算常规赛最终排位分 (含罚分逻辑)
            raw_pt = user["total_pt"]
            matches = user["total_matches"]
            penalty = max(0, 18 - matches) * 50
            ranking_pt = raw_pt - penalty
            
            # 2. 备份数据 (评奖用)
            user["regular_raw_pt"] = raw_pt          # 原始分
            user["regular_ranking_pt"] = ranking_pt  # 罚分后的排位分
            
            # 3. 决赛初始分 = 排位分 / 2
            start_pt = round(ranking_pt / 2, 1)
            user["total_pt"] = start_pt
            
            # 4. 标记决赛身份
            user["is_finalist"] = True
            
            msg_lines.append(f"👤 {user['name']}")
            msg_lines.append(f"   常规赛: {raw_pt} (罚:{penalty}) = {ranking_pt}")
            msg_lines.append(f"   决赛起始: {start_pt} pt")

        ctx_data["is_playoffs"] = True
        self._save_data()

        msg_lines.append("----------------")
        msg_lines.append("✅ 决赛圈已锁定，非决赛选手将无法加入对局。")
        msg_lines.append("📊 请使用 /决赛榜 或 /finals_rank 查询决赛榜单。")
        
        yield event.plain_result("\n".join(msg_lines))

    @command("mj_finals_rank", alias=["决赛榜", "finals_rank"])
    async def show_finals_rank(self, event: AstrMessageEvent):
        """显示决赛实时排行榜"""
        ctx_id = self._get_context_id(event)
        ctx_data = self.data.get(ctx_id, {})
        
        if not ctx_data.get("is_playoffs"):
            yield event.plain_result("⚠️ 当前未进行季后赛，请使用 /rank。")
            return

        finalists = []
        for uid, data in ctx_data.items():
            if isinstance(data, dict) and data.get("is_finalist"):
                finalists.append(data)
        
        finalists.sort(key=lambda x: x["total_pt"], reverse=True)

        msg = ["🏆 **决赛 实时排位**", "(起始分 = 常规赛排位分 / 2)"]
        for i, user in enumerate(finalists):
            # 显示格式：排名. 名字 — 当前总分 (决赛起始分: xxx)
            start_pt = user.get("regular_ranking_pt", 0) / 2 # 重新算一下仅仅为了展示，或者取 total_pt
            # 其实直接显示当前分即可，因为 total_pt 已经是折半后+决赛变动的总和了
            msg.append(f"{i+1}. {user['name']} — {user['total_pt']} pt")
            
        yield event.plain_result("\n".join(msg))

    @command("mj_reset", alias=["新赛季"])
    async def reset_season(self, event: AstrMessageEvent):
        """重置当前群组的所有数据（开启新赛季）"""
        ctx_id = self._get_context_id(event)
        
        # 1. 检查是否有正在进行的对局，强制清理
        if ctx_id in self.active_matches:
            del self.active_matches[ctx_id]
            logger.info(f"Context {ctx_id} active match cleared due to season reset.")

        # 2. 清除数据库中的所有记录（包括决赛标记 is_playoffs）
        if ctx_id in self.data:
            self.data[ctx_id] = {} # 这一步会彻底抹除决赛状态
            self._save_data()
            yield event.plain_result("🔄 赛季数据已完全重置！\n所有积分已清零，敬请期待新赛季！")
        else:
            yield event.plain_result("⚠️ 当前没有数据可重置。")
