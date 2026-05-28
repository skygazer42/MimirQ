"""
Named governance rule packs.

Rule packs are *optional* presets that expand into additional RegexRule entries.
They are disabled by default and must be explicitly enabled via pipeline options
or governance profiles.
"""

from __future__ import annotations

from app.rag.preprocessing.cleaning import RegexRule

# Keep rule packs conservative and line-oriented. Prefer anchored patterns to avoid
# removing real content in the middle of paragraphs.
GOVERNANCE_RULE_PACKS: dict[str, list[RegexRule]] = {
    "web_cookie_banners": [
        # Headings / banners.
        RegexRule(pattern=r"(?mi)^\s*cookie\s+consent\b.*$", repl="", flags=0),
        # Common banner lines.
        RegexRule(pattern=r"(?mi)^\s*we\s+use\s+cookies?\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*this\s+(?:site|website)\s+uses\s+cookies?\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*by\s+continuing\s+to\s+(?:use|browse|navigate)\b.*cookies?\b.*$", repl="", flags=0),
        # Button-like standalone lines.
        RegexRule(pattern=r"(?mi)^\s*(?:accept|agree|allow)\s+cookies?\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*(?:reject|decline)\s+cookies?\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*manage\s+(?:cookies?|preferences?)\s*$", repl="", flags=0),
    ],
    "email_disclaimer": [
        # Confidentiality / intended recipient.
        RegexRule(pattern=r"(?mi)^\s*this\s+(?:e-?mail|email|message)\b.*\bintended\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*(?:and\s+)?may\s+contain\s+(?:confidential|privileged)\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*if\s+you\s+are\s+not\s+(?:the\s+)?intended\s+recipient\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*please\s+(?:notify|contact)\s+the\s+sender\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*(?:delete|destroy)\s+(?:this\s+)?e-?mail\b.*$", repl="", flags=0),
        # Disclaimer about opinions / security.
        RegexRule(pattern=r"(?mi)^\s*any\s+views?\s+or\s+opinions?\s+(?:presented|expressed)\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*e-?mail\s+transmission\s+cannot\s+be\s+guaranteed\b.*$", repl="", flags=0),
    ],
    "web_navigation": [
        # Common navigation prompts.
        RegexRule(pattern=r"(?mi)^\s*(?:skip|jump)\s+to\s+content\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*back\s+to\s+top\s*$", repl="", flags=0),
        # Share blocks / buttons (line-oriented).
        RegexRule(pattern=r"(?mi)^\s*share\s+this\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*share\s+on\s+(?:twitter|x|facebook|linkedin)\b.*$", repl="", flags=0),
        # Breadcrumb-like headers ("Home / ...", "Home > ...", "Home » ...").
        RegexRule(pattern=r"(?mi)^\s*home\s*(?:/|>|»|\|)\s*\S.+$", repl="", flags=0),
    ],
    "chat_export_noise": [
        # Slack/Teams export headers/footers and navigation prompts.
        RegexRule(pattern=r"(?mi)^\s*(?:slack\s+export|exported\s+from\s+slack)\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*(?:microsoft\s+teams\s+export|exported\s+from\s+microsoft\s+teams)\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*view\s+in\s+(?:slack|teams|microsoft\s+teams)\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*(?:jump|go)\s+to\s+message\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*reply\s+in\s+thread\s*$", repl="", flags=0),
        # Common system message noise (line-oriented).
        RegexRule(pattern=r"(?mi)^\s*.*\bhas\s+joined\s+the\s+channel\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*.*\bhas\s+left\s+the\s+channel\b.*$", repl="", flags=0),
        # Timestamp-only lines (keep conservative: only time/date alone on a line).
        RegexRule(pattern=r"(?mi)^\s*\d{1,2}:\d{2}\s*(?:am|pm)\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*\d{4}-\d{2}-\d{2}\s*$", repl="", flags=0),
        # Chinese UI strings (best-effort).
        RegexRule(pattern=r"(?m)^\s*\u5728\s*slack\s*\u4e2d\u67e5\u770b\s*$", repl="", flags=0),  # 在 Slack 中查看
    ],
    "pdf_watermark": [
        # Watermark-like full-line stamps (keep conservative).
        RegexRule(pattern=r"(?mi)^\s*draft\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*(?:company\s+)?confidential\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*strictly\s+confidential\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*internal\s+only\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*for\s+internal\s+use\s+only\s*$", repl="", flags=0),
        # Chinese (common PDF exports).
        RegexRule(pattern=r"(?m)^\s*(?:机密|保密|内部资料|内部使用|仅供内部使用)\s*$", repl="", flags=0),
    ],
    "confluence_jira_noise": [
        # Confluence export noise (best-effort, line-oriented).
        RegexRule(pattern=r"(?mi)^\s*powered\s+by\s+atlassian\s+confluence\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*view\s+in\s+confluence\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*created\s+by\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*last\s+updated\b.*$", repl="", flags=0),
    ],
    "wechat_mp_noise": [
        # WeChat official account (公众号) export / copy-paste call-to-action lines.
        RegexRule(pattern=r"(?m)^\s*\u9605\u8bfb\u539f\u6587\s*$", repl="", flags=0),  # 阅读原文
        RegexRule(pattern=r"(?m)^\s*\u70b9\u51fb\u4e0a\u65b9.*(?:\u5173\u6ce8|\u8ba2\u9605).*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*\u957f\u6309.*\u8bc6\u522b.*\u4e8c\u7ef4\u7801.*(?:\u5173\u6ce8|\u6dfb\u52a0).*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*(?:\u626b\u4e00\u626b|\u626b\u63cf).*\u4e8c\u7ef4\u7801.*(?:\u5173\u6ce8|\u6dfb\u52a0).*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*(?:\u5728\u770b|\u70b9\u8d5e|\u8f6c\u53d1|\u5206\u4eab(?:\u5230)?\u670b\u53cb\u5708)\s*$", repl="", flags=0),
    ],
    "pdf_header_footer_cn": [
        # Chinese page header/footer lines that include a title/company prefix.
        # Plain "第 N 页" forms are already covered by DEFAULT_MARKDOWN_RULES.
        RegexRule(
            pattern=r"(?m)^[ \t]*[\u4e00-\u9fffA-Za-z0-9（）()《》·._/\\ -]{2,80}[ \t]+第[ \t]*\d+[ \t]*页(?:[ \t]*/[ \t]*(?:\u5171[ \t]*)?\d+[ \t]*页)?[ \t]*$",
            repl="",
            flags=0,
        ),
        RegexRule(
            pattern=r"(?m)^[ \t]*[\u4e00-\u9fffA-Za-z0-9（）()《》·._/\\ -]{2,80}[ \t]+第[ \t]*\d+[ \t]*页[ \t]*$",
            repl="",
            flags=0,
        ),
        RegexRule(
            pattern=r"(?m)^[ \t]*[\u4e00-\u9fffA-Za-z0-9（）()《》·._/\\ -]{2,80}[ \t]*[|｜][ \t]*第[ \t]*\d+[ \t]*页(?:[ \t]*/[ \t]*\u5171?[ \t]*\d+[ \t]*页)?[ \t]*$",
            repl="",
            flags=0,
        ),
    ],
    "notion_export_noise": [
        # Notion markdown export noise (best-effort, line-oriented).
        RegexRule(pattern=r"(?mi)^\s*exported\s+from\s+notion\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*created\s+time\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*last\s+edited\s+time\b.*$", repl="", flags=0),
    ],
    "markdown_export_noise": [
        # Generic "exported/converted by ..." headers and footers.
        RegexRule(pattern=r"(?mi)^\s*generated\s+by\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*exported\s+from\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*created\s+with\b.*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*last\s+updated\b.*$", repl="", flags=0),
    ],
    # ---------- A 股年报 / 招股书 / 金融披露文档常见噪声 ----------
    "cn_finance_report_artifacts": [
        # 披露免责声明 / 真实性承诺(常见在年报/公告/招股书首页)
        RegexRule(
            pattern=r"(?m)^.*(?:董事会|监事会)(?:、|及).*(?:全体)?(?:成员|董事|监事).*(?:真实|准确|完整).*(?:承诺|保证).*$",
            repl="",
            flags=0,
        ),
        RegexRule(
            pattern=r"(?m)^.*(?:本(?:公司|公告|报告|说明书))?.*(?:不存在|无)(?:虚假记载|误导性陈述|重大遗漏).*$",
            repl="",
            flags=0,
        ),
        # 报告标识/披露指引 line-oriented
        RegexRule(pattern=r"(?m)^\s*(?:股票代码|证券代码)[:：].*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*(?:股票简称|证券简称)[:：].*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*(?:公告编号|公告序号)[:：].*$", repl="", flags=0),
        # 年报披露说明
        RegexRule(pattern=r"(?m)^\s*年度报告(?:全文)?披露于.*$", repl="", flags=0),
        # 简式 / 详式 报告备注
        RegexRule(
            pattern=r"(?m)^\s*本(?:简式|详式)?(?:权益变动报告书|要约收购报告书).*依据.*$",
            repl="",
            flags=0,
        ),
    ],
    # ---------- 政府公文 / 红头文件常见噪声 ----------
    "cn_gov_redhead_artifacts": [
        # 抄送 / 印发 / 签发(末尾常见,line-oriented)
        RegexRule(pattern=r"(?m)^\s*抄\s*送[:：].*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^.*(?:办公厅|办公室|发文办)\s*\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*印发\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*签\s*发[:：\s]*\S.*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*承办\s*(?:单位|处室|司局|部门)[:：].*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*主送[:：].*$", repl="", flags=0),
        # 主题词(已废,但旧公文常见)
        RegexRule(pattern=r"(?m)^\s*主题\s*词[:：].*$", repl="", flags=0),
        # 联系电话块
        RegexRule(pattern=r"(?m)^\s*联系\s*(?:人|电话)[:：].*$", repl="", flags=0),
    ],
    # ---------- 电子病历 / 医疗报告常见表头噪声(脱敏前去除展示性字段) ----------
    "cn_medical_record_artifacts": [
        # 医院 / 科室 / 床号 / 工号(line-oriented)
        RegexRule(pattern=r"(?m)^\s*(?:门诊号|住院号|病案号|就诊卡号)[:：]\s*\S+\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*(?:床位号|床号|病床号)[:：]\s*\S+\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*(?:主管医生|主治医师|主任医师|住院医师|查房医师)[:：]\s*\S+\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*(?:护士长|责任护士|主管护士)[:：]\s*\S+\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*(?:科室|入院科室|出院科室|当前科室)[:：]\s*\S+\s*$", repl="", flags=0),
        # 病历打印 / 系统标识
        RegexRule(pattern=r"(?m)^\s*打印(?:时间|人)[:：].*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*病历(?:打印|录入|审核)(?:时间|人)?[:：].*$", repl="", flags=0),
    ],
    # ---------- 飞书 / Lark 知识库导出常见噪声 ----------
    "feishu_lark_noise": [
        RegexRule(pattern=r"(?mi)^\s*由\s*(?:飞书|lark)\s*(?:文档|知识库|妙记)?\s*导出\s*$", repl="", flags=0),
        RegexRule(pattern=r"(?mi)^\s*powered\s+by\s+(?:lark|feishu)\b.*$", repl="", flags=0),
        # 文档元信息 line-oriented
        RegexRule(pattern=r"(?m)^\s*(?:最后(?:编辑|修改)|最近编辑)[:：\s].*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*(?:文档(?:所有者|归属|拥有人|拥有者))[:：\s].*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*(?:协作者|共享给)[:：\s].*$", repl="", flags=0),
        RegexRule(pattern=r"(?m)^\s*(?:创建(?:时间|于)|创建人)[:：\s].*$", repl="", flags=0),
        # 妙记 / 妙享标识
        RegexRule(pattern=r"(?mi)^\s*(?:妙记|妙享)\s*文档\s*$", repl="", flags=0),
    ],
}


def list_governance_rule_packs() -> list[str]:
    return sorted(GOVERNANCE_RULE_PACKS.keys())


__all__ = [
    "GOVERNANCE_RULE_PACKS",
    "list_governance_rule_packs",
]
