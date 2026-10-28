"""手动输入扫描数据跑一遍（读屏做好之前先这样用）

python -m sc_mining.demo
"""
from . import data
from .signals import describe
from .laser import recommend
from .refinery import best_stations, methods, unpriced, sell_plan
from .uex import apply_live


def ask(prompt, cast=float):
    while True:
        try:
            return cast(input(prompt).strip())
        except ValueError:
            print("  输入有误，再来一次")


def main():
    if apply_live(data):
        print("（已使用 UEX 在线矿价）")
    print(f"MOLE 挖矿助手 · 数据版本 {data.GAME_VERSION}\n")

    sig = ask("雷达信号值（直接回车跳过）：", lambda s: int(s) if s else None)
    if sig:
        print("  " + describe(sig))

    mass = ask("质量 kg：")
    res = ask("抗性 %：")
    inst = ask("不稳定性：")
    plans = recommend(mass, res, inst)
    print(f"\n推荐方案（当前模型：{plans[0].model}，K={plans[0].k:.3f}）：")
    for i, p in enumerate(plans, 1):
        print(f"  {i}. {p.summary()}")

    if input("\n破完了要记录结果用于校准吗？(y/N) ").strip().lower() == "y":
        from .laser import record
        heads = input("  用了哪些矿头（helix_ii,hofstede_s2,arbor_mh2 逗号分隔）：").strip()
        gadget = input("  贴了什么工具（sabir/optimax/boremax/okunis/waveshift/stalwart，没有直接回车）：").strip()
        thr = ask("  功率开到多少 %：") / 100
        broke = input("  破开了吗？(y/n) ").strip().lower() == "y"
        forecast = input("  游戏里的难度评级（简单/中等/困难/极难/地狱，可不填）：").strip()
        record(mass, res, heads, gadget or None, thr, broke, forecast)
        print("  已记录")

    print("\n矿袋内容（格式 矿物=SCU，逗号分隔，回车跳过）：")
    raw = input("> ").strip()
    if raw:
        bag = {k.strip(): float(v) for k, v in (p.split("=") for p in raw.split(","))}
        for name, sys_, value, detail in best_stations(bag):
            d = "，".join(f"{m} {b:+d}%" for m, b in detail.items())
            print(f"  {name}（{sys_}）≈ {value:,.0f} aUEC｜{d}")
        if unpriced(bag):
            print("  缺价格：" + "、".join(unpriced(bag)))
        print("精炼方式：" + " / ".join(m for m, _ in methods()))
        print("卖到：" + "，".join(f"{m} → {c}（{p:,}）" for m, c, p in sell_plan(bag) if c))


if __name__ == "__main__":
    main()
