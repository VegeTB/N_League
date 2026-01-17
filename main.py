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

@register("N_league", "Vege", "日麻对局记录插件", "1.0.0")
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
        计算PT逻辑 (默认 M-League 规则)
        请根据您的群规修改此处
        """
        # M-League 规则: (Score - 30000) / 1000 + Uma
        # Uma: +30 / +10 / -10 / -30
        uma_map = {1: 50.0, 2: 10.0, 3: -10.0, 4: -30.0}
        # 注意：rank 1 的 50.0 包含了 (30马点 + 20冈)
        # 如果您的规则是 (Score - 30000)/1000 + 马点(15/5/-5/-15) + 25000原点，请自行调整
        
        # M-League计算公式：((得分 - 30000) / 1000) + 马点
        # 实际上 M-League 1位马点是+50 (含oka)，2位+10，3位-10，4位-30
        pt = (score - 30000) / 1000.0 + (uma_map.get(rank, 0) - (20.0 if rank == 1 else 0))
        # 修正: 上面的写法有点乱，直接写死 M-League 最终值方便理解
        # 1位: (Score-30000)/1000 + 50
        # 2位: (Score-30000)/1000 + 10
        # 3位: (Score-30000)/1000 - 10
        # 4位: (Score-30000)/1000 - 30
        
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
            "🀄️ 对局室已建立！\n"
            "请4位参赛者发送 /mj_join 加入比赛。\n"
            "人满后自动开始记录。"
        )

    @command("mj_join", alias=["加入对局", "join"])
    async def join_match(self, event: AstrMessageEvent):
        """加入当前对局"""
        ctx_id = self._get_context_id(event)
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()

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

        # 加入玩家
        match["players"][user_id] = user_name
        current_count = len(match["players"])

        if current_count == 4:
            match["status"] = "playing"
            players_list = "\n".join([f"- {name}" for name in match["players"].values()])
            yield event.plain_result(
                f"✅ 4人集结完毕，对局开始！\n{players_list}\n\n"
                "🏁 对局结束后，请每位玩家发送：\n"
                "/mj_end [点数] (例如: /mj_end 35000)\n"
                "当4人都提交后将自动结算。"
            )
        else:
            yield event.plain_result(f"👋 {user_name} 加入成功 ({current_count}/4)")

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

        # 记录分数
        match["scores"][user_id] = score
        submitted_count = len(match["scores"])
        
        yield event.plain_result(f"💾 分数已记录 ({submitted_count}/4)")

        # 检查是否满4人数据
        if submitted_count == 4:
            # 修复了 yield from 报错，改用 for 循环 yield
            for item in self._finalize_match(event, ctx_id, match):
                yield item

    def _finalize_match(self, event, ctx_id, match):
        """结算对局核心逻辑"""
        # 1. 排序确定位次 (按分数降序)
        sorted_scores = sorted(match["scores"].items(), key=lambda x: x[1], reverse=True)
        
        # 2. 计算PT并更新生涯数据
        ctx_data = self.data.setdefault(ctx_id, {})
        result_msg = ["🀄️ **本局结算**"]
        
        for rank_idx, (uid, score) in enumerate(sorted_scores):
            rank = rank_idx + 1 # 1, 2, 3, 4
            username = match["players"][uid]
            
            # 计算本场PT
            pt_change = self._calculate_pt_custom(score, rank)
            pt_str = f"+{pt_change}" if pt_change > 0 else f"{pt_change}"
            
            # 更新生涯数据
            user_stat = ctx_data.setdefault(uid, {
                "name": username,
                "total_pt": 0.0,
                "total_matches": 0,
                "ranks": [0, 0, 0, 0], # [1位次数, 2位, 3位, 4位]
                "max_score": 0,
                "avoid_4_rate": 0.0
            })
            
            # 更新名字（防止改名）
            user_stat["name"] = username
            
            # 基础累加
            user_stat["total_pt"] = round(user_stat["total_pt"] + pt_change, 1)
            user_stat["total_matches"] += 1
            user_stat["ranks"][rank-1] += 1
            
            # 更新最高得点
            if score > user_stat["max_score"]:
                user_stat["max_score"] = score
            
            # 更新避四率 (非4位次数 / 总场数)
            not_4th_count = sum(user_stat["ranks"][:3])
            user_stat["avoid_4_rate"] = round((not_4th_count / user_stat["total_matches"]) * 100, 2)
            
            # 构建输出消息
            icon = ["🥇", "🥈", "🥉", "💀"][rank-1]
            result_msg.append(f"{icon} {username}: {score} ({pt_str}pt)")

        # 3. 保存并清除缓存
        self._save_data()
        del self.active_matches[ctx_id]
        
        yield event.plain_result("\n".join(result_msg))

    @command("mj_chombo", alias=["冲和", "错和", "罚分"])
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
            yield event.plain_result("⚠️ 格式错误，请 @ 需要处罚的用户。\n示例: /mj_chombo @某人")
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
        参数: pt / 位次 / 最高得点 / 避四率
        """
        ctx_id = self._get_context_id(event)
        ctx_data = self.data.get(ctx_id, {})
        
        if not ctx_data:
            yield event.plain_result("⚠️ 暂无对局记录。")
            return

        # 转换为列表以便排序: [(uid, data), ...]
        users = list(ctx_data.items())
        
        msg_header = ""
        sorted_users = []

        if query_type.lower() in ["pt", "分数"]:
            msg_header = "🏆 **生涯 PT 排行榜**"
            sorted_users = sorted(users, key=lambda x: x[1]["total_pt"], reverse=True)
            formatter = lambda d: f"{d['total_pt']} pt"
            
        elif query_type in ["位次", "一位率"]:
            msg_header = "👑 **一位次数 排行榜**"
            # 按一位次数排序，同一次数按总场数少者优先（胜率高）
            sorted_users = sorted(users, key=lambda x: (x[1]["ranks"][0], -x[1]["total_matches"]), reverse=True)
            formatter = lambda d: f"一位 {d['ranks'][0]} 次 / {d['total_matches']} 场"
            
        elif query_type in ["最高得点", "最大得点"]:
            msg_header = "💥 **单场最高得点 排行榜**"
            sorted_users = sorted(users, key=lambda x: x[1]["max_score"], reverse=True)
            formatter = lambda d: f"{d['max_score']} 点"
            
        elif query_type in ["避四率", "避四"]:
            msg_header = "🛡️ **避四率 排行榜** (至少5场)"
            # 过滤场数过少的人
            valid_users = [u for u in users if u[1]["total_matches"] >= 5]
            sorted_users = sorted(valid_users, key=lambda x: x[1]["avoid_4_rate"], reverse=True)
            formatter = lambda d: f"{d['avoid_4_rate']}% (共{d['total_matches']}场)"
            
        else:
            yield event.plain_result("❓ 未知查询类型。请使用: pt, 位次, 最高得点, 避四率")
            return

        msg_lines = [msg_header]
        
        # 修复: 移除 [:15] 限制，显示所有玩家
        for i, (uid, data) in enumerate(sorted_users): 
            stats_str = formatter(data)
            msg_lines.append(f"{i+1}. {data['name']} — {stats_str} [试合:{data['total_matches']}]")

        yield event.plain_result("\n".join(msg_lines))

    @command("mj_reset", alias=["新赛季"])
    async def reset_season(self, event: AstrMessageEvent):
        """重置当前群组的所有数据（开启新赛季）"""
        ctx_id = self._get_context_id(event)
        
        if ctx_id in self.data:
            self.data[ctx_id] = {}
            self._save_data()
            yield event.plain_result("🔄 数据已重置，新赛季开始！")
        else:
            yield event.plain_result("⚠️ 当前没有数据可重置。")
