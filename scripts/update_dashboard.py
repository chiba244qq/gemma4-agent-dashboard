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

    # 5. Assemble payload
    payload = {
        "last_updated_utc": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "last_updated_jst": now_jst.strftime("%Y-%m-%d %H:%M:%S JST"),
        "active_job": active_submission,
        "my_team": my_team_info,
        "best_score": best_score,
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
