"""天眼查微信小程序端接口客户端（无需商业凭据）——官方 API 未配置或失效时的兜底方案。

依据抓包 packet0 / packet1 实现，两个接口均已实测**匿名可用**（无需 Authorization）：

    POST /cloud-tempest/app/searchCompany                       按公司名搜企业 → id
    POST /cloud-company-background/company/investListV2         按 id 查对外投资

请求头需带小程序标识（version: TYC-XCX-WX、xweb_xhr、微信小程序 UA 与 Referer），
否则会被识别为非小程序来源。

对外投资支持按持股比例区间过滤：percentLevelStart = 用户设置的下限，percentLevelEnd = 100。

能力边界（务必知悉）：
    · 仅支持「按名称搜企业」与「对外投资穿透」两条链路
    · 网站 / APP / 公众号 / 微博 / 小程序备案等维度没有对应接口，统一返回空
    · 属于非公开接口，可能触发风控、返回不完整数据，或随时失效
"""

import asyncio
import logging

import aiohttp

BASE_URL = "https://capi.tianyancha.com"
SEARCH_PATH = "/cloud-tempest/app/searchCompany"
INVEST_PATH = "/cloud-company-background/company/investListV2"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
      "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
      "UnifiedPCWindowsWechat(0xf2541113) XWEB/16771")
REFERER = "https://servicewechat.com/wx9f2867fc22873452/151/page-frame.html"

HEADERS = {
    "Content-Type": "application/json",
    "Version": "TYC-XCX-WX",
    "xweb_xhr": "1",
    "User-Agent": UA,
    "Referer": REFERER,
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


class TycMiniException(Exception):
    pass


class TycMiniClient(object):
    """小程序端兜底客户端。

    方法与 AsyncTycClient 保持同名，便于在作业里直接替换：
    不支持的方法返回空列表，作业会按「未查询到记录」正常继续。
    """

    def __init__(self, percent_start=0, proxy=None, timeout=20):
        self.percent_start = self._normalize_percent(percent_start)
        self.proxy = proxy or None
        self.timeout = timeout
        self.page_size = 100
        self.logger = logging.getLogger(__name__)
        # gid -> 企业全称（由搜索结果缓存，供 get_company_name 使用）
        self._name_cache = {}

    @staticmethod
    def _normalize_percent(value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return 0
        return max(0, min(v, 100))

    # ---------------- 底层请求 ----------------
    async def _post(self, path, payload):
        url = BASE_URL + path
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout, headers=HEADERS) as session:
            async with session.post(url, json=payload, proxy=self.proxy) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise TycMiniException("天眼查小程序接口 HTTP {}: {}".format(resp.status, text[:120]))

        import json
        try:
            data = json.loads(text)
        except Exception as exc:
            raise TycMiniException("天眼查小程序接口响应非 JSON: {}".format(exc))

        if data.get("state") != "ok" or data.get("errorCode") not in (0, None):
            raise TycMiniException("天眼查小程序接口返回异常: state={} errorCode={} message={}".format(
                data.get("state"), data.get("errorCode"), data.get("message")))
        return data

    # ---------------- 能力 1：按公司名搜企业（packet0） ----------------
    async def search_company(self, word):
        """按公司名查询企业，返回 {gid, name, reg_status} 或 None。"""
        word = (word or "").strip()
        if not word:
            return None

        data = await self._post(SEARCH_PATH, {
            "sortType": 0, "pageSize": 20, "pageNum": 1,
            "word": word, "allowModifyQuery": 1,
        })
        body = data.get("data") or {}
        items = body.get("companyList") or []
        if not items:
            return None

        first = items[0]
        gid = str(first.get("id") or first.get("gidForB") or "").strip()
        if not gid:
            return None

        # 搜索结果里的企业名带 <em> 高亮标签，需要剥离
        name = self._strip_em(first.get("name"))
        if name:
            self._name_cache[gid] = name

        return {
            "gid": gid,
            "name": name,
            "reg_status": self._strip_em(first.get("regStatus")),
        }

    @staticmethod
    def _strip_em(value):
        if not isinstance(value, str):
            return ""
        return value.replace("<em>", "").replace("</em>", "").strip()

    # ---------------- 能力 2：对外投资（packet1） ----------------
    async def get_invest_list(self, gid):
        """按 GID 拉取对外投资，持股比例区间为 [percent_start, 100]。"""
        if not gid:
            return []

        results = []
        page_num = 1
        while page_num <= 20:
            data = await self._post(INVEST_PATH, {
                "gid": str(gid),
                "pageSize": self.page_size,
                "pageNum": page_num,
                "benefitSharesType": 1,
                "registation": "-100",
                "province": "-100",
                "category": "-100",
                "percentLevelStart": int(self.percent_start),
                "percentLevelEnd": 100,
                "fullSearchText": "",
            })
            body = data.get("data") or {}
            items = body.get("result") or []
            total = body.get("total") or 0

            for item in items:
                sub_gid = str(item.get("id") or "").strip()
                if sub_gid and item.get("name"):
                    self._name_cache[sub_gid] = self._strip_em(item.get("name"))
            results.extend(items)

            if len(results) >= total or len(items) < self.page_size:
                break
            page_num += 1
            await asyncio.sleep(1.5)

        self.logger.info("天眼查兜底接口：GID %s 对外投资 %d 条（持股比例 ≥ %s%%）",
                         gid, len(results), self.percent_start)
        return results

    # ---------------- 与 AsyncTycClient 对齐的其余方法 ----------------
    async def get_company_name(self, gid):
        """兜底接口没有「按 GID 反查名称」的能力，只能返回已缓存的结果。"""
        return self._name_cache.get(str(gid), "")

    async def get_web_list(self, gid):
        return []

    async def get_app_list(self, gid):
        return []

    async def get_wechat_list(self, gid):
        return []

    async def get_mini_program_list(self, gid):
        return []

    async def get_weibo_list(self, gid):
        return []

    async def get_icp_record_list(self, gid):
        return []

    async def get_app_icp_record_list(self, gid):
        return []