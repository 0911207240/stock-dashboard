"""LINE Flex Message 建構器 — 股票分析泡泡卡片"""

from data_fetcher import SECTORS, WATCHLIST


def _vol_price_tag(chg_pct: float, vol_ratio: float,
                   close: float = 0, high: float = 0) -> str:
    """根據量比 × 漲跌方向輸出量價結構文字"""
    up     = chg_pct >  0.3
    down   = chg_pct < -0.3
    surge  = vol_ratio >= 2.0
    grow   = vol_ratio >= 1.3
    shrink = vol_ratio <  0.8

    upper_shadow = (high - close) / close * 100 if close > 0 and high > close else 0

    if surge and up and upper_shadow > 2.0:
        return "爆量帶影 ⚠️"
    if surge and up:
        return "爆量大漲 🔥"
    if surge and down:
        return "爆量殺跌 ❌"
    if grow and up:
        return "量增攻 ✅"
    if grow and down:
        return "量增跌 ⚠️"
    if shrink and up:
        return "量縮漲（弱）"
    if shrink and down:
        return "量縮守 🟡"
    return "量能平穩"


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

    # 補到 3 個（用熱門股填充，排除已有的）
    used_codes = {current_code} | {r["action"]["text"] for r in related}
    defaults = [("台積電", "2330"), ("鴻海", "2317"), ("00878", "00878"), ("0050", "0050")]
    for label, text in defaults:
        if text not in used_codes and len(related) < 3:
            related.append(_qr_item(label, text))
            used_codes.add(text)

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
    high: float,
    chg_pct: float,
    vol_ratio: float,
    rs: float | None,
    rsi: float,
    rsi6: float,
    ma_tag: str,
    macd_tag: str,
    k_val: float,
    d_val: float,
    dist_high: float,
    dist_low: float,
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

    vp_tag = _vol_price_tag(chg_pct, vol_ratio, close, high)

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
                         "text": f"量比 {vol_ratio:.1f}x  {vp_tag}",
                         "color": "#888888", "size": "xs", "align": "end", "wrap": True},
                    ],
                },
            ],
        },
    ]

    # 相對大盤強弱
    if rs is not None:
        rs_label = f"強於大盤 +{rs:.1f}%" if rs > 0 else f"弱於大盤 {rs:.1f}%"
        rs_color = "#EF5350" if rs > 0 else "#26A69A"
        body.append(_row("vs 大盤", rs_label, rs_color))

    body.append(_sep())

    # ── 技術面 ───────────────────────────────────────
    rsi_color = "#EF5350" if rsi > 75 else "#26A69A" if rsi < 30 else "#333333"
    rsi_tag   = " ⚠️超買" if rsi > 75 else " 超賣" if rsi < 30 else ""

    kd_tag    = " ⚠️超買" if k_val > 80 else " 超賣" if k_val < 20 else ""
    kd_color  = "#EF5350" if k_val > 80 else "#26A69A" if k_val < 20 else "#333333"

    macd_color = "#EF5350" if "多" in macd_tag or "黃金" in macd_tag else "#26A69A"

    dist_high_str = f"{dist_high:.1f}%"
    dist_low_str  = f"+{dist_low:.1f}%"

    body += [
        {"type": "text", "text": "📈 技術面",
         "weight": "bold", "size": "sm", "color": "#555555", "margin": "sm"},
        _row("RSI", f"{rsi:.0f}{rsi_tag}（RSI6 {rsi6:.0f}）", rsi_color),
        _row("KD",  f"K {k_val:.0f} / D {d_val:.0f}{kd_tag}", kd_color),
        _row("MACD", macd_tag, macd_color),
        _row("均線", ma_tag),
        _row("布林位置", f"{bb_pos:.0f}%"),
        _row("ATR", f"{atr_pct:.1f}%"),
        _row("6M高低", f"距高 {dist_high_str} / 距低 {dist_low_str}"),
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
            # 連續買超天數 + 近期累計
            cons  = inst_data.get("consecutive_days", 0)
            n_net = inst_data.get("n_day_net")
            if cons and n_net is not None:
                cons_abs = abs(cons)
                direction = "買超" if cons > 0 else "賣超"
                n_days    = inst_data.get("history_days", cons_abs)
                cons_color = "#EF5350" if cons > 0 else "#26A69A"
                body.append(_row(
                    f"連續{direction}",
                    f"{cons_abs}日 / 近{n_days}日 {n_net:+,}張",
                    cons_color,
                ))
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
    return msg
