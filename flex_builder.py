"""LINE Flex Message 建構器 — 股票分析泡泡卡片"""

from data_fetcher import SECTORS, WATCHLIST


def _qr_item(label: str, text: str) -> dict:
    return {
        "type": "action",
        "action": {"type": "message", "label": label, "text": text},
    }


def _quick_reply_items(current_ticker: str) -> list[dict]:
    """根據當前股票回傳相關快捷按鈕（最多 4 個）"""
    current_code = current_ticker.replace(".TW", "").replace(".TWO", "")

    # 找出同族群的其他股票（最多 2 檔）
    related = []
    for sector, members in SECTORS.items():
        if sector in ("全部", "我的持股", "台灣電子績優", "低價波段($50以下)"):
            continue
        names_in_sector = [n for n in members if n in WATCHLIST]
        codes_in_sector = [WATCHLIST[n].replace(".TW","").replace(".TWO","") for n in names_in_sector]
        if current_code in codes_in_sector:
            for name in names_in_sector:
                code = WATCHLIST[name].replace(".TW","").replace(".TWO","")
                if code != current_code and len(related) < 2:
                    label = name if len(name) <= 5 else code
                    related.append(_qr_item(label, code))
            break

    # 補到 3 個（用熱門股填充）
    defaults = [("台積電", "2330"), ("鴻海", "2317"), ("00878", "00878"), ("0050", "0050")]
    for label, text in defaults:
        if text != current_code and len(related) < 3:
            related.append(_qr_item(label, text))

    related.append(_qr_item("說明", "說明"))
    return related[:4]


def _sep() -> dict:
    return {"type": "separator", "margin": "sm"}


def _row(label: str, value: str, value_color: str = "#333333") -> dict:
    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {"type": "text", "text": label,
             "size": "sm", "color": "#888888", "flex": 3},
            {"type": "text", "text": value,
             "size": "sm", "color": value_color, "align": "end", "flex": 4, "wrap": True},
        ],
    }


def build_analysis_flex(
    name: str,
    ticker: str,
    date_str: str,
    close: float,
    chg_pct: float,
    vol_ratio: float,
    rsi: float,
    rsi6: float,
    ma_tag: str,
    bb_pos: float,
    atr_pct: float,
    inst_data: dict,
    margin_data: dict,
    holder_label: str,
    daytrade_score: int,
    entry_exit: dict | None,
    top_signals: list[str],
) -> dict:
    """回傳 LINE Flex Message dict（type=flex）"""
    code     = ticker.replace(".TW", "").replace(".TWO", "")
    is_up    = chg_pct >= 0
    arrow    = "▲" if is_up else "▼"
    chg_color   = "#EF5350" if is_up else "#26A69A"
    header_bg   = "#C62828" if is_up else "#00695C"

    # ── 基本價格區 ──────────────────────────────────
    body = [
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": f"${close:.1f}",
                 "weight": "bold", "size": "xxl", "flex": 3},
                {
                    "type": "box", "layout": "vertical", "flex": 2,
                    "contents": [
                        {"type": "text",
                         "text": f"{arrow}{abs(chg_pct):.1f}%",
                         "color": chg_color, "weight": "bold",
                         "size": "lg", "align": "end"},
                        {"type": "text",
                         "text": f"量比 {vol_ratio:.1f}x",
                         "color": "#888888", "size": "xs", "align": "end"},
                    ],
                },
            ],
        },
        _sep(),
    ]

    # ── 技術面 ───────────────────────────────────────
    rsi_color = "#EF5350" if rsi > 75 else "#26A69A" if rsi < 30 else "#333333"
    rsi_tag   = " ⚠️超買" if rsi > 75 else " 超賣" if rsi < 30 else ""
    body += [
        {"type": "text", "text": "📈 技術面",
         "weight": "bold", "size": "sm", "color": "#555555", "margin": "sm"},
        _row("RSI", f"{rsi:.0f}{rsi_tag}（RSI6 {rsi6:.0f}）", rsi_color),
        _row("均線", ma_tag),
        _row("布林位置", f"{bb_pos:.0f}%"),
        _row("ATR", f"{atr_pct:.1f}%"),
    ]

    # ── 籌碼面（台股才有） ───────────────────────────
    if inst_data or margin_data or holder_label:
        body.append(_sep())
        body.append({"type": "text", "text": "💼 籌碼面",
                     "weight": "bold", "size": "sm", "color": "#555555", "margin": "sm"})
        if inst_data:
            f = inst_data.get("foreign_net", 0)
            t = inst_data.get("trust_net",   0)
            d = inst_data.get("dealer_net",  0)
            body.append(_row("外/投/自(張)", f"{f:+,} / {t:+,} / {d:+,}"))
        if margin_data:
            mr    = margin_data.get("margin_change", 0)
            sr    = margin_data.get("short_change",  0)
            ratio = margin_data.get("margin_ratio",  0)
            body.append(_row("融資/券/券資比", f"{mr:+,} / {sr:+,} / {ratio:.1f}%"))
        if holder_label:
            body.append(_row("集保大戶", holder_label))

    # ── 當沖評分 ─────────────────────────────────────
    if daytrade_score > 0 and entry_exit:
        score_color = "#EF5350" if daytrade_score >= 60 else \
                      "#FF9800" if daytrade_score >= 40 else "#888888"
        body.append(_sep())
        body += [
            {
                "type": "box", "layout": "horizontal", "margin": "sm",
                "contents": [
                    {"type": "text", "text": "🎯 當沖評分",
                     "weight": "bold", "size": "sm", "color": "#555555", "flex": 3},
                    {"type": "text", "text": f"{daytrade_score}分",
                     "weight": "bold", "color": score_color,
                     "align": "end", "flex": 2},
                ],
            },
            _row("甜蜜點", f"${entry_exit['entry_low']}～${entry_exit['entry_high']}"),
            _row("停損",   f"${entry_exit['stop']}（-{entry_exit['risk_pct']:.1f}%）"),
            _row("停利①", f"${entry_exit['tp1']}（+{entry_exit['upside_pct1']:.1f}% RR={entry_exit['rr1']}）"),
            _row("停利②", f"${entry_exit['tp2']}（+{entry_exit['upside_pct2']:.1f}% RR={entry_exit['rr2']}）"),
        ]
        if top_signals:
            body.append({
                "type": "text",
                "text": "→ " + "  ".join(top_signals[:2]),
                "size": "xs", "color": "#888888", "wrap": True, "margin": "xs",
            })

    msg = {
        "type": "flex",
        "altText": f"【{name} {code}】{date_str} 分析",
        "contents": {
            "type": "bubble",
            "size": "kilo",
            "header": {
                "type": "box",
                "layout": "horizontal",
                "backgroundColor": header_bg,
                "paddingAll": "12px",
                "contents": [
                    {"type": "text", "text": name,
                     "weight": "bold", "color": "#FFFFFF",
                     "size": "md", "flex": 3},
                    {"type": "text", "text": f"{code}  {date_str}",
                     "color": "#FFFFFF", "align": "end",
                     "size": "sm", "gravity": "bottom", "flex": 2},
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "12px",
                "spacing": "xs",
                "contents": body,
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "8px",
                "contents": [{
                    "type": "text",
                    "text": "⚠️ 資料 T+1，僅供參考",
                    "color": "#AAAAAA", "size": "xs", "align": "center",
                }],
            },
        },
        "quickReply": {
            "items": _quick_reply_items(ticker),
        },
    }
