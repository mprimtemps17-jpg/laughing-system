# 生成レポート: time_eval_template

- 方法: template / 形式: care / seed: 1 / 設定: configs/gen/time_eval_template.yaml
- 計画した場面: 8 / 採用: 24 件 / 不採用の場面: 0 / 回答待ち: 0
- 出力: `data/generated/time_eval_template.jsonl`（生成記録: `time_eval_template.log.jsonl`）

> 作成意図のラベルは正解ではありません。実験に使う前に、人間が独立に判定してください。

- split: eval 24
- domain: time 24
- variant: known_compatible 8, known_conflict 8, unknown_conflict 8
- route: absent 3, direct 6, group_chat 4, memo 2, private_only 3, third_party 6
- intended_label: あり 8, なし 8, 判定対象外 8
- relationship: club 3, friends 3, group_work 3, lab_junior_A 3, lab_senior_A 3, part_time 3, roommates 3, seminar 3
