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

    # 4. Fetch Discussions (Top 8)
    print("Fetching forum topics...")
    topics = []
    try:
        t_resp = api.competition_list_topics(COMPETITION)
        for t in t_resp.topics[:8]:
            topics.append({
                "id": getattr(t, "id", ""),
                "title": getattr(t, "title", ""),
                "votes": getattr(t, "vote_count", 0),
                "comments": getattr(t, "comment_count", 0),
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

    # 5. Assemble payload
    payload = {
        "last_updated_utc": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "last_updated_jst": now_jst.strftime("%Y-%m-%d %H:%M:%S JST"),
        "active_job": active_submission,
        "my_team": my_team_info,
        "best_score": best_score,
        "gemini_forum_insights": gemini_insights,
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
                "version": "V9.2 Early-Edit Trigger",
                "ref": 58038278,
                "status": "RUNNING (PENDING)",
                "status_color": "emerald",
                "badge": "現在投入中（Day 16）",
                "target_date": "2026-11-06 09:00 投入（採点進行中）",
                "expected_score": "0.20 〜 0.24",
                "objective": "失敗の58%を占める未編集死（Empty Patch）をCall 8で強制遮断",
                "benefits": [
                    "Colab L4 実機ベンチマークで『Empty Patch 率 0.0%（未編集ゼロ）』を事前実証済",
                    "所要時間を 230 秒（-20%短縮）に圧縮し、12時間タイムアウト壁を安全完走",
                    "Call 8 強制編集により、Grader-First 原則と連動して部分点を確実に拾い上げる"
                ],
                "risks": "推敲が浅い段階での編集によりテスト合格率がわずかに下がる懸念",
                "condition": "現在 Kaggle 採点機上で進行中（4xL4 GPU）"
            },
            {
                "version": "V10 Diverse Sampling (Idris Method)",
                "ref": None,
                "status": "NEXT CANDIDATE A (上振れ狙い)",
                "status_color": "purple",
                "badge": "次期候補 A (上振れ突破)",
                "target_date": "Day 17 (2026-11-07 投入予定)",
                "expected_score": "0.22 〜 0.25 (ゴールド境界突破)",
                "objective": "Temperature 1.0 + Top-P 0.95 による多様な探索空間の獲得",
                "benefits": [
                    "Colab 実測最速 190秒（15.8分完走）の多様性サンプリングで難問を突破",
                    "単一決定論的エージェント特有の同じ誤答ループを脱出し、ゴールド圏内（14問解決）を狙う",
                    "Empty Patch 0.0% 実証済みの基盤上で多様性探索を展開"
                ],
                "risks": "高温サンプリングによる構文エラー・ハルシネーションの増加リスク",
                "condition": "V9.2 で未編集死撲滅が確認された後に投入"
            },
            {
                "version": "V9.1 Base-Restore",
                "ref": 58008114,
                "status": "COMPLETE (Score 0.15)",
                "status_color": "sky",
                "badge": "Day 15 実証完了",
                "target_date": "18時間11分完走 (スコア 0.15 確定)",
                "expected_score": "0.15 (9問解決)",
                "objective": "自己ベスト V9 原文の完全復元 ＋ 復唱禁止による時間短縮",
                "benefits": [
                    "18時間11分で安定完走（11回連続完走達成・エラー0）",
                    "復唱禁止により実行時間を短縮したが、長考によるEmpty Patchが20%残り0.15に留まる",
                    "この実機データにより、V9.2のCall 8強制編集の必要性を完全に裏付けた"
                ],
                "risks": "開いた後に1行も編集できないEmpty Patchの病巣が再確認された",
                "condition": "完了・知見抽出済"
            },
            {
                "version": "V13 Coupled-Sync Hunter",
                "ref": None,
                "status": "FUTURE CANDIDATE (Private対策)",
                "status_color": "indigo",
                "badge": "最終盤候補 (連動追随)",
                "target_date": "Day 18 (2026-11-08 投入予定)",
                "expected_score": "0.24+",
                "objective": "28.6% 存在する「複数ファイル連動修正タスク」の追随解決",
                "benefits": [
                    "主ファイルを編集した直後、定義変更されたシンボルを grep し連動ファイルを1回だけ確認",
                    "1ファイルのみ修正して ImportError や引数不整合で落ちていた難問を救済",
                    "Private テストセット（未知の同期 Python コードベース）での普遍的汎化力を担保"
                ],
                "risks": "探索ターン数とトークン消費の増加（14,336 崖への接近リスク）",
                "condition": "単一ファイル修正の安定後に導入"
            }
        ],
        "unsolved_challenges": [
            {
                "id": "CHALLENGE-01",
                "title": "58% Empty Patch の壁（未編集死の撲滅）",
                "category": "推論速度・行動規律",
                "severity": "CRITICAL",
                "severity_color": "rose",
                "metric": "失敗タスクの 58% (34/58問)",
                "fact": "エージェントは特別ツールなしでも 93% の確率で 3 手目までに正解ファイルを開けている。しかし、開いた後に 58% が 1 行もコードを編集できず時間切れで 0 点（0-byte diff）になっている。",
                "bottleneck": "4×L4 GPU 環境の推論速度が 17.25 tok/s (58ms/tok) と遅いため、思考（Thinking）や既存コードの復唱、read_file の追加呼出で 5,000 トークン上限を使い果たしてしまう。",
                "current_hypothesis": "V9.1 で「復唱禁止」を入れ実効トークンを削る。それでも残る場合は V9.2 で「Call 8 初回編集強制」を導入し、思考より先に edit_file を打たせる。"
            },
            {
                "id": "CHALLENGE-02",
                "title": "12時間壁と8分枠の綱引き（スループット vs 深さ）",
                "category": "物理タイムアウト制約",
                "severity": "CRITICAL",
                "severity_color": "rose",
                "metric": "全体 12h 上限 (1秒超過で No Score 0点)",
                "fact": "7分枠（V12.3）は 18時間48分で確実に安全完走するが、7〜8分で解ける後半の難問を逃し 0.17 に圧縮。8分枠は 0.20 を出せるが全体時間が 26〜28 時間に迫り、12 時間壁の崖っぷちになる。",
                "bottleneck": "Kaggle 採点サーバーの 12 時間グローバル制限。58 問を 1 問ずつ順次実行するため、1 問あたりの平均秒数が直接全体の完走可否を決定する。",
                "current_hypothesis": "タスク上限時間は 8 分を維持しつつ、ツール出力の切り詰め（head -20）と復唱禁止により「中央値 5〜6 分」で解かせて早期 return を促す。"
            },
            {
                "id": "CHALLENGE-03",
                "title": "28.6% の複数ファイル連動見落とし（Coupled Files Drift）",
                "category": "コンテキスト把握・局所化",
                "severity": "HIGH",
                "severity_color": "amber",
                "metric": "可解タスクの 28.6% (34/119問)",
                "fact": "全可解タスクの 28.6% は 2 ファイル以上の連動修正を必要とする（例: FastAPI の applications.py と routing.py）。エージェントは 1 ファイル目を直すと満足して終了し、連動側の不整合でテストが落ちる。",
                "bottleneck": "コンテキスト長制限（14k崖）を恐れるあまり単一ファイルに集中しすぎるバイアスと、モデルの複数ステップ計画能力の限界。",
                "current_hypothesis": "主ファイル編集後に連動シンボルの grep を 1 手だけ許容する規律（V13 Coupled-Sync Hunter）を設計中。"
            },
            {
                "id": "CHALLENGE-04",
                "title": "Private テストセットへの未知リポジトリ適応（ドメインシフト）",
                "category": "汎化性能・過学習回避",
                "severity": "HIGH",
                "severity_color": "amber",
                "metric": "Private 重複 0% / 100% 同期コード",
                "fact": "ホスト公式発表により、公開リポジトリ（FastAPI/Rich）は Private に 1 つも含まれず、Private は全問同期 Python コードであることが確定。公開セット専用ハックは Private で全滅する。",
                "bottleneck": "ローカル検証や公開スコアを上げるために「:!docs_src」などの特定リポジトリ構造に依存した除外ルールを入れると、未知リポジトリで正解ファイルを不可視化してしまう。",
                "current_hypothesis": "リポジトリ固有の仮定を全廃し、V9 の普遍的プロンプト規律（標準仕様抽出・3〜5行最小ブロック編集・Grader-First）を堅持する。"
            }
        ],
        "key_findings": [
            {
                "title": "ADK 14,336-Token Compaction Cliff",
                "title_en": "ADK 14,336-Token Compaction Cliff",
                "title_ja": "① Google ADK 14,336トークン圧縮崖（突然の記憶喪失）",
                "tag": "STABILITY",
                "tag_en": "STABILITY",
                "tag_ja": "記憶制約",
                "desc": "Google ADK summarizer drops all tool calls/results at 14,336 tokens, cutting resolution rate from 47.7% (0 compactions) to 7.1% (2+ compactions).",
                "desc_en": "Google ADK summarizer drops all tool calls/results at 14,336 tokens, cutting resolution rate from 47.7% (0 compactions) to 7.1% (2+ compactions).",
                "desc_ja": "Google ADKの履歴管理は累積14,336トークンを超えた瞬間に過去の全ツール結果・行番号・要件を要約消去します。実測で解決率が47.7%（0回）➔ 26.4%（1回）➔ 7.1%（2回以上）へ激減するため、14k未満の維持が必須です。",
                "detail_ja": "【背景・技術仕様】\nファイルを丸ごと読み込むと1回で数千トークンを消費し、即座に14kの崖に到達します。read_fileを40〜80行に絞り、コマンド出力も head -20 で切り詰める必要があります（ただしプロンプト自体を削りすぎるとV11のように基礎推論力が落ちる点に注意）。"
            },
            {
                "title": "17.25 tok/s Speed & 58% Empty Patch Trap",
                "title_en": "17.25 tok/s Speed & 58% Empty Patch Trap",
                "title_ja": "② 17.25 tok/s 物理定数と「未編集ゼロ点（58%）」の罠",
                "tag": "HARDWARE",
                "tag_en": "HARDWARE",
                "tag_ja": "推論速度・未編集罠",
                "desc": "Generation speed is fixed at 17.25 tok/s (~5,000 tokens/task). 93% of failed runs open the right file by Turn 3, yet 58% die with 0-byte empty patches.",
                "desc_en": "Generation speed is fixed at 17.25 tok/s (~5,000 tokens/task). 93% of failed runs open the right file by Turn 3, yet 58% die with 0-byte empty patches.",
                "desc_ja": "4×L4環境での生成速度は17.25 tok/s（58ms/tok、1問上限約5,000トークン）で固定。失敗タスクの93%は3手目までに正解ファイルを開いているにもかかわらず、58%がコード復唱や長考で時間切れとなり「1文字も編集せず（Empty Patch）」0点で死んでいます。",
                "detail_ja": "【背景・技術仕様】\nV12.3で探索ミス率を3.2%に下げてもスコアが0.17で不変だった理由がこれです。ボトルネックは「ファイルを探すこと」ではなく「開いた後に復唱せず即座に edit_file を実行させること（No Restatement & Call 9-12 初回編集強制）」にあります。"
            },
            {
                "title": "12-Hour Global Timeout Wall (7m vs 8m Cap)",
                "title_en": "12-Hour Global Timeout Wall (7m vs 8m Cap)",
                "title_ja": "③ 12時間グローバルタイムアウト壁（7分 vs 8分のジレンマ）",
                "tag": "TIMEOUT",
                "tag_en": "TIMEOUT",
                "tag_ja": "時間制約",
                "desc": "8m cap runs at ~28h edge (causing 0.24 / 0.17 / No Score variance). 7m cap (V12.3) finishes in 18h48m (-9h), trading late solves for 100% completion.",
                "desc_en": "8m cap runs at ~28h edge (causing 0.24 / 0.17 / No Score variance). 7m cap (V12.3) finishes in 18h48m (-9h), trading late solves for 100% completion.",
                "desc_ja": "全体制限（12hエンジン上限 / 実測約28h）を1秒でも超えると全問0点（No Score）で失格となります。8分設定は境界線上にあり、同一ZIPでも『0.24 / 0.17 / No Score』に分裂します。7分設定（V12.3）は実測18時間48分（-9時間短縮）で確実に完走します。",
                "detail_ja": "【背景・技術仕様】\n7分キャップは完走を100%保証する一方、7〜8分目にギリギリ解ける1〜2問を切り捨てるためスコアが0.17前後に圧縮されます。現在進行中のV9.1は「8分枠を維持しつつ、復唱禁止で実質実行時間を削る」ハイブリッド戦略を採っています。"
            },
            {
                "title": "Grader-First Rule (Two-Container Trap)",
                "title_en": "Grader-First Rule (Two-Container Trap)",
                "title_ja": "④ Grader-First 原則（二段階コンテナと偽陰性の罠）",
                "tag": "CRITICAL",
                "tag_en": "CRITICAL",
                "tag_ja": "採点仕様",
                "desc": "Agent sandbox lacks anyio/typing_inspection wheels, causing false-negative pytest failures. Reverting valid edits via git checkout causes self-destruction.",
                "desc_en": "Agent sandbox lacks anyio/typing_inspection wheels, causing false-negative pytest failures. Reverting valid edits via git checkout causes self-destruction.",
                "desc_ja": "エージェントの作業コンテナ（Container A）は -p no:anyio 強制や wheel 不足により、正しいコードでも pytest がエラー（偽陰性）を出します。これに騙されて git checkout で正解パッチを自ら消去する自己破壊を防ぐ規律が Grader-First です。",
                "detail_ja": "【背景・技術仕様】\n本番採点機（Container B）は提出された git diff だけをまっさらな完全環境に適用し、JUnit XML の4条件で採点します。手元のテストが環境起因で赤でも、仕様に合致したソース diff が残っていれば満点になります。"
            },
            {
                "title": "Private Domain Shift & Dead Tasks (Host Verified)",
                "title_en": "Private Domain Shift & Dead Tasks (Host Verified)",
                "title_ja": "⑤ 本番 Private の完全ドメインシフトとデッドタスク",
                "tag": "BREAKTHROUGH",
                "tag_en": "BREAKTHROUGH",
                "tag_ja": "本番環境仕様",
                "desc": "Host confirmed: (1) 0% of public repos (FastAPI/Rich) appear in Private test set, (2) 100% of Private tasks are solvable, (3) 0% touch async def.",
                "desc_en": "Host confirmed: (1) 0% of public repos (FastAPI/Rich) appear in Private test set, (2) 100% of Private tasks are solvable, (3) 0% touch async def.",
                "desc_ja": "ホスト公式発表（Topic 747248 / 745998）により、①公開リポジトリ（FastAPI, Rich等）は本番テストセットに1つも含まれない、②公開にあるデッドタスク（2問）と違い本番は全問100%解決可能、③本番に async def 修正は0件（100%同期コード）と確定。",
                "detail_ja": "【背景・技術仕様】\nしたがって、FastAPI特有のディレクトリ構造や非同期専用ハックへの過学習（Overfitting）は本番Privateで一斉転落（Shakeup）を招きます。未知の同期Pythonリポジトリで普遍的に機能するV9系の仕様抽出＋3〜5行ブロック編集が最善の武器となります。"
            }
        ]
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"Successfully generated {OUTPUT_FILE} ({OUTPUT_FILE.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
