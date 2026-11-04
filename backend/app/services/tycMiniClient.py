"""天眼查微信小程序端接口（同步版）——仅用于任务创建时「按公司名解析 GID」。

与 osint_service/clients/tyc_mini_client.py 同源（抓包 packet0），
应用侧只需要「名称 → GID」这一步，对外投资查询由 osint-service 侧的异步客户端完成。

接口实测匿名可用（无需 Authorization），但属于非公开接口，
可能触发风控或随时失效，故仅作兜底。
"""

import requests

BASE_URL = "https://capi.tianyancha.com"
SEARCH_PATH = "/cloud-tempest/app/searchCompany"

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


def _strip_em(value):
    if not isinstance(value, str):
        return ""
    return value.replace("<em>", "").replace("</em>", "").strip()


class TycMiniClient(object):
    """小程序端兜底客户端（同步）。"""

    def __init__(self, proxy=None, timeout=20):
        self.proxy = proxy or None
        self.timeout = timeout

    def search_company(self, word):
        """按公司名查询企业，返回 {gid, name, reg_status} 或 None。

        任何异常都返回 None，由调用方决定是否降级，不阻断任务创建。
        """
        word = (word or "").strip()
        if not word:
            return None

        proxies = None
        if self.proxy:
            url = self.proxy if "://" in self.proxy else "http://" + self.proxy
            proxies = {"http": url, "https": url}

        try:
            resp = requests.post(
                BASE_URL + SEARCH_PATH,
                json={"sortType": 0, "pageSize": 20, "pageNum": 1,
                      "word": word, "allowModifyQuery": 1},
                headers=HEADERS,
                proxies=proxies,
                timeout=self.timeout,
                verify=False,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
        except Exception:
            return None

        if data.get("state") != "ok" or data.get("errorCode") not in (0, None):
            return None

        items = (data.get("data") or {}).get("companyList") or []
        if not items:
            return None

        first = items[0]
        gid = str(first.get("id") or first.get("gidForB") or "").strip()
        if not gid:
            return None

        return {
            "gid": gid,
            "name": _strip_em(first.get("name")),
            "reg_status": _strip_em(first.get("regStatus")),
        }