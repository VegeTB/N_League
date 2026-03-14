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

@register("N_league", "Vege", "日麻对局记录插件", "2.0.0")
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
        
    def _get_user_match(self, ctx_id: str, user_id: str):
        """查找指定用户当前所在的对局ID及对局数据"""
        if ctx_id not in self.active_matches:
            return None, None
        for mid, match in self.active_matches[ctx_id].items():
            if user_id in match["players"]:
                return mid, match
        return None, None

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
        """开始一场新的对局，自动分配桌号"""
        ctx_id = self._get_context_id(event)
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        
        # 检查是否已经在其他对局中
        mid, existing_match = self._get_user_match(ctx_id, user_id)
        if existing_match:
            yield event.plain_result(f"⚠️ 你已经在对局 #{mid} 中了，无法分身！")
            return

        if ctx_id not in self.active_matches:
            self.active_matches[ctx_id] = {}
            
        # 寻找空闲桌号 (1, 2, 3...)
        match_id = 1
        while str(match_id) in self.active_matches[ctx_id]:
            match_id += 1
        match_id = str(match_id)

        # 创建并自动加入
        self.active_matches[ctx_id][match_id] = {
            "players": {user_id: user_name},
            "scores": {},
            "status": "recruiting"
        }
        
        yield event.plain_result(
            f"对局 #{match_id} 已建立！\n"
            f"选手 {user_name} 已加入！ (1/4)\n"
            f"请其他选手发送 /加入对局 加入。\n"
            f"(多桌同开时请务必加上对局ID）\n"
        )

    @command("mj_join", alias=["加入对局", "join"])
    async def join_match(self, event: AstrMessageEvent, match_id: str = ""):
        """加入当前招募中的对局"""
        ctx_id = self._get_context_id(event)
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        ctx_data = self.data.get(ctx_id, {})
        match_id = str(match_id).strip()

        # 检查是否已经在对局中
        mid, existing_match = self._get_user_match(ctx_id, user_id)
        if existing_match:
            yield event.plain_result(f"👉 {user_name} 已经在对局 #{mid} 中了。")
            return

        if ctx_id not in self.active_matches or not self.active_matches[ctx_id]:
            yield event.plain_result("⚠️ 当前没有正在招募的对局，请先发送 /对局开始")
            return

        # 决赛圈锁
        if ctx_data.get("is_playoffs", False):
            user_data = ctx_data.get(user_id)
            if not user_data or not user_data.get("is_finalist"):
                yield event.plain_result(f"🔒 决赛进行中！{user_name} 不是决赛选手，无法加入。")
                return

        target_match = None
        target_mid = None

        # 路由逻辑：寻找要加入的桌
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

        # 执行加入
        target_match["players"][user_id] = user_name
        current_count = len(target_match["players"])

        if current_count == 4:
            target_match["status"] = "playing"
            players_list = "\n".join([f"- {name}" for name in target_match["players"].values()])
            yield event.plain_result(
                f"✅ 对局 #{target_mid} 集结完毕，GAME START！\n{players_list}\n\n"
                f"🏁 结束后请本桌选手发送：/得点 [点数]"
            )
        else:
            yield event.plain_result(f"选手 {user_name} 加入对局 #{target_mid} ！ ({current_count}/4)")

    @command("mj_cancel", alias=["取消对局", "撤销对局", "关闭对局"])
    async def cancel_match(self, event: AstrMessageEvent):
        """自动识别并解散用户当前所在的对局"""
        ctx_id = self._get_context_id(event)
        user_id = event.get_sender_id()

        mid, match = self._get_user_match(ctx_id, user_id)
        
        if match:
            status = match["status"]
            del self.active_matches[ctx_id][mid]
            
            # 维护外层字典整洁
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
        """自动识别用户所在的对局并录入分数"""
        ctx_id = self._get_context_id(event)
        user_id = event.get_sender_id()
        
        mid, match = self._get_user_match(ctx_id, user_id)
        
        if not match:
            yield event.plain_result("⚠️ 你当前不在任何对局中")
            return

        if match["status"] != "playing":
            yield event.plain_result(f"⚠️ 对局 #{mid} 尚未开始")
            return

        # 记录分数 (允许覆盖修改)
        match["scores"][user_id] = score
        submitted_count = len(match["scores"])
        
        # 检查是否满4人数据
        if submitted_count == 4:
            total_score = sum(match["scores"].values())
            
            if total_score != 100000:
                diff = total_score - 100000
                diff_str = f"+{diff}" if diff > 0 else f"{diff}"
                
                details = []
                for uid, s in match["scores"].items():
                    name = match["players"][uid]
                    details.append(f"{name}: {s}")
                details_str = "\n".join(details)
                
                yield event.plain_result(
                    f"⚠️ 对局 #{mid} 点数核算不通过\n"
                    f"四家得点之和为 {total_score} (误差 {diff_str})\n"
                    f"目标: 100000\n"
                    f"----------------\n"
                    f"当前提交:\n{details_str}\n"
                    f"👉 请本桌发现错误的选手重新发送 /得点 [正确点数] 修正。"
                )
                return 

            yield event.plain_result(f"✅ 对局 #{mid} 点数核算通过 (100000)，正在结算...")
            
            for item in self._finalize_match(event, ctx_id, mid, match):
                yield item
        else:
            yield event.plain_result(f"💾 分数已记录 ({submitted_count}/4)")

    def _finalize_match(self, event, ctx_id, match, mid):
        """结算对局核心逻辑（含同分平分马点机制 + 总得点记录）"""
        sorted_scores = sorted(match["scores"].items(), key=lambda x: x[1], reverse=True)
        ctx_data = self.data.setdefault(ctx_id, {})
        result_msg =[f"🀄️ 对局结束"]
        
        UMA_SLOTS =[50.0, 10.0, -10.0, -30.0]
        ICONS =["🥇", "🥈", "🥉", "💀"]

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
                    "ranks": [0, 0, 0, 0], "max_score": 0, "total_score": 0, "avoid_4_rate": 0.0
                })
                
                if "total_score" not in user_stat: user_stat["total_score"] = 0
                user_stat["name"] = username
                user_stat["total_pt"] = round(user_stat["total_pt"] + final_pt, 1)
                user_stat["total_matches"] += 1
                user_stat["ranks"][i] += 1
                user_stat["total_score"] += score
                
                if score > user_stat["max_score"]: user_stat["max_score"] = score
                not_4th_count = sum(user_stat["ranks"][:3])
                user_stat["avoid_4_rate"] = round((not_4th_count / user_stat["total_matches"]) * 100, 2)
                
                result_msg.append(f"{ICONS[i]} {username}: {score} ({pt_str}pt)")
            i = j
            
        self._save_data()

        del self.active_matches[ctx_id][mid]
        if not self.active_matches[ctx_id]:
            del self.active_matches[ctx_id]
        
        yield event.plain_result("\n".join(result_msg))


    @command("mj_chombo", alias=["冲和", "错和", "罚分", "chombo"])
    async def chombo(self, event: AstrMessageEvent):
        """
        错和处罚：扣除指定用户 20pt
        用法: /mj_chombo @用户 [备注]
        """
        ctx_id = self._get_context_id(event)
        
        target_uid = None
        for comp in event.get_messages():
            if isinstance(comp, At):
                target_uid = str(comp.qq)
                break
        
        if not target_uid:
            yield event.plain_result("⚠️ 格式错误，请 @ 需要处罚的用户。\n示例: /chombo @某人 诈和")
            return

        reason_parts =[]
        for comp in event.get_messages():
            # 过滤掉 At 组件（艾特），仅获取其他的普通文本
            if not isinstance(comp, At) and hasattr(comp, 'text'):
                reason_parts.append(comp.text)
                
        raw_text = " ".join(reason_parts).strip()
        
        # 剔除指令本身的文字（防止把 "/mj_chombo" 也当成原因）
        for cmd in["/mj_chombo", "/冲和", "/错和", "/罚分", "mj_chombo", "冲和", "错和", "罚分"]:
            if raw_text.startswith(cmd):
                raw_text = raw_text[len(cmd):].strip()
                break
                
        # 如果提取完没剩下字，就给个默认备注
        reason = raw_text if raw_text else "无备注"
        # ------------------------

        ctx_data = self.data.setdefault(ctx_id, {})
        
        if target_uid not in ctx_data:
            ctx_data[target_uid] = {
                "name": f"用户{target_uid}",
                "total_pt": 0.0,
                "total_matches": 0,
                "ranks":[0, 0, 0, 0],
                "max_score": 0,
                "total_score": 0,
                "avoid_4_rate": 0.0
            }
        
        user_data = ctx_data[target_uid]
        user_data["total_pt"] = round(user_data["total_pt"] - 20.0, 1)
        self._save_data()
        
        # --- 修改：在返回消息中展示备注 ---
        yield event.plain_result(
            f"🚫 **Chombo 处罚执行**\n"
            f"对象: {user_data['name']}\n"
            f"原因: {reason}\n"
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
                penalty = max(0, 20 - matches) * 50
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

    @command("mj_stats", alias=["个人数据", "查数据", "战绩", "吃鱼"])
    async def my_stats(self, event: AstrMessageEvent):
        """
        查询个人或他人生涯数据
        用法: /吃鱼 (查询自己)
              /吃鱼 @被查询用户 (查询他人)
        """
        ctx_id = self._get_context_id(event)
        ctx_data = self.data.get(ctx_id, {})
        
        if not ctx_data:
            yield event.plain_result("⚠️ 暂无对局记录。")
            return

        # 1. 确定要查询的用户ID
        target_uid = event.get_sender_id() # 默认查自己
        target_name = event.get_sender_name()
        
        # 检查是否有 @
        for comp in event.get_messages():
            if isinstance(comp, At):
                target_uid = str(comp.qq)
                # 尝试从数据中获取名字，获取不到就用默认占位
                if target_uid in ctx_data:
                    target_name = ctx_data[target_uid]["name"]
                else:
                    target_name = f"用户{target_uid}"
                break

        if target_uid not in ctx_data:
            yield event.plain_result(f"⚠️ 未找到 {target_name} 的参赛记录。")
            return

        user = ctx_data[target_uid]
        total_games = user["total_matches"]
        
        if total_games == 0:
            yield event.plain_result(f"⚠️ {user['name']} 还没有完成过对局。")
            return

        # 2. 计算排名 (需要遍历所有用户)
        users_list = []
        for uid, data in ctx_data.items():
            # 计算排位分: 原始分 - 罚分
            raw_pt = data["total_pt"]
            penalty = max(0, 18 - data["total_matches"]) * 50
            ranking_pt = raw_pt - penalty
            users_list.append({
                "uid": uid,
                "raw_pt": raw_pt,
                "ranking_pt": ranking_pt
            })
        
        # 2.1 原始PT排名
        users_list.sort(key=lambda x: x["raw_pt"], reverse=True)
        raw_rank = next((i + 1 for i, u in enumerate(users_list) if u["uid"] == target_uid), "N/A")
        
        # 2.2 排位PT排名
        users_list.sort(key=lambda x: x["ranking_pt"], reverse=True)
        ranking_rank = next((i + 1 for i, u in enumerate(users_list) if u["uid"] == target_uid), "N/A")
        
        # 3. 计算各项统计数据
        ranks = user["ranks"] # [1位数, 2位数, 3位数, 4位数]
        
        # 顺位率
        rates = [f"{r / total_games * 100:.2f}%" for r in ranks]
        
        # 平均顺位: (1*数 + 2*数 + 3*数 + 4*数) / 总场数
        rank_sum = sum((i + 1) * count for i, count in enumerate(ranks))
        avg_rank_val = rank_sum / total_games
        
        # 平均点数
        total_score = user.get("total_score", 0) # 兼容旧数据
        avg_score = int(total_score / total_games)
        
        # 排位分计算细节
        current_penalty = max(0, 18 - total_games) * 50
        current_ranking_pt = user["total_pt"] - current_penalty

        # 4. 构建面板
        msg = [
            f"📊 {user['name']} 的赛季数据",
            f"------------------------",
            f"🔢 ===PT排名===",
            f"• 原始PT: {user['total_pt']} pt (第 {raw_rank} 名)",
            f"• 排位PT: {round(current_ranking_pt, 1)} pt (第 {ranking_rank} 名)",
            f"  *(罚分: -{current_penalty} pt)*",
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
            f"• 避四率: {user['avoid_4_rate']}%",
            f"",
            f"注意：Season 1的平均得点数据不全，可能不具有实际参考价值。"
        ]
        
        yield event.plain_result("\n".join(msg))
    
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
        """重置当前群组的所有数据并清除所有正在进行的对局"""
        ctx_id = self._get_context_id(event)
        
        if ctx_id in self.active_matches:
            del self.active_matches[ctx_id]

        if ctx_id in self.data:
            self.data[ctx_id] = {} 
            self._save_data()
            yield event.plain_result("🔄 赛季数据已完全重置！\n所有积分已清零，新的赛季请加油！")
        else:
            yield event.plain_result("⚠️ 当前没有数据可重置。")
