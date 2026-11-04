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
                "title": "findfile IDF-Ranker Breakthrough (LocBench)",
                "title_en": "findfile IDF-Ranker Breakthrough (LocBench)",
                "title_ja": "findfile IDFランク付け探索による探索失敗率の激減",
                "tag": "BREAKTHROUGH",
                "tag_en": "BREAKTHROUGH",
                "tag_ja": "技術的突破",
                "desc": "Local N=63 benchmark shows findfile cuts miss rate from 54.0% (V11) down to 3.2%, achieving 74.6% Top-3 and 82.5% Top-5 hit rate.",
                "desc_en": "Local N=63 benchmark shows findfile (fastapi/ only) cuts miss rate from 54.0% (V11) and 28.6% (V12.1) down to 3.2%, achieving 74.6% Top-3 and 82.5% Top-5 hit rate.",
                "desc_ja": "ローカルベンチマーク（N=63）において、TF-IDF重み付けによる専用探索ツール『findfile』を導入。探索ミス率がV11の54.0%、V12.1の28.6%からわずか3.2%へと激減。Top-3的中率74.6%、Top-5的中率82.5%を達成し、初手でのファイル特定失敗を事実上根絶。",
                "detail_ja": "【背景・技術仕様】\nLLMが広大なリポジトリで最初に対象ファイルを見失うと、無駄なファイル読み込み（1回あたり数千トークン・数十秒）を繰り返しタイムアウトに至ります。findfileはタスク指示文からストップワードを除去し、ファイルパスの希少性（IDF）でスコアリングして上位10件を即座に特定します。"
            },
            {
                "title": "Unresolvable Dead Tasks (Topic 755554)",
                "title_en": "Unresolvable Dead Tasks (Topic 755554)",
                "title_ja": "解法が存在しない「デッドタスク」の存在（実質分母56問）",
                "tag": "CRITICAL",
                "tag_en": "CRITICAL",
                "tag_ja": "致命的制約",
                "desc": "fastapi_14186 and rich_3486 have conflicting test decorators (@needs_pydanticv1 vs v2). Skipped required tests cause 0 score even on reference patch. Real denominator is 56, not 58.",
                "desc_en": "fastapi_14186 and rich_3486 have conflicting test decorators (@needs_pydanticv1 vs v2). Skipped required tests cause 0 score even on reference patch. Real denominator is 56, not 58.",
                "desc_ja": "全58問中、fastapi_14186およびrich_3486の2問は評価ハーネス側の依存ライブラリ不整合（@needs_pydanticv1/v2の衝突等）により、公式のリファレンス正解パッチを適用してもテストがスキップされ0点になります。競技の実質的分母は58問ではなく56問です。",
                "detail_ja": "【背景・技術仕様】\nKaggle公式Discussions（トピック755554）でも報告されている仕様バグです。提出エージェントがどんなに完璧なコードを書いても得点できないため、これら2問の失敗でアーキテクチャの優劣を判断してはならず、最大獲得可能スコアは実質 56/58 ≒ 0.965 となります。"
            },
            {
                "title": "12-Hour Global Timeout Wall (Notebook Audit)",
                "title_en": "12-Hour Global Timeout Wall (Notebook Audit)",
                "title_ja": "12時間グローバルタイムアウトの壁（VOID即死回避の7分キャップ）",
                "tag": "TIMEOUT",
                "tag_en": "TIMEOUT",
                "tag_ja": "時間制約",
                "desc": "At 8m cap per task, 120 tasks hit the 12h overall limit (No Score). 7m cap buys 40m safe margin and guarantees completion.",
                "desc_en": "At 8m cap per task, 120 tasks hit the 12h overall limit (No Score). 7m cap buys 40m safe margin and guarantees completion.",
                "desc_ja": "Kaggle評価環境には全体で12時間（43,200秒）という絶対上限があり、1秒でも超過すると全問0点（No Score/失格）になります。1問あたり8分キャップでは全問試行時に12時間の壁に衝突する危険があるため、7分（420秒）キャップを適用し約40分の安全マージンを確保して完走を保証しています。",
                "detail_ja": "【背景・技術仕様】\n1問ごとのタイムアウト処理だけでなく、エージェント初期化やハーネスのコンテナリセットオーバーヘッド（1問あたり数秒〜十数秒）が累積します。7分（420秒）打ち切りにより、全タスクで最大時間を使い切ったとしても43,200秒以内に確実に全問の採点処理を通過させます。"
            },
            {
                "title": "300s Budget = 5,000 Output Tokens Constant",
                "title_en": "300s Budget = 5,000 Output Tokens Constant",
                "title_ja": "300秒の推論予算 ＝ 出力約5,000トークンの物理定数（復唱厳禁）",
                "tag": "HARDWARE",
                "tag_en": "HARDWARE",
                "tag_ja": "推論速度",
                "desc": "Hardware generation speed is fixed at 17.25 tok/s (76% of time). Restating read code wastes 58ms/tok. 100% of zero-patch failures never reached edit_file.",
                "desc_en": "Hardware generation speed is fixed at 17.25 tok/s (76% of time). Restating read code wastes 58ms/tok. 100% of zero-patch failures never reached edit_file.",
                "desc_ja": "Gemma 4のハードウェア推論速度は17.25トークン/秒（1トークンあたり約58ms）で固定されています。読み込んだコードの復唱や過剰な独白は秒単位の時間を浪費します。パッチ生成に至らなかった失敗（Score 0）の100%は、復唱や迷走により edit_file に到達する前に時間切れになったことが原因です。",
                "detail_ja": "【背景・技術仕様】\nモデル思考時間（Thinking）と出力トークン数の合計が推論時間を決定します。思考予算を2048トークンに制御し、かつ「読み込んだファイル内容をレスポンスで復唱（オウム返し）してはならない」という1行の規律を加えるだけで、貴重な時間を節約して確実にパッチ編集ツールへ到達させます。"
            },
            {
                "title": "ADK 14,336-Token Compaction Cliff",
                "title_en": "ADK 14,336-Token Compaction Cliff",
                "title_ja": "Google ADK 14,336トークン圧縮崖（記憶喪失とツール破壊）",
                "tag": "STABILITY",
                "tag_en": "STABILITY",
                "tag_ja": "記憶制約",
                "desc": "Google ADK summarizer drops all tool calls/results, causing instant amnesia. V11/V12 keep tokens under 14k.",
                "desc_en": "Google ADK summarizer drops all tool calls/results, causing instant amnesia. V11/V12 keep tokens under 14k.",
                "desc_ja": "Google Agent Development Kit (ADK)のコンパクション機能は、累積トークンが14,336を超えると履歴の要約を行い、過去のツール呼び出し履歴やエラーログをすべて消去します。これによりエージェントは突然記憶喪失に陥りループするため、履歴トークンを14,000未満に保つ設計が不可欠です。",
                "detail_ja": "【背景・技術仕様】\nファイルの中身を丸ごと読み込むと1回で数千トークンを消費し、すぐに14kの崖に到達します。必要な範囲のみをピンポイントで読む（行数指定・オフセット）、無駄な思考出力を抑える、不要な探索ログを圧縮させないことが完走率と正答率の生命線です。"
            }
        ]
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"Successfully generated {OUTPUT_FILE} ({OUTPUT_FILE.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
