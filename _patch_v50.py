# -*- coding: utf-8 -*-
"""v49 → v50 一次性补丁。

设计原则（沿用本项目既有铁律）：
  · 全部替换在内存里原子完成；任何一条 count 不匹配 ⇒ 立刻中止、**不写盘**
  · 每条规则带期望命中次数，逐条断言
  · 写回时保留原换行风格（本文件是纯 LF）与 BOM 状态
  · 改完自证：跑一遍断言复查关键串

v50 只做四类【不改变交易行为】的修正：
  ① 删死键 AGGR_STOP_LOSS_ATR
  ② check_exit 里 5 处静默 except→pass 改为记 EXIT-DEGRADE（只加日志）
  ③ 三处注释与代码对齐（文档漂移）
  ④ run_standard 取 K 线补 bar=ANALYSIS_BAR
  另：VERSION → v50、追加 v50 改动记录、新增 [AA] 自检组（3 项）
"""
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

SRC = r"C:\Users\1\Desktop\OKXBot\okx_bot_merged_1.py"
BAK = SRC + ".v49.bak"

text = io.open(SRC, encoding="utf-8", newline="").read()

# ── 风格探测 ────────────────────────────────────────────────────
bom = text.startswith("\ufeff")
crlf = text.count("\r\n")
lf_only = text.count("\n") - crlf
print("原文件：%d 字符，BOM=%s，CRLF=%d，裸LF=%d" % (len(text), bom, crlf, lf_only))

RULES = []          # (名字, old, new, 期望命中次数)


# ── ① VERSION ───────────────────────────────────────────────────
RULES.append((
    "VERSION v49→v50",
    'VERSION = "v49"',
    'VERSION = "v50"',
    1,
))

# ── ③a TREND_WINDOW 注释 ────────────────────────────────────────
RULES.append((
    "TREND_WINDOW 注释：根 1H → 根 15m",
    "# L3.5 趋势反转显著性退出（数学拐点兑现）。对最近 TREND_WINDOW 根 1H 对数价格\n"
    "#    做 OLS，斜率 t 统计量 < -2 ≈ 95% 置信（单侧）趋势已反转为下跌。\n",
    "# L3.5 趋势反转显著性退出（数学拐点兑现）。对最近 TREND_WINDOW 根【15m】对数\n"
    "#    价格做 OLS，斜率 t 统计量 < -2 ≈ 95% 置信（单侧）趋势已反转为下跌。\n"
    "#    ★ v50 更正：原写「根 1H」是 v36 把 ANALYSIS_BAR 改成 15m 之前的遗留\n"
    "#      （v48 只改了 check_exit 内的同名注释，漏了常量定义这一处）。\n"
    "#      实际窗口 = 12×15m = 3 小时。数值不动 —— 重标定回 12 小时会让本层\n"
    "#      更晚卖，与「该卖要卖」的方向相反。\n",
    1,
))

# ── ③b TIME_EXIT_HOURS 注释 ─────────────────────────────────────
RULES.append((
    "TIME_EXIT_HOURS 注释：24h → 6h",
    "#    实测 12h 过密（交易成本吃收益），故取 24h 作兜底。\n",
    "#    实测 12h 过密（交易成本吃收益）。\n"
    "#    ★ v50 更正：这里原写「故取 24h 作兜底」，与下面的值不符 ——\n"
    "#      v36 改成短期高频后实际取 6.0h（按 15m 信号周期重标），注释没跟上。\n",
    1,
))

# ── ③c _USER_SPECIAL 注释 ───────────────────────────────────────
RULES.append((
    "_USER_SPECIAL 注释：5 个 → 6 个",
    "# 这 5 个键不走 _USER_MAP —— 它们要同时改多个全局或需要换算，单独处理。\n",
    "# 这些键要【单独处理】（同时改多个全局 / 单位换算 / 类型转换）。\n"
    "# ★ v50 更正：原写「这 5 个键不走 _USER_MAP」，与集合内容不符 ——\n"
    "#   集合实为 6 个：前 5 个（max_position_ratio / min_cand_score /\n"
    "#   stop_atr / time_exit_days / max_hold_days）确实不在 _USER_MAP；\n"
    "#   trail_dd_target **在** _USER_MAP 里（有通用映射），但它还要同步改\n"
    "#   AGGR_TRAIL_DD_TARGET，所以也一并列在这里。\n",
    1,
))

# ── ① 删死键 ────────────────────────────────────────────────────
RULES.append((
    "删除死键 AGGR_STOP_LOSS_ATR",
    "\nAGGR_STOP_LOSS_ATR = 1.5\nAGGR_BREAK_EVEN_ATR = 1.0\n",
    "\n# ★ v50：原 AGGR_STOP_LOSS_ATR = 1.5 已删除 —— 全仓库零引用（唯一一处出现）。\n"
    "#   激进型止损自 v42/v45 起统一走 AGGR_STOP_ATR_INIT / AGGR_STOP_ATR_END，\n"
    "#   这个残留键只会让人「以为改了激进型止损、其实改了个没人读的变量」。\n"
    "AGGR_BREAK_EVEN_ATR = 1.0\n",
    1,
))

# ── ②e check_exit：当前 ATR 重算 ────────────────────────────────
RULES.append((
    "check_exit 留痕：当前 ATR 重算",
    '                    pos["atr_now_pct"] = to_1h_atr(a) / p\n'
    "            except Exception:\n"
    "                pass\n",
    '                    pos["atr_now_pct"] = to_1h_atr(a) / p\n'
    "            except Exception as _e:\n"
    '                _exit_layer_err(sym, "当前ATR重算(沿用入场ATR)", _e)\n',
    1,
))

# ── ②a L3.5 ─────────────────────────────────────────────────────
RULES.append((
    "check_exit 留痕：L3.5 趋势反转",
    '                            f"(95%置信) 盈利{profit * 100:.2f}%")\n'
    "            except Exception:\n"
    "                pass\n",
    '                            f"(95%置信) 盈利{profit * 100:.2f}%")\n'
    "            except Exception as _e:\n"
    '                _exit_layer_err(sym, "L3.5趋势反转", _e)\n',
    1,
))

# ── ②b L6 ───────────────────────────────────────────────────────
RULES.append((
    "check_exit 留痕：L6 效率比",
    '                    return EXIT_ER_FAIL, f"效率比{er:.2f} < {ER_THRESHOLD}，震荡无趋势"\n'
    "            except Exception:\n"
    "                pass\n",
    '                    return EXIT_ER_FAIL, f"效率比{er:.2f} < {ER_THRESHOLD}，震荡无趋势"\n'
    "            except Exception as _e:\n"
    '                _exit_layer_err(sym, "L6效率比", _e)\n',
    1,
))

# ── ②c L8 ───────────────────────────────────────────────────────
RULES.append((
    "check_exit 留痕：L8 顶部共振/部分止盈",
    '                        return EXIT_PARTIAL_TAKE, f"浮盈{profit*100:.2f}%≥2ATR"\n'
    "            except Exception:\n"
    "                pass\n",
    '                        return EXIT_PARTIAL_TAKE, f"浮盈{profit*100:.2f}%≥2ATR"\n'
    "            except Exception as _e:\n"
    '                _exit_layer_err(sym, "L8顶部共振", _e)\n',
    1,
))

# ── ②d L7.5 ─────────────────────────────────────────────────────
RULES.append((
    "check_exit 留痕：L7.5 顶部共振（标准型）",
    "                    return EXIT_TOP_RESONANCE, (f\"超买共振 {'/'.join(sigs_t)} \"\n"
    '                                             f"盈利{profit * 100:.2f}%")\n'
    "            except Exception:\n"
    "                pass\n",
    "                    return EXIT_TOP_RESONANCE, (f\"超买共振 {'/'.join(sigs_t)} \"\n"
    '                                             f"盈利{profit * 100:.2f}%")\n'
    "            except Exception as _e:\n"
    '                _exit_layer_err(sym, "L7.5顶部共振", _e)\n',
    1,
))

# ── ⑦ 新增 _exit_layer_err 助手 ─────────────────────────────────
_EXIT_HELPER = '''def _exit_layer_err(sym: str, layer: str, exc: Exception) -> None:
    """某一层退出判定因异常被跳过时【留痕】。

    ★ 存在的理由（v50）：check_exit 里 L3.5 / L6 / L7.5 / L8 与「当前 ATR
      重算」各自包在 try/except 里，异常一旦发生 ⇒ 该层【静默消失】，日志里
      一个字都没有。这正是用户反复遇到的「该卖没卖、查不到证据」的成因形态
      —— v48 只覆盖了「K 线取不到」那一条路径。

    ★ 本函数**只写日志**，不改变任何判定结果、不参与任何计算。
      失败时自己也会被吞掉：丢证据可以忍，丢交易不行。

    层名用中文，是因为用户是照「可调参数说明.txt」里的层名沟通的
    （L3.5 趋势反转 / L7.5 顶部共振 / L8 顶部共振…）。
    """
    try:
        logline(f"EXIT-DEGRADE {sym} {layer} 判定异常，本层本轮跳过："
                f"{type(exc).__name__}: {str(exc)[:80]}", level="WARN")
    except Exception:
        pass


'''

RULES.append((
    "新增 _exit_layer_err 助手",
    "def log_path() -> str:\n",
    _EXIT_HELPER + "def log_path() -> str:\n",
    1,
))

# ── ④ run_standard 补 bar= ──────────────────────────────────────
RULES.append((
    "run_standard 取 K 线补 bar=ANALYSIS_BAR",
    "                        candles = client.candles(sym, limit=100)\n",
    "                        candles = client.candles(\n"
    "                            sym, bar=ANALYSIS_BAR, limit=100)\n",
    1,
))

# ── 应用（先全量预检，再写盘） ──────────────────────────────────
print("\n=== 预检 ===")
fail = False
for name, old, new, want in RULES:
    got = text.count(old)
    flag = "OK " if got == want else "!! "
    print("  %s%-42s 命中 %d（期望 %d）" % (flag, name, got, want))
    if got != want:
        fail = True
if fail:
    print("\n中止：有规则命中数不符，文件【未改动】。")
    sys.exit(1)

print("\n=== 应用 ===")
for name, old, new, want in RULES:
    text = text.replace(old, new, want)
    print("  ✓ %s" % name)

# ── v50 改动记录（插在 v49 块之前）──────────────────────────────
V50_BLOCK = """# ── v50（2026-10-05）────────────────────────────────────────────
#    用户：「分析现有 okxbot 的代码与功能，识别其中可优化 / 可删减 / 存在
#    问题的部分，给出筛选与改进建议，并实施必要的修正，保持原有功能意图
#    不变」。
#
#    ★ 结论先行：这是一个【死代码极少】的代码库 —— 190 个顶层常量里只有
#      1 个真死键；131 个顶层函数、10 个顶层类全部有引用；不存在裸
#      `except:`。所以本轮不做任何「清理式重构」，只做四类【不改变交易
#      行为】的修正。真正的结构问题（run_standard 与 run_aggressive 45%
#      重复、quant_core 内 9 个函数无调用点）已在报告里给出建议，但
#      **不实施** —— 它们会动到主循环，与「保持原有功能意图不变」冲突。
#
#    ① 删死键 AGGR_STOP_LOSS_ATR = 1.5。全仓库唯一一处出现、零引用。
#       v42/v45 起激进型止损统一走 AGGR_STOP_ATR_INIT/END，这个残留键是
#       「以为改了止损、其实改的是个没人读的变量」的典型隐患。
#
#    ② ★ 可观测性（本轮最重要的一条）：check_exit 里 L3.5 / L6 / L7.5 / L8
#       四层退出判定 + 「当前 ATR 重算」各自包在 try/except pass 里 ——
#       一旦取数或计算异常，该层【静默消失】，日志里一个字都没有。这正是
#       用户反复踩的「该卖没卖、却查不到证据」的成因形态（v48 只覆盖了
#       「K 线取不到」那一条路径）。现统一改为记一行 EXIT-DEGRADE WARN，
#       含【层名 + 异常类型 + 异常摘要】。
#       ★ 只加日志、不改任何判定：_exit_layer_err 不参与计算，自己失败也
#         会被吞掉 ——「丢证据可以忍，丢交易不行」。
#
#    ③ 注释与代码对齐（三处「文档漂移」，都是「以为是这样」的来源）：
#       · TREND_WINDOW 处仍写「根 1H」，实际是 12 根 15m（v48 只改了
#         check_exit 内的同名注释，漏了常量定义处）；
#       · TIME_EXIT_HOURS 上方仍写「故取 24h 作兜底」，实际 = 6.0（v36 改的）；
#       · _USER_SPECIAL 上方写「这 5 个键不走 _USER_MAP」，实际 6 个，且
#         trail_dd_target 就在 _USER_MAP 里（它只是额外要同步改激进型）。
#
#    ④ run_standard 取 K 线补上 bar=ANALYSIS_BAR（原依赖 candles() 的形参
#       默认值）。当前行为完全不变，但去掉「哪天默认值一改、标准型就静默
#       换了分析周期」的隐患 —— 与激进型那处写法对齐。
#
#    ★ 未触碰：退出层级顺序、任何阈值数值、选币打分、敞口 E、
#      菜单项数与编号（仍是 35 项）。
#    ★ 自检新增 [AA] 组（3 项）：死键确已删除 / 层异常必须留痕（行为级）/
#      源码级断言 check_exit 内不再有静默 except pass。
#    ★ 建议但【未实施】（需用户决策，详见报告）：
#      · run_standard 与 run_aggressive 45% 重复（82 行 / 8 个 ≥6 行共同块）；
#      · quant_core 内 9 个函数（ewma_vol / garch11_step / garch_long_run /
#        annualize_vol / realized_vol / max_drawdown / var_normal /
#        avg_pairwise_corr / bayes_posterior_drift）在任何地方都没有调用点。

"""

_anchor = "# ── v49（2026-10-05）"
_pos = text.find(_anchor)
if _pos < 0:
    print("\n中止：找不到 v49 改动记录锚点，文件【未改动】。")
    sys.exit(1)
text = text[: _pos] + V50_BLOCK + text[_pos:]
print("  ✓ 追加 v50 改动记录")

# ── [AA] 自检组 ─────────────────────────────────────────────────
AA_BLOCK = '''
    # ── [AA] v50：退出层的「静默失败」必须留痕 ────────────────────
    print("\\n[AA] v50：死键清理 + 退出层异常留痕")

    # AA1 死键确已删除（行为级：globals 里不该再有它）
    _aa1_ok = (globals().get("AGGR_STOP_LOSS_ATR") is None)
    check("死键 AGGR_STOP_LOSS_ATR 已从模块全局移除", _aa1_ok)

    # AA2 行为断言：L7.5 顶部共振计算抛异常时，必须【留痕】且不崩
    #     ★ 断言的是「_exit_layer_err 被调用 + 层名正确」，不是「不抛异常」
    #       —— 后者是最弱的断言（v49 的 GBK 假绿就是栽在这上面）。
    try:
        _aa2_rec = []
        _aa2_bak = globals()["_exit_layer_err"]
        globals()["_exit_layer_err"] = (
            lambda _s, _l, _e: _aa2_rec.append((_s, _l, type(_e).__name__)))
        _pmA = PM()
        _pmA.add("AA-USDT", Decimal("100"), Decimal("1"), 2.0, 100.0,
                 aggr=False)
        _pmA.positions["AA-USDT"]["highest_price"] = 106.0
        _aa_c = [[i, 96.0 + 0.5 * i, 96.0 + 0.5 * i, 96.0 + 0.5 * i,
                  96.0 + 0.5 * i, 0, 0, 0, 0] for i in range(60)]
        _aa_bak_boll = Ind.boll
        Ind.boll = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            _aa2_r = _pmA.check_exit("AA-USDT", 106.0, 100.0, candles=_aa_c)
        finally:
            Ind.boll = _aa_bak_boll
            globals()["_exit_layer_err"] = _aa2_bak
        _aa2_ok = any(("L7.5" in _l) for _s, _l, _e in _aa2_rec)
    except Exception:
        _aa2_ok = False
    check("L7.5 计算异常 → 记 EXIT-DEGRADE 留痕（层名含 L7.5）", _aa2_ok)

    # AA3 源码级：check_exit 里不再有「except → pass」的静默对
    #     ★ 断言前先剔掉注释行 —— 否则我自己的解释性注释会把断言顶掉（误报）
    try:
        _aa3_src = __import__("inspect").getsource(PM.check_exit)
        _aa3_lines = [l for l in _aa3_src.splitlines()
                      if l.strip() and not l.strip().startswith("#")]
        _aa3_silent = 0
        for _i in range(len(_aa3_lines) - 1):
            if _aa3_lines[_i].strip().startswith("except"):
                if _aa3_lines[_i + 1].strip() == "pass":
                    _aa3_silent += 1
        _aa3_ok = (_aa3_silent == 0)
    except Exception:
        _aa3_ok = True      # onefile 下取不到源码 → 降级通过
    check("check_exit 内已无静默 except→pass（源码级，取不到源码则降级）",
          _aa3_ok)


'''

_aa_anchor = ('    check("_log_open 确实写入启动横幅（源码级，取不到源码则降级）", _z4_ok)\n'
              "\n"
              "\n"
              "    print()\n")
if text.count(_aa_anchor) != 1:
    print("\n中止：找不到 [Z] 组结尾锚点（命中 %d 次），文件【未改动】。"
          % text.count(_aa_anchor))
    sys.exit(1)
text = text.replace(_aa_anchor,
                    '    check("_log_open 确实写入启动横幅（源码级，取不到源码则降级）", _z4_ok)\n\n'
                    + AA_BLOCK
                    + "    print()\n", 1)
print("  ✓ 新增 [AA] 自检组（3 项）")

# ── 写盘 ────────────────────────────────────────────────────────
assert text.startswith("\ufeff") == bom, "BOM 状态被改变"
new_crlf = text.count("\r\n")
if crlf == 0:
    assert new_crlf == 0, "原本纯 LF，写回后出现了 CRLF"

if not os.path.exists(BAK):
    io.open(BAK, "w", encoding="utf-8", newline="").write(
        io.open(SRC, encoding="utf-8", newline="").read())
    print("\n备份：%s" % BAK)
else:
    print("\n备份已存在（未覆盖）：%s" % BAK)

io.open(SRC, "w", encoding="utf-8", newline="").write(text)
print("已写盘：%d 字符（原 %d）" % (len(text), len(io.open(BAK, encoding="utf-8").read())))

# ── 复查 ────────────────────────────────────────────────────────
print("\n=== 复查 ===")
chk = io.open(SRC, encoding="utf-8").read()
checks = [
    ('VERSION = "v50"', 1),
    ("AGGR_STOP_LOSS_ATR = 1.5", 0),
    ("AGGR_STOP_LOSS_ATR", 3),        # 仅剩 v50 说明注释里的 3 处
    ("_exit_layer_err(sym,", 5),
    ("def _exit_layer_err", 1),
    ("# ── v50（2026-10-05）", 1),
    ("[AA] v50", 1),
    ("bar=ANALYSIS_BAR, limit=100", 2),
    ("# L3.5 趋势反转显著性退出（数学拐点兑现）。对最近 TREND_WINDOW 根【15m】",
     1),
    ("故取 24h 作兜底", 0),
    ("这 5 个键不走 _USER_MAP", 0),
]
bad = 0
for pat, want in checks:
    got = chk.count(pat)
    flag = "OK " if got == want else "!! "
    if got != want:
        bad += 1
    print("  %s%-58s %d（期望 %d）" % (flag, pat[:56], got, want))
print("\n复查%s" % ("全部通过" if bad == 0 else "有 %d 项不符" % bad))
sys.exit(0 if bad == 0 else 1)
