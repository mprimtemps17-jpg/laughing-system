"""テンプレートによる場面生成（研究設計 v0.2 の3変種構造）。

1つの基本場面から、次の変種を作る（対象発言は①と③で同一）。
  known_conflict   ① Aが制約を知っており、対象発言が制約に反する      → 作成意図「あり」
  known_compatible ② Aが制約を知っており、対象発言が制約に適合する    → 作成意図「なし」
  unknown_conflict ③ Bだけが制約を知っており、①と同じ発言をする       → 作成意図「判定対象外」
  known_updated    （境界対照）制約が後から解消され、①と同じ発言をする → 作成意図「なし」

語彙や文型を足すときは、各ドメインのリストに追加する。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .spec import SceneSpec

INTENDED = {
    "known_conflict": "あり",
    "known_compatible": "なし",
    "unknown_conflict": "判定対象外",
    "known_updated": "なし",
}

ACKS = {"casual": ["分かった", "了解", "OK、分かった", "そっか、了解"],
        "polite": ["分かりました", "承知しました", "了解です"]}
YES = {"casual": ["うん、そう", "そうそう", "うん"], "polite": ["はい、そうです", "はい、そうなんです"]}

RELATIONSHIPS = {
    # 名前: (背景の文, Aの口調, Bの口調)。None は設定の tones から選ぶ
    "friends": ("AとBは友人。", "casual", "casual"),
    "seminar": ("AとBは同じゼミの学生。", None, None),
    "club": ("AとBは同じサークルの同期。", "casual", "casual"),
    "roommates": ("AとBはルームメイト。", "casual", "casual"),
    "part_time": ("AとBは同じアルバイト先の同僚。", None, None),
    "lab_junior_A": ("Aは研究室の後輩、Bは先輩。", "polite", "casual"),
    "lab_senior_A": ("Aは研究室の先輩、Bは後輩。", "casual", "polite"),
    "group_work": ("AとBは同じ授業のグループワークのメンバー。", None, None),
}


def tones(spec: SceneSpec) -> tuple[str, str]:
    _, ta, tb = RELATIONSHIPS[spec.relationship]
    return ta or spec.tone, tb or spec.tone


def pick(rng: random.Random, xs):
    return xs[rng.randrange(len(xs))]


def hm(x: float) -> str:
    """18.5 → 18時半"""
    h = int(x)
    return f"{h}時半" if x - h >= 0.5 else f"{h}時"


@dataclass
class Scene:
    """1つの基本場面の材料。各ドメインがこれを埋める。"""
    signature: str  # 場面の同一性（予備と評価で重複させないため）
    setting: str  # 場面の説明（背景の1文目）
    constraint_said: str  # Bが制約を伝える発言
    constraint_fact: str  # 背景で地の文として書く制約（「Bは〜」）
    constraint_quote: str  # グループチャット・第三者経由で使う短い言い方（「〜がある」）
    invite: str  # Aが話を切り出す発言（未知条件など）
    prompt: str  # Bが決定を促す発言
    conflict: str  # ①③の対象発言
    compatible: str  # ②の対象発言
    reason_conflict: str
    reason_compatible: str
    updated_said: str | None = None  # 制約が解消されたことを伝える発言（known_updated 用）
    chat_quote: str | None = None  # 前日のグループチャットでの書き込み（省略時は constraint_quote）


def _s(tone: str, casual: str, polite: str) -> str:
    return casual if tone == "casual" else polite


# ---------------------------------------------------------------- time（予定・時間）
@dataclass
class TimeActivity:
    noun: str  # 場面の識別にも使う（予備と評価で同じ活動を使わない）
    setting: str
    hours: float  # 活動にかかる時間
    invite: tuple[str, str]  # 誘い (casual, polite)。{day} に今日/明日が入る
    verb: tuple[str, str]  # 「じゃあ◯時から＿＿」に入る形
    can: tuple[str, str]  # 「◯時からなら＿＿」に入る形
    window: tuple[float, float] = (9.0, 21.0)  # 開始時刻として自然な範囲


TIME_ACTIVITIES = [
    TimeActivity("通話", "明日の課題について30分通話する時刻を決めている", 0.5,
                 ("明日の課題について、{day}30分通話しよう", "明日の課題について、{day}30分通話しませんか"),
                 ("通話しよう", "通話しましょう"), ("通話できる？", "通話できますか？"),
                 (9.0, 21.5)),
    TimeActivity("打合せ", "大学内で30分間の打合せをする時刻を決めている", 0.5,
                 ("{day}、大学で30分打合せしよう", "{day}、大学で30分打合せしませんか"),
                 ("打合せしよう", "打合せしましょう"), ("打合せできる？", "打合せできますか？"),
                 (9.0, 18.0)),
    TimeActivity("勉強会", "図書館で1時間の勉強会をする時刻を決めている", 1.0,
                 ("{day}、図書館で1時間勉強会しよう", "{day}、図書館で1時間勉強会しませんか"),
                 ("勉強会しよう", "勉強会しましょう"), ("勉強会できる？", "勉強会できますか？"),
                 (9.0, 20.0)),
    TimeActivity("読み合わせ", "発表資料の読み合わせをオンラインで1時間する時刻を決めている", 1.0,
                 ("{day}、発表資料の読み合わせを1時間やろう", "{day}、発表資料の読み合わせを1時間やりませんか"),
                 ("読み合わせしよう", "読み合わせしましょう"), ("読み合わせできる？", "読み合わせできますか？"),
                 (9.0, 21.0)),
    TimeActivity("買い出し", "備品の買い出しに1時間行く時刻を決めている", 1.0,
                 ("{day}、備品の買い出しに1時間行こう", "{day}、備品の買い出しに1時間行きませんか"),
                 ("買い出しに行こう", "買い出しに行きましょう"), ("買い出しに行ける？", "買い出しに行けますか？"),
                 (10.0, 19.0)),
    TimeActivity("発表練習", "ゼミ発表の練習を45分する時刻を決めている", 0.75,
                 ("{day}、発表練習を45分やろう", "{day}、発表練習を45分やりませんか"),
                 ("発表練習しよう", "発表練習しましょう"), ("発表練習できる？", "発表練習できますか？"),
                 (9.0, 20.0)),
    TimeActivity("映画", "一緒に映画を見に行く回を決めている", 2.0,
                 ("{day}、映画を見に行こう", "{day}、映画を見に行きませんか"),
                 ("映画に行こう", "映画に行きましょう"), ("映画に行ける？", "映画に行けますか？"),
                 (10.0, 20.0)),
    TimeActivity("ランチ", "一緒にランチに行く時刻を決めている", 1.0,
                 ("{day}、一緒にランチ行こう", "{day}、一緒にランチに行きませんか"),
                 ("ランチに行こう", "ランチに行きましょう"), ("ランチに行ける？", "ランチに行けますか？"),
                 (11.0, 13.5)),
    TimeActivity("引っ越しの手伝い", "Aの引っ越しの手伝いに来てもらう時刻を決めている", 2.0,
                 ("{day}、引っ越しの手伝いをお願いしたいんだけど", "{day}、引っ越しの手伝いをお願いできませんか"),
                 ("手伝いに来て", "手伝いに来てください"), ("手伝いに来られる？", "手伝いに来られますか？"),
                 (9.0, 16.0)),
    TimeActivity("面接練習", "就活の面接練習を1時間する時刻を決めている", 1.0,
                 ("{day}、面接練習を1時間やろう", "{day}、面接練習を1時間やりませんか"),
                 ("面接練習しよう", "面接練習しましょう"), ("面接練習できる？", "面接練習できますか？"),
                 (9.0, 20.0)),
    TimeActivity("ビラ配り", "新歓のビラ配りを1時間する時刻を決めている", 1.0,
                 ("{day}、新歓のビラ配りを1時間やろう", "{day}、新歓のビラ配りを1時間やりませんか"),
                 ("ビラ配りしよう", "ビラ配りしましょう"), ("ビラ配りできる？", "ビラ配りできますか？"),
                 (10.0, 17.0)),
    TimeActivity("カラオケ", "2時間カラオケに行く時刻を決めている", 2.0,
                 ("{day}、カラオケ行こう", "{day}、カラオケに行きませんか"),
                 ("カラオケに行こう", "カラオケに行きましょう"), ("カラオケに行ける？", "カラオケに行けますか？"),
                 (11.0, 20.0)),
]
# (用事, ありうる長さ(時間))
TIME_REASONS = [("バイト", [3, 4, 5]), ("授業", [1.5, 3]), ("ゼミ", [1.5, 2]), ("通院", [1, 1.5]),
                ("家族の用事", [2, 3]), ("サークルの練習", [2, 3]), ("塾講師のバイト", [2, 3]), ("就活の面接", [1, 1.5])]
LATEST_END = 22.0  # 活動が終わる最も遅い時刻


def _half_hours(lo: float, hi: float) -> list[float]:
    return [x / 2 for x in range(int(lo * 2), int(hi * 2) + 1)]


def _time_plan(act: TimeActivity, lengths: list[float], rng: random.Random):
    """制約 [s, e)、衝突する開始時刻 t、適合する開始時刻 t2 を、活動の自然な時間帯の中で決める。"""
    lo, hi = act.window
    cands = [(s, L) for s in (9, 10, 11, 12, 13, 14, 15, 16, 17, 18) for L in lengths if s + L <= 22]
    rng.shuffle(cands)
    for s, L in cands:
        e = s + L
        ts = [x for x in _half_hours(lo, hi) if s <= x <= e - 0.5]
        after = [x for x in _half_hours(lo, hi) if e + 0.5 <= x <= e + 1.5 and x + act.hours <= LATEST_END]
        before = [x for x in _half_hours(lo, hi) if s - 2.0 <= x and x + act.hours <= s - 0.5]
        if ts and (after or before):
            if after:
                return s, e, rng.choice(ts), rng.choice(after), "後"
            return s, e, rng.choice(ts), rng.choice(before), "前"
    raise ValueError(f"{act.noun} に合う時刻の組み合わせがない")


def time_scene(spec: SceneSpec, rng: random.Random) -> Scene:
    ta, tb = tones(spec)
    act = pick(rng, TIME_ACTIVITIES)
    reason, lengths = pick(rng, TIME_REASONS)
    day = "今日" if spec.route_known == "group_chat" else pick(rng, ["今日", "明日"])
    s, e, t, t2, where = _time_plan(act, lengths, rng)
    when = f"{reason}が終わった後の{hm(t2)}" if where == "後" else f"{reason}の前の{hm(t2)}"
    conflict = (_s(ta, f"{act.noun}は{day}{hm(t)}開始で決定にするね", f"{act.noun}は{day}{hm(t)}開始で決定にしますね")
                if spec.act == "decide" else
                _s(ta, f"じゃあ{day}{hm(t)}から{act.verb[0]}", f"では{day}{hm(t)}から{act.verb[1]}"))
    compatible = pick(rng, [
        _s(ta, f"{when}からなら{act.can[0]}", f"{when}からなら{act.can[1]}"),
        _s(ta, f"{when}からにしよう。大丈夫？", f"{when}からにしましょうか。大丈夫ですか？"),
    ])
    return Scene(
        signature=f"time:{act.noun}",
        setting=act.setting,
        constraint_said=_s(tb, f"{day}は{hm(s)}から{hm(e)}まで{reason}で、{act.noun}はできない",
                           f"{day}は{hm(s)}から{hm(e)}まで{reason}があるので、{act.noun}はできません"),
        constraint_fact=f"Bは{day}{hm(s)}から{hm(e)}まで{reason}で、{act.noun}はできない。",
        constraint_quote=f"{day}は{hm(s)}から{hm(e)}まで{reason}がある",
        chat_quote=f"明日は{hm(s)}から{hm(e)}まで{reason}がある",
        invite=_s(ta, *act.invite).format(day=day),
        prompt=_s(tb, f"{act.noun}の開始時刻を決めよう", f"{act.noun}の開始時刻を決めましょう"),
        conflict=conflict,
        compatible=compatible,
        reason_conflict=f"Bの{reason}（{hm(s)}〜{hm(e)}）と{hm(t)}開始が重なり、確認や調整がない。",
        reason_compatible=f"{reason}の時間を避けた{hm(t2)}を提示している。",
        updated_said=_s(tb, f"ごめん、{reason}がなくなったから、{day}は何時でも大丈夫になった",
                        f"すみません、{reason}がなくなったので、{day}は何時でも大丈夫になりました"),
    )


# ---------------------------------------------------------------- budget（予算）
BUDGET_ACTIVITIES = [
    # (場面, 費目, 上限候補, 高い選択肢, 安い選択肢, 誘い(casual, polite), 促し(casual, polite))
    ("2人で夕食を食べる店を相談している", "夕食", [1000, 1500, 2000], ["コースの店", "焼肉の食べ放題"], ["定食の店", "ラーメン屋"],
     ("今日の夕食、一緒に行こう", "今日の夕食、一緒に行きませんか"), ("店を決めよう", "店を決めましょう")),
    ("週末の1泊旅行の宿を決めている", "宿代", [5000, 6000, 8000], ["温泉旅館", "駅前のホテル"], ["ゲストハウス", "ビジネスホテル"],
     ("週末の旅行、そろそろ宿を押さえよう", "週末の旅行、そろそろ宿を押さえませんか"), ("どこに泊まるか決めよう", "どこに泊まるか決めましょう")),
    ("共通の友人への誕生日プレゼントを2人で選んでいる", "プレゼント代（1人あたり）", [1000, 1500, 2000],
     ["ブランドのマグカップ", "名入れのボールペン"], ["ハンドクリームのセット", "入浴剤の詰め合わせ"],
     ("Cの誕生日プレゼント、2人で用意しよう", "Cさんの誕生日プレゼント、2人で用意しませんか"), ("何にするか決めよう", "何にするか決めましょう")),
    ("ライブの後に入るカフェを決めている", "カフェ代", [800, 1000, 1200], ["ホテルのラウンジ", "アフタヌーンティーの店"], ["チェーンのカフェ", "駅ナカの喫茶店"],
     ("ライブの後、どこかでお茶しよう", "ライブの後、どこかでお茶しませんか"), ("どこに入るか決めよう", "どこに入るか決めましょう")),
    ("ゼミの打ち上げの会場を決めている", "打ち上げ代", [2000, 2500, 3000], ["個室の居酒屋のコース", "イタリアンのコース"], ["大学近くの食堂", "お好み焼き屋"],
     ("ゼミの打ち上げ、会場を探そう", "ゼミの打ち上げ、会場を探しませんか"), ("会場を決めよう", "会場を決めましょう")),
]


def budget_scene(spec: SceneSpec, rng: random.Random) -> Scene:
    ta, tb = tones(spec)
    setting, item, limits, hi, lo, invite, prompt = pick(rng, BUDGET_ACTIVITIES)
    L = pick(rng, limits)
    p = int(round(L * rng.choice([2, 2.5, 3]) / 100) * 100)
    q = int(round(L * rng.choice([0.6, 0.8]) / 100) * 100)
    o_hi, o_lo = pick(rng, hi), pick(rng, lo)
    per = "1人" if item != "プレゼント代（1人あたり）" else "1人あたり"
    conflict = (_s(ta, f"{per}{p}円の{o_hi}に決定ね。支払いは各自で", f"{per}{p}円の{o_hi}に決定しますね。支払いは各自でお願いします")
                if spec.act != "propose" else
                _s(ta, f"{per}{p}円の{o_hi}にしよう。支払いは各自で", f"{per}{p}円の{o_hi}にしましょう。支払いは各自でお願いします"))
    return Scene(
        signature=f"budget:{item}:{o_hi}",
        setting=setting,
        constraint_said=_s(tb, f"今回の{item}は{L}円までしか出せない", f"今回の{item}は{L}円までしか出せません"),
        constraint_fact=f"Bは今回の{item}に{L}円までしか出せない。",
        constraint_quote=f"{item}は{L}円までしか出せない",
        invite=_s(ta, *invite),
        prompt=_s(tb, *prompt),
        conflict=conflict,
        compatible=_s(ta, f"{per}{q}円の{o_lo}はどう？", f"{per}{q}円の{o_lo}はどうですか？"),
        reason_conflict=f"Bの上限{L}円を超える{p}円の自己負担を確認なく決めている。",
        reason_compatible=f"上限{L}円以内の{q}円の選択肢を提案している。",
        updated_said=_s(tb, f"さっきの話だけど、{item}は{p}円まで出せることになった",
                        f"先ほどの件ですが、{item}は{p}円まで出せることになりました"),
    )


# ---------------------------------------------------------------- dietary（食事の制約）
DIETARY = [
    # (食べられないもの, 言い方, 衝突する店, 適合する店)
    ("えび", "えびアレルギーで、えびは食べられない", ["えび料理の専門店", "えびフライが名物の洋食屋"], ["そば屋", "焼き鳥屋"]),
    ("そば", "そばアレルギーで、そばは食べられない", ["駅前のそば屋", "手打ちそばの店"], ["うどん屋", "カレー屋"]),
    ("生魚", "生魚が食べられない", ["回転寿司", "海鮮丼の店"], ["とんかつ屋", "オムライスの店"]),
    ("辛いもの", "辛いものが体質的に食べられない", ["激辛ラーメンの店", "四川料理の店"], ["和定食の店", "パスタの店"]),
    ("乳製品", "乳製品を食べると体調を崩すので食べられない", ["チーズフォンデュの店", "クリーム系パスタの専門店"], ["和定食の店", "焼き魚の定食屋"]),
]


def dietary_scene(spec: SceneSpec, rng: random.Random) -> Scene:
    ta, tb = tones(spec)
    food, said, bad, good = pick(rng, DIETARY)
    meal = pick(rng, ["お昼", "夕飯"])
    b, g = pick(rng, bad), pick(rng, good)
    conflict = (_s(ta, f"{meal}は{b}に決定ね", f"{meal}は{b}に決定しますね") if spec.act != "propose"
                else _s(ta, f"{meal}は{b}にしよう", f"{meal}は{b}にしましょう"))
    return Scene(
        signature=f"dietary:{food}:{meal}",
        setting=f"{meal}に2人で行く店を決めている",
        constraint_said=_s(tb, f"言ってなかったかもだけど、{said}", f"言っていなかったかもしれませんが、{said.replace('ない', 'ません')}"),
        constraint_fact=f"Bは{said}。",
        constraint_quote=said,
        invite=_s(ta, f"{meal}、一緒に食べに行こう", f"{meal}、一緒に食べに行きませんか"),
        prompt=_s(tb, "どの店にするか決めよう", "どの店にするか決めましょう"),
        conflict=conflict,
        compatible=_s(ta, f"{meal}、{g}はどう？", f"{meal}、{g}はどうですか？"),
        reason_conflict=f"Bが{food}を食べられないと知りながら、{b}を確認なく決めている。",
        reason_compatible=f"{food}を避けられる{g}を提案している。",
    )


# ---------------------------------------------------------------- access（手段・アクセス）
ACCESS = [
    # (場面, できないこと(casual, polite), 事実, 衝突する依頼, 適合する依頼, 署名)
    ("提出用ファイルを準備している", ("共有フォルダの権限がなくて、まだ開けない", "共有フォルダの権限がなくて、まだ開けません"), "Bには共有フォルダの閲覧権限がなく、ファイルを開けない",
     ("共有フォルダのファイルを開いて、今ここに貼って", "共有フォルダのファイルを開いて、ここに貼ってください"),
     ("ファイルを直接送るから、届いたら確認してくれる？", "ファイルを直接お送りするので、届いたら確認していただけますか？"), "folder"),
    ("明日のゼミの準備をしている", ("ノートパソコンが修理中で、今週は手元にない", "ノートパソコンが修理中で、今週は手元にありません"), "Bのノートパソコンは修理中で、今週は手元にない",
     ("じゃあ今夜、自分のパソコンでスライドを全部直しておいて", "では今夜、ご自身のパソコンでスライドを全部直しておいてください"),
     ("大学のパソコン室で一緒に直す時間を作れる？", "大学のパソコン室で一緒に直す時間を作れますか？"), "laptop"),
    ("研究室で使う機材を準備している", ("研究室の鍵を持っていないから、一人では入れない", "研究室の鍵を持っていないので、一人では入れません"), "Bは研究室の鍵を持っておらず、一人では入れない",
     ("じゃあ明日の朝、先に研究室に入って機材を出しておいて", "では明日の朝、先に研究室に入って機材を出しておいてください"),
     ("明日の朝は一緒に行って、鍵を開けるね", "明日の朝は一緒に行って、鍵を開けますね"), "key"),
    ("グループ課題の分担を決めている", ("その分析ソフトのライセンスを持っていない", "その分析ソフトのライセンスを持っていません"), "Bはその分析ソフトのライセンスを持っていない",
     ("分析ソフトでの集計はBの担当に決定ね", "分析ソフトでの集計はBさんの担当に決定しますね"),
     ("集計はこっちでやるから、図の作成をお願いできる？", "集計はこちらでやるので、図の作成をお願いできますか？"), "license"),
    ("サークルの合宿の準備をしている", ("車の免許を持っていないから、運転はできない", "車の免許を持っていないので、運転はできません"),
     "Bは車の免許を持っておらず、運転できない",
     ("じゃあ当日のレンタカーの運転はBに決定ね", "では当日のレンタカーの運転はBさんにお願いしますね"),
     ("運転はこっちでやるから、地図アプリで道案内をお願いできる？", "運転はこちらでやるので、道案内をお願いできますか？"), "license_car"),
    ("オンラインの打合せの準備をしている", ("家のWi-Fiが故障中で、今週はビデオ通話ができない", "家のWi-Fiが故障中で、今週はビデオ通話ができません"),
     "Bの家のWi-Fiは故障中で、今週はビデオ通話ができない",
     ("じゃあ今夜は家からビデオ通話で参加して", "では今夜は家からビデオ通話で参加してください"),
     ("今夜は大学の部屋を借りるから、そこから一緒に参加しよう", "今夜は大学の部屋を借りるので、そこから一緒に参加しましょう"), "wifi"),
    ("引っ越しの手伝いの段取りを決めている", ("腰を痛めていて、重い物は持てない", "腰を痛めていて、重い物は持てません"),
     "Bは腰を痛めていて、重い物を持てない",
     ("じゃあ冷蔵庫と洗濯機を運ぶのはBの担当で決定ね", "では冷蔵庫と洗濯機を運ぶのはBさんの担当でお願いしますね"),
     ("重い物は業者に頼むから、小物の箱詰めをお願いできる？", "重い物は業者に頼むので、小物の箱詰めをお願いできますか？"), "back"),
]


def access_scene(spec: SceneSpec, rng: random.Random) -> Scene:
    ta, tb = tones(spec)
    setting, said, fact, bad, good, sig = pick(rng, ACCESS)
    return Scene(
        signature=f"access:{sig}",
        setting=setting,
        constraint_said=_s(tb, *said),
        constraint_fact=f"{fact}。",
        constraint_quote=said[0],
        invite=_s(ta, "作業を進めよう", "作業を進めませんか"),
        prompt=_s(tb, "どう進めるか決めよう", "どう進めるか決めましょう"),
        conflict=_s(ta, *bad),
        compatible=_s(ta, *good),
        reason_conflict="Bにはできないと知っている作業を、代わりの手段なしに求めている。",
        reason_compatible="Bの制約を踏まえた代わりの手段を示している。",
    )


# ---------------------------------------------------------------- prior_knowledge（前提知識）
PRIOR = [
    ("昨日の打合せ", "実験の手順", "昨日決めたあの手順で、今日から実験を進めておいて", "昨日決めた手順で、今日から実験を進めておいてください",
     "昨日決まったのは、測定を先に全部やってから分析する手順。その手順で進めておいて",
     "昨日決まったのは、測定を先に全部やってから分析する手順です。その手順で進めておいてください"),
    ("先週のミーティング", "発表の分担", "先週決めた分担どおりに、スライドを作っておいて", "先週決めた分担どおりに、スライドを作っておいてください",
     "先週決まった分担は、Bが結果のパート担当。そこのスライドを作っておいて",
     "先週決まった分担は、Bさんが結果のパート担当です。そこのスライドを作っておいてください"),
    ("今朝のバイトの朝礼", "新しいレジ締めのやり方", "今朝言われた新しいやり方で、今日のレジ締めをお願い", "今朝言われた新しいやり方で、今日のレジ締めをお願いします",
     "今朝言われたのは、現金を数える前に先に売上票を出すやり方。それで今日のレジ締めをお願い",
     "今朝言われたのは、現金を数える前に先に売上票を出すやり方です。それで今日のレジ締めをお願いします"),
    ("先週のサークルの会議", "合宿の集合場所", "会議で決まった場所に、当日は8時集合でよろしく", "会議で決まった場所に、当日は8時集合でお願いします",
     "会議で決まった集合場所は、大学の正門前。当日は8時集合でよろしく",
     "会議で決まった集合場所は、大学の正門前です。当日は8時集合でお願いします"),
    ("昨日のグループ通話", "レポートの修正方針", "昨日話した方針で、第2章を書き直しておいて", "昨日話した方針で、第2章を書き直しておいてください",
     "昨日決まった方針は、先行研究の比較を表にまとめること。その方針で第2章を書き直しておいて",
     "昨日決まった方針は、先行研究の比較を表にまとめることです。その方針で第2章を書き直しておいてください"),
    ("今朝の店長との面談", "シフトの変更点", "今朝決まった新しいシフトのとおりに、来週は入って", "今朝決まった新しいシフトのとおりに、来週は入ってください",
     "今朝決まったのは、来週から土曜を早番にすること。そのシフトで来週は入って",
     "今朝決まったのは、来週から土曜を早番にすることです。そのシフトで来週は入ってください"),
]


def prior_scene(spec: SceneSpec, rng: random.Random) -> Scene:
    ta, tb = tones(spec)
    event, topic, bad_c, bad_p, good_c, good_p = pick(rng, PRIOR)
    return Scene(
        signature=f"prior:{event}",
        setting=f"Aが{event}で決まった{topic}をBに伝えている",
        constraint_said=_s(tb, f"{event}には出ていないし、内容もまだ聞いていない", f"{event}には出ていませんし、内容もまだ聞いていません"),
        constraint_fact=f"Bは{event}に出ておらず、内容をまだ聞いていない。",
        constraint_quote=f"{event}に出ていない",
        invite=_s(ta, f"{topic}の件だけど", f"{topic}の件ですが"),
        prompt=_s(tb, "今日は何をすればいい？", "今日は何をすればいいですか？"),
        conflict=_s(ta, bad_c, bad_p),
        compatible=_s(ta, good_c, good_p),
        reason_conflict=f"Bが{event}の内容を知らないと分かっていて、説明なしに前提にしている。",
        reason_compatible="決まった内容を説明したうえで依頼している。",
    )


DOMAINS = {
    "time": time_scene,
    "budget": budget_scene,
    "dietary": dietary_scene,
    "access": access_scene,
    "prior_knowledge": prior_scene,
}


# ---------------------------------------------------------------- 変種の組み立て
def build_variants(spec: SceneSpec, sc: Scene, rng: random.Random) -> list[dict]:
    ta, tb = tones(spec)
    rel = RELATIONSHIPS[spec.relationship][0]
    base_bg = f"{rel}{sc.setting}。"
    ack = pick(rng, ACKS[ta])

    # 既知（Aが知っている）条件の背景と会話
    if spec.route_known == "direct":
        known_bg = base_bg
        known_turns = [("B", sc.constraint_said), ("A", ack), ("B", sc.prompt)]
    elif spec.route_known == "group_chat":
        known_bg = (base_bg + f"\n前日、BはAも入っているグループチャットに「{sc.chat_quote or sc.constraint_quote}」と書き込み、"
                    "Aはそれに「了解」と返信している。")
        known_turns = [("A", sc.invite), ("B", sc.prompt)]
    elif spec.route_known == "third_party":
        heard = _s(ta, f"Cから聞いたけど、{sc.constraint_quote}んだよね？",
                   f"Cさんから聞いたのですが、{sc.constraint_quote}んですよね？")
        known_bg = base_bg
        known_turns = [("A", heard), ("B", f"{pick(rng, YES[tb])}。{sc.prompt}")]
    else:
        raise ValueError(f"unknown route_known: {spec.route_known}")

    # 未知（Bだけが知っている）条件
    if spec.route_unknown == "private_only":
        unk_bg = (base_bg + f"\n{sc.constraint_fact}この事情はBだけが知っている。"
                  "Aには伝えておらず、Aが別の経路で知ったこともない。")
    elif spec.route_unknown == "absent":
        # Cは2人の予定に関係のない人物にする（「なぜCがAに伝えないのか」という不自然さを避ける）
        unk_bg = (base_bg + f"\nAが席を外している間に、Bはたまたま通りかかった知人Cと立ち話をし、「{sc.constraint_quote}」と話した。"
                  "Cはすぐに立ち去った。Aはその場におらず、戻ってきた後もこの話は出ていない。")
    elif spec.route_unknown == "memo":
        unk_bg = (base_bg + f"\nBは自分の手帳にだけ「{sc.constraint_quote}」と書いている。"
                  "AはBの手帳を見ておらず、Bから聞いたこともない。")
    else:
        raise ValueError(f"unknown route_unknown: {spec.route_unknown}")
    unk_turns = [("A", sc.invite), ("B", sc.prompt)]

    out = []
    for v in spec.variants:
        if v == "known_conflict":
            bg, turns, target, why, route = known_bg, known_turns, sc.conflict, sc.reason_conflict, spec.route_known
        elif v == "known_compatible":
            bg, turns, target, why, route = known_bg, known_turns, sc.compatible, sc.reason_compatible, spec.route_known
        elif v == "unknown_conflict":
            bg, turns, target, route = unk_bg, unk_turns, sc.conflict, spec.route_unknown
            why = "対象発言は制約に反するが、Aは制約を知らないと本文に明示されている。"
        elif v == "known_updated":
            if sc.updated_said is None:
                continue  # このドメインには「制約の解消」の文型がまだない
            bg, route = known_bg, spec.route_known
            turns = known_turns[:-1] + [("B", sc.updated_said), ("A", pick(rng, ACKS[ta])), known_turns[-1]]
            target, why = sc.conflict, "制約は後から解消されており、最新の条件には反しない。"
        else:
            raise ValueError(f"unknown variant: {v}")
        out.append({
            "variant": v, "route": route, "background": bg,
            "turns": [{"speaker": s, "text": t} for s, t in turns],
            "target": target, "intended_label": INTENDED[v], "intended_reason": why,
        })
    return out


def generate_scene(spec: SceneSpec, rng: random.Random) -> tuple[str, list[dict]]:
    sc = DOMAINS[spec.domain](spec, rng)
    return sc.signature, build_variants(spec, sc, rng)
