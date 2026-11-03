"""0.zone（零零信安）移动端资产查询客户端。

接口契约（已用真实 API KEY 实测确认）：
    POST https://0.zone/api/data/
    Content-Type: application/json
    body: {"query": ..., "query_type": "apk", "page": N, "pagesize": M, "zone_key_id": ...}
    响应: {"code": 0, "message": "success", "total": N, "data": [...]}，code 非 0 即失败

查询语法（重要）：
    `type=="微信小程序"&&group=="企业全称"`
    · 小程序 / 公众号 / APK 同属 apk 模块，靠记录里的 type 字段区分
    · **&& 两侧不能有空格**：写成 `type=="x" && group=="y"` 会被服务端解析成
      字段 `' group'` 并报「当前移动端应用不支持使用 ' group' 查询」
    · 支持的 query_type 仅：site / app / apk / email / code / darknet / domain / org / member / branch

记录结构：
    {
      "title": "腾讯营销游戏行业顾问",      # 名称
      "type": "微信公众号",                  # 或 微信小程序 / 安卓APK
      "company": "深圳市腾讯计算机系统有限公司",
      "group": "深圳市腾讯计算机系统有限公司",
      "msg": {"wechat_id": "...", "iconUrl": "...", ...},
      "timestamp": "2026-10-14 10:26:17"
    }
"""

import asyncio
import json
import logging

import aiohttp

API_URL = "https://0.zone/api/data/"

# 记录 type 字段的取值
TYPE_MP = "微信小程序"
TYPE_OA = "微信公众号"


class ZeroZoneClient(object):
    def __init__(self, key, proxy=None, timeout=60):
        self.key = (key or "").strip()
        self.proxy = proxy or None
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

    async def query(self, asset_type, company_name, pagesize=100, max_page=5):
        """按企业全称查询指定类型（小程序 / 公众号）的资产。

        :param asset_type: TYPE_MP 或 TYPE_OA
        :param company_name: 企业工商全称
        :return: 原始记录列表
        """
        if not self.key:
            raise RuntimeError("未配置 0.zone API KEY，请先在系统设置中填写")

        company_name = (company_name or "").strip()
        if not company_name:
            return []

        # 注意：&& 两侧不能有空格，否则服务端会把字段名解析成 "' group'"
        query = 'type=="{}"&&group=="{}"'.format(asset_type, company_name)

        results = []
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        headers = {"Content-Type": "application/json"}

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for page in range(1, max_page + 1):
                payload = {
                    "query": query,
                    "query_type": "apk",
                    "page": page,
                    "pagesize": pagesize,
                    "zone_key_id": self.key,
                }
                async with session.post(API_URL, json=payload, proxy=self.proxy) as resp:
                    text = await resp.text()
                    if resp.status != 200:
                        raise RuntimeError("0.zone HTTP {}: {}".format(resp.status, text[:200]))

                try:
                    data = json.loads(text)
                except Exception as exc:
                    raise RuntimeError("0.zone 响应非 JSON: {} ({})".format(text[:200], exc))

                code = data.get("code")
                if code != 0:
                    raise RuntimeError("0.zone 查询失败 code={} message={}".format(
                        code, data.get("message")))

                items = data.get("data")
                if not isinstance(items, list) or not items:
                    break

                results.extend(items)

                # 不满一页说明已到末页
                if len(items) < pagesize:
                    break

                # 免费额度按请求次数计，翻页之间稍作停顿
                await asyncio.sleep(1)

        self.logger.info("0.zone %s 查询完成: %s 条 (company=%s)",
                         asset_type, len(results), company_name)
        return results