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
                "version": "V37 Idris-V31 (T=1.0, top_k=64)",
                "ref": 58985238,
                "status": "RUNNING (PENDING)",
                "status_color": "emerald",
                "badge": "本番採点中（Ref 58985238）",
                "target_date": "2026-11-27 15:14 JST 投入（評価完了待ち）",
                "expected_score": "0.20 壁突破狙い（L4 2回連続 33.3% / タイムアウト 0 件）",
                "objective": "Idris V31 の簡潔規律（One check, one repair, then submit）と T=1.0 / top_k=64 探索の 32k 本番環境での検証",
                "benefits": [
                    "L4 12問診断で 2 回連続 33.3%（4/12 PASS）を記録し、同環境での V9（25.0%）・V35（25.0%）を上回る安定性",
                    "タイムアウト 0 件（V9 は 4 件・V35 は 2 件）、Avg Step Latency 25.88s〜27.65s と軽量",
                    "Gate 1（vLLM パーサー純粋性）& Gate 2（Colab L4 6/6 test_patch=100%, 33.3% PASS）通過済"
                ],
                "risks": "Colab L4（3,584 トークン制限・4bit 量子化）上での検証であり、本番（32,768 トークン・高分散 Public LB）での優位再現は未確定",
                "condition": "現在 Kaggle 評価キューで採点進行中（確定スコア待ち）"
            },
            {
                "version": "V38 Idris-Edit-Hardened (L4 A/B 完了)",
                "ref": None,
                "status": "HOLD (TIED IN A/B)",
                "status_color": "amber",
                "badge": "L4 12問ペア比較完了",
                "target_date": "2026-11-27 02:57 JST L4 完了",
                "expected_score": "L4 True Pass Rate 33.3%（V37 と 4/12 引き分け）",
                "objective": "Call 8 編集前倒し・空 old_string 禁止 & python3 -c フォールバック・提出前 1 回チェックによる NO_DIFF / TEST_FAIL 削減",
                "benefits": [
                    "Avg 1st Edit Turn が 8.5 → 7.5 ターンへ早まり、Patch Rate も 50.0% → 58.3%（7/12）へ改善",
                    "V37 と同一の 4 問（rich_4077, rich_3882, rich_3278, rich_3894）を安定突破"
                ],
                "risks": "rich_4076 で miss_old=6 により python3 -c フォールバックへ逃げられず NO_DIFF 終了。またプロンプト増量・提出前チェック必須化により L4 上の切り詰め回数が 48回 → 58回（Peak 11,959 tok）へ増加",
                "condition": "V37 を上回れなかったため保留（まず V37 本番結果を確認）"
            },
            {
                "version": "V35 Single-Compacted-V2 (本番 0.12 / L4 再検 25.0%)",
                "ref": 58825693,
                "status": "COMPLETE (0.12)",
                "status_color": "rose",
                "badge": "Colab 乖離・人工物検証済",
                "target_date": "2026-11-24 20:00 JST 投入（Ref 58825693: 0.12）",
                "expected_score": "Colab 41.7% → 本番 0.12（L4 再検では 25.0%）",
                "objective": "ADK EventsCompactionConfig 相当の履歴圧縮（V35）による本番スコア向上の検証",
                "benefits": [
                    "L4 上の Patch Rate は 66.7%（8/12）と高く、平均レイテンシも 25.43s/step と高速"
                ],
                "risks": "Colab L4 の max_ctx=3584 左切り詰め（先頭 Issue 消失）下では圧縮が有利に働く『環境由来の人工物』が含まれていた懸念があり、本番（32,768 tokens）では 0.12 に留まった",
                "condition": "L4 再比較でも V9 と同率 25.0%（3/12）に収束し、優位性を確認できず"
            },
            {
                "version": "今後の方針（V37 本番評価 & 切り詰めなし検証）",
                "ref": None,
                "status": "NEXT STRATEGY",
                "status_color": "indigo",
                "badge": "最新戦略ロードマップ",
                "target_date": "〜Final（締切 2026-12-02）",
                "expected_score": "環境ギャップ排除 & 0.20 壁突破",
                "objective": "V37 本番スコアの確認と、A100 等での切り詰めなし環境・構造的ボトルネック（NO_DIFF）への対処",
                "benefits": [
                    "Ref 58985238（V37）の本番結果で Idris V31 規律 + T=1.0/top_k=64 が 32k 本番で機能するか評価",
                    "A100 割当時に colab_a100_notrunc_diagnostic.ipynb（max_ctx=12,288〜20,480）で『切り詰め 0 回』の真の比較を実施",
                    "12 問 L4 での小幅プロンプト調整のループを止め、失敗モード別の構造対策に集中"
                ],
                "risks": "Public LB は同一 ZIP でも 0.12〜0.20 で大きく揺れるため、単発スコアの過度な解釈は禁物",
                "condition": "Ref 58985238 確定待ち"
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
                "title": "Colab L4 (3,584 tok) 切り詰め人工物 & 駆け込み NO_DIFF の壁",
                "category": "検証環境ギャップ・編集失敗",
                "severity": "CRITICAL",
                "severity_color": "rose",
                "metric": "L4 切り詰め 38〜62回 / V37・V38 L4 頭打ち 33.3%",
                "fact": "Colab L4 は max_ctx=3584 で入力先頭を切り捨てるため、V9 (62回超過) より履歴圧縮の V35 (39回超過) が有利に見える環境由来の人工物が発生しやすい。また 12 ターン制限下では調査が長引き、edit_file(..., old='') による NO_DIFF が全系統で多発（V37: 5〜6件, V38: 4件）。",
                "bottleneck": "本番は 32,768 トークン（ADK compaction 14,336）であり L4 と挙動が異なる。さらに 12 問規模の L4 ではプロンプト微調整をしても 33.3% 付近で頭打ち傾向が見られた。",
                "current_hypothesis": "V37 本番結果（Ref 58985238）で 32k 環境での実力を確認しつつ、A100 による切り詰めゼロ比較と失敗モード別の構造対策へ移行する。"
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
                "title": "V37/V38 L4 A/B Diagnostics & Context Truncation Artifact Analysis",
                "title_en": "V37/V38 L4 A/B Diagnostics & Context Truncation Artifact Analysis",
                "title_ja": "⑥ V37/V38 L4 診断（33.3% 安定）と 3,584 トークン先頭切り詰め人工物の特定",
                "tag": "DIAGNOSTICS",
                "tag_en": "DIAGNOSTICS",
                "tag_ja": "最新実測知見",
                "desc": "V37 achieved 33.3% twice on L4 (0 timeouts), tying V38 (33.3%). Diagnostics revealed L4 max_ctx=3584 left-truncation drops issue heads and late empty-old_string edits cause NO_DIFF.",
                "desc_en": "V37 achieved 33.3% twice on L4 (0 timeouts), tying V38 (33.3%). Diagnostics revealed L4 max_ctx=3584 left-truncation drops issue heads and late empty-old_string edits cause NO_DIFF.",
                "desc_ja": "V35 (0.12) の乖離調査から、Colab L4 の max_ctx=3584 左切り詰めが『先頭の Issue 文』を削る環境由来の人工物（V9: 62回 vs V35: 39回超過）を生む点を特定。一方、V37 (T=1.0, top_k=64) は L4 で 2回連続 33.3%・タイムアウト 0件を記録し、V38 との比較でも 33.3% 同率だったため V37（Ref 58985238）を本番提出。",
                "detail_ja": "【次手への反映】\n・V38 は着手ターン（8.5→7.5）と Patch Rate（50.0%→58.3%）を改善したものの、トークン膨張で切り詰めが 48回→58回に増え Pass Rate は 33.3% 止まり。\n・今後は Ref 58985238 (V37) の本番結果と A100 切り詰めゼロ検証で真の効果を切り分けます。"
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
