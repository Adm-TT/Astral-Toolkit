# 数据来源对照（4.10.2）

原则：以 SCMiner.rocks 为准（用户指定）；SCMiner 没有的数据再多方对照，择最准。优先级：游戏文件解包数据（带构建号）> 多个独立来源一致 > 单一社区来源；
数值冲突时记录在这里，并写明取舍理由。

| 数据 | 对照来源 | 结论 |
|---|---|---|
| S2 矿头功率/修正 | starcitizen.tools（解包，4.10.2-LIVE.12881860）、SCMiner、汉化包注释 | 三方一致，取 Wiki。Hofstede-S2 绿区 +60%：Wiki 与 SCMiner 一致，汉化包漏写 |
| 被动模组 | Wiki、SCMiner、汉化包注释 | 功率/绿区三方一致。Torrent III 充能速率：Wiki +45%（4.10.2），汉化包 +40%（旧版），SCMiner 未列 → 取 +45% |
| 手持工具 | Wiki、SCMiner、汉化包注释 | OptiMax 抗性：Wiki 一处 −25%、一处 −30%，SCMiner 与汉化包 −30% → 取 −30%。其余一致 |
| 修正叠加方式 | SCMiner 配装器示例、grimhex | 连乘，已用 SCMiner 示例验算一致 |
| 多矿头合力 | grimhex、AO Gaming | 实际输出相加（两家均说明是建模选择，非官方） |
| 破碎公式 | 用户定：功率 × 模组 × (1 − 抗性) × 5；Mort13 实测公式相同；SCMiner 计算器 0.36、配装器约 0.28 | 采用用户公式，其他仅作参考 |
| 矿物信号 | SCMiner 矿物目录（用户指定为准）、grimhex、api.star-citizen.wiki | 取 SCMiner。Agricium：SCMiner 3885，grimhex 3895 → 3885；Borase 稀有度按 SCMiner 为史诗 |
| 精炼站加成 | UEX、cryon.rocks、SCMiner | 一致；叠加方式（乘在产出上）未经证实，待游戏终端报价核对 |
| 精炼产出率 / 精炼费 / 用时 | SCMiner 4.10.2 精炼模拟器（用户指定）；timesaver.gg 的 88–93% 为过时数据，已弃用 | Dinyx、Ferron、Pyrometric 45%；中档 38.25%；低档 31.5% |
| 收购价 | UEX（玩家上报） | 刷新时最新报价偏离均价 >25% 改用均价，并与内置快照比对提示 |
| 中文译名 | 用户提供的汉化包（上一小版本） | 只用于对照中文，不取数值 |

| S1 矿头、Pitman、Impact II、Klein-S2、其余被动模组、采矿船矿头位/矿袋 | erkul.games 解包（4.10.2-LIVE.12913470），抽查 Helix I 与 Wiki 一致；原有 Rieger-C3 / Focus III / Torrent III 与原值一致 | 采用。注意：erkul 新构建里 Helix II 最小功率 1479（Wiki 旧构建 1232.5）、充能 +0%（原值 +40%），Lancet MH2 最小功率 1305（原值 1087.5）；按「SCMiner 为准」保留原值，待 SCMiner 核对 |
