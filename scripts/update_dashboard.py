#!/usr/bin/env python3
"""Fetch latest Kaggle status and output dashboard_data.json."""

import datetime
import json
import os
import sys
from pathlib import Path

COMPETITION = "gemma-4-developer-agent"
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_FILE = BASE_DIR / "data" / "dashboard_data.json"


def main():
    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi()
    api.authenticate()

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_jst = now_utc.astimezone(datetime.timezone(datetime.timedelta(hours=9)))

    # 1. Fetch Submissions
    print("Fetching submissions...")
    raw_subs = api.competition_submissions(COMPETITION)
    submissions = []
    active_submission = None

    for s in raw_subs:
        dt = s.date.replace(tzinfo=datetime.timezone.utc)
        dt_jst = dt.astimezone(datetime.timezone(datetime.timedelta(hours=9)))
        status_str = str(s.status).replace("SubmissionStatus.", "")
        
        # Calculate duration if complete
        sub_info = {
            "ref": s.ref,
            "date_utc": dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "date_jst": dt_jst.strftime("%Y-%m-%d %H:%M:%S JST"),
            "status": status_str,
            "score": float(s.public_score) if s.public_score else None,
            "description": s.description or "",
            "error": s.error_description or ""
        }
        submissions.append(sub_info)

        if status_str == "PENDING" and active_submission is None:
            elapsed_sec = (now_utc - dt).total_seconds()
            elapsed_hours = elapsed_sec / 3600.0
            # Standard duration estimate: ~28 hours
            est_total_hours = 28.0
            progress_pct = min(98.0, max(5.0, (elapsed_hours / est_total_hours) * 100.0))
            est_done_jst = dt_jst + datetime.timedelta(hours=est_total_hours)

            active_submission = {
                "ref": s.ref,
                "description": s.description or "",
                "start_jst": dt_jst.strftime("%Y-%m-%d %H:%M:%S JST"),
                "elapsed_hours": round(elapsed_hours, 1),
                "progress_pct": round(progress_pct, 1),
                "est_completion_jst": est_done_jst.strftime("%Y-%m-%d %H:%M:%S JST"),
            }

    # Best completed score
    completed = [s for s in submissions if s["status"] == "COMPLETE" and s["score"] is not None]
    best_score = max([s["score"] for s in completed]) if completed else 0.0

    # 2. Fetch Leaderboard
    print("Fetching leaderboard...")
    raw_lb = api.competition_leaderboard_view(COMPETITION)
    leaderboard = []
    my_team_info = None

    for i, entry in enumerate(raw_lb, 1):
        team_name = getattr(entry, "team_name", getattr(entry, "teamName", ""))
        score_val = getattr(entry, "score", 0.0)
        try:
            score_float = float(score_val)
        except (ValueError, TypeError):
            score_float = 0.0
        
        is_my_team = "tsuyoshi chiba" in team_name.lower() or "chiba" in team_name.lower()
        lb_item = {
            "rank": i,
            "team_name": team_name,
            "score": score_float,
            "is_my_team": is_my_team
        }
        leaderboard.append(lb_item)
        if is_my_team and my_team_info is None:
            my_team_info = lb_item

    # If my team wasn't in top 20, default to known stats
    if not my_team_info:
        my_team_info = {
            "rank": 314,
            "team_name": "Tsuyoshi Chiba",
            "score": best_score or 0.20,
            "is_my_team": True
        }

    # 3. Cutoffs
    gold_cutoff_score = 0.24 # Effective gold threshold
    silver_cutoff_score = 0.21
    bronze_cutoff_score = 0.20

    # 4. Fetch Discussions (Top 15)
    print("Fetching forum topics...")
    topics = []
    try:
        t_resp = api.competition_list_topics(COMPETITION)
        t_list = getattr(t_resp, "topics", []) if not isinstance(t_resp, list) else t_resp
        for t in t_list[:15]:
            tid = getattr(t, "id", "")
            title = getattr(t, "title", "")
            votes = getattr(t, "votes", 0) or getattr(t, "vote_count", 0)
            comments = getattr(t, "comment_count", 0)
            author = getattr(t, "author_name", "") or ""
            url = getattr(t, "topic_url", "") or f"/competitions/{COMPETITION}/discussion/{tid}"
            topics.append({
                "id": tid,
                "title": title,
                "votes": votes or 0,
                "comments": comments or 0,
                "author": author,
                "url": f"https://www.kaggle.com{url}" if url.startswith("/") else url
            })
    except Exception as e:
        print("Forum fetch failed:", e)

    # Preserve existing gemini insights if present
    gemini_insights = []
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                prev_data = json.load(f)
                gemini_insights = prev_data.get("gemini_forum_insights", [])
        except Exception:
            pass

    if not gemini_insights:
        gemini_insights = [
            {
                "topic_id": 747248,
                "title": "Private Dataset Specification & Solvability",
                "badge": "Host Confirmed",
                "insight": "ホスト公式発表: Private は公開リポジトリ（FastAPI/Rich）と重複ゼロ、全問100%解決可能、かつ async def 修正は0件（100%同期コード）。特定リポジトリへの過学習を排し、普遍的なPython標準仕様の抽出が最善解。"
            },
            {
                "topic_id": 745998,
                "title": "Temperature & Diverse Sampling Strategies",
                "badge": "Community Breakthrough",
                "insight": "Idrisメソッド等の検証により、同一の決定論的モデル（T=0.2）でのループを脱出するために Temperature 1.0 + Top-P 0.95 による多様性探索が有効と実証。次期候補 V10 の採用根拠。"
            },
            {
                "topic_id": 746112,
                "title": "14,336-Token Compaction Cliff & Generation Latency",
                "badge": "Physical Constraint",
                "insight": "実推論速度 17.25 tok/s (58ms/tok) の物理制約下では、思考や復唱でのトークン浪費が 58% Empty Patch の主因。既存コード復唱を禁止し、Call 8〜12 での早期編集到達がスコアを左右する。"
            }
        ]

    # Load Mini-Kaggle Evaluator results if present
    mini_kaggle_data = None
    mini_eval_file = BASE_DIR / "data" / "mini_kaggle_eval_results.json"
    if mini_eval_file.exists():
        try:
            with open(mini_eval_file, "r", encoding="utf-8") as f:
                mini_kaggle_data = json.load(f)
        except Exception as e:
            print(f"Failed to load mini_kaggle_eval_results.json: {e}")

    # 5. Assemble payload
    payload = {
        "last_updated_utc": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "last_updated_jst": now_jst.strftime("%Y-%m-%d %H:%M:%S JST"),
        "active_job": active_submission,
        "my_team": my_team_info,
        "best_score": best_score,
        "gemini_forum_insights": gemini_insights,
        "mini_kaggle_eval": mini_kaggle_data,
        "cutoffs": {
            "first_place": 0.29,
            "gold_safe": 0.24,
            "gold_tie_boundary": 0.22,
            "silver": 0.21,
            "bronze": 0.20
        },
        "submissions": submissions,
        "leaderboard_sample": leaderboard[:15],
        "discussions": topics,
        "pipeline": [
            {
                "version": "V23 Hybrid-Fast",
                "ref": 58451077,
                "status": "RUNNING (PENDING)",
                "status_color": "emerald",
                "badge": "本番採点中（Day 27 / Ref 58451077）",
                "target_date": "2026-11-17 10:20 JST 投入（評価完了待ち）",
                "expected_score": "0.20 帯安定化（A100 33.3% / L4 50.0% 実測）",
                "objective": "コード引用禁止・出力短縮による推論時間半減（-52.5%）と read_file 80-120行維持の両立",
                "benefits": [
                    "L4 実機テストで True Pass Rate 50.0%（3/6: rich_4077, rich_3882, rich_3278 初突破）を記録",
                    "Avg Step Latency 22.62s（L4）/ 23.52s（A100）で V9_Ultimate（49.55s）から約半減・タイムアウト耐性高",
                    "Patch Rate 66.7% 達成、Gate 1 & Gate 2（pre-submission-gate）完全通過済"
                ],
                "risks": "max_time_minutes=8 設定のため、Kaggle 本番の全体制限（62問×処理時間）に対して余裕を注視する必要あり",
                "condition": "現在 Kaggle L4 プールで採点進行中（確定結果を見て次手を判断）"
            },
            {
                "version": "今後の方針（Phase 1〜3 戦略）",
                "ref": None,
                "status": "NEXT STRATEGY",
                "status_color": "indigo",
                "badge": "最新戦略ロードマップ",
                "target_date": "Day 27〜Final（締切 2026-12-02）",
                "expected_score": "再現性重視・0.20 壁の安定突破狙い",
                "objective": "プロンプト文言の小手先調整を凍結し、統計的根拠とハーネス構造・検証規律に基づく改善に集中",
                "benefits": [
                    "方針1（V23 本番結果の評価）: mobassir 氏（11回同一提出で 0.14〜0.19 分散）および dominyellow 氏（6,187 ラン・30 変種比較で小規模微調整は全滅）の知見に基づき、プロンプト文言の反復微修正を凍結して Ref 58451077 のスコア・完走性を評価",
                    "方針2（時間安全枠 6〜7分最適化 & 挙動直接検証）: もし V23（8分枠）でタイムアウト傾向が出た場合は dominyellow 氏実証の 6〜7分枠へ調整し、evgendvorkin 氏の『既存テストだけでなく問題挙動そのものを直接検証する（Behavior Verification）』規律と AgentTool (skip_summarization: true) のみ検証",
                    "方針3（L4 高速評価基盤での評価タスク拡張）: swegemma 3-Tier 編集互換＋StoppingCriteria（約 20 分/6問）を拡張し、より多くのタスクでのペア比較で有意差が出た候補のみ提出"
                ],
                "risks": "新規識別子（Issue文に無いシンボルを隠れテストが要求するタスク 17/96問）など 31B モデル構造上限に由来する限界が存在",
                "condition": "Ref 58451077 の確定ステータスに応じて方針2を即時実行"
            },
            {
                "version": "L4 4連続比較検証（V24 / V25 / V26 / V27）",
                "ref": None,
                "status": "REJECTED IN A/B",
                "status_color": "amber",
                "badge": "Day 27 実機 A/B 不採用知見",
                "target_date": "2026-11-17 L4 検証完了",
                "expected_score": "L4 True Pass Rate 33.3%（V23 50.0% 未満）",
                "objective": "公開有力手法（Patchsmith exp025, T=0.0, Think=512, ADK {problem_description} ピン留め）の横並び効果検証",
                "benefits": [
                    "V25_Deterministic_T0（T=0.0）: 33.3%（25.55s）。決定論化は誤った探索経路から抜け出せず V23（T=0.2）に劣後",
                    "V26_Lean_Think512（512 tok）: 33.3%（19.11s 最速）。思考制限により Missing old_string が 2→7 に激増",
                    "V27_Issue_Pinned（{problem_description} ピン留め）: 33.3%（22.50s）。12ターン・L4 3584 tok 上限下では冗長となり効果限定的",
                    "V24_Patchsmith_Exp025: L4 途中で 1/5（長考 170s/turn＋thoughtループ多発）のため見送り"
                ],
                "risks": "いずれも単体では V23_Hybrid_Fast（50.0%）を超えられなかったため本番提出から除外",
                "condition": "不採用確定（L4 検証環境の高速化・3-Tier 編集改修の副産物を獲得）"
            },
            {
                "version": "V9_Ultimate (0.20 → 0.12) & V18 (0.18 → 0.13)",
                "ref": 58387461,
                "status": "VARIANCE PROOF",
                "status_color": "rose",
                "badge": "Day 20-26 分散・復旧実証",
                "target_date": "2026-11-11〜16（Ref 58387461: 0.12 / 58268405: 0.13）",
                "expected_score": "0.12 〜 0.20（同一 ZIP での実測振れ幅 ±0.08）",
                "objective": "Day 20 (0.00) からの復旧、および同一パッケージ再提出による本番分散の実測",
                "benefits": [
                    "Day 20 (Ref 58179275: 0.00) で vLLM tool_call_parser='gemma4' との構文衝突を特定し、Gate 1/2 検査を確立",
                    "V9_Ultimate（0.20→0.12）と V18（0.18→0.13）の再提出により、同一設定でも Public LB が大きく上下する分散特性を自社データで証明"
                ],
                "risks": "単発 LB スコア（58問中 1問=1.72点）に一喜一憂すると誤ったモデル選択を招く危険性",
                "condition": "完了・統計的評価方針へ反映済"
            }
        ],
        "unsolved_challenges": [
            {
                "id": "CHALLENGE-01",
                "title": "Public LB の高分散（同一 ZIP で 0.12〜0.20）と統計的検出力不足",
                "category": "評価安定性・サンプリング分散",
                "severity": "CRITICAL",
                "severity_color": "rose",
                "metric": "V9: 0.20→0.12 / V18: 0.18→0.13 / 公開B: 0.14→0.19",
                "fact": "我々の再提出実験に加え、mobassir 氏（11回提出で 8〜11問=0.14〜0.19）および dominyellow 氏（1タスク=0.017、同一ファイルで 1〜3問差は日常的）が示す通り、単発提出では ±0.03〜0.08 のノイズが乗る。",
                "bottleneck": "1〜2 問の真の改善を Public LB で有意に検出するには 18〜37 回の提出が必要であり、1日1提出かつ20〜30時間待ちの環境ではテスト不可能。",
                "current_hypothesis": "単発 LB でプロンプトを捨てず、L4 ローカル環境でタスク数を拡張した同条件ペア比較によってのみ採用・不採用を判定する。"
            },
            {
                "id": "CHALLENGE-02",
                "title": "Prompt-Only 微調整の限界と「Issue 文に無い新規識別子」の壁",
                "category": "推論能力・情報欠損",
                "severity": "CRITICAL",
                "severity_color": "rose",
                "metric": "30変種全滅 (dominyellow) / 新規識別子タスク正答率 3%",
                "fact": "dominyellow 氏の 6,187 ラン実験では 30 種のプロンプト・スキル変更のいずれも同時ペア比較で優位を示せず、また 96問中 17問は隠れテストが Issue に未記載の PR 作者命名識別子を直接 import するため解決率が 3%（通常 31%）に激減していた。",
                "bottleneck": "我々の L4 検証（V24〜V27 すべて 33.3%）でもプロンプト調整のみの天井が再確認された。また mobassir 氏実験でも Open-SWE-Traces 蒸留 LoRA はループ増加で悪化、include_thoughts=false は再考増加でタイムアウト悪化と報告されている。",
                "current_hypothesis": "文言微修正を止め、Behavior Verification（挙動の直接再現検証）と AgentTool によるコンテキスト分離、および 6〜7分予算バランスに絞る。"
            },
            {
                "id": "CHALLENGE-03",
                "title": "28.6% の複数ファイル連動見落とし & 全体タイムアウト（8分 vs 6〜7分）",
                "category": "時間予算・局所化",
                "severity": "HIGH",
                "severity_color": "amber",
                "metric": "連動修正 28.6% / 8分設定での Notebook Timeout 事例",
                "fact": "全可解タスクの 28.6% は 2ファイル以上の連動修正を要する一方、dominyellow 氏は 8分/240s 設定や 15分設定で Kaggle 全体の壁時間超過（Notebook Timeout 0点）を経験し、6分/28 calls 設定に戻すことで安定完走（0.17〜0.18）を実現した。",
                "bottleneck": "1問あたり上限を延ばすと全体タイムアウト失格リスクが跳ね上がり、短くしすぎると複数ファイル修正を最後までやり切れない。",
                "current_hypothesis": "V23 の 22.62s/step 高速化を土台にしつつ、Ref 58451077 の完走結果次第で 6〜7分枠＋command timeout 60s の安全構成を比較検証する。"
            },
            {
                "id": "CHALLENGE-04",
                "title": "Public/Private キュー長期滞留（15〜33時間待ち）による試行回数制約",
                "category": "インフラ・実験スループット",
                "severity": "HIGH",
                "severity_color": "amber",
                "metric": "Pending 制限 + 20〜30時間待ち",
                "fact": "Kaggle L4 GPU プール混雑により 1 回の提出結果確定に 20〜30 時間以上かかり、Pending 中は次提出が制限されるため締切（2026-12-02）までの実提出枠が限られる。",
                "bottleneck": "本番 LB に検証を頼れないため、Colab L4/A100 上のオフライン検証の忠実度と再現性が直接の勝敗要因になる。",
                "current_hypothesis": "swegemma 3-Tier 編集互換・StoppingCriteria 搭載の L4 高速ハーネス（約20分完走）と verify_pre_submission.py ゲートを厳守する。"
            }
        ],
        "key_findings": [
            {
                "title": "Community Meta-Analysis: 6,187 Runs & Statistical Power Limits",
                "title_en": "Community Meta-Analysis: 6,187 Runs & Statistical Power Limits",
                "title_ja": "① 大規模メタ分析（6,187ラン＆統計検出力）：プロンプト微調整の限界と分散",
                "tag": "META-ANALYSIS",
                "tag_en": "META-ANALYSIS",
                "tag_ja": "コンペ全体知見",
                "desc": "mobassir (11 draws: 0.14-0.19) and dominyellow (6,187 runs, 30 variants) prove prompt tweaks rarely beat baseline noise; new hidden test symbols drop solve rate from 31% to 3%.",
                "desc_en": "mobassir (11 draws: 0.14-0.19) and dominyellow (6,187 runs, 30 variants) prove prompt tweaks rarely beat baseline noise; new hidden test symbols drop solve rate from 31% to 3%.",
                "desc_ja": "mobassir 氏（同一構成 11回提出で 0.14〜0.19 分散）および dominyellow 氏（580時間・30変種ペア比較で時間予算以外すべて優位なし）の報告により、小幅なプロンプト変更の限界と単発 LB のノイズ（±0.05〜0.08）が判明。",
                "detail_ja": "【今後の方針への反映】\n20問以下の小開発セットの偶然の上振れを追いかけず、不要なプロンプト微調整を凍結して、L4 ペア比較のタスク数拡張と時間・検証規律の最適化へ移行します。"
            },
            {
                "title": "V23_Hybrid_Fast L4 50.0% & Simulator 3-Tier / StoppingCriteria Breakthrough",
                "title_en": "V23_Hybrid_Fast L4 50.0% & Simulator 3-Tier / StoppingCriteria Breakthrough",
                "title_ja": "② L4 高速検証基盤の確立（22.62s/step）と V23 の rich_3278 初突破（50.0%）",
                "tag": "BREAKTHROUGH",
                "tag_en": "BREAKTHROUGH",
                "tag_ja": "検証基盤・V23実績",
                "desc": "Fixing L4 OOM, StoppingCriteria for thought loops, and swegemma 3-Tier raw_exact matching unlocked rich_3278 and lifted V23_Hybrid_Fast to 50.0% (22.62s/step) on L4.",
                "desc_en": "Fixing L4 OOM, StoppingCriteria for thought loops, and swegemma 3-Tier raw_exact matching unlocked rich_3278 and lifted V23_Hybrid_Fast to 50.0% (22.62s/step) on L4.",
                "desc_ja": "PYTORCH_CUDA_ALLOC_CONF 先行設定・vision_tower 破棄・logits_to_keep=1・StoppingCriteria により L4 23.7GB でも OOM ゼロで 20分完走する検証基盤を確立。さらに swegemma 3-Tier 互換の raw_exact 修正で V23_Hybrid_Fast が rich_3278 を初突破し True Pass Rate 50.0% を達成。",
                "detail_ja": "【検証実績】\nV23 (50.0%, 22.62s) に対し、V24 (1/5 途中中止), V25 T=0.0 (33.3%, 25.55s), V26 Think=512 (33.3%, Missing old_string 7回), V27 Issue-Pinned (33.3%) のいずれも上回れず、現時点では V23 が最良です。"
            },
            {
                "title": "include_thoughts=true + Budget Cap vs include_thoughts=false Backfire",
                "title_en": "include_thoughts=true + Budget Cap vs include_thoughts=false Backfire",
                "title_ja": "③ thinking_budget と include_thoughts の適切なバランス（512以下は悪化）",
                "tag": "EXPERIMENT",
                "tag_en": "EXPERIMENT",
                "tag_ja": "思考予算知見",
                "desc": "mobassir showed include_thoughts=false backfires (re-thinking causes timeouts), while halving thinking_budget helps. Our V26 test showed 512 tokens drops precision (Missing old_string 2→7).",
                "desc_en": "mobassir showed include_thoughts=false backfires (re-thinking causes timeouts), while halving thinking_budget helps. Our V26 test showed 512 tokens drops precision (Missing old_string 2→7).",
                "desc_ja": "mobassir 実験では過去の思考履歴を消す（include_thoughts=false）と毎ターン再考が走りタイムアウトが激増。逆に thinking_budget を 4096→2048 に抑えるのが有効とされ、我々の V26（512制限）実測でも削りすぎは編集文字列不一致（7回）を招くため 2048 前後が適正と確認。",
                "detail_ja": "【運用指針】\nconfigs/sampling.yaml は include_thoughts=true, thinking_budget=2048, max_output_tokens=16384, temperature=0.2 を基準値として維持します。"
            },
            {
                "title": "Whole-Run Timeout Discipline (6-7m Safe Cap vs 8m Edge)",
                "title_en": "Whole-Run Timeout Discipline (6-7m Safe Cap vs 8m Edge)",
                "title_ja": "④ 全体制限（Notebook Timeout 0点）回避のための時間キャップ規律",
                "tag": "TIMEOUT",
                "tag_en": "TIMEOUT",
                "tag_ja": "時間管理",
                "desc": "dominyellow observed Notebook Timeout at 8m/240s and 15m/50calls while 6m/28calls always completed. Repair Lab exp025 caps single commands at 60s.",
                "desc_en": "dominyellow observed Notebook Timeout at 8m/240s and 15m/50calls while 6m/28calls always completed. Repair Lab exp025 caps single commands at 60s.",
                "desc_ja": "dominyellow 氏は 8分/240秒設定でも隠れテスト全体時間超過（0点）に陥り、6分/28コール設定で完走を安定させました。また Repair Lab exp025 では単一コマンド timeout を 60秒に絞っています。",
                "detail_ja": "【次手への反映】\n現在採点中の Ref 58451077 (V23, 8分/240s) が万一タイムアウトする、または今後の安定版を作る際は max_time_minutes=6〜7・timeout_seconds=60〜120 の安全設定を適用します。"
            },
            {
                "title": "vLLM Native Parser Purity & Behavior Verification Focus",
                "title_en": "vLLM Native Parser Purity & Behavior Verification Focus",
                "title_ja": "⑤ vLLM パーサー純粋性ゲートと『問題挙動の直接検証（Behavior Check）』",
                "tag": "CRITICAL",
                "tag_en": "CRITICAL",
                "tag_ja": "品質・検証規律",
                "desc": "Gate 1/2 prevents Day 20 (0.00) tool-format leaks while permitting official ADK placeholders ({problem_description}, {hints?}). Next focus: verifying reported defect behavior directly.",
                "desc_en": "Gate 1/2 prevents Day 20 (0.00) tool-format leaks while permitting official ADK placeholders ({problem_description}, {hints?}). Next focus: verifying reported defect behavior directly.",
                "desc_ja": "verify_pre_submission.py は Day 20 (0.00) の再発を物理遮断しつつ、Google ADK 正規変数（{problem_description}, {hints?}）のみを許容するよう更新済み。今後は evgendvorkin 氏らが着目する『既存テストだけでなくバグ再現挙動そのものを直接検証する手順』と AgentTool 分離を検証します。",
                "detail_ja": "【総括】\nLoRA/SFT は Open-SWE-Traces でのループ悪化や 15〜20% 遅延リスクが高いため見送り、Prompt＋検証規律＋時間枠制御にリソースを集中します。"
            }
        ]
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"Successfully generated {OUTPUT_FILE} ({OUTPUT_FILE.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
