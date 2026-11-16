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
                "ref": None,
                "status": "TESTING (Colab A/B 待機)",
                "status_color": "indigo",
                "badge": "最新設計（Day 26）",
                "target_date": "A100 Colab 実機比較中",
                "expected_score": "0.20+ (安定化狙い)",
                "objective": "V22 の 47% 高速化（コード引用禁止・出力短縮）を維持しつつ、read_file を 80-120 行へ緩和して Missing old_string を解消",
                "benefits": [
                    "V22 で実証された平均ステップ時間 45.62s → 24.15s（-47%）の高速化要因を継承",
                    "max_output_tokens=16384 へ引き上げ（HARNESS_README 推奨）による <|tool_call> 途中切断防止",
                    "Gate 1（ZIP構造 & vLLM ネイティブパーサー純粋性）通過済"
                ],
                "risks": "プロンプト調整のみではベースモデル 31B の限界（0.20 壁）を劇的に超えられない可能性",
                "condition": "Colab A100 で V9_Ultimate (50.0%) を上回った場合のみ提出候補化"
            },
            {
                "version": "V9_Ultimate (再提出) & V22_Context_Guard",
                "ref": 58387461,
                "status": "COMPLETE (0.12) / A/B不採用",
                "status_color": "rose",
                "badge": "Day 25-26 検証結果",
                "target_date": "2026-11-16 確定（Ref 58387461: 0.12）",
                "expected_score": "0.12 (同一ZIPで 0.20 → 0.12 へ分散下落)",
                "objective": "過去ベスト V9_Ultimate の再現性検証、および V22 の 60 行制限によるコンパクション回避検証",
                "benefits": [
                    "V22 の出力短縮でレイテンシ半減（45.62s → 24.15s）と Patch Rate 向上（50% → 66.7%）を確認",
                    "同一 V9_Ultimate ZIP の再提出で 0.20 → 0.12 となる大きなサンプリング分散を実測確認"
                ],
                "risks": "V22 は read_file 60行制限で Missing old_string が 0→4 へ悪化し True Pass Rate が 33.3% に低下（不採用）",
                "condition": "完了・教訓を V23 へ反映済"
            },
            {
                "version": "V18 Native Clean (2回提出) & V20/V21",
                "ref": 58268405,
                "status": "COMPLETE (0.18 → 0.13)",
                "status_color": "amber",
                "badge": "Day 21-24 検証結果",
                "target_date": "2026-11-11〜13（Ref 58226200: 0.18 / 58268405: 0.13）",
                "expected_score": "0.13〜0.18 (A/B 50.0% 頭打ち)",
                "objective": "vLLM ネイティブパーサー純粋化（Day 20 0.00 事故の復旧）と V20/V21 の Colab A/B 検証",
                "benefits": [
                    "prompts/system.md からツール構文記述を完全排除し、Day 20 (0.00) から 0.18 へ即座に回復",
                    "verify_pre_submission.py による Gate 1 / Gate 2 の提出前自動検査を確立"
                ],
                "risks": "V18/V20/V21 いずれも Colab True-Grader で 50.0%（3/6問）の天井を超えられず",
                "condition": "V18 2回目も 0.13 に振れ、プロンプト単体最適化の限界が顕在化"
            },
            {
                "version": "V17.1 (0.00事故) & V14/V15 (0.12〜0.15)",
                "ref": 58179275,
                "status": "FAILED / REJECTED",
                "status_color": "rose",
                "badge": "Day 17-20 失敗知見",
                "target_date": "2026-11-07〜10",
                "expected_score": "0.00 〜 0.15",
                "objective": "Call 7/8 強制編集・構造化推論・シミュレータ用プロンプトの実験",
                "benefits": [
                    "V17.1 (0.00) により vLLM tool_call_parser='gemma4' との構文衝突（```python 混入致命傷）を特定",
                    "V14 (0.12) / V15 (0.15) により過度な強制編集は精度を落とすことを確認"
                ],
                "risks": "プロンプトにシミュレータ用のツール構文例を書くと本番環境で全問 0 点になる",
                "condition": "完全解決（Gate 1 禁止ワード検査で再発防止済）"
            }
        ],
        "unsolved_challenges": [
            {
                "id": "CHALLENGE-01",
                "title": "同一 ZIP で 0.20 → 0.12 に振れる極端なスコア分散（T=0.2 の罠）",
                "category": "評価安定性・サンプリング分散",
                "severity": "CRITICAL",
                "severity_color": "rose",
                "metric": "V9_Ultimate: 0.20 → 0.12 / V18: 0.18 → 0.13",
                "fact": "過去ベスト 0.20 を出した V9_Ultimate と完全同一のパッケージを再提出（Ref 58387461）したところ 0.12 を記録。V18 でも 0.18 → 0.13 と下落し、同一設定でも Public スコアが最大 0.08 変動することが実測された。",
                "bottleneck": "Public テスト数が限られている上、temperature=0.2 の確率的サンプリングで 1〜2 手目の探索パスが分岐すると結果が大きく変わる。",
                "current_hypothesis": "temperature を下げる（例: 0.0〜0.1）検証、またはプロンプト微調整を超えたモデル適応（SFT/LoRA やエージェント構造改革）の検討が必要。"
            },
            {
                "id": "CHALLENGE-02",
                "title": "プロンプト単体最適化の天井（0.20 の壁 vs 上位 0.24〜0.29）",
                "category": "推論能力・モデル限界",
                "severity": "CRITICAL",
                "severity_color": "rose",
                "metric": "Colab 検証 33.3%〜50.0% 収束",
                "fact": "V9.1 / V9.2 / V14 / V15 / V18 / V20 / V21 / V22 の 8 系統以上のプロンプト改良を試したが、いずれもローカル True-Grader で 50.0% 前後、本番 LB で 0.12〜0.18 に留まり、0.20 を安定超えできていない。",
                "bottleneck": "31B ベースモデルのゼロショット推論能力と 14,336 トークン圧縮崖（LlmEventSummarizer のツール履歴欠落バグ）の両面が壁になっている。",
                "current_hypothesis": "V23 でレイテンシ短縮と edit 精度の両立を測りつつ、必要に応じて AgentTool によるコンテキスト分離や temperature 低下等の構造変更を検証する。"
            },
            {
                "id": "CHALLENGE-03",
                "title": "28.6% の複数ファイル連動見落とし（Coupled Files Drift）",
                "category": "コンテキスト把握・局所化",
                "severity": "HIGH",
                "severity_color": "amber",
                "metric": "可解タスクの 28.6% (34/119問)",
                "fact": "全可解タスクの 28.6% は 2 ファイル以上の連動修正を必要とする。エージェントは 1 ファイル目を直すと満足して終了し、連動側の不整合でテストが落ちる。",
                "bottleneck": "コンテキスト長制限（14k崖）と 8 分制限のため、十分なファイル間追跡ができない。",
                "current_hypothesis": "read_file の過度な制限（V22 の 60 行制限）は Missing old_string を増やすため、80〜120 行に緩和しつつコマンド出力を圧縮する。"
            },
            {
                "id": "CHALLENGE-04",
                "title": "Public/Private キュー長期滞留（15〜33時間待ち）による試行回数制約",
                "category": "インフラ・実験スループット",
                "severity": "HIGH",
                "severity_color": "amber",
                "metric": "Pending 制限 + 20〜30時間待ち",
                "fact": "Kaggle L4 GPU プール混雑により 1 回の提出結果確定に 20〜30 時間以上かかり、Pending 中は次提出が制限されるため本番試行回数が限られる。",
                "bottleneck": "本番 LB での試行錯誤が困難であり、Colab A100 上での事前再現検証の精度が生命線となる。",
                "current_hypothesis": "verify_pre_submission.py による Gate 1/2 通過品のみを厳選提出する運用を継続する。"
            }
        ],
        "key_findings": [
            {
                "title": "vLLM Native Parser Contamination (Day 20 Score 0.00)",
                "title_en": "vLLM Native Parser Contamination (Day 20 Score 0.00)",
                "title_ja": "① 本番 vLLM ネイティブパーサー汚染による 0.00 事故の解明",
                "tag": "CRITICAL",
                "tag_en": "CRITICAL",
                "tag_ja": "パーサー互換性",
                "desc": "Including markdown python tool syntax in prompts/system.md breaks vLLM tool_call_parser='gemma4', scoring 0.00 (Ref 58179275). Strict separation restored 0.18.",
                "desc_en": "Including markdown python tool syntax in prompts/system.md breaks vLLM tool_call_parser='gemma4', scoring 0.00 (Ref 58179275). Strict separation restored 0.18.",
                "desc_ja": "Day 20 (Ref 58179275) でプロンプトに ```python ツール形式を混入させた結果、本番 vLLM の gemma4 パーサーがツール呼出と認識できず全問 0 点（0.00）に転落。本番プロンプトからの完全分離により 0.18 へ復旧しました。",
                "detail_ja": "【対策】\npre-submission-gate により本番 ZIP の prompts/system.md を自動検査し、シミュレータ用構文の混入を物理的にブロックしています。"
            },
            {
                "title": "Extreme Run-to-Run Variance (0.20 → 0.12 / 0.18 → 0.13)",
                "title_en": "Extreme Run-to-Run Variance (0.20 → 0.12 / 0.18 → 0.13)",
                "title_ja": "② 同一パッケージで ±0.08 振れる極端なスコア分散の実測",
                "tag": "VARIANCE",
                "tag_en": "VARIANCE",
                "tag_ja": "再現性・分散",
                "desc": "Re-submitting identical V9_Ultimate dropped from 0.20 to 0.12 (Ref 58387461); V18 dropped from 0.18 to 0.13 (Ref 58268405).",
                "desc_en": "Re-submitting identical V9_Ultimate dropped from 0.20 to 0.12 (Ref 58387461); V18 dropped from 0.18 to 0.13 (Ref 58268405).",
                "desc_ja": "V9_Ultimate (0.20) と同一 ZIP の再提出で 0.12、V18 (0.18) の再提出で 0.13 を記録。Public タスク数の少なさと temperature=0.2 の確率的揺らぎだけで 0.05〜0.08 のスコア変動が起きることを実測で確認しました。",
                "detail_ja": "【示唆】\n直近のスコア低下はプロンプト改悪だけでなく、0.12〜0.20 の分散レンジ内の下振れが含まれています。プロンプトの微修正だけでは 0.24+ 帯への安定到達が困難であることが明白になりました。"
            },
            {
                "title": "V22 Latency Halving vs Read-Line Over-Restriction",
                "title_en": "V22 Latency Halving vs Read-Line Over-Restriction",
                "title_ja": "③ コード引用禁止で推論時間 47% 短縮、ただし read 60行制限は逆効果",
                "tag": "EXPERIMENT",
                "tag_en": "EXPERIMENT",
                "tag_ja": "A/B実験知見",
                "desc": "V22 cut step latency from 45.62s to 24.15s (-47%), but capping read_file at 60 lines caused 4 Missing old_string errors (33.3% vs V9 50.0%).",
                "desc_en": "V22 cut step latency from 45.62s to 24.15s (-47%), but capping read_file at 60 lines caused 4 Missing old_string errors (33.3% vs V9 50.0%).",
                "desc_ja": "A100-40GB 実機 A/B テストにおいて、V22 はコード引用禁止と出力短縮により平均ステップ時間を 45.62s → 24.15s（約半減）へ短縮し Patch Rate も 66.7% へ向上しましたが、read_file 60行制限により編集位置不一致が 4 回発生し Pass Rate が 33.3% に低下しました。",
                "detail_ja": "【次手】\nV23_Hybrid_Fast では高速化ルールのみを残し、read_file 上限を 80〜120 行へ緩和して検証します。"
            },
            {
                "title": "ADK 14,336-Token Compaction Cliff & LlmEventSummarizer Bug",
                "title_en": "ADK 14,336-Token Compaction Cliff & LlmEventSummarizer Bug",
                "title_ja": "④ ADK 14,336トークン圧縮崖と LlmEventSummarizer のツール履歴欠落",
                "tag": "STABILITY",
                "tag_en": "STABILITY",
                "tag_ja": "ハーネス仕様",
                "desc": "swegemma compacts context at 14,336 tokens; default summarizer drops function_call/function_response parts, blinding the agent.",
                "desc_en": "swegemma compacts context at 14,336 tokens; default summarizer drops function_call/function_response parts, blinding the agent.",
                "desc_ja": "HARNESS_README 及び Kaggle 議論により、14,336 トークン到達時の自動要約（LlmEventSummarizer）が function_call / function_response を無視し、エージェントが過去の編集や調査を忘却する問題が判明。max_output_tokens=16384 化と出力圧縮による閾値回避が重要です。",
                "detail_ja": "【公式ガイド知見】\nAgentTool (skip_summarization: true) による探索コンテキスト分離も有効な対策として挙げられています。"
            },
            {
                "title": "Prompt-Only Ceiling vs LoRA Serving Overhead",
                "title_en": "Prompt-Only Ceiling vs LoRA Serving Overhead",
                "title_ja": "⑤ Prompt-Only の天井と LoRA 適用時の 15〜20% 遅延トレードオフ",
                "tag": "STRATEGY",
                "tag_en": "STRATEGY",
                "tag_ja": "技術動向",
                "desc": "Community reports prompt-only outperforms naive SFT/LoRA, as LoRA adds 15-20% serving latency and risks format overfitting.",
                "desc_en": "Community reports prompt-only outperforms naive SFT/LoRA, as LoRA adds 15-20% serving latency and risks format overfitting.",
                "desc_ja": "Kaggle 議論では、安易な SFT/LoRA はツール構文過学習や推論速度の 15〜20% 低下を招き、堅牢な Prompt-Only に劣るケースが多いと報告されています。上位帯（0.24〜0.29）はエージェント構造分離や厳選学習（GRPO/不確実性マスク等）を模索しています。",
                "detail_ja": "【総括】\n当面はプロンプト内の冗長削減とコンテキスト境界管理（V23）で 0.20 帯の安定化を狙いつつ、次の抜本策を検討します。"
            }
        ]
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"Successfully generated {OUTPUT_FILE} ({OUTPUT_FILE.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
