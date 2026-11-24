# 歴代ベストスコア・各提出バージョン比較検証レポート（2026-11-24）

本ドキュメントは、Kaggle「The Gemma 4 Developer Agent Competition」における歴代ベストスコア（`0.20`）および `V9`〜`V37` の各方式について、本番提出結果と Colab L4 / A100（True-Grader v9.4・12タスク）での比較実験結果を客観的にまとめたものです。

---

## 1. 本番 Kaggle 提出と主要バージョンの実績一覧

| バージョン | Ref | 方式 | サンプリング / 予算 | Colab (L4 12問) | 本番 LB | 備考 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **V9 Ultimate** | `57774882`<br>*(再提出 `58387461`)* | 単一 `LlmAgent` | `T=0.2` / `Think 2048`<br>`28 calls` / `8m` / `240s` | `25.0%` (3/12)<br>Patch `50.0%` / `38.14s` | **`0.20` ★**<br>*(再提出 `0.12`)* | 歴代ベスト。ただし後の同一環境比較では Turn 1 長考(335s+)が多発。 |
| **V10 Diverse** | `57837665` | 単一 `LlmAgent` | `T=1.0, K=64` / `Think 4096`<br>`28 calls` / `8m` | — | `0.18` | V9 プロンプト＋多様性サンプリング。 |
| **V18 Native Clean** | `58226200`<br>*(再提出 `58268405`)* | 単一 `LlmAgent` | `T=0.2` / `Think 2048`<br>`28 calls` / `8m` / `240s` | `66.7%` *(旧6問)* | `0.18`<br>*(再提出 `0.13`)* | ツール構文記述汚染を除去した純粋ネイティブパーサー版。 |
| **V23 Hybrid-Fast** | `58451077` | 単一 `LlmAgent` | `T=0.2` / `Think 2048`<br>`32 calls` / `8m` | `66.7%` Patch *(旧)* | `0.15` | L4 OOM 修正＋3-Tier `raw_exact` 編集導入版。 |
| **V31 SafeCap-Compile** | `58501048` | 単一 `LlmAgent` | `T=0.2` / `Think 2048`<br>`36 calls` / `7m` / `60s` | `25.0%` (3/12)<br>Patch `41.7%` / `19.91s` | `0.17` | 安全上限(`60s/7m/36calls`)＋`py_compile`検証。 |
| **V32 Sequential-TwoStage** | `58551780` | `SequentialAgent`<br>(2段階) | `T=0.2` / `Think 2048`<br>`36 calls` / `7m` / `60s` | `25.0〜41.7%` *(旧Sim)*<br>A100: `41.7%` | `0.17` | 調査と編集を分離。ただし本番 Stage 2 に `{problem_description}` 欠落。 |
| **V33 Sequential-Fixed** | `58637410` | `SequentialAgent`<br>(2段階) | `T=0.2` / `Think 2048`<br>`36 calls` / **`8m`** / `60s` | `33.3%` (4/12)<br>**Patch `83.3%`** / `30.54s` | **Error**<br>*(12h超過)* | Stage 2 へ `{problem_description}+{hints?}` 追加。`8m`延長で本番12h制限超過。 |
| **V35 Single-Compacted-V2** | `58716319` | 単一 `LlmAgent`<br>(圧縮相性) | `T=0.2` / `Think 2048`<br>`36 calls` / `7m` / `60s` | **`33.3% 〜 41.7%`** (4〜5/12)<br>Patch `58.3〜66.7%` / `21.5〜23.7s` | `0.15` | `/tmp` `write_file`禁止・パイプ終了コード隠蔽防止・`git grep`明示。 |

---

## 2. 歴代ベスト `V9_Ultimate` vs `V35_Single_Compacted_V2` 直接ペア比較（L4 12問）

10/30 に `0.20` を記録した `V9_Ultimate` と、現行の `V35_Single_Compacted_V2` を **同じ L4 環境・同じ `turn_max_tokens=2048`・同じ 12 タスク（`rich`）** で直接比較した結果（2026-11-23 実施）：

| 指標 | V9_Ultimate_Think2048 (`0.20` 構成) | V35_Single_Compacted_V2_Think2048 | 差分 |
| :--- | :--- | :--- | :--- |
| **True Pass Rate** | `25.0%`（3 / 12） | **`41.7%`（5 / 12）** | **`+16.7pt` (+2問)** |
| **Patch Rate** | `50.0%`（6 / 12） | **`66.7%`（8 / 12）** | **`+16.7pt`** |
| **Missing `old_string`** | `7` | **`1`** | **`-6回`** |
| **Avg Step Latency** | `38.14s` | **`21.52s`** | **約 44% 高速化** |
| **PASS タスク** | `4077, 3882, 3278` | **`4077, 3882, 3518, 3278, 3894`** | `3518`, `3894` を追加獲得 |

### 所見
* **同一条件では `V35` が `V9` を全指標で上回った**: `V9` は Turn 1 で 335〜339 秒（約 5.5 分）のツールなし長考を 5 問で発生させ、`tests/` 配下への一時ファイル作成ミス等により `NO_PATCH` が 6 問にのぼりました。
* **10/30 の `0.20` の解釈**: 同じ `V9` を 11/15 に再提出した際は `0.12` に下がっており、今回の直接比較結果と合わせても、`10/30` の `0.20` は当時の評価環境差または確率的分散の上振れであった可能性が高いと考えられます。

---

## 3. Colab L4 での主要 A/B 検証結果まとめ（V33〜V37）

### A. 2段階分離（`V33`） vs 単一＋履歴圧縮（`V34` / `V35`）
* **`V33_Sequential_Fixed`**（`420s` 忠実条件）: Pass `33.3%` (4/12), **Patch Rate `83.3%`** (`10/12`), `30.54s/step`
  * Stage 1 が特定した箇所を Stage 2 が迷わず編集できるため Patch Rate が極めて高い一方、2 ステージ合計の時間が重く、`rich_3278` (`416.3s`) が 7 分枠で時間切れになり、本番で `8m` に延長した際は 12 時間全体タイムアウトになりました。
* **`V34_Single_Compacted`**: Pass `33.3%` (4/12), Patch Rate `66.7%`, `22.31s/step`
  * 引き継ぎ遅延がなく `rich_3278` を `246.4s` で突破した一方、序盤探索の空振りで `rich_3518` が `NO_PATCH`。
* **`V35_Single_Compacted_V2`**: Pass `33.3% 〜 41.7%`, Patch Rate `58.3% 〜 66.7%`, `21.52s 〜 23.70s/step`
  * `[760595]` の罠対策（`/tmp` `write_file` 禁止・パイプ終了コード隠蔽防止・`git grep -- '*.py'` 徹底）により `rich_3518` を奪還し、単一エージェントで唯一 `5/12 (41.7%)` に到達しました。

### B. `V36_Compacted_Pinned`（末尾 Issue ピン留め ＋ `thinking_budget` 2048 vs 4096）
* `V36_Pinned_Think2048`: Pass `25.0%` (3/12), Patch `58.3%`, `27.16s/step`
* `V36_Pinned_Think4096`: Pass `16.7%` (2/12), Patch `33.3%`, **`61.60s/step`**
  * **`thinking_budget: 4096` は L4 上で深刻な長考遅延（`663s〜966s`）を招き逆効果**であることが確認されました。また、単一エージェントでの `system.md` 末尾への `{problem_description}` 重複ピン留めもコンテキスト増により逆効果でした。

### C. `V37_IdrisV31` 規律（`max_output_tokens: 4096` / 1回チェック・1回修正で即提出）
* `V37_T02` (`T=0.2`): Pass `25.0%` (3/12), Patch `66.7%`, `22.25s/step`, Missing `old_string: 3`
* `V37_T10_TopK64` (`T=1.0, K=64`): Pass `25.0%` (3/12), Patch `50.0%`, `31.81s/step`, Missing `old_string: 9`
  * L4 環境では `T=1.0, top_k=64` による不安定化（`old_string` ミス増加）が目立ち、早期提出規律も未修復パッチの提出を招きました。

---

## 4. Kaggle Notebook API による公式ハーネス比較試行の記録

* **試行内容**: 2026-11-24 に Kaggle API (`kaggle kernels push --accelerator NvidiaTeslaL4x4`) を用いて、公式 Python 3.12 BYOD イメージ上で `v9_ultimate` と `v35_8m` の 20 タスク（`fastapi` 10 + `rich` 10）ペア比較ノートブック（`tsuyoshichiba/v9-vs-v35-paired-eval`）を実行しました。
* **結果（制約の確認）**: `KernelWorkerStatus.ERROR`。通常 Notebook ワーカー側では `L4×4` ではなく **`Tesla T4`（Compute Capability 7.5）** が割り当てられ、`vLLM` が `ValueError: Bfloat16 is only supported on GPUs with compute capability of at least 8.0` で起動不可となりました。
* **結論**: Kaggle API 経由の通常 Notebook セッションでは 31B-QAT の公式ハーネス検証は実行できず、事前検証は Colab（L4 / A100-80GB）で行う必要があります。

---

## 5. 現時点のまとめと次の一手

1. **最も期待値が高い型は `V35_Single_Compacted_V2`**（同一条件で `V9` に `41.7% vs 25.0%` で勝利、平均 `21.5s/step`）。
2. **`thinking_budget: 2048` を維持**し、`4096` や `T=1.0` への過度な拡張は避けるのが L4 環境では安定します。
3. **次の現実的な提出候補**:
   * **案 1**: `V35_Single_Compacted_V2` を `max_time_minutes: 8`・`timeout_seconds: 120` に微調整して再挑戦（単一エージェントのため `V9`/`V18` 同様に 12 時間枠内での完走可能性が高い）。
   * **案 2**: `V33_Sequential_Fixed`（`Patch Rate 83.3%`）を `max_time_minutes: 7` に戻して完走させる。
